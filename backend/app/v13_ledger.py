"""
V13 Session Trade Ledger & Performance Audit Engine.

Features:
1. Monotonic Peak Classification ("The Ratchet Engine"):
   - Tiers: WATCHLIST (72.0-79.9) < STRONG (80.0-84.9) < HIGH_CONFIDENCE (85.0+)
   - Stocks only upgrade tiers, never downgrade or get deleted when scores decay.
2. Immutable First Detection Stage (Write-Once Rule):
   - When a stock first enters the ledger, its first_detection_stage is written ONCE
     and permanently locked (e.g. EARLY_TRIGGER, ACTIONABLE, etc.).
3. Trailing Stop Loss / T1 Priority Rule:
   - Once Target 1 is hit, the trade is permanently a WIN (+1.5R or +2.5R).
   - Reversals below entry/SL after T1 are never counted as losses.
4. Complete EOD Telegram Performance Audit generation with all percentage metrics.
5. Disk persistence (session_trade_ledger.json) with daily auto-rollover.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, time as dtime
from typing import Any, Dict, List, Optional

import pandas as pd

from .config import IST_TZ, EOD_RESET_TIME

logger = logging.getLogger("v13_ledger")

LEDGER_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LEDGER_FILE_PATH = os.path.join(LEDGER_DATA_DIR, "active performance live eod", "session_trade_ledger.json")
LEDGER_HISTORY_DIR = os.path.join(LEDGER_DATA_DIR, "EOD performance history")
SENT_ALERTS_CACHE_FILE = os.path.join(LEDGER_DATA_DIR, "telegram notification audit", "sent_alerts_cache.json")


def get_effective_trading_date(dt: Optional[datetime] = None) -> str:
    """
    Returns the effective trading session date string (YYYY-MM-DD).
    In NSE:
    - On weekdays before EOD_RESET_TIME (configurable via .env, default 09:00 AM), the active session is still the previous trading session (e.g. yesterday, or Friday if Monday morning).
    - On weekends (Saturday/Sunday), the active session is Friday.
    - On weekdays at or after EOD_RESET_TIME, the active session is today.
    """
    now = dt or datetime.now(IST_TZ)
    current_date = now.date()
    weekday = now.weekday()  # 0=Monday, ..., 4=Friday, 5=Saturday, 6=Sunday
    current_time = now.time()

    if weekday in (5, 6):
        # Weekend -> Friday's session
        days_back = 1 if weekday == 5 else 2
        return (current_date - timedelta(days=days_back)).strftime("%Y-%m-%d")

    # Weekday (Monday - Friday)
    if current_time < EOD_RESET_TIME:
        # Before reset time -> Previous trading session
        days_back = 3 if weekday == 0 else 1
        return (current_date - timedelta(days=days_back)).strftime("%Y-%m-%d")

    return current_date.strftime("%Y-%m-%d")


def _calc_first_stage(t1_progress: float, exec_status: str) -> str:
    """Determine initial entry progress stage."""
    status_upper = str(exec_status or "").upper()
    if status_upper == "EARLY_TRIGGER" or t1_progress < 25.0:
        return "EARLY_TRIGGER"
    elif t1_progress < 75.0:
        return "ACTIONABLE"
    elif t1_progress < 100.0:
        return "TARGET_NEAR"
    return "TARGET_HIT"


def _calc_tier(score: float) -> str:
    if score >= 85.0:
        return "HIGH_CONFIDENCE"
    elif score >= 80.0:
        return "STRONG"
    return "WATCHLIST"


@dataclass
class TrackedSetup:
    symbol: str
    name: str
    sector: str
    direction: str
    setup_type: str

    # Scores & Monotonic Peak Ratchet
    initial_score: float
    peak_score: float
    peak_tier: str  # "HIGH_CONFIDENCE", "STRONG", "WATCHLIST"

    # Price levels & Risk
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    risk_amount: float
    ltp: float

    # Execution Lifecycle (Write-Once Immutability)
    first_detection_stage: str  # "EARLY_TRIGGER", "ACTIONABLE", "TARGET_NEAR", "TARGET_HIT"
    current_status: str
    t1_progress_pct: float

    # Outcome tracking
    outcome: str  # "OPEN", "T1_HIT", "T2_HIT", "SL_HIT", "T1_HIT_TRAILED", "T1_WIN_BE_EXIT", "EOD_PARTIAL_WIN"
    realized_r: float
    highest_progress_pct: float

    registered_at: str
    last_updated_at: str
    outcome_time: Optional[str] = None
    t1_was_hit: bool = False


class SessionTradeLedger:
    """Thread-safe intraday trade performance ledger for V13 screener."""

    def __init__(self, data_file: str = LEDGER_FILE_PATH):
        self.data_file = data_file
        self.lock = threading.RLock()
        self.date_str = get_effective_trading_date()
        self.records: Dict[str, TrackedSetup] = {}
        self.telegram_records: Dict[str, TrackedSetup] = {}
        self.eod_audit_sent_date: Optional[str] = None
        self.weekly_audit_sent_week: Optional[str] = None

        self._load_from_disk()

    def _dispatch_catchup_audit(self, session_date: str) -> bool:
        """
        Catch-Up EOD Performance Audit Guard:
        If server was closed early (e.g. at 15:15 before 15:30 EOD settlement),
        auto-settles previous session trades and dispatches the missing audit to Telegram
        on next boot/rollover before archiving.
        """
        try:
            from .telegram_bot import send_telegram_text
            ist_now = datetime.now(IST_TZ)
            self._settle_eod_trades(ist_now)
            report_text = self.format_telegram_eod_report(market_regime="Previous Session Recap")
            sent = send_telegram_text(report_text, sync_send=True)
            if sent:
                self.eod_audit_sent_date = session_date
                logger.info(f"Catch-up EOD performance audit successfully dispatched for session {session_date}")
                return True
        except Exception as e:
            logger.error(f"Catch-up EOD audit dispatch failed for {session_date}: {e}")
        return False

    def _check_rollover(self, current_date: Optional[Any] = None) -> None:
        """Archive previous session's ledger at 09:00 AM on a new session date."""
        if isinstance(current_date, datetime):
            target_date = get_effective_trading_date(current_date)
        elif isinstance(current_date, str) and len(current_date) >= 10:
            target_date = current_date[:10]
        else:
            target_date = get_effective_trading_date()

        if not isinstance(self.date_str, str) or len(str(self.date_str)) > 10:
            self.date_str = str(self.date_str)[:10] if self.date_str else target_date

        if self.date_str != target_date:
            if self.records or self.telegram_records:
                # Catch-Up Guard: If previous session's EOD audit was never sent, send it before archiving!
                if not self.eod_audit_sent_date:
                    self._dispatch_catchup_audit(self.date_str)

                try:
                    os.makedirs(LEDGER_HISTORY_DIR, exist_ok=True)
                    archive_path = os.path.join(
                        LEDGER_HISTORY_DIR, f"ledger_{self.date_str}.json"
                    )
                    should_save_archive = True
                    if os.path.exists(archive_path) and os.path.getsize(archive_path) > 0:
                        try:
                            with open(archive_path, "r", encoding="utf-8") as ef:
                                existing_arch = json.load(ef)
                            existing_rec_cnt = len(existing_arch.get("screener_records") or existing_arch.get("records") or {})
                            existing_tg_cnt = len(existing_arch.get("telegram_alerted_trades") or {})
                            if existing_rec_cnt > len(self.records) or existing_tg_cnt > len(self.telegram_records):
                                should_save_archive = False
                                logger.info(
                                    f"Preserving existing larger archive {archive_path} "
                                    f"({existing_rec_cnt} records / {existing_tg_cnt} tg trades vs {len(self.records)} / {len(self.telegram_records)})"
                                )
                        except Exception:
                            pass
                    if should_save_archive:
                        self._save_to_disk_path(archive_path)
                        logger.info(f"Archived session ledger to {archive_path}")
                except Exception as e:
                    logger.error(f"Failed to archive ledger: {e}")

                # Synchronized Telegram Notification History Archive & Rollover
                try:
                    from .telegram_bot import archive_session_telegram_alerts, rollover_sent_alerts_cache
                    archive_session_telegram_alerts(self.date_str, self.telegram_records or self.records)
                    rollover_sent_alerts_cache(target_date, self.date_str)
                except Exception as e:
                    logger.error(f"Failed to archive/rollover telegram alerts: {e}")

            self.date_str = target_date
            self.records.clear()
            self.telegram_records.clear()
            self.eod_audit_sent_date = None
            self._save_to_disk()

    def update_from_scan(
        self,
        candidates: List[Any],
        diagnostics: List[Any] = None,
        universe: List[Any] = None,
        now_dt: Optional[datetime] = None,
    ) -> int:
        """
        Feed live candidates and diagnostic setups into the monotonic ledger.
        Ensures write-once immutability for first_detection_stage and monotonic peak tier locks.
        Continuously tracks stop-loss and targets even if setup score drops below 72.
        Settles open trades at 03:30 PM MTM.
        """
        ist_now = now_dt or datetime.now(IST_TZ)
        effective_date = get_effective_trading_date(ist_now)
        now_iso = ist_now.isoformat()

        with self.lock:
            self._check_rollover(effective_date)
            new_or_updated = 0

            # 1. Collect all incoming candidates and diagnostics
            signal_items = list(candidates or [])
            if diagnostics:
                signal_items.extend(diagnostics)

            incoming_signals: Dict[str, Any] = {}
            for item in signal_items:
                def get_attr_map(attr: str, default: Any = None) -> Any:
                    if isinstance(item, dict):
                        return item.get(attr, default)
                    return getattr(item, attr, default)

                s_sym = str(get_attr_map("symbol") or "").strip().upper()
                if not s_sym:
                    continue
                s_dir = str(get_attr_map("direction") or get_attr_map("signal_type") or "BULLISH").upper()
                incoming_signals[f"{s_sym}_{s_dir}"] = item

            # 2. Build universe price lookup map (symbol -> ltp) if universe is provided
            universe_price_map: Dict[str, float] = {}
            if universe:
                for u in universe:
                    if isinstance(u, dict):
                        u_sym = str(u.get("symbol") or "").strip().upper()
                        snap = u.get("snapshot") or {}
                        u_ltp = float(snap.get("price") or snap.get("close") or snap.get("ltp") or u.get("price") or 0.0)
                        if u_sym and u_ltp > 0:
                            universe_price_map[u_sym] = u_ltp
                    else:
                        u_sym = str(getattr(u, "symbol", "") or "").strip().upper()
                        snap = getattr(u, "snapshot", {}) or {}
                        if isinstance(snap, dict):
                            u_ltp = float(snap.get("price") or snap.get("close") or snap.get("ltp") or getattr(u, "price", 0.0) or 0.0)
                        else:
                            u_ltp = float(getattr(snap, "price", 0.0) or getattr(snap, "close", 0.0) or getattr(u, "price", 0.0) or 0.0)
                        if u_sym and u_ltp > 0:
                            universe_price_map[u_sym] = u_ltp

            # 3. Process candidate and diagnostic setups
            for item in signal_items:
                def get_attr(attr: str, default: Any = None) -> Any:
                    if isinstance(item, dict):
                        return item.get(attr, default)
                    return getattr(item, attr, default)

                sym = str(get_attr("symbol") or "").strip().upper()
                if not sym:
                    continue

                direction = str(get_attr("direction") or get_attr("signal_type") or "BULLISH").upper()
                score = float(get_attr("score") or 0.0)
                name = str(get_attr("name") or sym)
                sector = str(get_attr("sector") or "NSE Equity")
                setup_type = str(get_attr("setup_type") or "V13_BREAKOUT")

                tp = get_attr("risk") or {}
                if isinstance(tp, dict):
                    entry = float(tp.get("entry") or get_attr("entry_price") or 0.0)
                    sl = float(tp.get("stop_loss") or get_attr("stop_loss") or 0.0)
                    t1 = float(tp.get("target_1") or get_attr("target_1") or 0.0)
                    t2 = float(tp.get("target_2") or get_attr("target_2") or 0.0)
                    risk_amt = float(tp.get("risk_amount") or get_attr("risk_amount") or abs(entry - sl))
                else:
                    entry = float(get_attr("entry_price") or 0.0)
                    sl = float(get_attr("stop_loss") or 0.0)
                    t1 = float(get_attr("target_1") or 0.0)
                    t2 = float(get_attr("target_2") or 0.0)
                    risk_amt = float(get_attr("risk_amount") or abs(entry - sl))

                ltp = float(get_attr("ltp") or get_attr("price") or entry)
                t1_prog = float(get_attr("t1_progress_pct") or 0.0)
                exec_status = str(get_attr("execution_status") or "").upper()

                key = f"{sym}_{direction}"

                if key not in self.records:
                    # Guard: Never register new trade setups during the 09:15 - 09:30 AM Opening Range formation window
                    if ist_now.weekday() <= 4 and ist_now.time() < pd.Timestamp("09:30").time():
                        continue

                    # New setups are strictly registered ONLY if score >= 72.0
                    if score < 72.0:
                        continue

                    # Record immutable first_detection_stage (0-25% Early, 25-75% Actionable, 75-99% Near Target, 100%+ Hit)
                    first_stage = _calc_first_stage(t1_prog, exec_status)
                    initial_tier = _calc_tier(score)

                    # Determine initial outcome
                    initial_outcome, initial_r = self._evaluate_outcome(
                        direction, ltp, entry, sl, t1, t2, t1_prog, "OPEN"
                    )

                    self.records[key] = TrackedSetup(
                        symbol=sym,
                        name=name,
                        sector=sector,
                        direction=direction,
                        setup_type=setup_type,
                        initial_score=score,
                        peak_score=score,
                        peak_tier=initial_tier,
                        entry_price=entry,
                        stop_loss=sl,
                        target_1=t1,
                        target_2=t2,
                        risk_amount=risk_amt,
                        ltp=ltp,
                        first_detection_stage=first_stage,  # STRICTLY IMMUTABLE
                        current_status=exec_status or "EARLY_TRIGGER",
                        t1_progress_pct=t1_prog,
                        outcome=initial_outcome,
                        realized_r=initial_r,
                        highest_progress_pct=t1_prog,
                        registered_at=now_iso,
                        last_updated_at=now_iso,
                        outcome_time=now_iso if initial_outcome != "OPEN" else None,
                    )
                    new_or_updated += 1
                else:
                    # Update Existing Registration: Track price even if score drops below 72!
                    rec = self.records[key]

                    # 1. Update peak score & tier monotonically
                    if score > rec.peak_score:
                        rec.peak_score = score
                    if score >= 85.0:
                        rec.peak_tier = "HIGH_CONFIDENCE"
                    elif score >= 80.0 and rec.peak_tier != "HIGH_CONFIDENCE":
                        rec.peak_tier = "STRONG"

                    # 2. Dynamic progress calculation
                    if t1_prog == 0.0 and rec.target_1 != rec.entry_price:
                        if rec.direction == "BULLISH":
                            t1_dist = rec.target_1 - rec.entry_price
                            t1_prog = ((ltp - rec.entry_price) / t1_dist * 100.0) if t1_dist > 0 else 0.0
                        else:
                            t1_dist = rec.entry_price - rec.target_1
                            t1_prog = ((rec.entry_price - ltp) / t1_dist * 100.0) if t1_dist > 0 else 0.0

                    if t1_prog > rec.highest_progress_pct:
                        rec.highest_progress_pct = t1_prog

                    # 3. Evaluate Trailing Target / SL Outcomes (Unconditional tracking)
                    new_outcome, new_r = self._evaluate_outcome(
                        rec.direction, ltp, rec.entry_price, rec.stop_loss,
                        rec.target_1, rec.target_2, t1_prog, rec.outcome
                    )
                    if new_outcome != rec.outcome:
                        rec.outcome = new_outcome
                        rec.realized_r = new_r
                        if new_outcome != "OPEN":
                            rec.outcome_time = now_iso

                    rec.ltp = ltp
                    rec.t1_progress_pct = t1_prog
                    if exec_status:
                        rec.current_status = exec_status
                    rec.last_updated_at = now_iso
                    new_or_updated += 1

            # 4. Fallback price tracking for open setups not in candidates/diagnostics but present in universe
            for key, rec in self.records.items():
                if key not in incoming_signals and rec.outcome in ("OPEN", "T1_HIT_TRAILED"):
                    u_ltp = universe_price_map.get(rec.symbol)
                    if u_ltp and u_ltp > 0:
                        rec.ltp = u_ltp
                        if rec.direction == "BULLISH":
                            t1_dist = rec.target_1 - rec.entry_price
                            t1_prog = ((u_ltp - rec.entry_price) / t1_dist * 100.0) if t1_dist > 0 else 0.0
                        else:
                            t1_dist = rec.entry_price - rec.target_1
                            t1_prog = ((rec.entry_price - u_ltp) / t1_dist * 100.0) if t1_dist > 0 else 0.0

                        if t1_prog > rec.highest_progress_pct:
                            rec.highest_progress_pct = t1_prog
                        rec.t1_progress_pct = t1_prog

                        new_outcome, new_r = self._evaluate_outcome(
                            rec.direction, u_ltp, rec.entry_price, rec.stop_loss,
                            rec.target_1, rec.target_2, t1_prog, rec.outcome
                        )
                        if new_outcome != rec.outcome:
                            rec.outcome = new_outcome
                            rec.realized_r = new_r
                            rec.outcome_time = now_iso
                        rec.last_updated_at = now_iso
                        new_or_updated += 1

            # 4b. Live tracking for telegram-alerted trades against their locked alert parameters
            for key, rec in self.telegram_records.items():
                if rec.outcome in ("OPEN", "T1_HIT_TRAILED"):
                    live_p = universe_price_map.get(rec.symbol)
                    if not live_p or live_p <= 0:
                        inc = incoming_signals.get(key)
                        if inc:
                            live_p = float(inc.get("ltp") or inc.get("price") or 0.0)

                    if live_p and live_p > 0:
                        rec.ltp = live_p
                        if rec.direction == "BULLISH":
                            t1_dist = rec.target_1 - rec.entry_price
                            t1_prog = ((live_p - rec.entry_price) / t1_dist * 100.0) if t1_dist > 0 else 0.0
                        else:
                            t1_dist = rec.entry_price - rec.target_1
                            t1_prog = ((rec.entry_price - live_p) / t1_dist * 100.0) if t1_dist > 0 else 0.0

                        if t1_prog > rec.highest_progress_pct:
                            rec.highest_progress_pct = t1_prog
                        rec.t1_progress_pct = t1_prog

                        new_outcome, new_r = self._evaluate_outcome(
                            rec.direction, live_p, rec.entry_price, rec.stop_loss,
                            rec.target_1, rec.target_2, t1_prog, rec.outcome
                        )
                        if new_outcome != rec.outcome:
                            rec.outcome = new_outcome
                            rec.realized_r = new_r
                            rec.outcome_time = now_iso
                        rec.last_updated_at = now_iso
                        new_or_updated += 1

            # 5. 03:30 PM MTM Auto-Settlement for all remaining OPEN and T1_HIT_TRAILED trades
            if ist_now.weekday() <= 4 and ist_now.time() >= dtime(15, 30):
                self._settle_eod_trades(ist_now)

            self._save_to_disk()
            return new_or_updated

    def _settle_eod_trades(self, ist_now: datetime) -> None:
        """Settle any remaining OPEN and T1_HIT_TRAILED trades at 03:30 PM MTM across both record sets."""
        now_iso = ist_now.isoformat()
        for group in (self.records.values(), self.telegram_records.values()):
            for rec in group:
                if rec.outcome == "OPEN":
                    entry = rec.entry_price
                    ltp = rec.ltp if rec.ltp > 0 else entry
                    risk = rec.risk_amount if rec.risk_amount > 0 else abs(entry - rec.stop_loss)
                    if risk <= 0:
                        risk = max(entry * 0.01, 0.01)

                    dir_mult = 1.0 if str(rec.direction).upper() == "BULLISH" else -1.0
                    floating_r = round(((ltp - entry) * dir_mult) / risk, 2)

                    if floating_r > 0.05:
                        rec.outcome = "CLOSED_EOD_PROFIT"
                    elif floating_r < -0.05:
                        rec.outcome = "CLOSED_EOD_LOSS"
                    else:
                        rec.outcome = "CLOSED_EOD_FLAT"

                    rec.realized_r = floating_r
                    rec.outcome_time = now_iso

                elif rec.outcome == "T1_HIT_TRAILED":
                    entry = rec.entry_price
                    ltp = rec.ltp if rec.ltp > 0 else entry
                    risk = rec.risk_amount if rec.risk_amount > 0 else abs(entry - rec.stop_loss)
                    if risk <= 0:
                        risk = max(entry * 0.01, 0.01)

                    dir_mult = 1.0 if str(rec.direction).upper() == "BULLISH" else -1.0
                    floating_r = ((ltp - entry) * dir_mult) / risk
                    blended_r = round(0.75 + (0.50 * floating_r), 2)

                    rec.outcome = "EOD_PARTIAL_WIN"
                    rec.realized_r = blended_r
                    rec.outcome_time = now_iso

        # Update Telegram Notification History archive with finalized EOD outcomes
        try:
            from .telegram_bot import archive_session_telegram_alerts
            archive_session_telegram_alerts(self.date_str, self.telegram_records or self.records)
        except Exception as e:
            logger.debug(f"Could not update telegram archive on EOD settlement: {e}")

    def record_telegram_alert(self, signal: Dict[str, Any]) -> None:
        """
        Record a trade actually dispatched to Telegram with locked alert parameters.
        Stored under self.telegram_records[key] and synced to session_trade_ledger.json.
        """
        with self.lock:
            def get_val(key: str, default=None):
                if isinstance(signal, dict):
                    return signal.get(key, default)
                return getattr(signal, key, default)

            sym = str(get_val("symbol") or "").strip().upper()
            if not sym:
                return
            direction = str(get_val("direction") or get_val("signal_type") or "BULLISH").upper()
            key = f"{sym}_{direction}"

            tp = get_val("risk") or get_val("trade_params") or {}
            if isinstance(tp, dict):
                entry = float(tp.get("entry") or get_val("entry_price") or 0.0)
                sl = float(tp.get("stop_loss") or get_val("stop_loss") or 0.0)
                t1 = float(tp.get("target_1") or get_val("target_1") or 0.0)
                t2 = float(tp.get("target_2") or get_val("target_2") or 0.0)
                risk_amt = float(tp.get("risk_amount") or get_val("risk_amount") or abs(entry - sl))
            else:
                entry = float(get_val("entry_price") or 0.0)
                sl = float(get_val("stop_loss") or 0.0)
                t1 = float(get_val("target_1") or 0.0)
                t2 = float(get_val("target_2") or 0.0)
                risk_amt = float(get_val("risk_amount") or abs(entry - sl))

            score = float(get_val("score") or 0.0)
            ltp = float(get_val("ltp") or get_val("price") or entry)
            t1_prog = float(get_val("t1_progress_pct") or 0.0)
            exec_status = str(get_val("execution_status") or "").upper()
            # Guard: Never record telegram alerted trade if alert arrived before 09:30 AM on trading days
            ist_dt = datetime.now(IST_TZ)
            now_iso = ist_dt.isoformat()
            if ist_dt.weekday() <= 4 and ist_dt.time() < pd.Timestamp("09:30").time():
                return

            if key not in self.telegram_records:
                first_stage = _calc_first_stage(t1_prog, exec_status)
                tier = _calc_tier(score)
                init_outcome, init_r = self._evaluate_outcome(direction, ltp, entry, sl, t1, t2, t1_prog, "OPEN")

                self.telegram_records[key] = TrackedSetup(
                    symbol=sym,
                    name=str(get_val("name") or sym),
                    sector=str(get_val("sector") or "NSE Equity"),
                    direction=direction,
                    setup_type=str(get_val("setup_type") or ("CONFIRMED_BREAKDOWN_SHORT" if direction == "BEARISH" else "V13_BREAKOUT")),
                    initial_score=score,
                    peak_score=score,
                    peak_tier=tier,
                    entry_price=entry,
                    stop_loss=sl,
                    target_1=t1,
                    target_2=t2,
                    risk_amount=risk_amt,
                    ltp=ltp,
                    first_detection_stage=first_stage,
                    current_status=exec_status or "ACTIONABLE_IN_PLAY",
                    t1_progress_pct=t1_prog,
                    outcome=init_outcome,
                    realized_r=init_r,
                    highest_progress_pct=t1_prog,
                    registered_at=now_iso,
                    last_updated_at=now_iso,
                    outcome_time=now_iso if init_outcome != "OPEN" else None,
                )
                self._save_to_disk()
                logger.info(f"Recorded telegram alerted trade for {key} (Entry: {entry}, SL: {sl}, T1: {t1})")

                # Hook: Record Initial Conviction Snapshot in Standalone Conviction Audit Diary
                try:
                    from .v13_conviction_audit import GLOBAL_CONVICTION_AUDITOR, is_conviction_audit_enabled
                    if is_conviction_audit_enabled():
                        GLOBAL_CONVICTION_AUDITOR.record_entry(signal)
                except Exception as ce:
                    logger.debug(f"Conviction audit record_entry skipped: {ce}")

    def _evaluate_outcome(
        self,
        direction: str,
        ltp: float,
        entry: float,
        sl: float,
        t1: float,
        t2: float,
        t1_prog: float,
        prev_outcome: str,
    ) -> tuple[str, float]:
        """
        V14 Dual-Tranche Outcome Model (Harmonized 2.5R Architecture):
        - Tranche 1 (50% Quantity): Target 1 = +1.5R (Locks in +0.75R)
        - Tranche 2 (50% Quantity): Target 2 = +2.5R (Locks in +1.25R, Total Win = +2.00R)
        - Trailing: Once T1 is hit, remaining 50% SL moves to Breakeven (Entry).
          If Breakeven is hit: Realized R = +0.75R + 0.00R = +0.75R.
        - Stop Loss before T1: 100% position exits at SL = -1.00R.
        """
        # If already T2 hit, outcome is locked at full +2.00R win
        if prev_outcome == "T2_HIT":
            return "T2_HIT", 2.0

        # If already stopped out, outcome is locked as a loss (-1.0R)
        if prev_outcome == "SL_HIT":
            return "SL_HIT", -1.0

        # If already exited at Breakeven after T1, outcome is locked at +0.75R
        if prev_outcome == "T1_WIN_BE_EXIT":
            return "T1_WIN_BE_EXIT", 0.75

        # If already closed at EOD, outcome is locked
        if prev_outcome in ("CLOSED_EOD_PROFIT", "CLOSED_EOD_LOSS", "CLOSED_EOD_FLAT", "EOD_PARTIAL_WIN"):
            return prev_outcome, 0.0

        # If already T1 hit (Tranche 1 locked at +0.75R, Tranche 2 trailing with SL at Breakeven)
        if prev_outcome in ("T1_HIT", "T1_HIT_TRAILED"):
            # Check T2 Hit (+2.5R on remaining 50% -> total +2.00R)
            if direction == "BULLISH" and t2 > 0 and ltp >= t2:
                return "T2_HIT", 2.0
            elif direction == "BEARISH" and t2 > 0 and ltp <= t2:
                return "T2_HIT", 2.0

            # Check Breakeven Hit on trailing Tranche 2 (LTP returns to entry)
            if direction == "BULLISH" and entry > 0 and ltp <= entry:
                return "T1_WIN_BE_EXIT", 0.75
            elif direction == "BEARISH" and entry > 0 and ltp >= entry:
                return "T1_WIN_BE_EXIT", 0.75

            return "T1_HIT_TRAILED", 0.75

        # Check for T2 Hit first (rapid expansion past T2 on same bar)
        if direction == "BULLISH" and t2 > 0 and ltp >= t2:
            return "T2_HIT", 2.0
        elif direction == "BEARISH" and t2 > 0 and ltp <= t2:
            return "T2_HIT", 2.0

        # Check for T1 Hit
        if (t1_prog >= 100.0) or (direction == "BULLISH" and t1 > 0 and ltp >= t1) or (direction == "BEARISH" and t1 > 0 and ltp <= t1):
            return "T1_HIT_TRAILED", 0.75

        # Check for SL Hit (only if T1 was never reached)
        if direction == "BULLISH" and sl > 0 and ltp <= sl:
            return "SL_HIT", -1.0
        elif direction == "BEARISH" and sl > 0 and ltp >= sl:
            return "SL_HIT", -1.0

        return "OPEN", 0.0

    def get_summary_metrics(self, check_rollover: bool = True) -> Dict[str, Any]:
        """Compute exact category-wise, lifecycle, and overall session metrics."""
        effective_date = get_effective_trading_date()
        with self.lock:
            if check_rollover:
                self._check_rollover(effective_date)
            # Auto-settle if queried after 03:30 PM on a weekday
            ist_now = datetime.now(IST_TZ)
            if ist_now.weekday() <= 4 and ist_now.time() >= dtime(15, 30):
                self._settle_eod_trades(ist_now)
            all_setups = list(self.records.values())

        total = len(all_setups)
        if total == 0:
            return {"total": 0, "total_signals": 0}

        # Lifecycle breakdown (0-25%, 25-75%, 75-99%, 100%+)
        early_count = sum(1 for s in all_setups if s.first_detection_stage == "EARLY_TRIGGER")
        actionable_count = sum(1 for s in all_setups if s.first_detection_stage == "ACTIONABLE")
        near_target_count = sum(1 for s in all_setups if s.first_detection_stage == "TARGET_NEAR")
        target_hit_count = sum(1 for s in all_setups if s.first_detection_stage == "TARGET_HIT")

        # Outcomes overall
        t1_total_hits = sum(1 for s in all_setups if s.outcome in ("T1_HIT", "T2_HIT", "T1_HIT_TRAILED", "T1_WIN_BE_EXIT", "EOD_PARTIAL_WIN"))
        t2_runners = sum(1 for s in all_setups if s.outcome == "T2_HIT")
        t1_only = t1_total_hits - t2_runners  # T1 Hits minus T2 Runners
        sl_losses = sum(1 for s in all_setups if s.outcome == "SL_HIT")
        eod_profits = sum(1 for s in all_setups if s.outcome in ("CLOSED_EOD_PROFIT", "EOD_PARTIAL_WIN"))
        eod_losses = sum(1 for s in all_setups if s.outcome == "CLOSED_EOD_LOSS")
        eod_flats = sum(1 for s in all_setups if s.outcome in ("CLOSED_EOD_FLAT", "T1_WIN_BE_EXIT"))
        eod_settled = eod_profits + eod_losses + eod_flats
        open_eod = sum(1 for s in all_setups if s.outcome in ("OPEN", "T1_HIT_TRAILED"))
        total_r = sum(s.realized_r for s in all_setups)

        def tier_metrics(tier_name: str) -> Dict[str, Any]:
            tier_setups = [s for s in all_setups if s.peak_tier == tier_name]
            count = len(tier_setups)
            if count == 0:
                return {
                    "total": 0, "early_caught": 0, "early_pct": 0.0,
                    "t1_hit": 0, "t1_pct": 0.0,
                    "t1_only": 0, "t1_only_pct": 0.0,
                    "t2_hit": 0, "t2_pct": 0.0,
                    "sl_hit": 0, "sl_pct": 0.0,
                    "eod_settled": 0, "eod_settled_pct": 0.0,
                    "eod_profits": 0, "eod_profit_pct": 0.0,
                    "eod_losses": 0, "eod_loss_pct": 0.0,
                    "eod_flats": 0, "eod_flat_pct": 0.0,
                    "open": 0, "open_pct": 0.0,
                }
            early = sum(1 for s in tier_setups if s.first_detection_stage == "EARLY_TRIGGER")
            t1_total = sum(1 for s in tier_setups if s.outcome in ("T1_HIT", "T2_HIT", "T1_HIT_TRAILED", "T1_WIN_BE_EXIT", "EOD_PARTIAL_WIN"))
            t2 = sum(1 for s in tier_setups if s.outcome == "T2_HIT")
            t1_only = t1_total - t2
            sl = sum(1 for s in tier_setups if s.outcome == "SL_HIT")
            eod_p = sum(1 for s in tier_setups if s.outcome in ("CLOSED_EOD_PROFIT", "EOD_PARTIAL_WIN"))
            eod_l = sum(1 for s in tier_setups if s.outcome == "CLOSED_EOD_LOSS")
            eod_f = sum(1 for s in tier_setups if s.outcome in ("CLOSED_EOD_FLAT", "T1_WIN_BE_EXIT"))
            eod_set = eod_p + eod_l + eod_f
            op = sum(1 for s in tier_setups if s.outcome in ("OPEN", "T1_HIT_TRAILED"))

            return {
                "total": count,
                "early_caught": early,
                "early_pct": round((early / count) * 100, 1),
                "t1_hit": t1_total,
                "t1_pct": round((t1_total / count) * 100, 1),
                "t1_only": t1_only,
                "t1_only_pct": round((t1_only / count) * 100, 1),
                "t2_hit": t2,
                "t2_pct": round((t2 / count) * 100, 1),
                "sl_hit": sl,
                "sl_pct": round((sl / count) * 100, 1),
                "eod_settled": eod_set,
                "eod_settled_pct": round((eod_set / count) * 100, 1),
                "eod_profits": eod_p,
                "eod_profit_pct": round((eod_p / count) * 100, 1),
                "eod_losses": eod_l,
                "eod_loss_pct": round((eod_l / count) * 100, 1),
                "eod_flats": eod_f,
                "eod_flat_pct": round((eod_f / count) * 100, 1),
                "open": op,
                "open_pct": round((op / count) * 100, 1),
            }

        high_conf = tier_metrics("HIGH_CONFIDENCE")
        strong = tier_metrics("STRONG")
        watchlist = tier_metrics("WATCHLIST")

        # Reconcile exact Telegram Dispatched Alerts
        if self.telegram_records:
            tg_alerts: list[TrackedSetup] = list(self.telegram_records.values())
        else:
            tg_alerts = []
            if os.path.exists(SENT_ALERTS_CACHE_FILE):
                try:
                    with open(SENT_ALERTS_CACHE_FILE, "r", encoding="utf-8") as f:
                        sent_cache = json.load(f)
                    for sym, info in sent_cache.items():
                        if not isinstance(info, dict):
                            continue
                        item_date = info.get("date")
                        if item_date == self.date_str:
                            d = str(info.get("direction", "BULLISH")).upper()
                            key = f"{sym}_{d}"
                            rec = self.records.get(key)
                            if rec:
                                tg_alerts.append(rec)
                except Exception as e:
                    logger.warning(f"Error loading sent_alerts_cache for audit: {e}")

        tg_total = len(tg_alerts)
        if tg_total > 0:
            tg_t1_total = sum(1 for s in tg_alerts if s.outcome in ("T1_HIT", "T2_HIT", "T1_HIT_TRAILED", "T1_WIN_BE_EXIT", "EOD_PARTIAL_WIN"))
            tg_t2_runners = sum(1 for s in tg_alerts if s.outcome == "T2_HIT")
            tg_t1_only = tg_t1_total - tg_t2_runners
            tg_sl_losses = sum(1 for s in tg_alerts if s.outcome == "SL_HIT")
            tg_eod_profits = sum(1 for s in tg_alerts if s.outcome in ("CLOSED_EOD_PROFIT", "EOD_PARTIAL_WIN"))
            tg_eod_losses = sum(1 for s in tg_alerts if s.outcome == "CLOSED_EOD_LOSS")
            tg_eod_flats = sum(1 for s in tg_alerts if s.outcome in ("CLOSED_EOD_FLAT", "T1_WIN_BE_EXIT"))
            tg_eod_settled = tg_eod_profits + tg_eod_losses + tg_eod_flats
            tg_open = sum(1 for s in tg_alerts if s.outcome in ("OPEN", "T1_HIT_TRAILED"))
            tg_r = sum(s.realized_r for s in tg_alerts)
            telegram_scorecard = {
                "total_dispatched": tg_total,
                "t1_only": tg_t1_only,
                "t1_only_pct": round((tg_t1_only / tg_total) * 100, 1),
                "t2_runners": tg_t2_runners,
                "t2_rate_pct": round((tg_t2_runners / tg_total) * 100, 1),
                "total_target_wins": tg_t1_total,
                "win_rate_pct": round((tg_t1_total / tg_total) * 100, 1),
                "sl_losses": tg_sl_losses,
                "sl_loss_pct": round((tg_sl_losses / tg_total) * 100, 1),
                "eod_settled": tg_eod_settled,
                "eod_settled_pct": round((tg_eod_settled / tg_total) * 100, 1),
                "eod_profits": tg_eod_profits,
                "eod_profit_pct": round((tg_eod_profits / tg_total) * 100, 1),
                "eod_losses": tg_eod_losses,
                "eod_loss_pct": round((tg_eod_losses / tg_total) * 100, 1),
                "eod_flats": tg_eod_flats,
                "eod_flat_pct": round((tg_eod_flats / tg_total) * 100, 1),
                "open": tg_open,
                "open_pct": round((tg_open / tg_total) * 100, 1),
                "net_realized_r": round(tg_r, 2),
            }
        else:
            telegram_scorecard = {
                "total_dispatched": 0,
                "t1_only": 0, "t1_only_pct": 0.0,
                "t2_runners": 0, "t2_rate_pct": 0.0,
                "total_target_wins": 0, "win_rate_pct": 0.0,
                "sl_losses": 0, "sl_loss_pct": 0.0,
                "eod_settled": 0, "eod_settled_pct": 0.0,
                "eod_profits": 0, "eod_profit_pct": 0.0,
                "eod_losses": 0, "eod_loss_pct": 0.0,
                "eod_flats": 0, "eod_flat_pct": 0.0,
                "open": 0, "open_pct": 0.0,
                "net_realized_r": 0.0,
            }

        # Top performers (Strictly winning trades with positive realized R)
        winning_setups = [
            s for s in all_setups
            if s.outcome in ("T1_HIT", "T2_HIT", "T1_HIT_TRAILED", "T1_WIN_BE_EXIT", "CLOSED_EOD_PROFIT", "EOD_PARTIAL_WIN") and s.realized_r > 0
        ]
        sorted_by_prog = sorted(winning_setups, key=lambda s: (s.realized_r, s.highest_progress_pct), reverse=True)
        top_performers = [
            {
                "symbol": s.symbol,
                "direction": s.direction,
                "r_mult": s.realized_r,
                "t1_prog": round(s.highest_progress_pct, 1),
            }
            for s in sorted_by_prog[:3]
        ]

        return {
            "total_signals": total,
            "date": self.date_str,
            "telegram_scorecard": telegram_scorecard,
            "lifecycle": {
                "early_count": early_count,
                "early_pct": round((early_count / total) * 100, 1),
                "actionable_count": actionable_count,
                "actionable_pct": round((actionable_count / total) * 100, 1),
                "near_target_count": near_target_count,
                "near_target_pct": round((near_target_count / total) * 100, 1),
                "target_hit_count": target_hit_count,
                "target_hit_pct": round((target_hit_count / total) * 100, 1),
            },
            "high_confidence": high_conf,
            "strong": strong,
            "watchlist": watchlist,
            "overall": {
                "total_triggered": total,
                "t1_wins": t1_total_hits,
                "win_rate_pct": round((t1_total_hits / total) * 100, 1) if total > 0 else 0.0,
                "t1_only": t1_only,
                "t1_only_pct": round((t1_only / total) * 100, 1) if total > 0 else 0.0,
                "t2_runners": t2_runners,
                "t2_rate_pct": round((t2_runners / total) * 100, 1) if total > 0 else 0.0,
                "sl_losses": sl_losses,
                "sl_loss_pct": round((sl_losses / total) * 100, 1) if total > 0 else 0.0,
                "eod_settled": eod_settled,
                "eod_settled_pct": round((eod_settled / total) * 100, 1) if total > 0 else 0.0,
                "eod_profits": eod_profits,
                "eod_losses": eod_losses,
                "eod_flats": eod_flats,
                "open_eod": open_eod,
                "open_pct": round((open_eod / total) * 100, 1) if total > 0 else 0.0,
                "net_realized_r": round(total_r, 2),
            },
            "top_performers": top_performers,
        }

    def format_telegram_eod_report(self, market_regime: str = "Neutral", now_dt: Optional[datetime] = None) -> str:
        """Render the complete Telegram EOD Performance Audit Markdown text."""
        effective_now = now_dt or datetime.now(IST_TZ)
        m = self.get_summary_metrics(check_rollover=False)
        if m.get("total_signals", 0) == 0:
            msg = (
                "=================================================\n"
                "📊 *NSE-PULSE V13: DAILY EOD PERFORMANCE AUDIT*\n"
                f"📅 Date: {self.date_str} | Session: {market_regime}\n"
                "=================================================\n"
                "No qualified setups (Score ≥ 72) were recorded today."
            )
            try:
                from .nse_calendar import format_holiday_telegram_notice
                holiday_notice = format_holiday_telegram_notice(effective_now)
                if holiday_notice:
                    msg += f"\n\n{holiday_notice}"
            except Exception:
                pass
            return msg

        lc = m["lifecycle"]
        hc = m["high_confidence"]
        st = m["strong"]
        wl = m["watchlist"]
        ov = m["overall"]

        top_lines = []
        for idx, p in enumerate(m.get("top_performers", []), 1):
            top_lines.append(f"   {idx}. *{p['symbol']}* (+{p['r_mult']}R / {p['t1_prog']}%)")
        top_str = "\n".join(top_lines) if top_lines else "   • None (No Target 1 hits today)"

        # Telegram Dispatched Alerts Scorecard Section
        tg = m.get("telegram_scorecard") or {}
        tg_section = ""
        if tg.get("total_dispatched", 0) > 0:
            tg_section = (
                "-------------------------------------------------\n"
                "📱 *TELEGRAM LIVE ALERTS SCORECARD (Real-World Traded):*\n"
                "⚙️ Active Alerts Triggered on Phone Today\n"
                "-------------------------------------------------\n"
                f"   • Total Dispatched Alerts : {tg['total_dispatched']} (100%)\n"
                f"   • Target 1 Only Wins      : {tg['t1_only']} ({tg['t1_only_pct']}%)\n"
                f"   • Target 2 Runners        : {tg['t2_runners']} ({tg['t2_rate_pct']}% Deep Trend)\n"
                f"   • Total Target Wins       : {tg['total_target_wins']} ({tg['win_rate_pct']}% Win Rate)\n"
                f"   • Stop Loss (SL Hit)      : {tg['sl_losses']} ({tg['sl_loss_pct']}% Loss Rate)\n"
                f"   • EOD Auto-Settled (MTM)  : {tg['eod_settled']} ({tg['eod_settled_pct']}%)\n"
                f"     ├─ 🟢 Closed in Profit  : {tg['eod_profits']} ({tg['eod_profit_pct']}%)\n"
                f"     ├─ 🔴 Closed in Loss    : {tg['eod_losses']} ({tg['eod_loss_pct']}%)\n"
                f"     └─ ⚪ Closed Flat (C2C) : {tg['eod_flats']} ({tg['eod_flat_pct']}%)\n"
                f"   • Open at EOD             : {tg['open']} ({tg['open_pct']}%)\n"
                f"   • Net Realized R-Multiple : {tg['net_realized_r']:+.2f} R\n\n"
            )

        report = (
            "=================================================\n"
            "📊 *NSE-PULSE V13: DAILY EOD PERFORMANCE AUDIT*\n"
            f"📅 Date: {m['date']} | Session: {market_regime}\n"
            "=================================================\n\n"
            "⚡ *EXECUTION LIFECYCLE BREAKDOWN (Timing Accuracy):*\n"
            f"  • ⚡ Early Triggers (0–25% Prog)    : {lc['early_count']} ({lc['early_pct']}% - Golden Entry)\n"
            f"  • 🎯 Actionable Plays (25–75% Prog) : {lc['actionable_count']} ({lc['actionable_pct']}% - Continuation)\n"
            f"  • ⏳ Near Target (75–99% Prog)      : {lc['near_target_count']} ({lc['near_target_pct']}%  - Trailing Zone)\n"
            f"  • 🏆 Target 1 Hit (≥ 100% Prog)     : {lc['target_hit_count']} ({lc['target_hit_pct']}% - Accomplished)\n\n"
            f"{tg_section}"
            "-------------------------------------------------\n"
            "🏆 *QUALITY TIER BREAKDOWN (Peak Score):*\n"
            "-------------------------------------------------\n"
            "🥇 *HIGH CONFIDENCE (Peak Score ≥ 85):*\n"
            f"   • Total Setups     : {hc['total']}\n"
            f"   • Early Caught     : {hc['early_caught']}  ({hc['early_pct']}% Caught at Base)\n"
            f"   • Target 1 (Only)  : {hc['t1_only']}  ({hc['t1_only_pct']}% T1 Win)\n"
            f"   • Target 2 Runners : {hc['t2_hit']}  ({hc['t2_pct']}% T2 Runner Rate)\n"
            f"   • Stop Loss (SL)   : {hc['sl_hit']}  ({hc['sl_pct']}% SL Loss Rate)\n"
            f"   • EOD Auto-Settled : {hc['eod_settled']}  ({hc['eod_settled_pct']}% MTM Settled)\n"
            f"     ├─ 🟢 Closed in Profit : {hc['eod_profits']} ({hc['eod_profit_pct']}%)\n"
            f"     ├─ 🔴 Closed in Loss   : {hc['eod_losses']} ({hc['eod_loss_pct']}%)\n"
            f"     └─ ⚪ Closed Flat (C2C): {hc['eod_flats']} ({hc['eod_flat_pct']}%)\n"
            f"   • Open at EOD      : {hc['open']}  ({hc['open_pct']}%)\n\n"
            "🥈 *STRONG SETUPS (Peak Score 80–84.9):*\n"
            f"   • Total Setups     : {st['total']}\n"
            f"   • Early Caught     : {st['early_caught']}  ({st['early_pct']}% Caught at Base)\n"
            f"   • Target 1 (Only)  : {st['t1_only']}  ({st['t1_only_pct']}% T1 Win)\n"
            f"   • Target 2 Runners : {st['t2_hit']}  ({st['t2_pct']}% T2 Runner Rate)\n"
            f"   • Stop Loss (SL)   : {st['sl_hit']}  ({st['sl_pct']}% SL Loss Rate)\n"
            f"   • EOD Auto-Settled : {st['eod_settled']}  ({st['eod_settled_pct']}% MTM Settled)\n"
            f"     ├─ 🟢 Closed in Profit : {st['eod_profits']} ({st['eod_profit_pct']}%)\n"
            f"     ├─ 🔴 Closed in Loss   : {st['eod_losses']} ({st['eod_loss_pct']}%)\n"
            f"     └─ ⚪ Closed Flat (C2C): {st['eod_flats']} ({st['eod_flat_pct']}%)\n"
            f"   • Open at EOD      : {st['open']}  ({st['open_pct']}%)\n\n"
            "🥉 *WATCHLIST (Peak Score 72–79.9):*\n"
            f"   • Total Setups     : {wl['total']}\n"
            f"   • Early Caught     : {wl['early_caught']} ({wl['early_pct']}% Caught at Base)\n"
            f"   • Target 1 (Only)  : {wl['t1_only']} ({wl['t1_only_pct']}% T1 Win)\n"
            f"   • Target 2 Runners : {wl['t2_hit']} ({wl['t2_pct']}% T2 Runner Rate)\n"
            f"   • Stop Loss (SL)   : {wl['sl_hit']} ({wl['sl_pct']}% SL Loss Rate)\n"
            f"   • EOD Auto-Settled : {wl['eod_settled']} ({wl['eod_settled_pct']}% MTM Settled)\n"
            f"     ├─ 🟢 Closed in Profit : {wl['eod_profits']} ({wl['eod_profit_pct']}%)\n"
            f"     ├─ 🔴 Closed in Loss   : {wl['eod_losses']} ({wl['eod_loss_pct']}%)\n"
            f"     └─ ⚪ Closed Flat (C2C): {wl['eod_flats']} ({wl['eod_flat_pct']}%)\n"
            f"   • Open at EOD      : {wl['open']} ({wl['open_pct']}%)\n\n"
            "=================================================\n"
            "🎯 *TOTAL SESSION ACCURACY & METRICS:*\n"
            f"   • Total Signals Triggered : {ov['total_triggered']} (100%)\n"
            f"   • Target 1 Only Wins      : {ov['t1_only']} ({ov['t1_only_pct']}% T1 Win Rate)\n"
            f"   • Target 2 Runners        : {ov['t2_runners']} ({ov['t2_rate_pct']}% Deep Trend Wins)\n"
            f"   • Total Target Wins       : {ov['t1_wins']} ({ov['win_rate_pct']}% Combined Win Rate)\n"
            f"   • Total Losses (SL Hit)   : {ov['sl_losses']} ({ov['sl_loss_pct']}% Loss Rate)\n"
            f"   • EOD Auto-Settled (MTM)  : {ov['eod_settled']} ({ov['eod_settled_pct']}% Settled at 15:30)\n"
            f"     ├─ 🟢 Closed in Profit  : {ov['eod_profits']} ({round((ov['eod_profits']/ov['total_triggered'])*100, 1) if ov['total_triggered'] > 0 else 0.0}%)\n"
            f"     ├─ 🔴 Closed in Loss    : {ov['eod_losses']} ({round((ov['eod_losses']/ov['total_triggered'])*100, 1) if ov['total_triggered'] > 0 else 0.0}%)\n"
            f"     └─ ⚪ Closed Flat (C2C) : {ov['eod_flats']} ({round((ov['eod_flats']/ov['total_triggered'])*100, 1) if ov['total_triggered'] > 0 else 0.0}%)\n"
            f"   • Open at EOD             : {ov['open_eod']} ({ov['open_pct']}% Unrealized)\n"
            f"   • Net Realized R-Multiple : {ov['net_realized_r']:+.2f} R\n\n"
            "🚀 *TOP 3 WINNERS OF THE DAY:*\n"
            f"{top_str}\n"
            "================================================="
        )

        # Check if next trading day is an upcoming NSE Holiday (e.g. Thursday EOD warning about Friday)
        try:
            from .nse_calendar import format_holiday_telegram_notice
            holiday_notice = format_holiday_telegram_notice(effective_now)
            if holiday_notice:
                report += f"\n\n{holiday_notice}"
        except Exception:
            pass

        return report

    def dispatch_eod_audit(
        self,
        market_regime: str = "Neutral",
        now_dt: Optional[datetime] = None,
        force: bool = False,
    ) -> bool:
        """
        Thread-safe, atomic EOD Performance Audit dispatcher for V13 SessionTradeLedger.
        Acquires self.lock and optimistically records eod_audit_sent_date BEFORE making the
        network call to Telegram (PulseX1000 bot), preventing duplicate notifications when
        v13-scan-worker and _v13_continuous_loop Watchdog 1 execute concurrently at 15:30 IST.
        """
        effective_now = now_dt or datetime.now(IST_TZ)
        today_str = get_effective_trading_date(effective_now)

        with self.lock:
            self._check_rollover(today_str)
            if not force and self.eod_audit_sent_date == today_str:
                return False
            # Prevent dispatching empty EOD notifications when no setups or alerts exist unless forced
            if not force and not self.records and not self.telegram_records:
                return False
            prev_sent_date = self.eod_audit_sent_date
            self.eod_audit_sent_date = today_str
            self._save_to_disk()

            # Also persist today's EOD archive snapshot non-destructively
            try:
                os.makedirs(LEDGER_HISTORY_DIR, exist_ok=True)
                archive_path = os.path.join(LEDGER_HISTORY_DIR, f"ledger_{today_str}.json")
                should_save_archive = True
                if os.path.exists(archive_path) and os.path.getsize(archive_path) > 0:
                    try:
                        with open(archive_path, "r", encoding="utf-8") as ef:
                            existing_arch = json.load(ef)
                        existing_rec_cnt = len(existing_arch.get("screener_records") or existing_arch.get("records") or {})
                        existing_tg_cnt = len(existing_arch.get("telegram_alerted_trades") or {})
                        if existing_rec_cnt > len(self.records) or existing_tg_cnt > len(self.telegram_records):
                            should_save_archive = False
                    except Exception:
                        pass
                if should_save_archive:
                    self._save_to_disk_path(archive_path)
            except Exception as e:
                logger.warning(f"Failed to save EOD archive snapshot for {today_str}: {e}")

        report_text = self.format_telegram_eod_report(
            market_regime=market_regime,
            now_dt=effective_now,
        )
        from .telegram_bot import send_telegram_text
        sent = send_telegram_text(report_text, sync_send=True)
        if not sent:
            with self.lock:
                self.eod_audit_sent_date = prev_sent_date
                self._save_to_disk()
        return bool(sent)

    def _save_to_disk(self) -> None:
        self._save_to_disk_path(self.data_file)

    def _save_to_disk_path(self, path: str) -> None:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp_path = path + ".tmp"
            data = {
                "date": self.date_str,
                "last_synced_at": datetime.now(IST_TZ).isoformat(),
                "eod_audit_sent_date": self.eod_audit_sent_date,
                "weekly_audit_sent_week": self.weekly_audit_sent_week,
                "telegram_alerted_trades": {k: asdict(v) for k, v in self.telegram_records.items()},
                "screener_records": {k: asdict(v) for k, v in self.records.items()},
                "records": {k: asdict(v) for k, v in self.records.items()},
            }
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception as e:
            logger.error(f"Error saving session ledger to {path}: {e}")

    def _load_from_disk(self) -> None:
        if not os.path.exists(self.data_file) or os.path.getsize(self.data_file) == 0:
            return
        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw_loaded_date = data.get("date")
            loaded_date = str(raw_loaded_date)[:10] if raw_loaded_date else None
            effective_date = get_effective_trading_date()

            if loaded_date == effective_date:
                self.date_str = effective_date
                self.eod_audit_sent_date = data.get("eod_audit_sent_date")
                self.weekly_audit_sent_week = data.get("weekly_audit_sent_week")
                records_data = data.get("screener_records") or data.get("records", {})
                valid_fields = {f.name for f in fields(TrackedSetup)}
                for k, v in records_data.items():
                    try:
                        clean_v = {kf: vf for kf, vf in v.items() if kf in valid_fields} if isinstance(v, dict) else v
                        self.records[k] = TrackedSetup(**clean_v)
                    except Exception:
                        pass
                tg_data = data.get("telegram_alerted_trades", {})
                for k, v in tg_data.items():
                    try:
                        clean_v = {kf: vf for kf, vf in v.items() if kf in valid_fields} if isinstance(v, dict) else v
                        self.telegram_records[k] = TrackedSetup(**clean_v)
                    except Exception:
                        pass
                logger.info(f"Loaded session ledger for {effective_date} with {len(self.records)} setups ({len(self.telegram_records)} telegram alerted)")
            else:
                logger.info(f"Existing ledger is from {loaded_date}, rolling over for session {effective_date}")
                if loaded_date and (data.get("records") or data.get("screener_records")):
                    # Catch-Up Guard on Startup: If previous session's EOD audit was never sent
                    if not data.get("eod_audit_sent_date"):
                        try:
                            # Rehydrate previous session temporarily to compute and dispatch audit
                            self.date_str = loaded_date
                            records_data = data.get("screener_records") or data.get("records", {})
                            valid_fields = {f.name for f in fields(TrackedSetup)}
                            self.records = {
                                k: TrackedSetup(**({kf: vf for kf, vf in v.items() if kf in valid_fields} if isinstance(v, dict) else v))
                                for k, v in records_data.items()
                            }
                            tg_data = data.get("telegram_alerted_trades", {})
                            self.telegram_records = {
                                k: TrackedSetup(**({kf: vf for kf, vf in v.items() if kf in valid_fields} if isinstance(v, dict) else v))
                                for k, v in tg_data.items()
                            }
                            dispatched = self._dispatch_catchup_audit(loaded_date)
                            if dispatched:
                                data["eod_audit_sent_date"] = loaded_date
                        except Exception as e:
                            logger.error(f"Catch-up EOD audit failed on startup for {loaded_date}: {e}")

                    try:
                        os.makedirs(LEDGER_HISTORY_DIR, exist_ok=True)
                        archive_path = os.path.join(LEDGER_HISTORY_DIR, f"ledger_{loaded_date}.json")
                        should_save_archive = True
                        if os.path.exists(archive_path) and os.path.getsize(archive_path) > 0:
                            try:
                                with open(archive_path, "r", encoding="utf-8") as ef:
                                    existing_arch = json.load(ef)
                                existing_rec_cnt = len(existing_arch.get("screener_records") or existing_arch.get("records") or {})
                                existing_tg_cnt = len(existing_arch.get("telegram_alerted_trades") or {})
                                cur_rec_cnt = len(data.get("screener_records") or data.get("records") or {})
                                cur_tg_cnt = len(data.get("telegram_alerted_trades") or {})
                                if existing_rec_cnt > cur_rec_cnt or existing_tg_cnt > cur_tg_cnt:
                                    should_save_archive = False
                            except Exception:
                                pass
                        if should_save_archive:
                            with open(archive_path, "w", encoding="utf-8") as af:
                                json.dump(data, af, ensure_ascii=False, indent=2)
                            logger.info(f"Archived previous ledger for {loaded_date} to {archive_path}")
                    except Exception as e:
                        logger.error(f"Failed to archive loaded ledger: {e}")

                    # Archive and rollover telegram alerts on startup rollover
                    try:
                        from .telegram_bot import archive_session_telegram_alerts, rollover_sent_alerts_cache
                        archive_session_telegram_alerts(loaded_date, data.get("telegram_alerted_trades") or data.get("records", {}))
                        rollover_sent_alerts_cache(effective_date, loaded_date)
                    except Exception as e:
                        logger.error(f"Failed to rollover telegram alerts on startup: {e}")

                self.date_str = effective_date
                self.records.clear()
                self.telegram_records.clear()
                self.eod_audit_sent_date = None
                self._save_to_disk()
        except Exception as e:
            logger.error(f"Error loading session ledger from {self.data_file}: {e}")


# Global Singleton Ledger Instance
GLOBAL_SESSION_LEDGER = SessionTradeLedger()
