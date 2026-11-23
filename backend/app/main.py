"""
FastAPI Main Application for NSE Nifty 500 Intraday Screener & Trade Signal Generator.
"""
import logging
import threading
import time
from datetime import datetime, time as dtime
import pandas as pd
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
from .prediction_engine import evaluate_prediction_setup
from .models import PredictionResponse
from .config import IST_TZ, NIFTY_500_STOCKS, EOD_RESET_TIME_STR

from .config import SECTORS
from .models import ScreenerResponse, StockHistoryResponse, MarketStatus
from .data_fetcher import run_screener, get_stock_history_and_indicators, get_market_status, _CACHE
from .market_context import build_live_context_cache
from .v13_models import V13Signal
from .v13_scanner import scan_v13_universe
from .telegram_bot import dispatch_telegram_alerts, send_telegram_text
from .v13_ledger import GLOBAL_SESSION_LEDGER, get_effective_trading_date
import yfinance as yf

logger = logging.getLogger("v13_main")

V13_NIFTY_CACHE_TTL_SECONDS = 180
_V13_NIFTY_CACHE = None
_V13_NIFTY_CACHE_AT = 0.0
_V13_NIFTY_CACHE_LOCK = threading.Lock()

V13_SCAN_CACHE_TTL_SECONDS = 30
V13_MAX_SCAN_LOCK_SECONDS = 300.0
_V13_SCAN_RESULT = None
_V13_SCAN_RESULT_AT = 0.0
_V13_SCAN_RUNNING = False
_V13_SCAN_LOCK = threading.Lock()
_V13_SCAN_THREAD = None
_V13_SCAN_STARTED_AT = 0.0
_V13_SCAN_GENERATED_AT = None
_EOD_FINAL_SCAN_DATE: Optional[str] = None

from .paper_trading import (
    record_prediction,
    qualifies_for_v12,
    is_duplicate_signal,
    get_open_paper_trades,
    get_all_paper_trades,
)


import os
import json
from dataclasses import asdict

EOD_SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), "data", "eod active", "eod_snapshot.json")
EOD_SNAPSHOT_HISTORY_DIR = os.path.join(os.path.dirname(__file__), "data", "EOD Snapshot history")

def _to_dict_safe(obj):
    """Recursively convert dataclasses, custom classes, and dicts to pure JSON-safe primitives."""
    if obj is None or isinstance(obj, (int, float, str, bool)):
        return obj
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        return _to_dict_safe(obj.to_dict())
    if hasattr(obj, "__dataclass_fields__"):
        return _to_dict_safe(asdict(obj))
    if hasattr(obj, "__dict__"):
        return _to_dict_safe(vars(obj))
    if isinstance(obj, dict):
        return {str(k): _to_dict_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_dict_safe(item) for item in obj]
    return str(obj)

def _save_eod_snapshot(data: dict):
    """Atomically write the validated EOD scan snapshot to disk stamped with effective session date."""
    try:
        os.makedirs(os.path.dirname(EOD_SNAPSHOT_PATH), exist_ok=True)
        session_date = get_effective_trading_date()
        data["date"] = session_date
        tmp_path = EOD_SNAPSHOT_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, EOD_SNAPSHOT_PATH)
    except Exception:
        pass

def _get_snapshot_session_date(data: dict) -> str:
    """Extract validated session date from snapshot, avoiding midnight calendar date confusion."""
    if not isinstance(data, dict):
        return ""
    if data.get("date"):
        return str(data["date"]).strip()
    gen_at = data.get("generated_at")
    if gen_at:
        try:
            clean_iso = gen_at.split("+")[0] if "+" in gen_at else gen_at
            dt = datetime.fromisoformat(clean_iso)
            if dt.tzinfo is None:
                dt = IST_TZ.localize(dt)
            return get_effective_trading_date(dt)
        except Exception:
            return gen_at[:10]
    return ""

def _is_snapshot_active(snap_date_str: str, now_dt: Optional[datetime] = None) -> bool:
    """
    EOD Display Window & Morning Rollover:
    - Same-day snapshot (at or after EOD_RESET_TIME) is active for the current day.
    - Before EOD_RESET_TIME on a trading day: Snapshot from the previous session (yesterday or Friday) is active.
    - Weekend (Saturday/Sunday): Friday's session snapshot is active.
    - At or after EOD_RESET_TIME on a new trading day: Previous snapshot expires, triggering clean slate reset before 09:15 AM open.
    """
    if not snap_date_str:
        return False
    now = now_dt or datetime.now(IST_TZ)
    return snap_date_str == get_effective_trading_date(now)

def _load_eod_snapshot() -> Optional[dict]:
    """
    Load saved EOD scan snapshot from disk.
    Date-Aware Gatekeeper:
    Preserves previous session EOD snapshot overnight until EOD_RESET_TIME.
    At EOD_RESET_TIME on a new session date, archives snapshot to history/ and returns None (clean slate).
    """
    if os.path.exists(EOD_SNAPSHOT_PATH):
        try:
            with open(EOD_SNAPSHOT_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                snap_date = _get_snapshot_session_date(data)
                if _is_snapshot_active(snap_date):
                    return data
                else:
                    # Morning Rollover! Archive previous session snapshot and reset disk state
                    try:
                        os.makedirs(EOD_SNAPSHOT_HISTORY_DIR, exist_ok=True)
                        arch_path = os.path.join(EOD_SNAPSHOT_HISTORY_DIR, f"eod_snapshot_{snap_date}.json")
                        with open(EOD_SNAPSHOT_PATH, "r", encoding="utf-8") as f:
                            snap_content = json.load(f)
                        with open(arch_path, "w", encoding="utf-8") as af:
                            json.dump(snap_content, af, ensure_ascii=False)
                        os.remove(EOD_SNAPSHOT_PATH)
                    except Exception:
                        pass
                    # Synchronized Ledger Rollover: keep active performance live eod in lockstep with screener
                    try:
                        GLOBAL_SESSION_LEDGER._check_rollover()
                    except Exception:
                        pass
                    return None
        except Exception:
            pass
    return None

def _get_premarket_universe() -> list:
    """Return universe list with 0 signals so stocks list cleanly in pre-market or waiting state."""
    try:
        hist_dir = EOD_SNAPSHOT_HISTORY_DIR
        files = sorted([f for f in os.listdir(hist_dir) if f.startswith("eod_snapshot_")], reverse=True) if os.path.exists(hist_dir) else []
        if files:
            latest = os.path.join(hist_dir, files[0])
            with open(latest, "r", encoding="utf-8") as f:
                d = json.load(f)
            u = d.get("universe", [])
            premarket_u = []
            for item in u:
                premarket_u.append({
                    "symbol": item.get("symbol"),
                    "name": item.get("name"),
                    "sector": item.get("sector"),
                    "status": "NO_SETUP",
                    "signals": [],
                    "snapshot": item.get("snapshot", {}),
                    "is_nifty500": item.get("is_nifty500", True),
                    "market_cap_cr": item.get("market_cap_cr", 0),
                })
            return premarket_u
    except Exception:
        pass
    return []

def _run_v13_scan_background(force_fresh: bool = False, is_eod_final: bool = False):
    """Run one V13 scan and publish only a fully completed result.
    If is_eod_final=True, forces fresh download of Bar 25 closed candles,
    saves the final EOD snapshot, finalizes ledger and shadow portfolio,
    and marks final scan complete for today."""
    global _V13_SCAN_RESULT, _V13_SCAN_RESULT_AT, _V13_SCAN_GENERATED_AT
    global _V13_SCAN_RUNNING, _V13_SCAN_THREAD, _EOD_FINAL_SCAN_DATE, _V13_SCAN_STARTED_AT

    t_start = time.monotonic()
    _V13_SCAN_STARTED_AT = t_start
    print(f"[V13 SCAN] Starting background scan cycle at {datetime.now(IST_TZ).strftime('%H:%M:%S')}...", flush=True)
    try:
        nifty = _get_v13_nifty_data()
        result = scan_v13_universe(
            NIFTY_500_STOCKS,
            nifty_df=nifty,
            force_fresh=force_fresh,
        )
        print(f"[V13 SCAN] scan_v13_universe completed in {time.monotonic() - t_start:.2f}s (candidates={len(result.get('candidates', []))}, valid={result.get('valid')}, invalid={result.get('invalid')})", flush=True)

        clean_result = _to_dict_safe(result)

        # Enrich signals with 3-Pillar Conviction Rating BEFORE saving snapshot to disk
        try:
            from .v13_conviction import evaluate_conviction, is_conviction_rating_enabled
            if is_conviction_rating_enabled():
                m_ctx = clean_result.get("market_context")
                u_list = clean_result.get("universe")
                for cand in clean_result.get("candidates", []):
                    if isinstance(cand, dict) and "conviction" not in cand:
                        cand["conviction"] = evaluate_conviction(cand, market_context=m_ctx, universe=u_list)
                for diag in clean_result.get("diagnostic_signals", []):
                    if isinstance(diag, dict) and "conviction" not in diag:
                        diag["conviction"] = evaluate_conviction(diag, market_context=m_ctx, universe=u_list)
        except Exception:
            pass

        # Publish only after the complete scan has returned.
        with _V13_SCAN_LOCK:
            has_new_candidates = bool(clean_result.get("candidates"))
            ist_now = datetime.now(IST_TZ)
            is_late_or_closed = ist_now.time() >= pd.Timestamp("15:00").time() or not get_market_status().is_open

            # Preserve today's candidates, diagnostics, and universe signals if current micro-cycle found 0 new setups or off-market
            # CRITICAL GUARD: Before 09:30 AM (Opening Range formation), NEVER hydrate old candidates from disk snapshot!
            # Also on is_eod_final, keep the fresh authoritative results.
            is_opening_range = (ist_now.weekday() <= 4 and ist_now.time() < pd.Timestamp("09:30").time())
            if not is_eod_final and not is_opening_range and is_late_or_closed:
                disk_snap = _load_eod_snapshot()
                if disk_snap:
                    if not clean_result.get("candidates") and disk_snap.get("candidates"):
                        clean_result["candidates"] = disk_snap.get("candidates")
                    if not clean_result.get("diagnostic_signals") and disk_snap.get("diagnostic_signals"):
                        clean_result["diagnostic_signals"] = disk_snap.get("diagnostic_signals")

            # Always stamp with fresh live completion timestamp and active session date
            effective_session_date = get_effective_trading_date()
            _V13_SCAN_GENERATED_AT = datetime.now(IST_TZ).isoformat()
            clean_result["generated_at"] = _V13_SCAN_GENERATED_AT
            clean_result["date"] = effective_session_date
            _V13_SCAN_RESULT = clean_result
            _V13_SCAN_RESULT_AT = time.monotonic()

            # Ensure every candidate is reflected inside its universe record's signals
            if clean_result.get("candidates") and clean_result.get("universe"):
                cand_map = {c.get("symbol"): c for c in clean_result["candidates"] if isinstance(c, dict)}
                for u_stock in clean_result["universe"]:
                    sym = u_stock.get("symbol")
                    if sym in cand_map:
                        existing = u_stock.get("signals") or []
                        cand_item = cand_map[sym]
                        if not any(s.get("signal_type") == cand_item.get("signal_type") for s in existing if isinstance(s, dict)):
                            u_stock["signals"] = [cand_item] + [s for s in existing if s.get("signal_type") != cand_item.get("signal_type")]
                            u_stock["status"] = "SIGNAL"

                # Keep candidate LTP and price updated with fresh universe snapshot
                u_price_map = {
                    str(u.get("symbol") or "").strip().upper(): u.get("snapshot", {}).get("price")
                    for u in clean_result["universe"]
                    if u.get("symbol") and isinstance(u.get("snapshot"), dict) and u.get("snapshot", {}).get("price") is not None
                }
                for cand in clean_result["candidates"]:
                    if isinstance(cand, dict):
                        csym = str(cand.get("symbol") or "").strip().upper()
                        if csym in u_price_map and u_price_map[csym] is not None:
                            cand["ltp"] = u_price_map[csym]
                            cand["price"] = u_price_map[csym]

            # EOD Freeze: Save snapshot to disk (now includes full conviction ratings & preserved diagnostics)
            if clean_result.get("candidates") or clean_result.get("universe"):
                _save_eod_snapshot(clean_result)

            # Calculation is complete and published: release scan running flag so API immediately reports is_scanning=False
            _V13_SCAN_RUNNING = False

        # Update Session Trade Ledger (Monotonic Ratchet + Immutable First Stage + Outcomes)
        try:
            candidates = clean_result.get("candidates", [])
            diagnostics = clean_result.get("diagnostic_signals", [])
            universe = clean_result.get("universe", [])
            GLOBAL_SESSION_LEDGER.update_from_scan(candidates, diagnostics, universe=universe)
            from .v13_live_movers_telegram import update_live_movers_ledger_outcomes
            update_live_movers_ledger_outcomes(universe=universe)
        except Exception:
            pass

        # Update Dynamic Conviction Drift on Closed 15m Scan Update
        try:
            from .v13_conviction_audit import GLOBAL_CONVICTION_AUDITOR, is_conviction_audit_enabled
            if is_conviction_audit_enabled():
                m_ctx = clean_result.get("market_context")
                u_list = clean_result.get("universe")
                GLOBAL_CONVICTION_AUDITOR.update_scan_cycle(m_ctx, u_list, GLOBAL_SESSION_LEDGER.telegram_records)
        except Exception:
            pass

        # Autonomous Conviction Shadow Portfolio Execution Cycle (Isolated & Non-Blocking)
        try:
            from .v13_shadow_portfolio import GLOBAL_SHADOW_PORTFOLIO, is_shadow_portfolio_enabled
            if is_shadow_portfolio_enabled():
                candidates = clean_result.get("candidates", [])
                diagnostics = clean_result.get("diagnostic_signals", [])
                uni_ltp_map = {}
                for u_item in clean_result.get("universe", []):
                    if isinstance(u_item, dict):
                        u_sym = str(u_item.get("symbol") or "").replace(".NS", "").strip().upper()
                        u_ltp = u_item.get("ltp") or (u_item.get("snapshot") or {}).get("price")
                        if u_sym and u_ltp:
                            try:
                                uni_ltp_map[u_sym] = float(u_ltp)
                            except (ValueError, TypeError):
                                pass
                GLOBAL_SHADOW_PORTFOLIO.process_scan_cycle(candidates, diagnostics, ltp_map=uni_ltp_map)
        except Exception as spe:
            logger.debug(f"Shadow portfolio process_scan_cycle skipped: {spe}")

        # Dispatch 100% Free Telegram Live Alerts for signals >= threshold (Deduplicated by symbol + direction)
        unique_signals = []
        try:
            candidates = clean_result.get("candidates", [])
            diagnostics = clean_result.get("diagnostic_signals", [])
            seen_keys = set()
            for sig in candidates:
                sym = sig.get("symbol") if isinstance(sig, dict) else getattr(sig, "symbol", "")
                s_dir = str((sig.get("direction") or sig.get("signal_type") or "BULLISH") if isinstance(sig, dict) else getattr(sig, "direction", "BULLISH")).upper()
                dedup_key = f"{sym}_{s_dir}"
                if sym and dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    unique_signals.append(sig)
            for sig in diagnostics:
                sym = sig.get("symbol") if isinstance(sig, dict) else getattr(sig, "symbol", "")
                s_dir = str((sig.get("direction") or sig.get("signal_type") or "BULLISH") if isinstance(sig, dict) else getattr(sig, "direction", "BULLISH")).upper()
                dedup_key = f"{sym}_{s_dir}"
                if sym and dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    unique_signals.append(sig)
            dispatch_telegram_alerts(
                unique_signals,
                market_context=clean_result.get("market_context"),
                universe=clean_result.get("universe"),
            )
        except Exception as _tge:
            logger.warning(f"Telegram dispatch failed: {_tge}")

        # Record Yahoo Candle Sync & Live Trigger Precision in Dedicated Audit Ledger
        try:
            from .v13_sync_ledger import GLOBAL_SYNC_LEDGER, is_sync_ledger_enabled
            if is_sync_ledger_enabled():
                ist_now = datetime.now(IST_TZ)
                now_mins = ist_now.hour * 60 + ist_now.minute + ist_now.second / 60.0
                if 555 <= now_mins <= 936:  # Active market session 09:15 to 15:30 + 15:36 settlement window
                    current_bar_idx = min(25, int((now_mins - 555) // 15) + (1 if now_mins >= 930 else 0))
                    if current_bar_idx > 0:
                        last_bar_idx = current_bar_idx  # 1-indexed (Bar 1 to 25)
                        b_start = 555 + (last_bar_idx - 1) * 15
                        b_end = b_start + 15
                        bar_range_str = f"{b_start//60:02d}:{b_start%60:02d} - {b_end//60:02d}:{b_end%60:02d} (Bar {last_bar_idx})"
                        close_time_str = f"{b_end//60:02d}:{b_end%60:02d}:00"
                        delivered_time_str = ist_now.strftime("%H:%M:%S")
                        close_dt = ist_now.replace(hour=b_end//60, minute=b_end%60, second=0, microsecond=0)
                        lag_sec = max(0, int((ist_now - close_dt).total_seconds()))
                        GLOBAL_SYNC_LEDGER.record_bar_sync(
                            bar_number=last_bar_idx,
                            bar_range_str=bar_range_str,
                            candle_close_time_str=close_time_str,
                            yahoo_delivered_time_str=delivered_time_str,
                            ingest_lag_seconds=lag_sec,
                            stocks_scanned_count=len(clean_result.get("universe", [])),
                        )
                # Build fresh universe snapshot LTP lookup map for accurate slippage measurement (Trap #3 Guard)
                sync_u_price_map = {
                    str(u.get("symbol") or "").replace(".NS", "").strip().upper(): (
                        u.get("ltp") or (u.get("snapshot") or {}).get("price")
                    )
                    for u in clean_result.get("universe", [])
                    if isinstance(u, dict) and u.get("symbol")
                }
                # Record qualified active stock breakout trigger events (score >= 72.0, Write-Once per session)
                for sig in clean_result.get("candidates", []):
                    sym = (sig.get("symbol") if isinstance(sig, dict) else getattr(sig, "symbol", "")) or ""
                    sym_clean = str(sym).replace(".NS", "").strip().upper()
                    s_dir = sig.get("direction") or sig.get("signal_type") if isinstance(sig, dict) else getattr(sig, "direction", "BULLISH")
                    s_score = float(sig.get("score", 0.0) if isinstance(sig, dict) else getattr(sig, "score", 0.0))
                    if s_score < 72.0:
                        continue
                    s_time = sig.get("signal_time") if isinstance(sig, dict) else getattr(sig, "signal_time", "")
                    tp_dict = (sig.get("trade_plan") or sig.get("risk") or {}) if isinstance(sig, dict) else (getattr(sig, "trade_plan", None) or getattr(sig, "risk", {}) or {})
                    # Distinct breakout trigger / candle close price vs live snapshot LTP (Trap #3 Guard)
                    s_entry = (
                        (sig.get("entry_price") if isinstance(sig, dict) else getattr(sig, "entry_price", None))
                        or (tp_dict.get("entry") if isinstance(tp_dict, dict) else getattr(tp_dict, "entry", None))
                        or (sig.get("close") if isinstance(sig, dict) else getattr(sig, "close", None))
                    )
                    s_ltp = (
                        sync_u_price_map.get(sym_clean)
                        or (sig.get("ltp") if isinstance(sig, dict) else getattr(sig, "ltp", None))
                        or (sig.get("price") if isinstance(sig, dict) else getattr(sig, "price", None))
                        or s_entry
                    )
                    bar_label = "Bar ?"
                    if s_time:
                        try:
                            st_h, st_m = [int(x) for x in s_time.split("T")[-1][:5].split(":")]
                            st_total = st_h * 60 + st_m
                            if 555 <= st_total <= 936:
                                b_num = min(25, int((st_total - 555) // 15) + 1)
                                bar_label = f"Bar {b_num}"
                        except Exception:
                            pass
                    GLOBAL_SYNC_LEDGER.record_trigger_alert(
                        symbol=sym_clean,
                        direction=s_dir,
                        score=s_score,
                        signal_bar_str=bar_label,
                        breakout_entry_price=s_entry,
                        candle_close_price=s_entry,
                        alert_price=s_ltp,
                        signal_time_str=s_time or ist_now.isoformat(),
                    )
        except Exception:
            pass

        # Autonomous Post-Scan EOD Performance Audit Dispatch (After 15:30 Bar 25 final scan completes)
        try:
            ist_now = datetime.now(IST_TZ)
            today_str = ist_now.strftime("%Y-%m-%d")
            should_dispatch_eod = is_eod_final or (
                ist_now.weekday() <= 4 and ist_now.time() >= pd.Timestamp("15:30:00").time()
            )
            if should_dispatch_eod:
                nifty_dir = (clean_result.get("market_context") or {}).get("nifty_direction", "Neutral")
                # 1. Primary V13 Ledger EOD Performance Audit Dispatch -> PulseX1000 Bot (Thread-Safe Atomic Lock)
                if GLOBAL_SESSION_LEDGER.eod_audit_sent_date != today_str:
                    try:
                        sent = GLOBAL_SESSION_LEDGER.dispatch_eod_audit(market_regime=nifty_dir, now_dt=ist_now)
                        if sent:
                            print(f"[EOD AUDIT] Auto-dispatched V13 EOD Performance Audit for {today_str} post-scan")
                    except Exception as le:
                        print(f"[EOD AUDIT ERROR] Failed session ledger EOD audit dispatch: {le}")

                # 1B. Dedicated NSE Live Movers EOD Performance Audit Dispatch -> NSE Live - Live Mover VIP Bot
                try:
                    from .v13_live_movers_telegram import dispatch_live_movers_eod_audit
                    lm_sent = dispatch_live_movers_eod_audit(
                        market_regime=nifty_dir,
                        universe=clean_result.get("universe", []),
                        now_dt=ist_now,
                    )
                    if lm_sent:
                        print(f"[LIVE MOVERS EOD AUDIT] Auto-dispatched Live Movers EOD Audit to VIP Bot for {today_str} post-scan")
                except Exception as lme:
                    print(f"[LIVE MOVERS EOD AUDIT ERROR] Failed Live Movers EOD audit dispatch: {lme}")

                # Mark final scan completed AFTER EOD dispatches to prevent watchdog race condition
                _EOD_FINAL_SCAN_DATE = today_str

                # 2. Dedicated 2nd Notification: Conviction Drift & Regime Decay Audit! (Decoupled & Independent)
                try:
                    from .v13_conviction_audit import GLOBAL_CONVICTION_AUDITOR, is_conviction_audit_enabled
                    if is_conviction_audit_enabled() and GLOBAL_CONVICTION_AUDITOR.eod_dispatched_date != today_str:
                        time.sleep(1.0)
                        GLOBAL_CONVICTION_AUDITOR.dispatch_eod_drift_audit()
                except Exception as ce:
                    print(f"[CONVICTION AUDIT ERROR] Failed EOD drift audit dispatch: {ce}")

                # 3. Dedicated 3rd Notification: Shadow Portfolio EOD Audit! (Decoupled & Independent)
                try:
                    from .v13_shadow_portfolio import GLOBAL_SHADOW_PORTFOLIO, is_shadow_portfolio_enabled
                    if is_shadow_portfolio_enabled() and GLOBAL_SHADOW_PORTFOLIO.eod_dispatched_date != today_str:
                        time.sleep(3.0)
                        GLOBAL_SHADOW_PORTFOLIO.dispatch_eod_shadow_audit()
                except Exception as spe:
                    print(f"[SHADOW PORTFOLIO EOD ERROR] {spe}")

                # Autonomous Friday Weekly Performance Audit Dispatch (Immediate after 15:30 on Friday)
                if ist_now.weekday() == 4:
                    current_week_str = f"{ist_now.year}-W{ist_now.isocalendar()[1]:02d}"
                    if GLOBAL_SESSION_LEDGER.weekly_audit_sent_week != current_week_str:
                        # Ensure Daily Audit notification reaches user's phone first with 3s buffer
                        time.sleep(3.0)
                        try:
                            from .v13_weekly_audit import dispatch_weekly_audit_to_telegram
                            weekly_sent = dispatch_weekly_audit_to_telegram(ist_now)
                            if weekly_sent:
                                GLOBAL_SESSION_LEDGER.weekly_audit_sent_week = current_week_str
                                GLOBAL_SESSION_LEDGER._save_to_disk()
                                print(f"[WEEKLY AUDIT] Auto-dispatched Weekly Performance Audit for week {current_week_str} post-scan")
                        except Exception as we:
                            print(f"[WEEKLY AUDIT ERROR] Failed Friday audit dispatch: {we}")
        except Exception as e:
            print(f"[EOD AUDIT ERROR] Failed post-scan audit dispatch: {e}")
    except Exception as exc:
        # Keep the previous completed result intact on scan failure.
        print(f"[V13 SCAN WORKER EXCEPTION] Background scan cycle failed: {exc}", flush=True)
        import traceback
        traceback.print_exc()
        logger.exception(f"[V13 SCAN WORKER EXCEPTION] Background scan cycle failed: {exc}")
    finally:
        with _V13_SCAN_LOCK:
            _V13_SCAN_RUNNING = False
            _V13_SCAN_THREAD = None


def _v13_continuous_loop():
    """Background daemon loop continuously refreshing V13 scan every ~60s during market hours and settlement."""
    global _V13_SCAN_RUNNING, _V13_SCAN_THREAD, _V13_SCAN_STARTED_AT, _V13_SCAN_RESULT, _V13_SCAN_RESULT_AT, _V13_SCAN_GENERATED_AT, _EOD_FINAL_SCAN_DATE
    while True:
        try:
            status = get_market_status()
            now = time.monotonic()
            ist_now = datetime.now(IST_TZ)
            today_str = ist_now.strftime("%Y-%m-%d")

            # 09:00 AM Morning Rollover & Clean Slate:
            # Preserves previous session snapshot overnight until 09:00 AM.
            # At 09:00 AM on a new session date, archives snapshot and resets to clean slate.
            effective_session = get_effective_trading_date(ist_now)
            with _V13_SCAN_LOCK:
                if _V13_SCAN_RESULT is not None:
                    res_date = _get_snapshot_session_date(_V13_SCAN_RESULT)
                    if not _is_snapshot_active(res_date, ist_now):
                        if os.path.exists(EOD_SNAPSHOT_PATH):
                            try:
                                os.makedirs(EOD_SNAPSHOT_HISTORY_DIR, exist_ok=True)
                                arch_path = os.path.join(EOD_SNAPSHOT_HISTORY_DIR, f"eod_snapshot_{res_date}.json")
                                with open(EOD_SNAPSHOT_PATH, "r", encoding="utf-8") as f:
                                    snap_content = json.load(f)
                                with open(arch_path, "w", encoding="utf-8") as af:
                                    json.dump(snap_content, af, ensure_ascii=False)
                                os.remove(EOD_SNAPSHOT_PATH)
                            except Exception:
                                pass
                        _V13_SCAN_RESULT = None
                        _V13_SCAN_RESULT_AT = 0.0
                        _V13_SCAN_GENERATED_AT = None
                        GLOBAL_SESSION_LEDGER._check_rollover(effective_session)
                else:
                    GLOBAL_SESSION_LEDGER._check_rollover(effective_session)

                # Self-healing watchdog: auto-release scan lock if previous worker exceeded deadline
                if _V13_SCAN_RUNNING and (now - _V13_SCAN_STARTED_AT > V13_MAX_SCAN_LOCK_SECONDS):
                    logger.warning("[WATCHDOG] V13 scan worker exceeded 300s timeout. Auto-releasing scan lock.")
                    _V13_SCAN_RUNNING = False
                    _V13_SCAN_THREAD = None

                is_stale = (_V13_SCAN_RESULT is None) or (now - _V13_SCAN_RESULT_AT >= V13_SCAN_CACHE_TTL_SECONDS)
                not_running = not _V13_SCAN_RUNNING

            # 1. Regular Live Market Hours Scanning (09:15 to 15:30)
            if status.is_open and is_stale and not_running:
                with _V13_SCAN_LOCK:
                    _V13_SCAN_RUNNING = True
                    _V13_SCAN_STARTED_AT = time.monotonic()
                    _V13_SCAN_THREAD = threading.Thread(
                        target=_run_v13_scan_background,
                        kwargs={"force_fresh": False, "is_eod_final": False},
                        name="v13-scan-worker",
                        daemon=True,
                    )
                    _V13_SCAN_THREAD.start()

            # 2. Dedicated Post-Market EOD Final Settlement Scan:
            # Triggered between 15:30:20 and 15:36:00 IST on weekdays after Bar 25 closes.
            # Ensures 15:30 candle is 100% closed, downloads fresh Bar 25 candle,
            # saves authoritative EOD snapshot, and finalizes the trading session.
            current_time = ist_now.time()
            is_eod_settlement_window = (
                ist_now.weekday() <= 4
                and pd.Timestamp("15:30:00").time() <= current_time <= pd.Timestamp("15:36:00").time()
            )
            if is_eod_settlement_window and _EOD_FINAL_SCAN_DATE != today_str and not_running:
                with _V13_SCAN_LOCK:
                    _V13_SCAN_RUNNING = True
                    _V13_SCAN_THREAD = threading.Thread(
                        target=_run_v13_scan_background,
                        kwargs={"force_fresh": True, "is_eod_final": True},
                        name="v13-scan-worker-eod-final",
                        daemon=True,
                    )
                    _V13_SCAN_THREAD.start()

            # 15:15 IST Auto-MIS Square-Off for Shadow Portfolio
            if ist_now.weekday() <= 4 and current_time >= pd.Timestamp("15:15").time():
                try:
                    from .v13_shadow_portfolio import GLOBAL_SHADOW_PORTFOLIO, is_shadow_portfolio_enabled
                    if is_shadow_portfolio_enabled():
                        live_ltp_map = {}
                        if isinstance(_V13_SCAN_RESULT, dict):
                            for u_item in _V13_SCAN_RESULT.get("universe", []):
                                if isinstance(u_item, dict):
                                    u_sym = str(u_item.get("symbol") or "").replace(".NS", "").strip().upper()
                                    u_ltp = u_item.get("ltp") or (u_item.get("snapshot") or {}).get("price")
                                    if u_sym and u_ltp:
                                        try:
                                            live_ltp_map[u_sym] = float(u_ltp)
                                        except (ValueError, TypeError):
                                            pass
                        GLOBAL_SHADOW_PORTFOLIO.square_off_all_mis(ltp_map=live_ltp_map)
                except Exception:
                    pass

            # Automated EOD Performance Audit Telegram Dispatch Watchdogs:
            # ONLY dispatched after the Final EOD Scan completes (_EOD_FINAL_SCAN_DATE == today_str)
            # or past 15:36:00 as a safety fallback timeout.
            can_dispatch_watchdogs = (
                ist_now.weekday() <= 4
                and (
                    _EOD_FINAL_SCAN_DATE == today_str
                    or current_time >= pd.Timestamp("15:36:00").time()
                )
            )
            if can_dispatch_watchdogs:
                today_str = ist_now.strftime("%Y-%m-%d")

                # Watchdog 1: Primary V13 Ledger EOD Audit -> PulseX1000 Bot (Thread-Safe Atomic Lock)
                nifty_dir = (_V13_SCAN_RESULT.get("market_context") or {}).get("nifty_direction", "Neutral") if _V13_SCAN_RESULT else "Neutral"
                if GLOBAL_SESSION_LEDGER.eod_audit_sent_date != today_str:
                    try:
                        sent = GLOBAL_SESSION_LEDGER.dispatch_eod_audit(market_regime=nifty_dir, now_dt=ist_now)
                        if sent:
                            print(f"[EOD AUDIT WATCHDOG] Auto-dispatched V13 EOD Performance Audit for {today_str}")
                    except Exception as e:
                        print(f"[EOD AUDIT WATCHDOG ERROR] {e}")

                # Watchdog 1B: Dedicated NSE Live Movers EOD Audit -> NSE Live - Live Mover VIP Bot
                try:
                    from .v13_live_movers_telegram import dispatch_live_movers_eod_audit
                    w_universe = _V13_SCAN_RESULT.get("universe", []) if isinstance(_V13_SCAN_RESULT, dict) else []
                    lm_sent = dispatch_live_movers_eod_audit(
                        market_regime=nifty_dir,
                        universe=w_universe,
                        now_dt=ist_now,
                    )
                    if lm_sent:
                        print(f"[LIVE MOVERS EOD WATCHDOG] Auto-dispatched Live Movers EOD Audit to VIP Bot for {today_str}")
                except Exception as lme:
                    print(f"[LIVE MOVERS EOD WATCHDOG ERROR] {lme}")

                # Watchdog 2: Conviction Drift & Regime Decay Audit! (Decoupled & Independent)
                try:
                    from .v13_conviction_audit import GLOBAL_CONVICTION_AUDITOR, is_conviction_audit_enabled
                    if is_conviction_audit_enabled() and GLOBAL_CONVICTION_AUDITOR.eod_dispatched_date != today_str:
                        time.sleep(1.0)
                        GLOBAL_CONVICTION_AUDITOR.dispatch_eod_drift_audit()
                except Exception as ce:
                    print(f"[CONVICTION AUDIT WATCHDOG ERROR] {ce}")

                # Watchdog 3: Shadow Portfolio EOD Audit! (Decoupled & Independent, at or after 15:30/15:35 IST)
                try:
                    from .v13_shadow_portfolio import GLOBAL_SHADOW_PORTFOLIO, is_shadow_portfolio_enabled
                    if is_shadow_portfolio_enabled() and GLOBAL_SHADOW_PORTFOLIO.eod_dispatched_date != today_str:
                        time.sleep(3.0)
                        GLOBAL_SHADOW_PORTFOLIO.dispatch_eod_shadow_audit()
                except Exception as spe:
                    print(f"[SHADOW PORTFOLIO WATCHDOG ERROR] {spe}")

                # Watchdog 4: Weekly Audit (dispatched on the final trading session of the week, e.g. Friday or Thursday before holiday)
                try:
                    from .nse_calendar import is_last_trading_day_of_week
                    is_weekly_session = is_last_trading_day_of_week(ist_now)
                except Exception:
                    is_weekly_session = (ist_now.weekday() == 4)

                if is_weekly_session:
                    current_week_str = f"{ist_now.year}-W{ist_now.isocalendar()[1]:02d}"
                    if GLOBAL_SESSION_LEDGER.weekly_audit_sent_week != current_week_str:
                        time.sleep(3.0)
                        try:
                            from .v13_weekly_audit import dispatch_weekly_audit_to_telegram
                            weekly_sent = dispatch_weekly_audit_to_telegram(ist_now)
                            if weekly_sent:
                                GLOBAL_SESSION_LEDGER.weekly_audit_sent_week = current_week_str
                                GLOBAL_SESSION_LEDGER._save_to_disk()
                                print(f"[WEEKLY AUDIT WATCHDOG] Auto-dispatched Weekly Performance Audit for week {current_week_str}")
                        except Exception as we:
                            print(f"[WEEKLY AUDIT WATCHDOG ERROR] {we}")
        except Exception:
            pass
        time.sleep(5)


def _get_active_universe_and_candidates():
    """Retrieve the current active universe and candidates from in-memory scan, EOD snapshot, or universe fallback."""
    universe = []
    candidates = []
    with _V13_SCAN_LOCK:
        if _V13_SCAN_RESULT:
            universe = _V13_SCAN_RESULT.get("universe", [])
            candidates = _V13_SCAN_RESULT.get("candidates", [])

    if not universe:
        disk_snap = _load_eod_snapshot()
        if disk_snap:
            universe = disk_snap.get("universe", [])
            candidates = disk_snap.get("candidates", [])

    if not universe:
        universe = _get_premarket_universe()

    if not universe:
        import json, os
        u_path = os.path.join(os.path.dirname(__file__), "data", "universe_1000cr.json")
        if os.path.exists(u_path):
            try:
                with open(u_path, "r", encoding="utf-8") as uf:
                    raw_u = json.load(uf)
                    universe = [
                        {
                            "symbol": item.get("symbol"),
                            "name": item.get("name"),
                            "sector": item.get("sector", "General"),
                            "status": "NO_SETUP",
                            "signals": [],
                            "snapshot": item.get("snapshot", {}),
                            "is_nifty500": item.get("is_nifty500", True),
                            "market_cap_cr": item.get("market_cap_cr", 0),
                        }
                        for item in raw_u
                    ]
            except Exception:
                pass
    return universe, candidates


def _v13_live_movers_telegram_loop():
    """
    Dedicated background worker for Live Movers V13 Active 20-EMA Telegram Bot.
    Runs every 60 seconds between 09:15 and 15:00 IST on trading days.
    Allows automated alerts even when the browser is completely closed.
    """
    from .v13_live_movers_telegram import (
        dispatch_live_movers_alerts,
        update_live_movers_ledger_outcomes,
        dispatch_live_movers_eod_audit,
    )
    from .v13_live_movers import compute_live_top_movers

    logger.info("Live Movers Telegram background worker initialized (60s loop, 09:15-15:35 IST).")
    while True:
        try:
            ist_now = datetime.now(IST_TZ)
            is_weekday = ist_now.weekday() <= 4
            t_now = ist_now.time()
            # Synchronize with V14 Screener: pause Telegram dispatch between 09:30:00 and 09:35:15 IST
            # while Bar 1 closes and the first fresh intraday V13 scan completes.
            is_bar_2_blackout = dtime(9, 30, 0) <= t_now < dtime(9, 35, 15)
            in_alert_window = is_weekday and (dtime(9, 15) <= t_now <= dtime(15, 0)) and not is_bar_2_blackout
            in_tracking_window = is_weekday and (dtime(9, 15) <= t_now <= dtime(15, 36))

            if in_tracking_window:
                universe, candidates = _get_active_universe_and_candidates()
                if universe:
                    movers_data = compute_live_top_movers(
                        universe,
                        df_cache=None,
                        category="V13_ACTIVE",
                        force=False,
                        v13_candidates=candidates,
                    )
                    runners = movers_data.get("runners", [])
                    short_runners = movers_data.get("short_runners", [])
                    if in_alert_window and (runners or short_runners):
                        market_ctx = _V13_SCAN_RESULT.get("market_context") if _V13_SCAN_RESULT else None
                        dispatch_live_movers_alerts(
                            runners, 
                            short_runners,
                            market_context=market_ctx,
                            universe=universe,
                        )
                    # Real-time outcome tracking using fresh NSE Live Mover ticks + universe fallback (Trap #2 Guard)
                    fresh_mover_items = (
                        runners
                        + short_runners
                        + movers_data.get("gainers", [])
                        + movers_data.get("losers", [])
                        + movers_data.get("exhaustion", [])
                    )
                    update_live_movers_ledger_outcomes(
                        universe=universe,
                        live_movers_items=fresh_mover_items,
                        now_dt=ist_now,
                    )
                    # At >= 15:30 IST, ensure Live Movers EOD Audit is dispatched to NSE Live - Live Mover VIP bot
                    if t_now >= dtime(15, 30):
                        nifty_dir = (_V13_SCAN_RESULT.get("market_context") or {}).get("nifty_direction", "Neutral") if _V13_SCAN_RESULT else "Neutral"
                        dispatch_live_movers_eod_audit(
                            market_regime=nifty_dir,
                            universe=universe,
                            now_dt=ist_now,
                        )
        except Exception as e:
            logger.warning(f"Error in live movers telegram background worker: {e}")

        time.sleep(60)


def _get_v13_nifty_data():
    """Return short-lived cached NIFTY intraday data for the V13 scanner."""
    global _V13_NIFTY_CACHE, _V13_NIFTY_CACHE_AT

    now = time.monotonic()

    with _V13_NIFTY_CACHE_LOCK:
        if (
            _V13_NIFTY_CACHE is not None
            and now - _V13_NIFTY_CACHE_AT < V13_NIFTY_CACHE_TTL_SECONDS
        ):
            return _V13_NIFTY_CACHE.copy()

    downloaded = yf.download(
        "^NSEI",
        period="1mo",
        interval="15m",
        group_by="ticker",
        threads=False,
        progress=False,
        timeout=15,
    )

    if downloaded is None or downloaded.empty:
        return downloaded

    with _V13_NIFTY_CACHE_LOCK:
        _V13_NIFTY_CACHE = downloaded.copy()
        _V13_NIFTY_CACHE_AT = time.monotonic()
        return _V13_NIFTY_CACHE.copy()


app = FastAPI(
    title="NSE Intraday Screener & Trade Signal Generator API",
    description="High-performance screening microservice for Nifty 500 stocks with 20 EMA, 14 RSI, RelVol, and dynamic trade levels.",
    version="2.0.0"
)

# Enable CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    """Trigger initial background scan warmup and start continuous scanner daemon."""
    global _V13_SCAN_RUNNING, _V13_SCAN_THREAD, _V13_SCAN_RESULT, _V13_SCAN_RESULT_AT, _V13_SCAN_GENERATED_AT

    # 1. Start continuous scanner daemon (only scans during market hours)
    threading.Thread(
        target=_v13_continuous_loop,
        name="v13-continuous-scan-daemon",
        daemon=True,
    ).start()

    # 2. Immediately hydrate from EOD disk snapshot
    snapshot = _load_eod_snapshot()
    if snapshot:
        with _V13_SCAN_LOCK:
            _V13_SCAN_RESULT = snapshot
            _V13_SCAN_RESULT_AT = time.monotonic()
            _V13_SCAN_GENERATED_AT = snapshot.get("generated_at")
        try:
            snap_cands = snapshot.get("candidates", [])
            if snap_cands:
                dispatch_telegram_alerts(
                    snap_cands,
                    market_context=snapshot.get("market_context"),
                    universe=snapshot.get("universe"),
                )
        except Exception as _ste:
            logger.debug(f"Startup telegram alert check skipped: {_ste}")

    # 3. Only kick off background scan on startup if market is actively OPEN
    status = get_market_status()
    with _V13_SCAN_LOCK:
        if not _V13_SCAN_RUNNING and status.is_open:
            _V13_SCAN_RUNNING = True
            _V13_SCAN_STARTED_AT = time.monotonic()
            _V13_SCAN_THREAD = threading.Thread(
                target=_run_v13_scan_background,
                name="v13-scan-worker-startup",
                daemon=True,
            )
            _V13_SCAN_THREAD.start()

    # 4. Start dedicated Live Movers Telegram Bot background worker (every 60s during 09:15 - 15:00 IST)
    threading.Thread(
        target=_v13_live_movers_telegram_loop,
        name="v13-live-movers-tg-daemon",
        daemon=True,
    ).start()

    # 5. Start isolated NIFTY 50 Intraday Options Quant background worker (Tab 4 paper tracking)
    threading.Thread(
        target=_v13_nifty_options_daemon_loop,
        name="v13-nifty-options-quant-daemon",
        daemon=True,
    ).start()


@app.get("/")
def root():
    return {
        "service": "NSE Intraday Screener & Trade Signal Generator API",
        "status": "online",
        "market": "National Stock Exchange of India (NSE)",
        "index": "Nifty 500",
        "universe_size": 500,
        "endpoints": ["/api/screener", "/api/market-status", "/api/stocks/{symbol}/history", "/api/sectors"]
    }


@app.get("/api/health")
def health_check():
    return {"status": "healthy"}


@app.get("/api/market-status", response_model=MarketStatus)
def market_status_endpoint(mode: Optional[str] = Query(None, description="'live' or 'simulation'")):
    """Returns the current Indian Standard Time (IST) and market open/close state."""
    return get_market_status(forced_mode=mode)


@app.get("/api/sectors", response_model=List[str])
def get_sectors():
    """Returns the list of unique sectors/industries across Nifty 500."""
    return SECTORS


@app.get("/api/screener", response_model=ScreenerResponse)
def get_screener_data(
    mode: str = Query("live", description="Data mode: 'live' or 'simulation'"),
    sector: Optional[str] = Query(None, description="Filter by sector name"),
    force_refresh: bool = Query(False, description="Bypass cache and recalculate")
):
    """
    Scans all 500 constituents of Nifty 500 on the 15m timeframe.
    Evaluates:
    1. Volatility & Momentum (Change >= +1.5% or <= -1.5%)
    2. Relative Volume (RelVol >= 1.5)
    3. Trend Confirmation (Price vs 20 EMA and RSI > 50 / < 50)
    Ranks stocks by:
    1. Active Signals First
    2. RelVol (Descending)
    3. |Price Change %| (Descending)
    """
    if force_refresh:
        _CACHE["screener_data"] = None
        _CACHE["cache_time"] = 0

    return run_screener(mode=mode, sector_filter=sector)


@app.get("/api/stocks/{symbol}/history", response_model=StockHistoryResponse)
def get_stock_history(symbol: str):
    """
    Returns 15m OHLCV candle series, 20 EMA line points, RSI points,
    and trade levels for TradingView Lightweight Charts rendering.
    """
    data = get_stock_history_and_indicators(symbol)
    if not data:
        raise HTTPException(status_code=404, detail=f"Stock data for symbol '{symbol}' not found")
    return data

@app.get("/api/predictions", response_model=PredictionResponse)
def get_predictions():
    """
    Scan Nifty 500 and return the strongest prediction setups.

    Market and sector context is fetched once per scan and reused
    across all stocks.
    """

    import yfinance as yf
    from datetime import datetime

    setups = []

    # ---------------------------------------------------------
    # Build market + sector context ONCE
    # ---------------------------------------------------------

    sectors = list(
        {
            stock["sector"]
            for stock in NIFTY_500_STOCKS
            if stock.get("sector")
        }
    )

    context_cache = build_live_context_cache(sectors)

    # ---------------------------------------------------------
    # Scan stocks
    # ---------------------------------------------------------

    for stock in NIFTY_500_STOCKS:
        symbol = stock["symbol"]
        sector = stock.get("sector", "")

        try:
            df = yf.Ticker(
                f"{symbol}.NS"
            ).history(
                period="5d",
                interval="15m"
            )

            if df is None or df.empty:
                continue

            context = context_cache.get(sector)

            setup = evaluate_prediction_setup(
                symbol=symbol,
                name=stock["name"],
                sector=sector,
                df=df,
                context=context,
            )

            if setup is not None:
                setups.append(setup)

                # ---------------------------------------------------------
                # V12 PAPER / SHADOW TRADING
                # ---------------------------------------------------------
                if (
                    qualifies_for_v12(setup)
                    and not is_duplicate_signal(setup)
                ):
                    signal_id = record_prediction(setup)
                    print(
                        f"V12 PAPER SIGNAL: {signal_id} | "
                        f"{setup.symbol} | "
                        f"Score {setup.confidence_score:.1f} | "
                        f"{setup.last_updated}"
                    )

        except Exception as e:
            print(
                f"Prediction scan failed for {symbol}: {e}"
            )

    # ---------------------------------------------------------
    # Highest setup score first
    # ---------------------------------------------------------

    setups.sort(
        key=lambda setup: setup.confidence_score,
        reverse=True
    )

    # Keep only top 5
    top_setups = setups[:5]

    return PredictionResponse(
        market_status=get_market_status(),
        scan_time=datetime.now(
            IST_TZ
        ).strftime(
            "%d %b %Y, %I:%M:%S %p IST"
        ),
        total_scanned=len(NIFTY_500_STOCKS),
        setups_found=len(top_setups),
        top_setups=top_setups
    )
    
@app.get("/api/paper-trading")
def get_paper_trading_data():
    """
    Return current paper/shadow trading records.

    No real orders are placed.
    """

    all_trades = get_all_paper_trades()
    open_trades = get_open_paper_trades()

    closed_trades = [
        trade
        for trade in all_trades
        if trade.get("status") != "OPEN"
    ]

    wins = [
        trade
        for trade in closed_trades
        if trade.get("outcome") in ("T1_FIRST", "T2_FIRST")
    ]

    losses = [
        trade
        for trade in closed_trades
        if trade.get("outcome") == "SL_FIRST"
    ]

    total_r = 0.0

    for trade in closed_trades:
        try:
            total_r += float(trade.get("realized_r", 0) or 0)
        except (TypeError, ValueError):
            pass

    return {
        "mode": "PAPER_TRADING",
        "real_orders": False,
        "total_trades": len(all_trades),
        "open_trades": len(open_trades),
        "closed_trades": len(closed_trades),
        "wins": len(wins),
        "losses": len(losses),
        "total_realized_r": round(total_r, 2),
        "trades": all_trades,
    }


@app.get("/api/v13/scan")
def get_v13_scan(
    force: bool = Query(False, description="Force a background refresh")
):
    try:
        global _V13_SCAN_RESULT, _V13_SCAN_RESULT_AT, _V13_SCAN_GENERATED_AT
        global _V13_SCAN_RUNNING, _V13_SCAN_THREAD, _V13_SCAN_STARTED_AT

        now = time.monotonic()
        market_open = get_market_status().is_open

        today_str = datetime.now(IST_TZ).strftime("%Y-%m-%d")

        with _V13_SCAN_LOCK:
            cached_result = _V13_SCAN_RESULT

            # Morning Rollover check: If in-memory result has expired, discard it!
            if cached_result is not None:
                cached_date = _get_snapshot_session_date(cached_result)
                if not _is_snapshot_active(cached_date, datetime.now(IST_TZ)):
                    _V13_SCAN_RESULT = None
                    _V13_SCAN_RESULT_AT = 0.0
                    _V13_SCAN_GENERATED_AT = None
                    cached_result = None

            # Watchdog reset if previous worker timed out
            if _V13_SCAN_RUNNING and (now - _V13_SCAN_STARTED_AT > V13_MAX_SCAN_LOCK_SECONDS):
                _V13_SCAN_RUNNING = False
                _V13_SCAN_THREAD = None

            cached_at = _V13_SCAN_RESULT_AT
            running = _V13_SCAN_RUNNING

            has_result = cached_result is not None
            is_fresh = has_result and (now - cached_at < V13_SCAN_CACHE_TTL_SECONDS)

            # If market is closed, only refresh when explicitly forced by user
            if not market_open:
                should_refresh = force
            else:
                should_refresh = force or not is_fresh

            if should_refresh and not running:
                _V13_SCAN_RUNNING = True
                _V13_SCAN_STARTED_AT = time.monotonic()
                # Off-market speedup: When market is closed, candles are frozen at 15:30.
                # Do NOT clear cache or redownload 1,468 stocks over the internet (takes ~90s).
                # Re-evaluating with cached data completes in ~2-3 seconds with updated live timestamp!
                worker_force_fresh = force if market_open else False
                _V13_SCAN_THREAD = threading.Thread(
                    target=_run_v13_scan_background,
                    kwargs={"force_fresh": worker_force_fresh, "is_eod_final": False},
                    name="v13-scan-worker",
                    daemon=True,
                )
                _V13_SCAN_THREAD.start()
                running = True

            result = cached_result

        # Synchronized Ledger Rollover: keep session ledger in exact lockstep with screener
        try:
            GLOBAL_SESSION_LEDGER._check_rollover()
        except Exception:
            pass

        # Intelligent EOD Snapshot Hydration:
        # Prioritize disk snapshot ONLY when:
        # 1. result is None (server just booted or memory uninitialized)
        # 2. Disk snapshot is strictly newer than current memory result
        disk_data = _load_eod_snapshot()
        disk_gen_at = (disk_data.get("generated_at") or "") if disk_data else ""
        mem_gen_at = (_V13_SCAN_GENERATED_AT or "")
        disk_is_newer = bool(disk_gen_at and (not mem_gen_at or disk_gen_at > mem_gen_at))

        # Do NOT overwrite fresh memory result with older disk snapshot!
        if disk_data and not _V13_SCAN_RUNNING and (result is None or disk_is_newer):
            result = disk_data
            with _V13_SCAN_LOCK:
                _V13_SCAN_RESULT = disk_data
                _V13_SCAN_RESULT_AT = time.monotonic()
                _V13_SCAN_GENERATED_AT = disk_data.get("generated_at")

        if result is None and market_open:
            start_wait = time.monotonic()
            while time.monotonic() - start_wait < 25.0:
                time.sleep(0.5)
                with _V13_SCAN_LOCK:
                    result = _V13_SCAN_RESULT
                if result is not None:
                    break

        ms = get_market_status()
        ms_dict = _to_dict_safe(ms)

        if result is None:
            today_str = datetime.now(IST_TZ).strftime("%Y-%m-%d")
            premarket_u = _get_premarket_universe()
            return {
                "market_status": "LIVE" if ms.is_open else "CLOSED",
                "market_status_details": ms_dict,
                "market_regime": None,
                "generated_at": _V13_SCAN_GENERATED_AT or datetime.now(IST_TZ).isoformat(),
                "is_scanning": bool(_V13_SCAN_RUNNING),
                "bullish": [],
                "bearish": [],
                "watchlist": [],
                "trade_ready": [],
                "diagnostic_signals": [],
                "universe": premarket_u,
                "warming_up": True if ms.is_open else False,
            }

        generated_at = _V13_SCAN_GENERATED_AT or datetime.now(IST_TZ).isoformat()

        candidates = result.get("candidates", [])
        diagnostic_signals = result.get("diagnostic_signals", [])
        universe = result.get("universe", [])

        def get_cand_dir(c):
            if isinstance(c, dict):
                return str(c.get("signal_type") or c.get("direction") or "").upper()
            return str(getattr(c, "signal_type", getattr(c, "direction", ""))).upper()

        bullish = [candidate for candidate in candidates if get_cand_dir(candidate) == "BULLISH"]
        bearish = [candidate for candidate in candidates if get_cand_dir(candidate) == "BEARISH"]

        watchlist = candidates
        trade_ready = []

        return {
            "market_status": "LIVE" if ms.is_open else "CLOSED",
            "market_status_details": ms_dict,
            "market_regime": (result.get("market_context") or {}).get("nifty_direction"),
            "generated_at": generated_at,
            "is_scanning": bool(_V13_SCAN_RUNNING),
            "bullish": bullish,
            "bearish": bearish,
            "watchlist": watchlist,
            "trade_ready": trade_ready,
            "diagnostic_signals": diagnostic_signals,
            "universe": universe,
        }
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v13/live-movers")
def get_v13_live_movers(
    category: str = Query("COMBINED", description="Index/Category filter: COMBINED, ALL, NIFTY_50, BANK_NIFTY, NIFTY_NEXT_50, FNO, ABOVE_20, BELOW_20"),
    force: bool = Query(False, description="Bypass in-memory cache and fetch fresh variations from NSE")
):
    """
    Independent endpoint for NSE Live Top Movers (Gainers & Losers).
    Processes live universe with 4-Tier Quant Filtration, 20-EMA High-Tight Flag
    execution engine, category/index filtering, and session registry.
    """
    try:
        from .v13_live_movers import compute_live_top_movers

        universe, candidates = _get_active_universe_and_candidates()
        result = compute_live_top_movers(universe, df_cache=None, category=category, force=force, v13_candidates=candidates)

        if category == "V13_ACTIVE":
            runners = result.get("runners", [])
            short_runners = result.get("short_runners", [])
            if runners or short_runners:
                try:
                    from .v13_live_movers_telegram import dispatch_live_movers_alerts
                    market_ctx = _V13_SCAN_RESULT.get("market_context") if _V13_SCAN_RESULT else None
                    dispatch_live_movers_alerts(
                        runners, 
                        short_runners,
                        market_context=market_ctx,
                        universe=universe,
                    )
                except Exception as tge:
                    logger.debug(f"Live movers telegram dispatch skipped on API request: {tge}")

        return result
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v13/market-pulse")
async def get_v13_market_pulse(force: bool = Query(False, description="Bypass in-memory cache and re-evaluate")):
    """
    Quantitative Market Environment Filter & Structural Playbook (Idea #1 + Idea #2).
    Evaluates:
      1. Idea #2: Live Intraday Tradeability & Chop Score (0-100, Traffic Light, Position Sizing)
      2. Idea #1: Next-Day / Pre-Market Structural Bias & Static Conditional Execution Zones
    Zero impact on existing scanner engine. Reads universe from RAM in < 1ms.
    """
    try:
        from .v13_market_pulse import compute_v13_market_pulse
        import asyncio

        universe, _ = _get_active_universe_and_candidates()
        market_ctx = _V13_SCAN_RESULT.get("market_context") if _V13_SCAN_RESULT else None
        with _V13_NIFTY_CACHE_LOCK:
            nifty_fallback = _V13_NIFTY_CACHE.copy() if _V13_NIFTY_CACHE is not None else None

        result = await asyncio.to_thread(
            compute_v13_market_pulse,
            universe=universe,
            market_context=market_ctx,
            force_refresh=force,
            fallback_nifty_df=nifty_fallback,
        )
        return result
    except Exception as exc:
        logger.error(f"Error computing v13_market_pulse: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v13/live-movers/test-telegram")
def test_live_movers_telegram():
    """Trigger a live test verification ping to all configured Live Movers Telegram chat IDs."""
    from .v13_live_movers_telegram import send_live_movers_test_ping
    return send_live_movers_test_ping()


@app.get("/api/v13/eod-audit")
def get_v13_eod_audit(
    send_telegram: bool = Query(False, description="Dispatch V13 EOD Audit to PulseX1000 Telegram Bot"),
    force: bool = Query(False, description="Force re-dispatch even if already sent today"),
):
    """
    Return the live Session Trade Ledger metrics and EOD Performance Audit.
    If send_telegram=True, dispatches the formatted audit message to the V13 PulseX1000 Telegram bot.
    """
    metrics = GLOBAL_SESSION_LEDGER.get_summary_metrics()
    nifty_dir = (_V13_SCAN_RESULT.get("market_context") or {}).get("nifty_direction", "Neutral") if _V13_SCAN_RESULT else "Neutral"
    report_text = GLOBAL_SESSION_LEDGER.format_telegram_eod_report(market_regime=nifty_dir)

    telegram_sent = False
    if send_telegram:
        telegram_sent = GLOBAL_SESSION_LEDGER.dispatch_eod_audit(market_regime=nifty_dir, force=force)

    return {
        "metrics": metrics,
        "report_text": report_text,
        "telegram_sent": telegram_sent,
    }


@app.get("/api/v13/live-movers/eod-audit")
def get_live_movers_eod_audit_endpoint(
    send_telegram: bool = Query(False, description="Dispatch Live Movers EOD Audit to NSE Live - Live Mover VIP Bot"),
    force: bool = Query(False, description="Force re-dispatch even if already sent today"),
    session_date: Optional[str] = Query(None, description="Optional target date YYYY-MM-DD"),
):
    """
    Return the NSE Live Movers Session Ledger metrics and EOD Performance Audit.
    If send_telegram=True, dispatches the formatted audit report exclusively to the
    dedicated 'NSE Live - Live Mover VIP' Telegram bot.
    """
    from .v13_live_movers_telegram import (
        get_live_movers_eod_metrics,
        format_live_movers_eod_report,
        dispatch_live_movers_eod_audit,
        update_live_movers_ledger_outcomes,
    )
    universe, _ = _get_active_universe_and_candidates()
    if universe and not session_date:
        update_live_movers_ledger_outcomes(universe=universe)

    nifty_dir = (_V13_SCAN_RESULT.get("market_context") or {}).get("nifty_direction", "Neutral") if _V13_SCAN_RESULT else "Neutral"
    metrics = get_live_movers_eod_metrics(session_date=session_date)
    report_text = format_live_movers_eod_report(session_date=session_date, market_regime=nifty_dir)

    telegram_sent = False
    if send_telegram:
        telegram_sent = dispatch_live_movers_eod_audit(
            market_regime=nifty_dir,
            universe=universe,
            force=force,
        )

    return {
        "metrics": metrics,
        "report_text": report_text,
        "telegram_sent": telegram_sent,
    }


@app.get("/api/v13/weekly-audit")
def get_v13_weekly_audit(
    send_telegram: bool = Query(False, description="Dispatch Weekly Audit to Telegram"),
    target_date: Optional[str] = Query(None, description="Optional target date YYYY-MM-DD"),
):
    """
    Return the official Quantitative Weekly EOD Performance Audit.
    If send_telegram=True, dispatches the formatted audit report to configured Telegram chats.
    """
    from .v13_weekly_audit import generate_weekly_eod_report, dispatch_weekly_audit_to_telegram
    target_dt = None
    if target_date:
        try:
            target_dt = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=IST_TZ)
        except Exception:
            pass

    report_text, summary_data = generate_weekly_eod_report(target_dt)
    telegram_sent = False
    if send_telegram:
        telegram_sent = dispatch_weekly_audit_to_telegram(target_dt)
        if telegram_sent:
            ist_now = target_dt or datetime.now(IST_TZ)
            current_week_str = f"{ist_now.year}-W{ist_now.isocalendar()[1]:02d}"
            GLOBAL_SESSION_LEDGER.weekly_audit_sent_week = current_week_str
            GLOBAL_SESSION_LEDGER._save_to_disk()

    return {
        "summary": summary_data,
        "report_text": report_text,
        "telegram_sent": telegram_sent,
    }


@app.get("/api/v13/telegram-history")
def get_v13_telegram_history(
    date: Optional[str] = Query(None, description="Session date YYYY-MM-DD (defaults to effective session date)")
):
    """
    Retrieve archived Telegram alerts with complete metadata and trade outcomes.
    """
    from .telegram_bot import get_archived_telegram_alerts
    target_date = date or get_effective_trading_date()
    alerts = get_archived_telegram_alerts(target_date)
    return {
        "date": target_date,
        "total_alerts": len(alerts),
        "alerts": alerts,
    }


@app.get("/api/v13/sync-ledger")
def get_v13_sync_ledger():
    """
    Returns Yahoo Candle Sync Latency & Live Trigger Precision Audit Ledger.
    Tracks T1 (Candle Close), T2 (Yahoo Delivery), T3 (Screener Alert), and T4 (Running Bar Mid-Candle Progress).
    """
    from .v13_sync_ledger import GLOBAL_SYNC_LEDGER
    return GLOBAL_SYNC_LEDGER.get_ledger_data()


@app.get("/api/v13/conviction-audit")
def get_v13_conviction_audit(
    send_telegram: bool = Query(False, description="Dispatch 2nd Conviction Audit to Telegram")
):
    """
    Returns the Conviction Drift & Regime Decay Audit metrics.
    If send_telegram=True, dispatches the dedicated 2nd audit card directly to Telegram.
    """
    from .v13_conviction_audit import GLOBAL_CONVICTION_AUDITOR
    if send_telegram:
        GLOBAL_CONVICTION_AUDITOR.dispatch_eod_drift_audit()
    return GLOBAL_CONVICTION_AUDITOR.get_audit_summary()


@app.get("/api/v13/shadow-portfolio")
def get_v13_shadow_portfolio(
    send_telegram: bool = Query(False, description="Dispatch 3rd Shadow Portfolio EOD Audit to Telegram")
):
    """
    Returns Autonomous Conviction Shadow Portfolio state, positions, and compounding metrics.
    If send_telegram=True, dispatches the dedicated 3rd audit scorecard directly to Telegram.
    """
    from .v13_shadow_portfolio import GLOBAL_SHADOW_PORTFOLIO
    if send_telegram:
        GLOBAL_SHADOW_PORTFOLIO.dispatch_eod_shadow_audit()
    return GLOBAL_SHADOW_PORTFOLIO.get_portfolio_summary()


@app.post("/api/v13/shadow-portfolio/reset")
def reset_v13_shadow_portfolio():
    """Reset shadow portfolio in-memory and on-disk state to clean starting capital."""
    from .v13_shadow_portfolio import GLOBAL_SHADOW_PORTFOLIO
    with GLOBAL_SHADOW_PORTFOLIO._lock:
        GLOBAL_SHADOW_PORTFOLIO._trading_capital = 100000.0
        GLOBAL_SHADOW_PORTFOLIO._secured_vault = 0.0
        GLOBAL_SHADOW_PORTFOLIO._open_trades.clear()
        GLOBAL_SHADOW_PORTFOLIO._closed_trades.clear()
        GLOBAL_SHADOW_PORTFOLIO._seen_symbols_today.clear()
        GLOBAL_SHADOW_PORTFOLIO._save_atomic()
    return {"status": "success", "message": "Shadow portfolio reset to clean ₹1,00,000 baseline."}


# ==============================================================================
# ISOLATED 4TH TAB MODULE: NIFTY 50 INTRADAY OPTIONS BUYING QUANT ENGINE (v2.3)
# ==============================================================================

def _v13_nifty_options_daemon_loop():
    """
    Isolated background daemon that tracks NIFTY 50 Options paper trades during
    market hours (09:15 - 15:30 IST) when Fyers is connected or an open paper
    trade is active, without touching any V13 equity scanner state.
    """
    time.sleep(12)
    while True:
        try:
            ist_now = datetime.now(IST_TZ)
            t_now = ist_now.time()
            is_weekday = ist_now.weekday() < 5
            if is_weekday and dtime(9, 15) <= t_now <= dtime(15, 30):
                from .v13_nifty_options_data import GLOBAL_NIFTY_OPTIONS_DATA
                from .v13_nifty_options_engine import evaluate_nifty_options_quant_pipeline
                from .v13_nifty_options_ledger import GLOBAL_NIFTY_OPTIONS_LEDGER

                fyers_st = GLOBAL_NIFTY_OPTIONS_DATA.get_fyers_status()
                ledger_st = GLOBAL_NIFTY_OPTIONS_LEDGER.get_ledger_summary()
                if fyers_st.get("connected") or ledger_st.get("open_trade") is not None:
                    prefs = GLOBAL_NIFTY_OPTIONS_DATA.get_sizing_preferences()
                    bundle = GLOBAL_NIFTY_OPTIONS_DATA.get_market_bundle(force_refresh=False)
                    eval_res = evaluate_nifty_options_quant_pipeline(
                        market_bundle=bundle,
                        capital_inr=prefs["capital_inr"],
                        risk_mode=prefs["risk_mode"],
                        risk_value=prefs["risk_value"],
                        lot_size=prefs["lot_size"],
                        now_dt=ist_now,
                    )
                    GLOBAL_NIFTY_OPTIONS_LEDGER.process_quant_evaluation(eval_res, now_dt=ist_now)
        except Exception as e:
            logger.debug(f"Isolated Nifty Options daemon tick skipped: {e}")

        # Fast 5s tracking if open trade is active, else 15s
        sleep_sec = 5 if (locals().get("ledger_st") and ledger_st.get("open_trade") is not None) else 15
        time.sleep(sleep_sec)


@app.get("/api/v13/nifty-options/dashboard")
def get_v13_nifty_options_dashboard(
    capital_inr: Optional[float] = Query(None, description="Trading Capital in INR (Universal)"),
    risk_mode: Optional[str] = Query(None, description="'PERCENT' or 'FIXED_INR'"),
    risk_value: Optional[float] = Query(None, description="Risk % (e.g. 2.0) or Fixed INR (e.g. 1500)"),
    lot_size: Optional[int] = Query(None, description="NIFTY Lot Size (default 75)"),
    force_refresh: bool = Query(False, description="Bypass 20s market data cache"),
):
    """
    Master endpoint for the 4th Tab (`🎯 Nifty 50 Options`).
    Returns Fyers connection status, 4 Hard Regime Gates, Smart Strike Selection,
    Entry Triggers, Universal Position Sizing, Option Chain Window, and Paper Ledger.
    """
    from .v13_nifty_options_data import GLOBAL_NIFTY_OPTIONS_DATA
    from .v13_nifty_options_engine import evaluate_nifty_options_quant_pipeline
    from .v13_nifty_options_ledger import GLOBAL_NIFTY_OPTIONS_LEDGER

    if any(x is not None for x in (capital_inr, risk_mode, risk_value, lot_size)):
        prefs = GLOBAL_NIFTY_OPTIONS_DATA.update_sizing_preferences(
            capital_inr=capital_inr,
            risk_mode=risk_mode,
            risk_value=risk_value,
            lot_size=lot_size,
        )
    else:
        prefs = GLOBAL_NIFTY_OPTIONS_DATA.get_sizing_preferences()

    bundle = GLOBAL_NIFTY_OPTIONS_DATA.get_market_bundle(force_refresh=force_refresh)
    now_ist = datetime.now(IST_TZ)
    eval_res = evaluate_nifty_options_quant_pipeline(
        market_bundle=bundle,
        capital_inr=prefs["capital_inr"],
        risk_mode=prefs["risk_mode"],
        risk_value=prefs["risk_value"],
        lot_size=prefs["lot_size"],
        now_dt=now_ist,
    )
    ledger_summary = GLOBAL_NIFTY_OPTIONS_LEDGER.process_quant_evaluation(eval_res, now_dt=now_ist)

    return {
        "status": "ok",
        "fyers_status": GLOBAL_NIFTY_OPTIONS_DATA.get_fyers_status(),
        "sizing_preferences": prefs,
        "quant_engine": eval_res,
        "paper_ledger": ledger_summary,
    }


@app.post("/api/v13/nifty-options/fyers-auth")
def post_v13_nifty_options_fyers_auth(payload: dict):
    """
    Save Fyers Non-Trading App (`NSE Paper Trade Lab`) credentials and/or exchange
    daily OAuth `auth_code` (or redirected `https://127.0.0.1/?auth_code=...` URL)
    for today's `access_token`.
    """
    from .v13_nifty_options_data import GLOBAL_NIFTY_OPTIONS_DATA

    return GLOBAL_NIFTY_OPTIONS_DATA.configure_fyers_And_exchange_token(
        app_id=payload.get("app_id"),
        secret_id=payload.get("secret_id"),
        redirect_uri=payload.get("redirect_uri"),
        auth_code_or_url=payload.get("auth_code_or_url"),
        direct_access_token=payload.get("direct_access_token"),
    )


@app.post("/api/v13/nifty-options/sizing")
def post_v13_nifty_options_sizing(payload: dict):
    """Update Universal Capital & Risk preferences dynamically."""
    from .v13_nifty_options_data import GLOBAL_NIFTY_OPTIONS_DATA

    prefs = GLOBAL_NIFTY_OPTIONS_DATA.update_sizing_preferences(
        capital_inr=payload.get("capital_inr"),
        risk_mode=payload.get("risk_mode"),
        risk_value=payload.get("risk_value"),
        lot_size=payload.get("lot_size"),
    )
    return {"status": "ok", "sizing_preferences": prefs}


@app.post("/api/v13/nifty-options/paper-trade/enter")
def post_v13_nifty_options_paper_enter():
    """Manually open a paper trade on the currently selected contract for live/study tracking."""
    from .v13_nifty_options_data import GLOBAL_NIFTY_OPTIONS_DATA
    from .v13_nifty_options_engine import evaluate_nifty_options_quant_pipeline
    from .v13_nifty_options_ledger import GLOBAL_NIFTY_OPTIONS_LEDGER

    prefs = GLOBAL_NIFTY_OPTIONS_DATA.get_sizing_preferences()
    bundle = GLOBAL_NIFTY_OPTIONS_DATA.get_market_bundle(force_refresh=False)
    now_ist = datetime.now(IST_TZ)
    eval_res = evaluate_nifty_options_quant_pipeline(
        market_bundle=bundle,
        capital_inr=prefs["capital_inr"],
        risk_mode=prefs["risk_mode"],
        risk_value=prefs["risk_value"],
        lot_size=prefs["lot_size"],
        now_dt=now_ist,
    )
    return GLOBAL_NIFTY_OPTIONS_LEDGER.enter_paper_trade_from_eval(
        eval_res,
        source="MANUAL_PAPER_EXECUTION",
        now_dt=now_ist,
    )


@app.post("/api/v13/nifty-options/paper-trade/close")
def post_v13_nifty_options_paper_close():
    """Manually square-off the currently open paper trade at live LTP."""
    from .v13_nifty_options_data import GLOBAL_NIFTY_OPTIONS_DATA
    from .v13_nifty_options_engine import evaluate_nifty_options_quant_pipeline
    from .v13_nifty_options_ledger import GLOBAL_NIFTY_OPTIONS_LEDGER

    prefs = GLOBAL_NIFTY_OPTIONS_DATA.get_sizing_preferences()
    bundle = GLOBAL_NIFTY_OPTIONS_DATA.get_market_bundle(force_refresh=False)
    now_ist = datetime.now(IST_TZ)
    eval_res = evaluate_nifty_options_quant_pipeline(
        market_bundle=bundle,
        capital_inr=prefs["capital_inr"],
        risk_mode=prefs["risk_mode"],
        risk_value=prefs["risk_value"],
        lot_size=prefs["lot_size"],
        now_dt=now_ist,
    )
    return GLOBAL_NIFTY_OPTIONS_LEDGER.close_open_trade_manual(
        current_eval=eval_res,
        reason="MANUAL_USER_EXIT",
        now_dt=now_ist,
    )


@app.post("/api/v13/nifty-options/paper-trade/reset")
def post_v13_nifty_options_paper_reset():
    """Reset today's Nifty Options paper trading ledger."""
    from .v13_nifty_options_ledger import GLOBAL_NIFTY_OPTIONS_LEDGER

    return {
        "status": "ok",
        "message": "Today's Nifty Options paper ledger reset.",
        "ledger": GLOBAL_NIFTY_OPTIONS_LEDGER.reset_today_ledger(),
    }


@app.get("/api/v13/nifty-options/ledger/sessions")
def get_v13_nifty_options_ledger_sessions(
    capital_inr: Optional[float] = Query(None, description="Committed Frontend Trading Capital in INR for ROI % calculation"),
    from_date: Optional[str] = Query(None, description="Optional start session_date (YYYY-MM-DD) for cumulative stats calculation"),
):
    """List all available historical & live Nifty Options paper ledger sessions with ROI % and cumulative stats."""
    from .v13_nifty_options_data import GLOBAL_NIFTY_OPTIONS_DATA
    from .v13_nifty_options_ledger import GLOBAL_NIFTY_OPTIONS_LEDGER

    prefs = GLOBAL_NIFTY_OPTIONS_DATA.get_sizing_preferences()
    eff_cap = (
        float(capital_inr)
        if (capital_inr is not None and float(capital_inr) > 0)
        else float(prefs.get("capital_inr", 100000.0))
    )
    return GLOBAL_NIFTY_OPTIONS_LEDGER.list_available_sessions(capital_inr=eff_cap, from_date=from_date)


@app.get("/api/v13/nifty-options/ledger/history")
def get_v13_nifty_options_ledger_history(
    session_date: str = Query(..., description="Session date in YYYY-MM-DD format"),
):
    """Fetch read-only paper ledger summary and closed trades for a specific historical session date."""
    from .v13_nifty_options_ledger import GLOBAL_NIFTY_OPTIONS_LEDGER

    try:
        ledger_data = GLOBAL_NIFTY_OPTIONS_LEDGER.get_historical_ledger_summary(session_date=session_date)
        return {"status": "ok", "paper_ledger": ledger_data}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))


@app.post("/api/v13/nifty-options/test-alert")
def post_v13_nifty_options_test_alert():
    """Trigger a live diagnostic test alert across all configured Alpha Telegram recipients."""
    from .v13_alpha_telegram import dispatch_alpha_test_alert

    res = dispatch_alpha_test_alert()
    return {
        "status": res.get("status", "ok"),
        "delivery": res,
    }


