"""
NSE-PULSE V13: Autonomous Conviction Shadow Portfolio Engine.

An isolated, quantitative paper-trading and capital compounding engine.
Executes virtual trades using a dynamic position sizing model based on live market LTP.

Key Quantitative Rules:
1. Strict Conviction Gate: Trades ONLY setups with Conviction Score >= 2.0 (Grade A+ and Grade B).
2. Time-Window Gate: Fresh entries allowed between 09:15 AM and 01:30 PM (13:30 IST) ONLY.
   Zero fresh entries are taken post-1:30 PM.
3. Unlimited Concurrent Slots: Executes every qualified setup across the universe without artificial capping.
4. Dynamic Sizing: Qty = Planned Risk / |Live LTP - SL|. Fixed Risk = ₹1,000 (Grade A+) or ₹500 (Grade B).
5. 4-Stage "Never-Lose-A-Winner" Lifecycle:
   - Target 1 Hit -> Book 50% shares (+0.75R / +0.375R banked), trail SL to Entry (Cost).
   - Remaining 50% runs risk-free for Target 2 or exits at Cost (₹0 loss).
   - 15:15 IST Auto-MIS Square-Off.
6. 50% Compounding Split & Permanent Digital Vault.
7. Standalone Clash-Free Telegram EOD Audit at 15:35 IST.
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

logger = logging.getLogger("v13_shadow_portfolio")

SHADOW_DIR = os.path.join(os.path.dirname(__file__), "data", "shadow_portfolio")
SHADOW_HISTORY_DIR = os.path.join(os.path.dirname(__file__), "data", "shadow_portfolio_history")


def is_shadow_portfolio_enabled() -> bool:
    """Dynamically check if Shadow Portfolio trading is enabled via .env."""
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path, override=True)
    except Exception:
        pass
    val = os.getenv("ENABLE_SHADOW_PORTFOLIO", "true").strip().lower()
    return val in ("true", "1", "yes")


def get_shadow_config() -> Dict[str, Any]:
    """Retrieve shadow portfolio operational thresholds with production defaults."""
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path, override=True)
    except Exception:
        pass

    return {
        "min_conviction": float(os.getenv("SHADOW_PORTFOLIO_MIN_CONVICTION", "2.0")),
        "cutoff_time_str": os.getenv("SHADOW_PORTFOLIO_ENTRY_CUTOFF_TIME", "13:30"),
        "base_capital": float(os.getenv("SHADOW_PORTFOLIO_BASE_CAPITAL", "100000.0")),
        "grade_a_risk": float(os.getenv("SHADOW_PORTFOLIO_GRADE_A_RISK", "1000.0")),
        "grade_b_risk": float(os.getenv("SHADOW_PORTFOLIO_GRADE_B_RISK", "500.0")),
        "circuit_breaker_r": float(os.getenv("SHADOW_PORTFOLIO_CIRCUIT_BREAKER_R", "4.0")),
        "profit_reinvest_pct": float(os.getenv("SHADOW_PORTFOLIO_PROFIT_REINVEST_PCT", "50.0")),
        "mis_exit_time_str": os.getenv("SHADOW_PORTFOLIO_MIS_EXIT_TIME", "15:15"),
        "eod_audit_time_str": os.getenv("SHADOW_PORTFOLIO_EOD_AUDIT_TIME", "15:35"),
        "telegram_min_score": float(os.getenv("TELEGRAM_MIN_SCORE", "75.0")),
        "telegram_max_t1_progress": float(os.getenv("TELEGRAM_MAX_T1_PROGRESS", "25.0")),
    }


@dataclass
class ShadowTrade:
    trade_id: str
    symbol: str
    name: str
    sector: str
    direction: str  # "BULLISH" or "BEARISH"
    conviction_score: float
    conviction_grade: str  # "GRADE_A_PLUS", "GRADE_B"
    entry_time: str
    entry_ltp: float
    breakout_level: float
    initial_sl: float
    current_sl: float
    target_1: float
    target_2: float
    planned_risk: float
    total_qty: int
    remaining_qty: int
    t1_booked_qty: int = 0
    booked_pnl: float = 0.0
    realized_pnl: float = 0.0
    realized_r: float = 0.0
    stage: str = "OPEN"  # "OPEN", "T1_HIT_TRAILED", "CLOSED"
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None  # "SL_HIT", "COST_EXIT", "T2_HIT", "MIS_SQUARE_OFF"
    highest_ltp: float = 0.0
    lowest_ltp: float = 0.0
    latest_ltp: float = 0.0


class ShadowPortfolioEngine:
    """
    Thread-safe autonomous paper-trading engine managing a virtual portfolio.
    Zero side-effects on primary screener and live alerts.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._session_date: str = ""
        self._trading_capital: float = 100000.0
        self._secured_vault: float = 0.0
        self._starting_capital: float = 100000.0
        self._starting_vault: float = 0.0
        self._eod_settled: bool = False
        self._open_trades: Dict[str, ShadowTrade] = {}
        self._closed_trades: List[ShadowTrade] = []
        self._eod_dispatched_date: Optional[str] = None
        self._circuit_breaker_active: bool = False
        self._seen_symbols_today: set[str] = set()
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

    def _get_active_file(self) -> str:
        os.makedirs(SHADOW_DIR, exist_ok=True)
        return os.path.join(SHADOW_DIR, "active_shadow_portfolio.json")

    def _get_history_file(self, date_str: str) -> str:
        os.makedirs(SHADOW_HISTORY_DIR, exist_ok=True)
        return os.path.join(SHADOW_HISTORY_DIR, f"shadow_portfolio_{date_str}.json")

    def _load_or_init_today(self) -> None:
        """Atomic loader with automatic multi-day archival and compounding rollover."""
        today = self._get_today_str()
        if self._session_date == today:
            return

        active_file = self._get_active_file()
        if os.path.exists(active_file):
            try:
                with open(active_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                loaded_date = data.get("session_date", "")
                self._trading_capital = float(data.get("trading_capital", 100000.0))
                self._secured_vault = float(data.get("secured_vault", 0.0))
                self._starting_capital = float(data.get("starting_capital", self._trading_capital))
                self._starting_vault = float(data.get("starting_vault", self._secured_vault))
                self._eod_settled = bool(data.get("eod_settled", False))

                if loaded_date == today:
                    self._session_date = today
                    self._eod_dispatched_date = data.get("eod_dispatched_date")
                    self._circuit_breaker_active = bool(data.get("circuit_breaker_active", False))
                    self._seen_symbols_today = set(data.get("seen_symbols_today", []))

                    self._open_trades = {}
                    for k, td in data.get("open_trades", {}).items():
                        try:
                            self._open_trades[k] = ShadowTrade(**td)
                        except Exception:
                            pass

                    self._closed_trades = []
                    for td in data.get("closed_trades", []):
                        try:
                            self._closed_trades.append(ShadowTrade(**td))
                        except Exception:
                            pass
                    return
                else:
                    # New trading session: Archive previous session data to history
                    if loaded_date:
                        try:
                            hist_file = self._get_history_file(loaded_date)
                            with open(hist_file, "w", encoding="utf-8") as hf:
                                json.dump(data, hf, indent=2, ensure_ascii=False)
                            logger.info(f"Archived previous shadow portfolio session {loaded_date} to {hist_file}")
                        except Exception as he:
                            logger.error(f"Failed to archive shadow portfolio {loaded_date}: {he}")

                        # Execute 50% compounding split on previous session only if NOT already settled at EOD
                        prev_eod_settled = bool(data.get("eod_settled", False))
                        if not prev_eod_settled:
                            prev_closed = [ShadowTrade(**td) for td in data.get("closed_trades", [])]
                            prev_net_pnl = sum(t.realized_pnl for t in prev_closed)
                            if prev_net_pnl > 0:
                                vault_split = round(prev_net_pnl * 0.50, 2)
                                reinvest_split = prev_net_pnl - vault_split
                                self._secured_vault += vault_split
                                self._trading_capital += reinvest_split
                                logger.info(
                                    f"Fallback Rollover Compounding applied: +₹{reinvest_split} to Capital (₹{self._trading_capital}), "
                                    f"+₹{vault_split} to Vault (₹{self._secured_vault})"
                                )
                            elif prev_net_pnl < 0:
                                self._trading_capital = max(10000.0, self._trading_capital + prev_net_pnl)
            except Exception as e:
                logger.error(f"Error loading active shadow portfolio: {e}")

        # Fresh slate initialization for today
        self._session_date = today
        self._starting_capital = self._trading_capital
        self._starting_vault = self._secured_vault
        self._eod_settled = False
        self._open_trades = {}
        self._closed_trades = []
        self._eod_dispatched_date = None
        self._circuit_breaker_active = False
        self._seen_symbols_today = set()
        self._save_atomic()

    def _save_atomic(self) -> None:
        """Atomic persist to prevent file corruption during sudden restarts."""
        try:
            active_file = self._get_active_file()
            tmp_file = active_file + ".tmp"
            payload = self.get_portfolio_summary()

            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp_file, active_file)
        except Exception as e:
            logger.debug(f"Shadow portfolio atomic save failed: {e}")

    @property
    def eod_dispatched_date(self) -> Optional[str]:
        return self._eod_dispatched_date

    def is_entry_window_open(self, now_dt: Optional[datetime] = None) -> bool:
        """
        Gate 1: Strictly permit fresh entries between 09:30 AM (after Opening Range completes)
        and 01:30 PM (13:30 IST) only.
        Before 09:30 AM and after 01:30 PM, zero fresh positions are initiated.
        """
        dt = now_dt or datetime.now(IST_TZ)
        cur_t = dt.time()
        start_t = dtime(9, 30)  # Opening Range completes at 09:30 AM IST
        cutoff_t = dtime(13, 30)  # 01:30 PM IST
        return start_t <= cur_t <= cutoff_t

    def process_scan_cycle(
        self,
        candidates: List[Any],
        diagnostics: Optional[List[Any]] = None,
        ltp_map: Optional[Dict[str, float]] = None,
        now_dt: Optional[datetime] = None,
    ) -> None:
        """
        Non-blocking execution cycle called on every closed 15m scan update.
        1. Manages open positions (SL, T1 Trailing, T2).
        2. Evaluates new qualifying signals (Conviction >= 2.0 before 13:30 IST).
        """
        if not is_shadow_portfolio_enabled():
            return

        with self._lock:
            self._load_or_init_today()
            dt = now_dt or datetime.now(IST_TZ)
            now_time_str = dt.strftime("%H:%M:%S")
            cfg = get_shadow_config()
            modified = False

            # Build comprehensive live LTP lookup
            price_lookup: Dict[str, float] = dict(ltp_map or {})

            all_signals = list(candidates or [])
            if diagnostics:
                all_signals.extend(diagnostics)

            for sig in all_signals:
                def get_attr(key: str, default=None):
                    if isinstance(sig, dict):
                        return sig.get(key, default)
                    return getattr(sig, key, default)

                sym = str(get_attr("symbol") or "").strip().upper()
                ltp = get_attr("ltp") or get_attr("price")
                if sym and ltp:
                    try:
                        price_lookup[sym] = float(ltp)
                    except (ValueError, TypeError):
                        pass

            # -------------------------------------------------------------
            # STEP 1: Lifecycle Management for Existing Open Positions
            # -------------------------------------------------------------
            trades_to_close: List[Tuple[str, float, str, str]] = []

            for key, trade in list(self._open_trades.items()):
                live_ltp = price_lookup.get(trade.symbol)
                if live_ltp is None or live_ltp <= 0:
                    continue

                trade.latest_ltp = live_ltp
                trade.highest_ltp = max(trade.highest_ltp or live_ltp, live_ltp)
                trade.lowest_ltp = min(trade.lowest_ltp or live_ltp, live_ltp)
                modified = True

                if trade.direction == "BULLISH":
                    if trade.stage == "OPEN":
                        # Check Stop Loss Hit
                        if live_ltp <= trade.current_sl:
                            trades_to_close.append((key, trade.current_sl, "SL_HIT", now_time_str))
                        # Check Target 1 Hit -> Book 50% & Trail SL to Entry
                        elif live_ltp >= trade.target_1:
                            half_qty = trade.total_qty // 2
                            if half_qty > 0:
                                t1_gain = round((trade.target_1 - trade.entry_ltp) * half_qty, 2)
                                trade.t1_booked_qty = half_qty
                                trade.remaining_qty = trade.total_qty - half_qty
                                trade.booked_pnl = t1_gain
                                trade.current_sl = trade.entry_ltp  # Trailed to Cost!
                                trade.stage = "T1_HIT_TRAILED"
                                modified = True
                                logger.info(
                                    f"[SHADOW PORTFOLIO] {trade.symbol} BULLISH hit T1 ({trade.target_1})! "
                                    f"Booked 50% shares (+₹{t1_gain}), SL trailed to Cost (₹{trade.entry_ltp})"
                                )
                    elif trade.stage == "T1_HIT_TRAILED":
                        # Trailed Stop Hit (Cost / Breakeven Reversal)
                        if live_ltp <= trade.current_sl:
                            trades_to_close.append((key, trade.entry_ltp, "COST_EXIT", now_time_str))
                        # Target 2 Runner Hit!
                        elif live_ltp >= trade.target_2:
                            trades_to_close.append((key, trade.target_2, "T2_HIT", now_time_str))

                else:  # BEARISH
                    if trade.stage == "OPEN":
                        if live_ltp >= trade.current_sl:
                            trades_to_close.append((key, trade.current_sl, "SL_HIT", now_time_str))
                        elif live_ltp <= trade.target_1:
                            half_qty = trade.total_qty // 2
                            if half_qty > 0:
                                t1_gain = round((trade.entry_ltp - trade.target_1) * half_qty, 2)
                                trade.t1_booked_qty = half_qty
                                trade.remaining_qty = trade.total_qty - half_qty
                                trade.booked_pnl = t1_gain
                                trade.current_sl = trade.entry_ltp  # Trailed to Cost!
                                trade.stage = "T1_HIT_TRAILED"
                                modified = True
                                logger.info(
                                    f"[SHADOW PORTFOLIO] {trade.symbol} BEARISH hit T1 ({trade.target_1})! "
                                    f"Booked 50% shares (+₹{t1_gain}), SL trailed to Cost (₹{trade.entry_ltp})"
                                )
                    elif trade.stage == "T1_HIT_TRAILED":
                        if live_ltp >= trade.current_sl:
                            trades_to_close.append((key, trade.entry_ltp, "COST_EXIT", now_time_str))
                        elif live_ltp <= trade.target_2:
                            trades_to_close.append((key, trade.target_2, "T2_HIT", now_time_str))

            # Execute closures
            for key, exit_price, reason, exit_time in trades_to_close:
                trade = self._open_trades.pop(key, None)
                if not trade:
                    continue

                trade.exit_price = exit_price
                trade.exit_reason = reason
                trade.exit_time = exit_time
                trade.stage = "CLOSED"

                if reason == "SL_HIT":
                    if trade.direction == "BULLISH":
                        pnl = (exit_price - trade.entry_ltp) * trade.total_qty
                    else:
                        pnl = (trade.entry_ltp - exit_price) * trade.total_qty
                    trade.realized_pnl = round(pnl, 2)
                    trade.realized_r = -1.0 if trade.conviction_grade == "GRADE_A_PLUS" else -0.5

                elif reason == "COST_EXIT":
                    # Remaining 50% closed at ₹0 gain/loss; keep banked T1 profit
                    trade.realized_pnl = trade.booked_pnl
                    trade.realized_r = +0.75 if trade.conviction_grade == "GRADE_A_PLUS" else +0.375

                elif reason == "T2_HIT":
                    if trade.direction == "BULLISH":
                        runner_pnl = (exit_price - trade.entry_ltp) * trade.remaining_qty
                    else:
                        runner_pnl = (trade.entry_ltp - exit_price) * trade.remaining_qty
                    trade.realized_pnl = round(trade.booked_pnl + runner_pnl, 2)
                    trade.realized_r = +2.5 if trade.conviction_grade == "GRADE_A_PLUS" else +1.25

                self._closed_trades.append(trade)
                modified = True
                logger.info(
                    f"[SHADOW PORTFOLIO CLOSED] {trade.symbol} ({reason}) Realized P&L: ₹{trade.realized_pnl:+.2f} ({trade.realized_r:+.2f}R)"
                )

            # Check Circuit Breaker: Halt if net loss <= -4.0R (-₹4,000)
            net_closed_r = sum(t.realized_r for t in self._closed_trades)
            if net_closed_r <= -cfg["circuit_breaker_r"]:
                if not self._circuit_breaker_active:
                    self._circuit_breaker_active = True
                    modified = True
                    logger.warning(
                        f"[SHADOW PORTFOLIO CIRCUIT BREAKER] Net loss reached {net_closed_r:.2f}R <= -{cfg['circuit_breaker_r']}R. "
                        f"Fresh entries frozen for today."
                    )

            # -------------------------------------------------------------
            # STEP 2: Filter and Initiate Fresh Entries (<= 01:30 PM Only)
            # -------------------------------------------------------------
            window_open = self.is_entry_window_open(dt)

            if window_open and not self._circuit_breaker_active:
                # STRICT TELEGRAM ALERT ALIGNMENT MANDATE:
                # Only initiate simulated trades on setups that qualify for live Telegram alerts:
                # 1. Candidate setups ONLY (diagnostics strictly excluded from new trade entries)
                # 2. Screener Score >= TELEGRAM_MIN_SCORE (default >= 75.0)
                # 3. Pristine Base Entry Guard: T1 Progress <= TELEGRAM_MAX_T1_PROGRESS (default <= 25.0%)
                # 4. Execution status cannot be TARGET_HIT, TARGET_NEAR, or EXPIRED_T1_NEAR
                # 5. Institutional 3-Pillar Conviction Rating >= 2.0 (Grade B / Grade A+)
                for sig in (candidates or []):
                    def get_val(key: str, default=None):
                        if isinstance(sig, dict):
                            return sig.get(key, default)
                        return getattr(sig, key, default)

                    sym = str(get_val("symbol") or "").strip().upper()
                    direction = str(get_val("direction") or get_val("signal_type") or "BULLISH").upper()
                    key = f"{sym}_{direction}"
                    if not sym or key in self._open_trades or sym in self._seen_symbols_today:
                        continue

                    # Gate 1: Telegram Minimum Score Threshold (default >= 75.0)
                    sig_score = float(get_val("score") or 0.0)
                    min_tg_score = cfg.get("telegram_min_score", 75.0)
                    if sig_score < min_tg_score:
                        continue

                    # Gate 2: Strict Early Entry Guard (T1 Progress <= 25.0% / max allowed)
                    exec_status = str(get_val("execution_status") or "").upper()
                    if exec_status in ("TARGET_HIT", "TARGET_NEAR", "EXPIRED_T1_NEAR"):
                        continue
                    t1_prog = float(get_val("t1_progress_pct") or 0.0)
                    max_tg_prog = cfg.get("telegram_max_t1_progress", 25.0)
                    if t1_prog > max_tg_prog:
                        continue

                    # Gate 3: Institutional 3-Pillar Conviction Rating (>= 2.0 ONLY: Grade B or Grade A+)
                    conv = get_val("conviction") or {}
                    total_score = float(conv.get("total_score") or 0.0)
                    if total_score < cfg["min_conviction"]:
                        continue

                    # Risk Sizing Assignment
                    if total_score >= 2.5:
                        planned_risk = cfg["grade_a_risk"]  # ₹1,000 (1.0R)
                        c_grade = "GRADE_A_PLUS"
                    else:
                        planned_risk = cfg["grade_b_risk"]  # ₹500 (0.5R)
                        c_grade = "GRADE_B"

                    # Trade Levels
                    tp = get_val("risk") or get_val("trade_params") or {}
                    if isinstance(tp, dict):
                        entry = float(tp.get("entry") or get_val("entry_price") or 0.0)
                        sl = float(tp.get("stop_loss") or get_val("stop_loss") or 0.0)
                        t1 = float(tp.get("target_1") or get_val("target_1") or 0.0)
                        t2 = float(tp.get("target_2") or get_val("target_2") or 0.0)
                    else:
                        entry = float(get_val("entry_price") or 0.0)
                        sl = float(get_val("stop_loss") or 0.0)
                        t1 = float(get_val("target_1") or 0.0)
                        t2 = float(get_val("target_2") or 0.0)

                    live_ltp = price_lookup.get(sym) or float(get_val("ltp") or entry)
                    if entry <= 0 or sl <= 0 or live_ltp <= 0:
                        continue

                    # Dynamic Position Sizing using Live LTP
                    live_risk_per_share = abs(live_ltp - sl)
                    if live_risk_per_share <= 0:
                        continue

                    shares_qty = max(1, int(planned_risk // live_risk_per_share))

                    # Open Trade Record
                    trade_record = ShadowTrade(
                        trade_id=f"SHADOW_{self._session_date.replace('-', '')}_{sym}_{direction}",
                        symbol=sym,
                        name=str(get_val("name") or sym),
                        sector=str(get_val("sector") or "NSE Equity"),
                        direction=direction,
                        conviction_score=total_score,
                        conviction_grade=c_grade,
                        entry_time=now_time_str,
                        entry_ltp=live_ltp,
                        breakout_level=entry,
                        initial_sl=sl,
                        current_sl=sl,
                        target_1=t1,
                        target_2=t2,
                        planned_risk=planned_risk,
                        total_qty=shares_qty,
                        remaining_qty=shares_qty,
                        stage="OPEN",
                        highest_ltp=live_ltp,
                        lowest_ltp=live_ltp,
                        latest_ltp=live_ltp,
                    )

                    self._open_trades[key] = trade_record
                    self._seen_symbols_today.add(sym)
                    modified = True
                    logger.info(
                        f"[SHADOW PORTFOLIO ENTRY] {sym} {direction} (Score: {total_score} | {c_grade}) "
                        f"Entry: ₹{live_ltp:.2f} | SL: ₹{sl:.2f} | Qty: {shares_qty} sh (Risk: ₹{planned_risk})"
                    )

            if modified:
                self._save_atomic()

    def square_off_all_mis(self, ltp_map: Optional[Dict[str, float]] = None) -> None:
        """
        Triggered at 15:15 IST (or market close).
        Liquidates all remaining open or trailed positions at current market price.
        """
        if not is_shadow_portfolio_enabled():
            return

        with self._lock:
            self._load_or_init_today()
            if not self._open_trades:
                return

            now_time_str = datetime.now(IST_TZ).strftime("%H:%M:%S")
            price_lookup = dict(ltp_map or {})
            modified = False

            for key, trade in list(self._open_trades.items()):
                live_ltp = price_lookup.get(trade.symbol)
                if not live_ltp or live_ltp <= 0:
                    live_ltp = trade.latest_ltp if trade.latest_ltp > 0 else trade.entry_ltp

                if trade.direction == "BULLISH":
                    open_gain = (live_ltp - trade.entry_ltp) * trade.remaining_qty
                else:
                    open_gain = (trade.entry_ltp - live_ltp) * trade.remaining_qty

                trade.exit_price = live_ltp
                trade.exit_reason = "MIS_SQUARE_OFF"
                trade.exit_time = now_time_str
                trade.stage = "CLOSED"
                trade.realized_pnl = round(trade.booked_pnl + open_gain, 2)

                # Realized R calculation
                trade.realized_r = round(trade.realized_pnl / trade.planned_risk, 2)

                self._closed_trades.append(trade)
                del self._open_trades[key]
                modified = True
                logger.info(
                    f"[SHADOW PORTFOLIO MIS CLOSE] {trade.symbol} closed at ₹{live_ltp:.2f}. "
                    f"P&L: ₹{trade.realized_pnl:+.2f} ({trade.realized_r:+.2f}R)"
                )

            if modified:
                self._save_atomic()

    def execute_eod_settlement(self) -> None:
        """
        Execute 15:30 EOD settlement:
        Calculates Net Realized P&L, splits 50% profit into Permanent Secured Vault,
        and compounds 50% profit into tomorrow's trading capital.
        """
        with self._lock:
            self._load_or_init_today()
            today = self._session_date

            # Liquidate any remaining open or trailed positions at EOD before settlement
            if self._open_trades:
                self.square_off_all_mis()

            net_pnl = sum(t.realized_pnl for t in self._closed_trades)

            # Split only on positive profitable session
            if net_pnl > 0:
                vault_share = round(net_pnl * 0.50, 2)
                reinvest_share = net_pnl - vault_share
                self._secured_vault = round(self._starting_vault + vault_share, 2)
                self._trading_capital = round(self._starting_capital + reinvest_share, 2)
            elif net_pnl < 0:
                # Losses absorbed by trading capital; vault untouched
                self._trading_capital = max(10000.0, round(self._starting_capital + net_pnl, 2))
                self._secured_vault = round(self._starting_vault, 2)
            else:
                self._trading_capital = round(self._starting_capital, 2)
                self._secured_vault = round(self._starting_vault, 2)

            self._eod_settled = True
            self._save_atomic()

            # Archive today's complete session to history directory
            try:
                hist_file = self._get_history_file(today)
                payload = self.get_portfolio_summary()
                with open(hist_file, "w", encoding="utf-8") as hf:
                    json.dump(payload, hf, indent=2, ensure_ascii=False)
                logger.info(f"Archived EOD shadow portfolio to {hist_file}")
            except Exception as e:
                logger.error(f"Failed to archive EOD shadow portfolio: {e}")

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Return structured portfolio snapshot for API responses and persistence."""
        with self._lock:
            all_closed = list(self._closed_trades)
            total_closed = len(all_closed)
            net_pnl = round(sum(t.realized_pnl for t in all_closed), 2)
            net_r = round(sum(t.realized_r for t in all_closed), 2)

            wins = sum(1 for t in all_closed if t.realized_pnl > 0)
            losses = sum(1 for t in all_closed if t.realized_pnl < 0)
            breakevens = sum(1 for t in all_closed if t.realized_pnl == 0)
            win_rate = round((wins / total_closed) * 100.0, 1) if total_closed > 0 else 0.0

            start_cap = self._starting_capital if self._starting_capital > 0 else self._trading_capital
            roi_pct = round((net_pnl / start_cap) * 100.0, 2) if start_cap > 0 else 0.0

            return {
                "enabled": is_shadow_portfolio_enabled(),
                "session_date": self._session_date,
                "trading_capital": round(self._trading_capital, 2),
                "secured_vault": round(self._secured_vault, 2),
                "starting_capital": round(start_cap, 2),
                "starting_vault": round(self._starting_vault, 2),
                "eod_settled": self._eod_settled,
                "circuit_breaker_active": self._circuit_breaker_active,
                "eod_dispatched_date": self._eod_dispatched_date,
                "metrics": {
                    "total_trades": total_closed + len(self._open_trades),
                    "open_count": len(self._open_trades),
                    "closed_count": total_closed,
                    "wins": wins,
                    "losses": losses,
                    "breakevens": breakevens,
                    "win_rate": win_rate,
                    "net_pnl": net_pnl,
                    "net_r": net_r,
                    "roi_pct": roi_pct,
                },
                "open_trades": {k: asdict(v) for k, v in self._open_trades.items()},
                "closed_trades": [asdict(v) for v in self._closed_trades],
                "seen_symbols_today": list(self._seen_symbols_today),
            }

    def format_telegram_shadow_audit(self) -> str:
        """Format an institutional-grade, transparent Telegram scorecard strictly < 3,000 chars."""
        data = self.get_portfolio_summary()
        metrics = data.get("metrics", {})
        total_closed = metrics.get("closed_count", 0)
        open_count = metrics.get("open_count", 0)

        if total_closed == 0 and open_count == 0:
            return ""

        date_str = data.get("session_date", self._get_today_str())
        start_cap = data.get("starting_capital", data.get("trading_capital", 100000.0))
        net_pnl = metrics.get("net_pnl", 0.0)
        net_r = metrics.get("net_r", 0.0)
        roi = metrics.get("roi_pct", 0.0)
        wr = metrics.get("win_rate", 0.0)
        wins = metrics.get("wins", 0)
        losses = metrics.get("losses", 0)

        today_vault_banked = round(net_pnl * 0.50, 2) if net_pnl > 0 else 0.0
        cumulative_vault = data.get("secured_vault", 0.0)
        tomorrow_cap = data.get("trading_capital", start_cap)

        lines = [
            "=================================================",
            "💼 *NSE-PULSE V13: SHADOW PORTFOLIO DAILY AUDIT*",
            f"📅 *Date:* `{date_str}` | *100% Autonomous Execution*",
            "=================================================",
            "📊 *PORTFOLIO PERFORMANCE SCORECARD:*",
            f"   • Starting Capital         : ₹{start_cap:,.2f}",
            f"   • Net Realized P&L         : *₹{net_pnl:+,.2f}* ({roi:+.2f}% ROI) {'🏆' if net_pnl >= 0 else '⚠️'}",
            f"   • Total Realized R-Multiple : *{net_r:+.2f} R*",
            f"   • Win Rate                 : *{wr}%* ({wins} Wins / {losses} Losses)",
            f"   • Closed Trades Executed   : {total_closed} (Conviction ≥ 2.0 Only)",
            "   • Post-1:30 PM New Entries : 0 (Hard Cutoff Respected) ⏰\n",
            "-------------------------------------------------",
            "🔒 *WEALTH PRESERVATION & COMPOUNDING:*",
            f"   • 🏦 Secured Vault Banked (50%): *₹{today_vault_banked:,.2f}*",
            f"   • 🔐 Cumulative Vault Total     : *₹{cumulative_vault:,.2f}* (Permanent Profit)",
            f"   • 🚀 Tomorrow's Capital         : *₹{tomorrow_cap:,.2f}* (Compounded)\n",
            "-------------------------------------------------",
            "🎯 *TRADE-BY-TRADE AUDIT TRAIL:*",
        ]

        # Append individual closed trades (up to top 15)
        for i, t in enumerate(self._closed_trades[:15], 1):
            dir_icon = "🟢" if t.direction == "BULLISH" else "🔴"
            res_icon = "✅" if t.realized_pnl > 0 else ("❌" if t.realized_pnl < 0 else "⚪")
            clean_exit_reason = (t.exit_reason or "").replace("_", " ")
            lines.append(
                f"{i}. *{t.symbol}* ({t.conviction_grade.replace('_', ' ')}) {dir_icon} {t.direction}\n"
                f"   • Entry: ₹{t.entry_ltp:.2f} ({t.entry_time}) | Exit: ₹{t.exit_price or 0.0:.2f} ({clean_exit_reason})\n"
                f"   • Realized P&L: *₹{t.realized_pnl:+,.2f}* ({t.realized_r:+.2f}R) {res_icon}"
            )

        if len(self._closed_trades) > 15:
            lines.append(f"   • ... and {len(self._closed_trades) - 15} additional trades settled.")

        lines.extend([
            "=================================================",
            "💡 *QUANTITATIVE VERDICT:*",
            "• Zero discretion. 100% mathematical execution.",
            "• Filtered out all low conviction noise (< 2.0 Pts).",
            "=================================================",
        ])

        return "\n".join(lines)

    def dispatch_eod_shadow_audit(self) -> bool:
        """
        Dispatch the standalone 15:35 IST Telegram notification.
        Idempotent per trading date.
        """
        if not is_shadow_portfolio_enabled():
            return False

        with self._lock:
            self._load_or_init_today()
            today = self._session_date

            if self._eod_dispatched_date == today:
                logger.info(f"Shadow Portfolio EOD audit already sent today ({today}), skipping duplicate.")
                return False

            if not self._closed_trades and not self._open_trades:
                logger.info("No shadow portfolio trades recorded today; audit dispatch skipped.")
                return False

            # Ensure all positions settled before report
            self.execute_eod_settlement()

            msg = self.format_telegram_shadow_audit()
            if not msg:
                return False

            try:
                from .telegram_bot import send_telegram_text
                sent = send_telegram_text(msg)
                if sent:
                    self._eod_dispatched_date = today
                    self._save_atomic()
                    logger.info(f"Successfully dispatched Shadow Portfolio EOD Audit to Telegram for {today}")
                    return True
            except Exception as e:
                logger.error(f"Failed to dispatch Shadow Portfolio EOD audit: {e}")
                return False

        return False


# Global Thread-Safe Singleton
GLOBAL_SHADOW_PORTFOLIO = ShadowPortfolioEngine()
