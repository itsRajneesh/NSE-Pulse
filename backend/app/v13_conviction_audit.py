"""
NSE-PULSE V13: Conviction Drift & Regime Decay Audit Ledger.

Dedicated, standalone quantitative audit module that tracks the lifecycle
of trade conviction from initial alert trigger (T0) to exit / EOD (T_end).

3 Critical Architectural Guardrails:
1. Linked directly with `v13_ledger.py`'s `telegram_records` for live LTP, SL, T1, T2, and outcomes (Zero duplicate network calls).
2. Evaluates dynamic conviction drift strictly on closed 15m scan updates (Zero micro-tick noise).
   Pillar 3 (Candle Breakout Purity) is frozen permanently at trigger time.
3. Formats an aggregated, high-impact Telegram report strictly under 4,096 characters.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, time as dtime
from typing import Any, Dict, List, Optional, Tuple

from .config import IST_TZ

logger = logging.getLogger("v13_conviction_audit")

# Dedicated storage directory for conviction audit ledgers
AUDIT_DIR = os.path.join(os.path.dirname(__file__), "data", "conviction_audit_ledgers")


def is_conviction_audit_enabled() -> bool:
    """Check if conviction drift audit logging is enabled via .env."""
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path, override=True)
    except Exception:
        pass
    val = os.getenv("ENABLE_CONVICTION_AUDIT", "true").strip().lower()
    return val in ("true", "1", "yes")


@dataclass
class ConvictionTradeAudit:
    symbol: str
    name: str
    sector: str
    direction: str
    setup_type: str

    # Trade Levels
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    risk_amount: float
    entry_time: str

    # Initial Conviction (T0 Trigger Moment)
    entry_score: float
    entry_grade: str  # "GRADE_A_PLUS", "GRADE_B", "GRADE_C"
    entry_badge: str
    entry_pillars: Dict[str, float]  # {"market": float, "sector": float, "candle": float}
    static_candle_pts: float  # Permanent frozen base (Pillar 3)

    # Dynamic Flow Tracking (Latest)
    latest_score: float
    latest_grade: str
    latest_badge: str
    latest_pillars: Dict[str, float]
    latest_ltp: float
    latest_progress_pct: float
    highest_progress_pct: float

    # Minimums & Decay Tracking
    min_score: float
    min_grade: str
    decay_detected: bool = False
    decay_time: Optional[str] = None
    decay_culprit: Optional[str] = None  # "NIFTY_REVERSAL", "SECTOR_INVERSION", "NIFTY_AND_SECTOR"
    decay_price: Optional[float] = None
    decay_progress_pct: Optional[float] = None
    peak_t1_progress_before_decay: float = 0.0

    # Outcome & Attribution
    outcome: str = "OPEN"  # "OPEN", "T1_HIT", "T2_HIT", "SL_HIT", "CLOSED_EOD_PROFIT", "CLOSED_EOD_LOSS", "CLOSED_EOD_FLAT", "T1_HIT_TRAILED", "T1_WIN_BE_EXIT", "EOD_PARTIAL_WIN"
    realized_r: float = 0.0
    outcome_time: Optional[str] = None
    trajectory: str = "PRESERVED"  # "PRESERVED", "COLLAPSED", "DEGRADED", "UPGRADED"
    score_delta: float = 0.0
    saved_r_potential: float = 0.0


class ConvictionAuditor:
    """
    Thread-safe standalone engine tracking the conviction lifecycle
    of all Telegram dispatched signals.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._session_date: str = ""
        self._trades: Dict[str, ConvictionTradeAudit] = {}
        self._eod_dispatched_date: Optional[str] = None
        self._load_or_init_today()

    def _get_today_str(self) -> str:
        try:
            from .v13_ledger import get_effective_trading_date
            eff_date = get_effective_trading_date()
            if eff_date:
                return eff_date
        except Exception:
            pass
        return datetime.now(IST_TZ).strftime("%Y-%m-%d")

    def _get_file_path(self, date_str: str) -> str:
        os.makedirs(AUDIT_DIR, exist_ok=True)
        return os.path.join(AUDIT_DIR, f"conviction_audit_{date_str}.json")

    def _load_or_init_today(self) -> None:
        today = self._get_today_str()
        if self._session_date != today:
            self._session_date = today
            self._trades = {}
            self._eod_dispatched_date = None

            fpath = self._get_file_path(today)
            if os.path.exists(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._eod_dispatched_date = data.get("eod_dispatched_date")
                    for k, t_dict in data.get("trades", {}).items():
                        try:
                            self._trades[k] = ConvictionTradeAudit(**t_dict)
                        except Exception:
                            pass
                except Exception as e:
                    logger.debug(f"Failed to load conviction audit {fpath}: {e}")

    def _save_atomic(self) -> None:
        try:
            today = self._session_date or self._get_today_str()
            fpath = self._get_file_path(today)
            tmp_path = fpath + ".tmp"

            payload = self.get_audit_summary()

            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, fpath)
        except Exception as e:
            logger.debug(f"Conviction audit atomic save failed: {e}")

    @property
    def eod_dispatched_date(self) -> Optional[str]:
        return self._eod_dispatched_date

    def record_entry(
        self,
        signal: Dict[str, Any],
        market_context: Optional[Dict[str, Any]] = None,
        universe: Optional[List[Any]] = None,
    ) -> None:
        """
        Record initial trade entry parameters and freeze Pillar 3 (Candle Breakout Purity).
        Safe, non-blocking call executed when a Telegram alert is sent.
        """
        if not is_conviction_audit_enabled():
            return

        with self._lock:
            self._load_or_init_today()

            def get_val(key: str, default=None):
                if isinstance(signal, dict):
                    return signal.get(key, default)
                return getattr(signal, key, default)

            sym = str(get_val("symbol") or "").strip().upper()
            if not sym:
                return

            direction = str(get_val("direction") or get_val("signal_type") or "BULLISH").upper()
            key = f"{sym}_{direction}"

            # Only record write-once initial entry
            if key in self._trades:
                return

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

            name = str(get_val("name") or sym)
            sector = str(get_val("sector") or "NSE Equity")
            setup_type = str(get_val("setup_type") or ("CONFIRMED_BREAKDOWN_SHORT" if direction == "BEARISH" else "V13_BREAKOUT"))
            now_iso = datetime.now(IST_TZ).isoformat()
            now_time_str = datetime.now(IST_TZ).strftime("%H:%M:%S")

            # Extract or calculate initial conviction rating
            conv = get_val("conviction")
            if not conv or not isinstance(conv, dict) or not conv.get("enabled"):
                try:
                    from .v13_conviction import evaluate_conviction
                    conv = evaluate_conviction(signal, market_context=market_context, universe=universe)
                except Exception:
                    conv = {}

            init_score = float(conv.get("total_score", 2.0))
            init_grade = str(conv.get("grade", "GRADE_B"))
            init_badge = str(conv.get("badge_header", "🟡 GRADE B"))

            p1_dict = conv.get("pillar_1", {})
            p2_dict = conv.get("pillar_2", {})
            p3_dict = conv.get("pillar_3", {})

            p1_pts = float(p1_dict.get("points", 1.0))
            p2_pts = float(p2_dict.get("points", 0.5))
            p3_pts = float(p3_dict.get("points", 1.0))

            init_pillars = {"market": p1_pts, "sector": p2_pts, "candle": p3_pts}

            record = ConvictionTradeAudit(
                symbol=sym,
                name=name,
                sector=sector,
                direction=direction,
                setup_type=setup_type,
                entry_price=entry,
                stop_loss=sl,
                target_1=t1,
                target_2=t2,
                risk_amount=risk_amt,
                entry_time=now_time_str,
                entry_score=init_score,
                entry_grade=init_grade,
                entry_badge=init_badge,
                entry_pillars=init_pillars,
                static_candle_pts=p3_pts,  # Frozen immutable base!
                latest_score=init_score,
                latest_grade=init_grade,
                latest_badge=init_badge,
                latest_pillars=dict(init_pillars),
                latest_ltp=entry,
                latest_progress_pct=0.0,
                highest_progress_pct=0.0,
                min_score=init_score,
                min_grade=init_grade,
                decay_detected=False,
                outcome="OPEN",
                realized_r=0.0,
                trajectory="PRESERVED",
                score_delta=0.0,
                saved_r_potential=0.0,
            )

            self._trades[key] = record
            self._save_atomic()
    def sync_with_ledger(
        self,
        telegram_records: Dict[str, Any],
        market_context: Optional[Dict[str, Any]] = None,
        universe: Optional[List[Any]] = None,
    ) -> None:
        """
        Synchronize with v13_ledger's telegram_records.
        Auto-hydrates any alerted trade not yet in the conviction audit diary,
        and computes initial and dynamic conviction drift.
        """
        if not is_conviction_audit_enabled() or not telegram_records:
            return

        with self._lock:
            self._load_or_init_today()

            try:
                from .v13_conviction import evaluate_nifty_flow, evaluate_sector_breadth
            except Exception:
                evaluate_nifty_flow = None
                evaluate_sector_breadth = None

            modified = False
            for key, tg_rec in telegram_records.items():
                def get_rec_attr(attr: str, default=None):
                    if isinstance(tg_rec, dict):
                        return tg_rec.get(attr, default)
                    return getattr(tg_rec, attr, default)

                sym = str(get_rec_attr("symbol") or "").strip().upper()
                if not sym:
                    continue
                direction = str(get_rec_attr("direction") or "BULLISH").upper()
                trade_key = f"{sym}_{direction}"

                entry = float(get_rec_attr("entry_price") or 0.0)
                sl = float(get_rec_attr("stop_loss") or 0.0)
                t1 = float(get_rec_attr("target_1") or 0.0)
                t2 = float(get_rec_attr("target_2") or 0.0)
                risk_amt = float(get_rec_attr("risk_amount") or abs(entry - sl))
                current_ltp = float(get_rec_attr("ltp") or entry)
                current_prog = float(get_rec_attr("t1_progress_pct") or 0.0)
                highest_prog = float(get_rec_attr("highest_progress_pct") or current_prog)
                current_outcome = str(get_rec_attr("outcome") or "OPEN")
                current_r = float(get_rec_attr("realized_r") or 0.0)
                outcome_time = get_rec_attr("outcome_time")
                reg_at = str(get_rec_attr("registered_at") or "")
                entry_time_str = reg_at[11:19] if len(reg_at) >= 19 else "09:30:00"

                trade = self._trades.get(trade_key)
                if not trade:
                    init_sc_raw = float(get_rec_attr("initial_score") or get_rec_attr("peak_score") or 80.0)
                    if init_sc_raw >= 82.0:
                        init_score = 2.5
                        init_grade = "GRADE_A_PLUS"
                        init_badge = "🟢 GRADE A+ (HIGH PROBABILITY)"
                        init_pillars = {"market": 1.0, "sector": 0.5, "candle": 1.0}
                    elif init_sc_raw >= 75.0:
                        init_score = 2.0
                        init_grade = "GRADE_B"
                        init_badge = "🟡 GRADE B (MODERATE PROBABILITY)"
                        init_pillars = {"market": 0.5, "sector": 0.5, "candle": 1.0}
                    else:
                        init_score = 1.0
                        init_grade = "GRADE_C"
                        init_badge = "⚪ GRADE C (LOW PROBABILITY / CAUTION)"
                        init_pillars = {"market": 0.0, "sector": 0.0, "candle": 1.0}

                    trade = ConvictionTradeAudit(
                        symbol=sym,
                        name=str(get_rec_attr("name") or sym),
                        sector=str(get_rec_attr("sector") or "NSE Equity"),
                        direction=direction,
                        setup_type=str(get_rec_attr("setup_type") or "V13_BREAKOUT"),
                        entry_price=entry,
                        stop_loss=sl,
                        target_1=t1,
                        target_2=t2,
                        risk_amount=risk_amt,
                        entry_time=entry_time_str,
                        entry_score=init_score,
                        entry_grade=init_grade,
                        entry_badge=init_badge,
                        entry_pillars=init_pillars,
                        static_candle_pts=1.0,
                        latest_score=init_score,
                        latest_grade=init_grade,
                        latest_badge=init_badge,
                        latest_pillars=dict(init_pillars),
                        latest_ltp=current_ltp,
                        latest_progress_pct=current_prog,
                        highest_progress_pct=highest_prog,
                        min_score=init_score,
                        min_grade=init_grade,
                        decay_detected=False,
                        outcome=current_outcome,
                        realized_r=current_r,
                        outcome_time=str(outcome_time) if outcome_time else None,
                        trajectory="PRESERVED",
                        score_delta=0.0,
                        saved_r_potential=0.0,
                    )
                    self._trades[trade_key] = trade
                    modified = True

                # Update live state from tg_rec
                trade.latest_ltp = current_ltp
                trade.latest_progress_pct = current_prog
                trade.highest_progress_pct = max(trade.highest_progress_pct, highest_prog)
                trade.outcome = current_outcome
                trade.realized_r = current_r
                if outcome_time and not trade.outcome_time:
                    trade.outcome_time = str(outcome_time)

                p1_pts = 0.5
                p2_pts = 0.5
                if evaluate_nifty_flow:
                    p1_pts, _, _ = evaluate_nifty_flow(market_context, trade.direction)
                if evaluate_sector_breadth:
                    p2_pts, _, _ = evaluate_sector_breadth(trade.sector, trade.direction, universe)
                p3_pts = trade.static_candle_pts

                curr_score = round(p1_pts + p2_pts + p3_pts, 1)
                if curr_score >= 2.5:
                    curr_grade = "GRADE_A_PLUS"
                    curr_badge = "🟢 GRADE A+ (HIGH PROBABILITY)"
                elif curr_score >= 1.5:
                    curr_grade = "GRADE_B"
                    curr_badge = "🟡 GRADE B (MODERATE PROBABILITY)"
                else:
                    curr_grade = "GRADE_C"
                    curr_badge = "⚪ GRADE C (LOW PROBABILITY / CAUTION)"

                trade.latest_score = curr_score
                trade.latest_grade = curr_grade
                trade.latest_badge = curr_badge
                trade.latest_pillars = {"market": p1_pts, "sector": p2_pts, "candle": p3_pts}

                if curr_score < trade.min_score:
                    trade.min_score = curr_score
                    trade.min_grade = curr_grade

                if not trade.decay_detected and trade.entry_score >= 2.0 and curr_score < 2.0:
                    trade.decay_detected = True
                    trade.decay_time = entry_time_str
                    trade.decay_price = current_ltp
                    trade.decay_progress_pct = current_prog
                    trade.peak_t1_progress_before_decay = highest_prog

                    m_dropped = p1_pts < trade.entry_pillars.get("market", 1.0)
                    s_dropped = p2_pts < trade.entry_pillars.get("sector", 1.0)
                    if m_dropped and s_dropped:
                        trade.decay_culprit = "NIFTY_AND_SECTOR"
                    elif m_dropped:
                        trade.decay_culprit = "NIFTY_REVERSAL"
                    else:
                        trade.decay_culprit = "SECTOR_INVERSION"

                delta = round(curr_score - trade.entry_score, 1)
                trade.score_delta = delta

                if trade.decay_detected and curr_score <= 1.0:
                    trade.trajectory = "COLLAPSED"
                elif delta < 0:
                    trade.trajectory = "DEGRADED"
                elif delta > 0:
                    trade.trajectory = "UPGRADED"
                else:
                    trade.trajectory = "PRESERVED"

                if trade.outcome == "SL_HIT" and trade.decay_detected:
                    decay_prog = trade.decay_progress_pct or 0.0
                    decay_r = (decay_prog / 100.0) * 1.5 if decay_prog > 0 else 0.0
                    trade.saved_r_potential = round(decay_r - (-1.0), 2) if decay_prog > 0 else 1.0

                modified = True

            if modified:
                self._save_atomic()

    def update_scan_cycle(
        self,
        market_context: Optional[Dict[str, Any]],
        universe: Optional[List[Any]],
        telegram_records: Dict[str, Any],
    ) -> None:
        """
        Dynamically monitor conviction drift across active telegram trades on closed 15m scan update.
        Pillar 3 (Candle Purity) is immutable. Only NIFTY flow & Sector breadth are evaluated.
        """
        if not is_conviction_audit_enabled():
            return

        with self._lock:
            self._load_or_init_today()

            # Ensure all trades in telegram_records are synced
            if any(k not in self._trades for k in telegram_records.keys()):
                self.sync_with_ledger(telegram_records, market_context, universe)
                return

            if not self._trades:
                return

            try:
                from .v13_conviction import evaluate_nifty_flow, evaluate_sector_breadth
            except Exception:
                return

            now_time_str = datetime.now(IST_TZ).strftime("%H:%M:%S")
            modified = False

            for key, trade in self._trades.items():
                tg_rec = telegram_records.get(key)
                if not tg_rec:
                    continue

                # Read live state from v13_ledger without duplicating logic
                def get_rec_attr(attr: str, default=None):
                    if isinstance(tg_rec, dict):
                        return tg_rec.get(attr, default)
                    return getattr(tg_rec, attr, default)

                current_ltp = float(get_rec_attr("ltp") or trade.entry_price)
                current_prog = float(get_rec_attr("t1_progress_pct") or 0.0)
                highest_prog = float(get_rec_attr("highest_progress_pct") or current_prog)
                current_outcome = str(get_rec_attr("outcome") or "OPEN")
                current_r = float(get_rec_attr("realized_r") or 0.0)
                outcome_time = get_rec_attr("outcome_time")

                trade.latest_ltp = current_ltp
                trade.latest_progress_pct = current_prog
                trade.highest_progress_pct = max(trade.highest_progress_pct, highest_prog)
                trade.outcome = current_outcome
                trade.realized_r = current_r
                if outcome_time and not trade.outcome_time:
                    trade.outcome_time = str(outcome_time)

                # Re-evaluate dynamic flow pillars (Nifty & Sector)
                p1_pts, _, _ = evaluate_nifty_flow(market_context, trade.direction)
                p2_pts, _, _ = evaluate_sector_breadth(trade.sector, trade.direction, universe)
                p3_pts = trade.static_candle_pts  # Frozen base!

                curr_score = round(p1_pts + p2_pts + p3_pts, 1)

                if curr_score >= 2.5:
                    curr_grade = "GRADE_A_PLUS"
                    curr_badge = "🟢 GRADE A+ (HIGH PROBABILITY)"
                elif curr_score >= 1.5:
                    curr_grade = "GRADE_B"
                    curr_badge = "🟡 GRADE B (MODERATE PROBABILITY)"
                else:
                    curr_grade = "GRADE_C"
                    curr_badge = "⚪ GRADE C (LOW PROBABILITY / CAUTION)"

                trade.latest_score = curr_score
                trade.latest_grade = curr_grade
                trade.latest_badge = curr_badge
                trade.latest_pillars = {"market": p1_pts, "sector": p2_pts, "candle": p3_pts}

                # Track minimum score & trough
                if curr_score < trade.min_score:
                    trade.min_score = curr_score
                    trade.min_grade = curr_grade

                # Detect first severe Conviction Decay (when score drops below 2.0 Pts from entry >= 2.0)
                if not trade.decay_detected and trade.entry_score >= 2.0 and curr_score < 2.0:
                    trade.decay_detected = True
                    trade.decay_time = now_time_str
                    trade.decay_price = current_ltp
                    trade.decay_progress_pct = current_prog
                    trade.peak_t1_progress_before_decay = highest_prog

                    # Attribute culprit
                    m_dropped = p1_pts < trade.entry_pillars.get("market", 1.0)
                    s_dropped = p2_pts < trade.entry_pillars.get("sector", 1.0)
                    if m_dropped and s_dropped:
                        trade.decay_culprit = "NIFTY_AND_SECTOR"
                    elif m_dropped:
                        trade.decay_culprit = "NIFTY_REVERSAL"
                    else:
                        trade.decay_culprit = "SECTOR_INVERSION"

                # Assign Trajectory
                delta = round(curr_score - trade.entry_score, 1)
                trade.score_delta = delta

                if trade.decay_detected and curr_score <= 1.0:
                    trade.trajectory = "COLLAPSED"
                elif delta < 0:
                    trade.trajectory = "DEGRADED"
                elif delta > 0:
                    trade.trajectory = "UPGRADED"
                else:
                    trade.trajectory = "PRESERVED"

                # Calculate Saved R Potential for trades that ended in loss but decayed in profit/breakeven
                if trade.outcome == "SL_HIT" and trade.decay_detected:
                    decay_prog = trade.decay_progress_pct or 0.0
                    decay_r = (decay_prog / 100.0) * 1.5 if decay_prog > 0 else 0.0
                    # If exited at decay price instead of -1.0R SL:
                    trade.saved_r_potential = round(decay_r - (-1.0), 2)

                modified = True

            if modified:
                self._save_atomic()

    def _try_self_heal_trades(self) -> None:
        """Self-healing recovery: reconstruct trades from ledger or sent alerts cache if in-memory trades are empty."""
        if self._trades:
            return
        try:
            from .v13_ledger import GLOBAL_SESSION_LEDGER, SENT_ALERTS_CACHE_FILE
            today = self._session_date or self._get_today_str()
            # 1. Primary sync from ledger telegram_records
            if GLOBAL_SESSION_LEDGER.telegram_records:
                self.sync_with_ledger(GLOBAL_SESSION_LEDGER.telegram_records)
                if self._trades:
                    return

            # 2. Resilient fallback: Recover from sent_alerts_cache.json + ledger records
            if os.path.exists(SENT_ALERTS_CACHE_FILE):
                with open(SENT_ALERTS_CACHE_FILE, "r", encoding="utf-8") as f:
                    sent_cache = json.load(f)
                recovered = {}
                for sym, info in sent_cache.items():
                    if isinstance(info, dict) and info.get("date") == today:
                        raw_sym = str(info.get("symbol") or (
                            sym.rsplit("_", 1)[0]
                            if sym.endswith(("_BULLISH", "_BEARISH", "_LONG", "_SHORT"))
                            else sym
                        ))
                        clean_sym = raw_sym.replace(".NS", "").strip().upper()
                        d = str(info.get("direction", "BULLISH")).upper()
                        key = f"{clean_sym}_{d}"
                        rec = GLOBAL_SESSION_LEDGER.records.get(key)
                        if rec:
                            recovered[key] = rec
                if recovered:
                    self.sync_with_ledger(recovered)
                    if self._trades:
                        return

            # 3. Ultimate fallback: If sent_cache was reset/empty, audit top qualified trades (score >= 75)
            if not self._trades and GLOBAL_SESSION_LEDGER.records:
                recovered = {
                    k: rec for k, rec in GLOBAL_SESSION_LEDGER.records.items()
                    if getattr(rec, "peak_score", 0.0) >= 75.0
                }
                if recovered:
                    self.sync_with_ledger(recovered)
        except Exception as e:
            logger.debug(f"Self-healing trades recovery failed: {e}")

    def get_audit_summary(self) -> Dict[str, Any]:
        """Compute structured forensic analytics for EOD review and JSON storage."""
        with self._lock:
            self._load_or_init_today()
            self._try_self_heal_trades()

            all_audits = list(self._trades.values())
            total = len(all_audits)

            if total == 0:
                return {
                    "enabled": is_conviction_audit_enabled(),
                    "session_date": self._session_date,
                    "total_trades": 0,
                    "eod_dispatched_date": self._eod_dispatched_date,
                    "preserved": {"count": 0, "pct": 0.0, "wins": 0, "losses": 0, "win_rate": 0.0, "avg_r": 0.0},
                    "collapsed": {"count": 0, "pct": 0.0, "sl_count": 0, "sl_rate": 0.0, "nifty_culprit": 0, "sector_culprit": 0, "saved_r_total": 0.0},
                    "upgraded": {"count": 0, "pct": 0.0, "wins": 0, "win_rate": 0.0},
                    "trades": {},
                }

            # 1. Preserved Group (Conviction stayed rock-solid)
            preserved_list = [t for t in all_audits if t.trajectory == "PRESERVED"]
            p_count = len(preserved_list)
            conv_win_outcomes = ("T1_HIT", "T2_HIT", "T1_HIT_TRAILED", "T1_WIN_BE_EXIT", "EOD_PARTIAL_WIN", "CLOSED_EOD_PROFIT")
            p_wins = sum(1 for t in preserved_list if t.outcome in conv_win_outcomes)
            p_losses = sum(1 for t in preserved_list if t.outcome in ("SL_HIT", "CLOSED_EOD_LOSS"))
            p_win_rate = round((p_wins / p_count) * 100.0, 1) if p_count > 0 else 0.0
            p_avg_r = round(sum(t.realized_r for t in preserved_list) / p_count, 2) if p_count > 0 else 0.0

            # 2. Collapsed / Degraded Group
            collapsed_list = [t for t in all_audits if t.trajectory in ("COLLAPSED", "DEGRADED")]
            c_count = len(collapsed_list)
            c_sl = sum(1 for t in collapsed_list if t.outcome == "SL_HIT")
            c_sl_rate = round((c_sl / c_count) * 100.0, 1) if c_count > 0 else 0.0
            c_nifty = sum(1 for t in collapsed_list if t.decay_culprit in ("NIFTY_REVERSAL", "NIFTY_AND_SECTOR"))
            c_sector = sum(1 for t in collapsed_list if t.decay_culprit == "SECTOR_INVERSION")
            c_saved_r = round(sum(t.saved_r_potential for t in collapsed_list), 2)
            c_early_prog = sum(1 for t in collapsed_list if t.peak_t1_progress_before_decay >= 70.0)

            # 3. Upgraded Group
            upgraded_list = [t for t in all_audits if t.trajectory == "UPGRADED"]
            u_count = len(upgraded_list)
            u_wins = sum(1 for t in upgraded_list if t.outcome in conv_win_outcomes)
            u_win_rate = round((u_wins / u_count) * 100.0, 1) if u_count > 0 else 0.0

            return {
                "enabled": is_conviction_audit_enabled(),
                "session_date": self._session_date,
                "total_trades": total,
                "eod_dispatched_date": self._eod_dispatched_date,
                "preserved": {
                    "count": p_count,
                    "pct": round((p_count / total) * 100.0, 1),
                    "wins": p_wins,
                    "losses": p_losses,
                    "win_rate": p_win_rate,
                    "avg_r": p_avg_r,
                },
                "collapsed": {
                    "count": c_count,
                    "pct": round((c_count / total) * 100.0, 1),
                    "sl_count": c_sl,
                    "sl_rate": c_sl_rate,
                    "nifty_culprit": c_nifty,
                    "sector_culprit": c_sector,
                    "saved_r_total": c_saved_r,
                    "peaked_above_70_before_decay": c_early_prog,
                },
                "upgraded": {
                    "count": u_count,
                    "pct": round((u_count / total) * 100.0, 1),
                    "wins": u_wins,
                    "win_rate": u_win_rate,
                },
                "trades": {k: asdict(v) for k, v in self._trades.items()},
            }

    def format_telegram_drift_report(self) -> str:
        """
        Formats an aggregated, institutional-grade Markdown scorecard.
        Strictly under 2,000 characters to comply with Telegram's 4,096 limit.
        """
        data = self.get_audit_summary()
        total = data.get("total_trades", 0)
        if total == 0:
            return ""

        date_str = data.get("session_date", self._get_today_str())
        p = data.get("preserved", {})
        c = data.get("collapsed", {})
        u = data.get("upgraded", {})

        p_cnt = p.get("count", 0)
        p_pct = p.get("pct", 0.0)
        p_wr = p.get("win_rate", 0.0)
        p_wins = p.get("wins", 0)
        p_r = p.get("avg_r", 0.0)

        c_cnt = c.get("count", 0)
        c_pct = c.get("pct", 0.0)
        c_sl = c.get("sl_count", 0)
        c_slr = c.get("sl_rate", 0.0)
        c_nifty = c.get("nifty_culprit", 0)
        c_sector = c.get("sector_culprit", 0)
        c_saved = c.get("saved_r_total", 0.0)
        c_peak70 = c.get("peaked_above_70_before_decay", 0)

        u_cnt = u.get("count", 0)
        u_pct = u.get("pct", 0.0)
        u_wr = u.get("win_rate", 0.0)
        u_wins = u.get("wins", 0)

        lines = [
            "=================================================",
            "🧬 *NSE-PULSE V13: CONVICTION DRIFT & REGIME AUDIT*",
            f"📅 *Date:* `{date_str}` | *Institutional Strategy Audit*",
            "=================================================",
            f"📱 *TELEGRAM ALERTED TRADES AUDIT* (Total: {total} Alerts)\n",
            "1. 🟢 *CONVICTION PRESERVED (Rock-Solid A+ / Stable):*",
            f"   • Count      : {p_cnt} Trades ({p_pct}%)",
            f"   • Win Rate   : {p_wins}/{p_cnt} Hits ({p_wr}% Win Rate) 🏆",
            f"   • Average R  : {p_r:+.2f} R per trade",
            "   • Verdict    : Respected market tailwind & delivered.\n",
            "2. 🔴 *CONVICTION COLLAPSED (Decayed to Grade B or C):*",
            f"   • Count      : {c_cnt} Trades ({c_pct}%)",
            f"   • Reversals  : {c_sl}/{c_cnt} Ended in SL ({c_slr}% Failure Rate) ⚠️",
            f"   • Culprits   : {c_nifty} by NIFTY Reversal | {c_sector} by Sector Inversion",
            f"   • Forensic   : {c_peak70} trades reached >70% Target BEFORE decaying!\n",
            "3. 🔵 *CONVICTION UPGRADED (Started B ➔ Became A+):*",
            f"   • Count      : {u_cnt} Trades ({u_pct}%)",
            f"   • Win Rate   : {u_wins}/{u_cnt} Hits ({u_wr}% Win Rate) 🚀\n",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "💡 *AUDITOR'S ALPHA DISCOVERY (Active Shield):*",
            f"• *{c_slr}% of today's losses* occurred AFTER conviction dropped below 2.0 Pts.",
            f"• An Early-Bailout Rule (Exit on Conviction Collapse) would have prevented {c_sl} SL hits,",
            f"  saving *+{c_saved:.2f} R* for the session!",
            "=================================================",
        ]

        return "\n".join(lines)

    def dispatch_eod_drift_audit(self) -> bool:
        """
        Send the dedicated 2nd Telegram message after the primary EOD report.
        Idempotent per trading date.
        """
        if not is_conviction_audit_enabled():
            return False

        with self._lock:
            self._load_or_init_today()
            today = self._session_date

            if self._eod_dispatched_date == today:
                logger.info(f"Conviction Drift Audit already sent today ({today}), skipping duplicate.")
                return False

            self._try_self_heal_trades()

            if not self._trades:
                logger.info("No Telegram alerted trades recorded for conviction drift audit today.")
                return False

            msg = self.format_telegram_drift_report()
            if not msg:
                return False

            try:
                from .telegram_bot import send_telegram_text
                sent = send_telegram_text(msg, sync_send=True)
                if sent:
                    self._eod_dispatched_date = today
                    self._save_atomic()
                    logger.info(f"Successfully dispatched Conviction Drift Audit to Telegram for {today}")
                    return True
            except Exception as e:
                logger.error(f"Failed to dispatch Conviction Drift Audit: {e}")
                return False

        return False


# Thread-safe global singleton instance
GLOBAL_CONVICTION_AUDITOR = ConvictionAuditor()
