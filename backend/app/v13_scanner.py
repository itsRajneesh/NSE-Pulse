from __future__ import annotations

from typing import Dict, Iterable, Any
import json
import time
import threading
import pandas as pd
import numpy as np
import yfinance as yf


V13_HISTORY_PERIOD = "1mo"
V13_INTERVAL = "15m"
V13_DOWNLOAD_CHUNK_SIZE = 50
V13_MIN_SESSIONS = 3
V13_CACHE_TTL_LIVE_SECONDS = 120
V13_CACHE_TTL_CLOSED_SECONDS = 300
V13_CACHE_TTL_SECONDS = 300  # Backward-compatible alias for existing test suites
V13_DOWNLOAD_MAX_RETRIES = 1
V13_RETRY_BASE_DELAY_SECONDS = 0.5


def _get_v13_cache_ttl() -> float:
    """Dynamic cache TTL: respects overridden V13_CACHE_TTL_SECONDS (e.g. in tests); else 120s during live market hours, 300s off-market."""
    if V13_CACHE_TTL_SECONDS != 300:
        return float(V13_CACHE_TTL_SECONDS)
    try:
        now_ist = pd.Timestamp.now(tz="Asia/Kolkata")
        if now_ist.weekday() < 5:
            mkt_start = pd.Timestamp("09:15").time()
            mkt_end = pd.Timestamp("15:36").time()  # Keep 120s TTL active through 15:30-15:36 settlement scan window
            curr_time = now_ist.time()
            if mkt_start <= curr_time <= mkt_end:
                return float(V13_CACHE_TTL_LIVE_SECONDS)
    except Exception:
        pass
    return float(V13_CACHE_TTL_CLOSED_SECONDS)


import os
import logging

logger = logging.getLogger("v13_scanner")

from app.v13_engine import (
    discover_v13_setups,
    evaluate_v13_diagnostic,
    _evaluate_direction,
    V13Candidate,
    _classification,
    WATCH_SCORE,
    _safe_float,
    _opening_range,
    _previous_day_levels,
    _normalise_columns,
    _ema,
    _rsi,
    _atr,
    _latest_session,
    _previous_session,
    _session_vwap,
    _relative_volume,
    _true_velocity,
)
from app.v13_market_context import build_nifty_context

_V13_CACHE: dict[tuple[str, str, str], tuple[float, pd.DataFrame]] = {}
_V13_CACHE_LOCK = threading.Lock()


def clear_v13_cache() -> None:
    """Flush the in-memory cache to force a fresh download of newly closed candles (e.g. for 15:30 Bar 25 final scan)."""
    with _V13_CACHE_LOCK:
        _V13_CACHE.clear()


def get_v13_cached_df(ticker: str) -> pd.DataFrame | None:
    """Retrieve an existing 15m DataFrame from _V13_CACHE if available (for instant 0ms chart drawer response)."""
    with _V13_CACHE_LOCK:
        key = (ticker, V13_HISTORY_PERIOD, V13_INTERVAL)
        item = _V13_CACHE.get(key)
        if item is not None:
            _, df = item
            if df is not None and not df.empty:
                return df.copy()
    return None


_SHORTABLE_SYMBOLS_CACHE: set[str] = set()
_SHORTABLE_CACHE_LOCK = threading.Lock()


def _load_fno_and_liquid_symbols() -> set[str]:
    """Gate #0 Helper: Load official F&O universe and Nifty liquid benchmark scrips."""
    global _SHORTABLE_SYMBOLS_CACHE
    with _SHORTABLE_CACHE_LOCK:
        if _SHORTABLE_SYMBOLS_CACHE:
            return _SHORTABLE_SYMBOLS_CACHE
        try:
            data_path = os.path.join(os.path.dirname(__file__), "data", "nse_index_constituents.json")
            if os.path.exists(data_path):
                with open(data_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    fno = set(raw.get("FNO", []))
                    n50 = set(raw.get("NIFTY_50", []))
                    nn50 = set(raw.get("NIFTY_NEXT_50", []))
                    mid50 = set(raw.get("NIFTY_MIDCAP_50", []))
                    _SHORTABLE_SYMBOLS_CACHE = fno | n50 | nn50 | mid50
                    return _SHORTABLE_SYMBOLS_CACHE
        except Exception as e:
            logger.warning(f"Error loading shortable symbols: {e}")
        return _SHORTABLE_SYMBOLS_CACHE


_5M_CONFIRM_CACHE: dict[str, tuple[float, bool]] = {}
_5M_CACHE_LOCK = threading.Lock()


def verify_0935_micro_confirmation(
    symbol: str,
    or_high: float,
    or_low: float,
    bar1_vol: float,
    direction: str,
) -> bool:
    """
    V14 Micro-Confirmation: Fetches 5m candle [09:30 - 09:35 AM IST] specifically
    for breakout candidates to verify solid body ratio (>= 50%) and volume surge (>= 0.45 * Bar 1).
    Incorporates dual-mode IST timezone localization and zero-division protection.
    """
    now_epoch = time.time()
    clean_sym = symbol.strip().upper().replace(".NS", "")
    cache_key = f"{clean_sym}_{direction}"

    with _5M_CACHE_LOCK:
        cached = _5M_CONFIRM_CACHE.get(cache_key)
        if cached is not None and (now_epoch - cached[0]) < 60.0:
            return cached[1]

    try:
        ticker = f"{clean_sym}.NS"
        df_5m = yf.download(
            tickers=ticker,
            period="5d",
            interval="5m",
            progress=False,
            timeout=8,
        )
        if df_5m is None or df_5m.empty:
            return False

        if isinstance(df_5m.columns, pd.MultiIndex):
            try:
                df_5m = df_5m.xs(ticker, level=1, axis=1)
            except Exception:
                df_5m = df_5m.droplevel(1, axis=1) if df_5m.columns.nlevels > 1 else df_5m

        df = df_5m.copy()

        # DEFENSIVE TWEAK #1: Dual-Mode Timezone check
        if df.index.tz is None:
            if len(df) > 0 and df.index[0].hour < 7:
                df.index = df.index.tz_localize("UTC").tz_convert("Asia/Kolkata")
            else:
                df.index = df.index.tz_localize("Asia/Kolkata")
        else:
            df.index = df.index.tz_convert("Asia/Kolkata")

        # Match closed 09:30:00 IST candle
        bar_0930 = df[df.index.strftime("%H:%M") == "09:30"]
        if bar_0930.empty:
            if len(df) >= 2 and df.index[-1].strftime("%H:%M") == "09:35":
                bar_5m = df.iloc[-2]
            else:
                return False
        else:
            bar_5m = bar_0930.iloc[-1]

        c_open = float(bar_5m["Open"])
        c_high = float(bar_5m["High"])
        c_low = float(bar_5m["Low"])
        c_close = float(bar_5m["Close"])
        c_vol = float(bar_5m["Volume"])

        total_range = c_high - c_low
        if total_range <= 0.0001:
            return False

        body_length = abs(c_close - c_open)
        body_ratio_passed = body_length >= (0.50 * total_range)
        volume_surge_passed = c_vol >= (0.45 * bar1_vol)

        if direction == "BULLISH":
            price_passed = c_close > or_high
        else:
            price_passed = c_close < or_low

        confirmed = bool(price_passed and body_ratio_passed and volume_surge_passed)
        with _5M_CACHE_LOCK:
            _5M_CONFIRM_CACHE[cache_key] = (now_epoch, confirmed)
        return confirmed

    except Exception as e:
        logger.warning(f"Error in 09:35 micro-confirmation for {clean_sym}: {e}")
        return False


def _download_v13_with_retry(tickers: list[str]):
    """Run a bounded Yahoo download with exponential backoff and socket timeout."""
    last_error = None
    for attempt in range(V13_DOWNLOAD_MAX_RETRIES + 1):
        try:
            downloaded = yf.download(
                tickers=tickers,
                period=V13_HISTORY_PERIOD,
                interval=V13_INTERVAL,
                group_by="ticker",
                threads=True,
                progress=False,
                timeout=15,
            )
            if downloaded is not None and not downloaded.empty:
                return downloaded
        except Exception as exc:
            last_error = exc

        if attempt < V13_DOWNLOAD_MAX_RETRIES:
            time.sleep(V13_RETRY_BASE_DELAY_SECONDS)

    return None


def _download_v13_chunk(tickers: list[str]) -> Dict[str, pd.DataFrame]:
    """Download one isolated V13 batch with a short-lived in-memory cache."""
    if not tickers:
        return {}

    now = time.monotonic()
    ttl = _get_v13_cache_ttl()
    cached: Dict[str, pd.DataFrame] = {}
    missing: list[str] = []

    with _V13_CACHE_LOCK:
        for ticker in tickers:
            key = (ticker, V13_HISTORY_PERIOD, V13_INTERVAL)
            item = _V13_CACHE.get(key)
            if item is not None:
                cached_at, df = item
                if now - cached_at < ttl:
                    cached[ticker] = df.copy()
                    continue
                _V13_CACHE.pop(key, None)
            missing.append(ticker)

    if not missing:
        return cached

    downloaded = _download_v13_with_retry(missing)

    result: Dict[str, pd.DataFrame] = dict(cached)

    if downloaded is None or downloaded.empty:
        return result

    if len(missing) == 1:
        ticker = missing[0]

        if isinstance(downloaded.columns, pd.MultiIndex):
            available = set(downloaded.columns.get_level_values(0))
            if ticker not in available:
                return result
            df = downloaded[ticker].copy()
        else:
            df = downloaded.copy()

        df = df.dropna(how="all")
        df = df.dropna(subset=["Open", "High", "Low", "Close"])

        if not df.empty:
            result[ticker] = df
            with _V13_CACHE_LOCK:
                _V13_CACHE[(ticker, V13_HISTORY_PERIOD, V13_INTERVAL)] = (
                    time.monotonic(),
                    df.copy(),
                )

        return result

    if not isinstance(downloaded.columns, pd.MultiIndex):
        return result

    available = set(downloaded.columns.get_level_values(0))

    for ticker in missing:
        if ticker not in available:
            continue

        df = downloaded[ticker].copy()
        df = df.dropna(how="all")
        df = df.dropna(subset=["Open", "High", "Low", "Close"])

        if not df.empty:
            result[ticker] = df
            with _V13_CACHE_LOCK:
                _V13_CACHE[(ticker, V13_HISTORY_PERIOD, V13_INTERVAL)] = (
                    time.monotonic(),
                    df.copy(),
                )

    return result


def build_universe_snapshot(df: pd.DataFrame) -> dict[str, Any]:
    """Calculate key snapshot metrics for a single stock."""
    session = _latest_session(df)

    if session.empty:
        return {
            "price": None,
            "ema20": None,
            "rsi14": None,
            "rel_vol": None,
            "vwap": None,
            "atr14": None,
            "true_velocity": None,
            "latest_session_change_pct": None,
        }

    close = df["Close"].astype(float)
    ema20 = _ema(close, 20)
    rsi14 = _rsi(close, 14)
    atr14 = _atr(df, 14)
    vwap = _session_vwap(session)
    rel_vol = _relative_volume(df, session, 20)
    true_velocity = _true_velocity(df)

    def latest(series):
        try:
            value = float(series.iloc[-1])
            return round(value, 4) if pd.notna(value) else None
        except (TypeError, ValueError, IndexError):
            return None

    try:
        price = float(session["Close"].iloc[-1])
        price = round(price, 4) if pd.notna(price) else None
    except (TypeError, ValueError, IndexError):
        price = None

    previous_session = _previous_session(df)
    latest_session_change_pct = None
    try:
        if not previous_session.empty:
            previous_close = float(previous_session["Close"].iloc[-1])
            latest_close = float(session["Close"].iloc[-1])
            if pd.notna(previous_close) and pd.notna(latest_close) and previous_close != 0:
                latest_session_change_pct = round(
                    ((latest_close / previous_close) - 1.0) * 100.0,
                    4,
                )
    except (TypeError, ValueError, IndexError, ZeroDivisionError):
        latest_session_change_pct = None

    high_val = round(float(session["High"].max()), 4) if not session.empty and "High" in session.columns else None
    low_val = round(float(session["Low"].min()), 4) if not session.empty and "Low" in session.columns else None
    open_val = round(float(session["Open"].iloc[0]), 4) if not session.empty and "Open" in session.columns else None
    vol_val = float(session["Volume"].sum()) if not session.empty and "Volume" in session.columns else None

    or_h, or_l = _opening_range(session)
    or_high_val = round(_safe_float(or_h), 2) if or_h is not None else None
    or_low_val = round(_safe_float(or_l), 2) if or_l is not None else None

    bar_end_iso = None
    if not session.empty:
        try:
            bar_start = pd.Timestamp(session.index[-1])
            bar_end = bar_start + pd.Timedelta(minutes=15)
            if bar_end.tzinfo is None:
                bar_end = bar_end.tz_localize("Asia/Kolkata")
            bar_end_iso = bar_end.isoformat()
        except Exception:
            bar_end_iso = None

    return {
        "price": price,
        "high": high_val,
        "low": low_val,
        "open": open_val,
        "volume": vol_val,
        "opening_range_high": or_high_val,
        "opening_range_low": or_low_val,
        "ema20": latest(ema20),
        "rsi14": latest(rsi14),
        "rel_vol": round(float(rel_vol), 4) if pd.notna(rel_vol) else None,
        "vwap": latest(vwap),
        "atr14": latest(atr14),
        "true_velocity": (
            round(float(true_velocity), 4)
            if true_velocity is not None
            else None
        ),
        "latest_session_change_pct": latest_session_change_pct,
        "bar_end_time": bar_end_iso,
    }


def compute_internal_sector_breadth(
    stock_list: list[dict[str, Any]],
    stock_data_map: dict[str, pd.DataFrame],
) -> dict[str, dict[str, Any]]:
    """
    Compute real-time VWAP-anchored sector breadth and median return across the universe.

    Quantitative Thresholds:
    - BULLISH: Median % change >= +0.35% AND >= 60.0% stocks are GREEN (LTP >= VWAP & Chg >= +0.15%)
    - BEARISH: Median % change <= -0.35% AND >= 60.0% stocks are RED (LTP <= VWAP & Chg <= -0.15%)
    - NEUTRAL: Range-bound buffer zone (-0.30% to +0.35%)
    """
    sector_changes: dict[str, list[dict[str, Any]]] = {}
    macro_greens = 0
    macro_reds = 0
    macro_total = 0

    for stock in stock_list:
        symbol = str(stock.get("symbol", "")).strip()
        sector = str(stock.get("sector", "NSE Equity")).strip() or "NSE Equity"
        df = stock_data_map.get(symbol)
        if df is None or df.empty or len(df) < 2:
            continue

        try:
            latest_sess = _latest_session(df)
            if latest_sess.empty:
                continue
            open_price = float(latest_sess["Open"].iloc[0])
            close_price = float(latest_sess["Close"].iloc[-1])
            if open_price <= 0:
                continue

            # Reference previous session close so gap-up sectors holding above VWAP are accurately captured
            prev_sess = _previous_session(df)
            ref_price = (
                float(prev_sess["Close"].iloc[-1])
                if (not prev_sess.empty and float(prev_sess["Close"].iloc[-1]) > 0)
                else open_price
            )
            chg_pct = ((close_price - ref_price) / ref_price) * 100.0

            # Session VWAP calculation
            vol = latest_sess["Volume"].astype(float)
            cl = latest_sess["Close"].astype(float)
            tot_vol = vol.sum()
            sess_vwap = (cl * vol).sum() / tot_vol if tot_vol > 0 else close_price

            # Strict VWAP + momentum classification (filters gap-up dumps & flat noise)
            is_green = (close_price >= sess_vwap) and (chg_pct >= 0.15)
            is_red = (close_price <= sess_vwap) and (chg_pct <= -0.15)

            if is_green:
                macro_greens += 1
            elif is_red:
                macro_reds += 1
            macro_total += 1

            sector_changes.setdefault(sector, []).append({
                "chg_pct": chg_pct,
                "is_green": is_green,
                "is_red": is_red,
            })
        except Exception:
            continue

    sector_context_map: dict[str, dict[str, Any]] = {}

    for sector, stock_records in sector_changes.items():
        if not stock_records:
            continue

        changes = [r["chg_pct"] for r in stock_records]
        median_pct = float(np.median(changes))
        green_count = sum(1 for r in stock_records if r["is_green"])
        red_count = sum(1 for r in stock_records if r["is_red"])
        total_stocks = len(stock_records)
        breadth_pct = (green_count / total_stocks) * 100.0 if total_stocks > 0 else 50.0
        red_breadth_pct = (red_count / total_stocks) * 100.0 if total_stocks > 0 else 50.0

        if median_pct >= 0.35 and breadth_pct >= 60.0:
            direction = "BULLISH"
        elif median_pct <= -0.35 and red_breadth_pct >= 60.0:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        sector_context_map[sector] = {
            "direction": direction,
            "change_pct": round(median_pct, 2),
            "breadth_pct": round(breadth_pct, 1),
            "red_breadth_pct": round(red_breadth_pct, 1),
            "green_count": green_count,
            "red_count": red_count,
            "total_count": total_stocks,
        }

    # Global universe macro advance/decline metrics
    macro_adv_ratio = round((macro_greens / macro_total) * 100.0, 1) if macro_total > 0 else 50.0
    sector_context_map["__GLOBAL__"] = {
        "macro_adv_ratio": macro_adv_ratio,
        "macro_greens": macro_greens,
        "macro_reds": macro_reds,
        "macro_total": macro_total,
    }

    return sector_context_map


def _apply_macro_breadth_veto(ctx: dict[str, Any] | None) -> None:
    """
    Macro Breadth Veto Guard (Double-Lock Pillar 1A):
    Prevents 3:15 PM MIS short-covering index bounces from labeling a broad market sell-off as BULLISH,
    and ensures individual stock scoring (+5.0 / -2.5) and top-level market_regime stay 100% synchronized.
    """
    if not ctx or not isinstance(ctx, dict):
        return
    macro_adv = ctx.get("macro_adv_ratio")
    if macro_adv is None:
        return
    try:
        adv_f = float(macro_adv)
    except (TypeError, ValueError):
        return

    curr_dir = str(ctx.get("nifty_direction") or "NEUTRAL").upper()
    if adv_f < 25.0:
        ctx["nifty_direction"] = "BEARISH"
    elif adv_f < 35.0 and curr_dir == "BULLISH":
        ctx["nifty_direction"] = "NEUTRAL"
    elif adv_f > 75.0:
        ctx["nifty_direction"] = "BULLISH"
    elif adv_f > 65.0 and curr_dir == "BEARISH":
        ctx["nifty_direction"] = "NEUTRAL"


def _evaluate_stock_entry(
    stock: dict[str, Any],
    df: pd.DataFrame,
    nifty_df: pd.DataFrame | None,
    sector_context_map: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[Any], list[Any], str]:
    """
    Evaluate setup, diagnostics, and snapshot for an individual stock.
    Returns (universe_record, candidates, diagnostic_signals, status).
    """
    symbol = str(stock.get("symbol", "")).strip()
    name = str(stock.get("name", symbol))
    sector = str(stock.get("sector", ""))
    is_n500 = bool(stock.get("is_nifty500", False))
    mcap = stock.get("market_cap_cr")

    universe_record = {
        "symbol": symbol,
        "name": name,
        "sector": sector,
        "status": "NO_SETUP",
        "signals": [],
        "snapshot": {},
        "is_nifty500": is_n500,
        "market_cap_cr": mcap,
    }

    if not validate_v13_history(df):
        universe_record["status"] = "INVALID"
        universe_record["snapshot"] = build_universe_snapshot(df)
        return universe_record, [], [], "INVALID"

    try:
        context = {}
        if nifty_df is not None and not nifty_df.empty:
            context = build_nifty_context(nifty_df, df.index[-1]) or {}

        # Sector Context Injection from Internal Sector Breadth Map
        if sector_context_map and sector:
            s_ctx = sector_context_map.get(sector, {})
            context["sector_direction"] = s_ctx.get("direction", "NEUTRAL")
            context["sector_change_pct"] = s_ctx.get("change_pct", 0.0)
            context["sector_breadth_pct"] = s_ctx.get("breadth_pct", 50.0)
            context["sector_name"] = sector

        if sector_context_map and "__GLOBAL__" in sector_context_map:
            context["macro_adv_ratio"] = sector_context_map["__GLOBAL__"].get("macro_adv_ratio", 50.0)
            _apply_macro_breadth_veto(context)

        # Timestamp-aware candle selection:
        # A 15m candle starting at T is completed at T + 15 mins.
        # Only drop the last candle if:
        # 1. Market is still within regular trading hours (before 15:30 IST)
        # 2. Candle is not the final session bar (>= 15:15 IST)
        # 3. Current exchange time is strictly before the candle's 15m close
        now_ts = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None)
        last_candle_start = pd.Timestamp(df.index[-1])
        if last_candle_start.tzinfo is not None:
            last_candle_start = last_candle_start.tz_localize(None)

        latest_sess = _latest_session(df)
        candle_end = last_candle_start + pd.Timedelta(minutes=15)
        is_after_market_close = now_ts.time() >= pd.Timestamp("15:30").time()
        is_final_session_candle = last_candle_start.time() >= pd.Timestamp("15:15").time()
        # V14 BAR 2 MICRO-CONFIRMATION PIPELINE (09:30 - 09:45 AM IST):
        # 1. 09:30:00 - 09:34:59: Complete blackout. Drop Bar 2 to eliminate early-wick opening sweep fakeouts.
        # 2. 09:35:00 - 09:44:59: Targeted 5m check. Only retain Bar 2 if 09:30-09:35 5m bar confirmed breakout.
        is_bar_2 = (len(latest_sess) == 2 and last_candle_start.time() == pd.Timestamp("09:30").time())
        bar_2_approved = False
        if is_bar_2:
            if now_ts.time() < pd.Timestamp("09:35").time():
                bar_2_approved = False
            else:
                or_high, or_low = _opening_range(latest_sess)
                bar1_vol = float(latest_sess["Volume"].iloc[0]) if len(latest_sess) >= 1 else 0.0
                curr_ltp = float(latest_sess["Close"].iloc[-1])

                is_candidate_long = (or_high is not None and curr_ltp > or_high)
                is_candidate_short = (or_low is not None and curr_ltp < or_low)

                if is_candidate_long or is_candidate_short:
                    cand_dir = "BULLISH" if is_candidate_long else "BEARISH"
                    bar_2_approved = verify_0935_micro_confirmation(
                        symbol=symbol,
                        or_high=or_high or 0.0,
                        or_low=or_low or 0.0,
                        bar1_vol=bar1_vol,
                        direction=cand_dir,
                    )
                else:
                    bar_2_approved = False

        should_drop = (
            not is_after_market_close
            and not is_final_session_candle
            and not (is_bar_2 and bar_2_approved)
            and now_ts < candle_end
            and len(df) > 35
            and len(latest_sess) >= 1
        )

        if should_drop:
            eval_df = df.iloc[:-1]
        else:
            eval_df = df

        candidates = []
        diagnostic_signals = []

        # STRICT OPENING RANGE GATE (09:15 - 09:30 AM IST):
        # The opening range is forming; zero signals are permitted to trigger during this window.
        is_opening_range_now = (
            now_ts.weekday() <= 4
            and pd.Timestamp("09:15").time() <= now_ts.time() < pd.Timestamp("09:30").time()
        )

        last_candle_payload = None
        if not eval_df.empty:
            try:
                lr = eval_df.iloc[-1]
                last_candle_payload = {
                    "open": float(lr.get("Open", 0.0)),
                    "high": float(lr.get("High", 0.0)),
                    "low": float(lr.get("Low", 0.0)),
                    "close": float(lr.get("Close", 0.0)),
                    "volume": float(lr.get("Volume", 0.0)),
                }
            except Exception:
                last_candle_payload = None

        first_ev = None
        if not is_opening_range_now and len(eval_df) >= 20:
            clean = _normalise_columns(eval_df)
            latest_session = _latest_session(clean)
            if not latest_session.empty:
                latest_ts = pd.DatetimeIndex(latest_session.index)[-1]
                for direction in ("BULLISH", "BEARISH"):
                    # V14 GATE #0: SEGMENTED EXECUTION GATE FOR SHORTING
                    # Bearish setups are strictly restricted to F&O universe and liquid benchmark scrips.
                    if direction == "BEARISH":
                        shortable = _load_fno_and_liquid_symbols()
                        clean_sym = symbol.strip().upper().replace(".NS", "")
                        if shortable and clean_sym not in shortable:
                            continue

                    ev = _evaluate_direction(clean, direction, context=context, allow_below_threshold=True, symbol=symbol)
                    if ev is not None:
                        if first_ev is None:
                            first_ev = ev
                        grade, action = _classification(ev.score)
                        cand = V13Candidate(
                            symbol=symbol,
                            name=name,
                            sector=sector,
                            signal_type=direction,
                            setup_type=ev.setup_type,
                            action=action,
                            grade=grade,
                            score=ev.score,
                            ltp=round(_safe_float(clean["Close"].iloc[-1]), 2),
                            entry_price=ev.entry,
                            stop_loss=ev.stop,
                            target_1=ev.target_1,
                            target_2=ev.target_2,
                            risk_amount=ev.risk,
                            risk_reward_t1="1:1.5",
                            risk_reward_t2="1:2.5",
                            ema20=round(ev.ema20, 2),
                            rsi14=round(ev.rsi14, 2),
                            rel_vol=round(ev.rel_vol, 2),
                            vwap=round(ev.vwap, 2),
                            atr14=round(ev.atr14, 2),
                            true_velocity=ev.true_velocity,
                            opening_range_high=round(_safe_float(_opening_range(latest_session)[0]), 2),
                            opening_range_low=round(_safe_float(_opening_range(latest_session)[1]), 2),
                            previous_day_high=round(_safe_float(_previous_day_levels(clean)[0]), 2),
                            previous_day_low=round(_safe_float(_previous_day_levels(clean)[1]), 2),
                            breakout_distance_atr=ev.breakout_distance_atr,
                            breakout_candle_range=ev.breakout_candle_range,
                            reasons=ev.reasons,
                            penalties=ev.penalties,
                            score_breakdown=ev.score_breakdown,
                            t1_progress_pct=ev.t1_progress_pct,
                            execution_status=ev.execution_status,
                            signal_time=latest_ts.isoformat(),
                        )
                        # Decorate candidate with metadata
                        if isinstance(cand, dict):
                            cand["is_nifty500"] = is_n500
                            cand["market_cap_cr"] = mcap
                            if last_candle_payload:
                                cand["last_candle"] = last_candle_payload
                        else:
                            try:
                                setattr(cand, "is_nifty500", is_n500)
                                setattr(cand, "market_cap_cr", mcap)
                                if last_candle_payload:
                                    setattr(cand, "last_candle", last_candle_payload)
                            except Exception:
                                pass

                        if ev.score >= WATCH_SCORE:
                            candidates.append(cand)
                        else:
                            diagnostic_signals.append(cand)

        # Zero-redundancy snapshot population:
        if first_ev is not None:
            price_val = round(_safe_float(eval_df["Close"].iloc[-1]), 4)
            high_val = round(float(latest_sess["High"].max()), 4) if not latest_sess.empty and "High" in latest_sess.columns else None
            low_val = round(float(latest_sess["Low"].min()), 4) if not latest_sess.empty and "Low" in latest_sess.columns else None
            open_val = round(float(latest_sess["Open"].iloc[0]), 4) if not latest_sess.empty and "Open" in latest_sess.columns else None
            vol_val = float(latest_sess["Volume"].sum()) if not latest_sess.empty and "Volume" in latest_sess.columns else None

            prev_sess = _previous_session(eval_df)
            latest_session_change_pct = None
            if not prev_sess.empty:
                prev_close = float(prev_sess["Close"].iloc[-1])
                if prev_close > 0:
                    latest_session_change_pct = round(((price_val / prev_close) - 1.0) * 100.0, 4)

            or_h, or_l = _opening_range(latest_sess)
            or_high_val = round(_safe_float(or_h), 2) if or_h is not None else None
            or_low_val = round(_safe_float(or_l), 2) if or_l is not None else None

            bar_end_iso = None
            if not latest_sess.empty:
                try:
                    bar_start = pd.Timestamp(latest_sess.index[-1])
                    bar_end = bar_start + pd.Timedelta(minutes=15)
                    if bar_end.tzinfo is None:
                        bar_end = bar_end.tz_localize("Asia/Kolkata")
                    bar_end_iso = bar_end.isoformat()
                except Exception:
                    bar_end_iso = None

            universe_record["snapshot"] = {
                "price": price_val,
                "high": high_val,
                "low": low_val,
                "open": open_val,
                "volume": vol_val,
                "opening_range_high": or_high_val,
                "opening_range_low": or_low_val,
                "ema20": first_ev.ema20,
                "rsi14": first_ev.rsi14,
                "rel_vol": first_ev.rel_vol,
                "vwap": first_ev.vwap,
                "atr14": first_ev.atr14,
                "true_velocity": first_ev.true_velocity,
                "latest_session_change_pct": latest_session_change_pct,
                "bar_end_time": bar_end_iso,
            }
        else:
            universe_record["snapshot"] = build_universe_snapshot(eval_df)

        if candidates:
            candidates.sort(
                key=lambda s: getattr(s, "score", 0.0) if not isinstance(s, dict) else s.get("score", 0.0),
                reverse=True,
            )
            universe_record["signals"] = list(candidates)
            universe_record["status"] = "SIGNAL"
            diagnostic_signals = []
        elif diagnostic_signals:
            dominant_diag = max(
                diagnostic_signals,
                key=lambda s: getattr(s, "score", 0.0) if not isinstance(s, dict) else s.get("score", 0.0),
            )
            diagnostic_signals = [dominant_diag]
            universe_record["signals"] = [dominant_diag]
            universe_record["status"] = "DIAGNOSTIC"
        else:
            universe_record["status"] = "NO_SETUP"

        return universe_record, candidates, diagnostic_signals, "VALID"

    except Exception:
        universe_record["status"] = "ENGINE_ERROR"
        return universe_record, [], [], "ENGINE_ERROR"


def _eval_stock_batch(
    args: Any,
) -> list[tuple[dict[str, Any], list[Any], list[Any], str]]:
    """Worker batch evaluator executed across CPU worker processes."""
    if len(args) == 3:
        batch, nifty_df, sector_context_map = args
    else:
        batch, nifty_df = args
        sector_context_map = None
    return [_evaluate_stock_entry(stock, df, nifty_df, sector_context_map) for stock, df in batch]


def scan_v13_universe(
    stocks: Iterable[dict[str, Any]],
    nifty_df: pd.DataFrame | None = None,
    force_fresh: bool = False,
) -> dict[str, Any]:
    """Scan the exact V13 universe with fail-closed population accounting and multi-process parallelism."""
    if force_fresh:
        clear_v13_cache()

    stock_list = list(stocks)

    if not stock_list:
        raise ValueError("V13 universe mismatch: stock list cannot be empty")

    metadata = {}
    for stock in stock_list:
        symbol = str(stock.get("symbol", "")).strip()
        if not symbol:
            raise ValueError("V13 universe contains a stock without symbol")
        if symbol in metadata:
            raise ValueError(f"V13 universe contains duplicate symbol: {symbol}")
        metadata[symbol] = stock

    requested = len(stock_list)
    market_context = None
    if nifty_df is not None and not nifty_df.empty:
        try:
            market_context = build_nifty_context(nifty_df, nifty_df.index[-1])
        except Exception:
            pass

    # Parallel chunk download
    stock_data_map: dict[str, pd.DataFrame] = {}
    for symbol, df in fetch_v13_stock_data(stock_list):
        stock_data_map[symbol] = df

    # Compute live Internal Sector Breadth Map across all universe sectors
    sector_context_map = compute_internal_sector_breadth(stock_list, stock_data_map)

    # Attach macro universe breadth to market_context and apply breadth veto guard
    if market_context is not None and isinstance(market_context, dict):
        if sector_context_map and "__GLOBAL__" in sector_context_map:
            market_context["macro_adv_ratio"] = sector_context_map["__GLOBAL__"].get("macro_adv_ratio", 50.0)
            _apply_macro_breadth_veto(market_context)

    returned = len(stock_data_map)
    pairs = [
        (stock, stock_data_map.get(str(stock.get("symbol", "")), pd.DataFrame()))
        for stock in stock_list
    ]

    # Multiprocess evaluation across CPU worker processes
    num_workers = min(8, os.cpu_count() or 4)
    chunk_size = (len(pairs) + num_workers - 1) // num_workers
    batches = [
        (pairs[i:i + chunk_size], nifty_df, sector_context_map)
        for i in range(0, len(pairs), chunk_size)
    ]

    eval_results = []
    try:
        import concurrent.futures
        with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(_eval_stock_batch, b) for b in batches]
            for f in concurrent.futures.as_completed(futures, timeout=120.0):
                eval_results.extend(f.result())
    except Exception as _pex:
        logger.warning(f"ProcessPoolExecutor fallback to ThreadPool: {_pex}")
        eval_results.clear()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = [executor.submit(_eval_stock_batch, b) for b in batches]
                for f in concurrent.futures.as_completed(futures, timeout=120.0):
                    eval_results.extend(f.result())
        except Exception:
            eval_results.clear()
            for b in batches:
                eval_results.extend(_eval_stock_batch(b))

    results = []
    diagnostic_signals = []
    universe = []
    valid = 0
    invalid = 0
    engine_errors = 0

    for universe_record, cands, diags, status in eval_results:
        universe.append(universe_record)
        results.extend(cands)
        diagnostic_signals.extend(diags)
        if status == "VALID":
            valid += 1
        elif status == "INVALID":
            invalid += 1
        else:
            engine_errors += 1

    missing = requested - returned
    if returned != requested:
        raise RuntimeError(
            "V13 population mismatch: "
            f"requested={requested}, returned={returned}, missing={missing}"
        )

    return {
        "requested": requested,
        "returned": returned,
        "valid": valid,
        "invalid": invalid,
        "engine_errors": engine_errors,
        "candidates": results,
        "diagnostic_signals": diagnostic_signals,
        "market_context": market_context,
        "sector_context_map": sector_context_map,
        "universe": universe,
    }


def validate_v13_history(df: pd.DataFrame) -> bool:
    """Validate that a stock has enough real trading sessions for V13."""
    if df is None or df.empty:
        return False

    required_columns = {"Open", "High", "Low", "Close", "Volume"}
    if not required_columns.issubset(set(df.columns)):
        return False

    clean = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    if clean.empty:
        return False

    index = pd.DatetimeIndex(clean.index)
    if index.tz is not None:
        index = index.tz_localize(None)

    session_count = index.normalize().nunique()
    return session_count >= V13_MIN_SESSIONS


def fetch_v13_stock_data(
    stocks: Iterable[dict[str, Any]],
    chunk_size: int = V13_DOWNLOAD_CHUNK_SIZE,
) -> Iterable[tuple[str, pd.DataFrame]]:
    """
    Yield V13 stock OHLCV data in batches with parallel chunk fetching.
    Guarantees every stock in universe is yielded (using empty DataFrame on fetch failure).
    """
    import concurrent.futures

    stock_list = list(stocks)
    chunks = [
        stock_list[i:i + chunk_size]
        for i in range(0, len(stock_list), chunk_size)
    ]

    all_downloaded: Dict[str, pd.DataFrame] = {}

    def process_chunk(chunk_stocks: list[dict[str, Any]]) -> Dict[str, pd.DataFrame]:
        tickers = [
            str(stock["yf_ticker"])
            for stock in chunk_stocks
            if stock.get("yf_ticker")
        ]
        return _download_v13_chunk(tickers)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
    try:
        futures = [executor.submit(process_chunk, chunk) for chunk in chunks]
        try:
            for future in concurrent.futures.as_completed(futures, timeout=90.0):
                try:
                    res = future.result()
                    if res:
                        all_downloaded.update(res)
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
            pass
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    for stock in stock_list:
        symbol = str(stock.get("symbol", ""))
        yf_ticker = str(stock.get("yf_ticker", ""))
        df = all_downloaded.get(yf_ticker)
        if df is None:
            df = pd.DataFrame()
        yield symbol, df






