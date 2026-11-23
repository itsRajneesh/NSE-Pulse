"""
v13_nifty_options_ledger.py
-------------------------------------------------------------------------------
Isolated Intraday Paper-Trading Ledger & Kill-Switch Engine for NIFTY 50 Options
- Tracks Open & Closed Paper Trades in `backend/app/data/nifty_options_quant/`
- Enforces Institutional Exit Rules:
  1. Initial / Trailed Stop-Loss Hit
  2. Target 1 (+1.5R): Books 50% & Trails SL to Entry + ₹2.0 Cost Buffer
  3. Step-Trailing Stop (+0.5R steps above T1) & Target 2 (+2.5R Full Exit)
  4. 20-Minute Wall-Clock Time-Stop (Exits if held >= 20m and PnL < +0.5R)
  5. 15:15 IST Mandatory Intraday Square-Off
- Enforces Intraday Kill-Switch (Max 3 trades/day or 2 consecutive SL hits)
- Supports both Auto-Signal Paper Execution and 1-Click Manual Paper Trade Testing
-------------------------------------------------------------------------------
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import uuid
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .v13_nifty_options_engine import (
    IST,
    MAX_FREEZE_LOTS,
    MAX_NSE_EXECUTABLE_FREEZE_QTY,
    compute_iceberg_slices,
    compute_nse_option_statutory_charges,
    compute_weighted_slice_entry,
    round_to_nse_tick,
)
from .v13_alpha_telegram import (
    dispatch_alpha_entry_alert,
    dispatch_alpha_exit_alert,
    dispatch_alpha_milestone_alert,
)

logger = logging.getLogger(__name__)

LEDGER_DIR = Path(__file__).resolve().parent / "data" / "nifty_options_quant"
LEDGER_DIR.mkdir(parents=True, exist_ok=True)


class NiftyOptionsPaperLedger:
    """
    Thread-safe intraday paper trading ledger for the 4th Tab (`🎯 Nifty 50 Options`).
    """

    DEFAULT_MAX_TRADES_PER_DAY = 20
    DEFAULT_MAX_CONSECUTIVE_LOSSES = 3
    MAX_TRADES_PER_DAY = 20
    MAX_CONSECUTIVE_LOSSES = 3
    DEFAULT_POST_T1_STEPUP_MINUTES = 45.0
    DEFAULT_POST_T1_MAX_HOLD_MINUTES = 60.0
    DEFAULT_POST_T1_LOCK_R = 0.5

    def __init__(self, enable_notifications: bool = True) -> None:
        self._lock = threading.RLock()
        self.enable_notifications: bool = enable_notifications
        self._session_date: str = datetime.now(IST).strftime("%Y-%m-%d")
        self._open_trade: Optional[Dict[str, Any]] = None
        self._closed_trades: List[Dict[str, Any]] = []
        self._auto_trade_enabled: bool = True
        self._last_guard_blocked: bool = False
        self._last_guard_reason: Optional[str] = None
        self._load_today()

    def get_max_trades_per_day(self) -> int:
        try:
            return int(os.getenv("NIFTY_OPTIONS_MAX_TRADES_PER_DAY", str(self.DEFAULT_MAX_TRADES_PER_DAY)).strip())
        except (ValueError, TypeError):
            return self.DEFAULT_MAX_TRADES_PER_DAY

    def get_max_consecutive_losses(self) -> int:
        try:
            return int(os.getenv("NIFTY_OPTIONS_MAX_CONSECUTIVE_LOSSES", str(self.DEFAULT_MAX_CONSECUTIVE_LOSSES)).strip())
        except (ValueError, TypeError):
            return self.DEFAULT_MAX_CONSECUTIVE_LOSSES

    def get_post_t1_stepup_minutes(self) -> float:
        try:
            return float(os.getenv("NIFTY_OPTIONS_POST_T1_STEPUP_MINUTES", str(self.DEFAULT_POST_T1_STEPUP_MINUTES)).strip())
        except (ValueError, TypeError):
            return self.DEFAULT_POST_T1_STEPUP_MINUTES

    def get_post_t1_max_hold_minutes(self) -> float:
        try:
            return float(os.getenv("NIFTY_OPTIONS_POST_T1_MAX_HOLD_MINUTES", str(self.DEFAULT_POST_T1_MAX_HOLD_MINUTES)).strip())
        except (ValueError, TypeError):
            return self.DEFAULT_POST_T1_MAX_HOLD_MINUTES

    def get_post_t1_lock_r(self) -> float:
        try:
            return float(os.getenv("NIFTY_OPTIONS_POST_T1_LOCK_R", str(self.DEFAULT_POST_T1_LOCK_R)).strip())
        except (ValueError, TypeError):
            return self.DEFAULT_POST_T1_LOCK_R

    def _ledger_file(self, date_str: str) -> Path:
        return LEDGER_DIR / f"ledger_{date_str}.json"

    def _check_rollover(self, now_dt: Optional[datetime] = None) -> None:
        if now_dt is None:
            now_dt = datetime.now(IST)
        today_str = now_dt.strftime("%Y-%m-%d")
        if today_str != self._session_date:
            self._session_date = today_str
            self._open_trade = None
            self._closed_trades = []
            self._load_today()

    def _load_today(self) -> None:
        fpath = self._ledger_file(self._session_date)
        if not fpath.exists():
            return
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._open_trade = data.get("open_trade")
                self._closed_trades = data.get("closed_trades") or []
                self._auto_trade_enabled = bool(data.get("auto_trade_enabled", True))
        except Exception as e:
            logger.warning(f"Failed loading Nifty Options ledger {fpath}: {e}")

    def _save_atomic(self) -> None:
        try:
            LEDGER_DIR.mkdir(parents=True, exist_ok=True)
            fpath = self._ledger_file(self._session_date)
            payload = {
                "session_date": self._session_date,
                "updated_at": datetime.now(IST).isoformat(),
                "auto_trade_enabled": self._auto_trade_enabled,
                "open_trade": self._open_trade,
                "closed_trades": self._closed_trades,
            }
            tmp = fpath.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(fpath)
        except Exception as e:
            logger.warning(f"Failed saving Nifty Options ledger: {e}")

    def get_kill_switch_status(self) -> Dict[str, Any]:
        with self._lock:
            total_taken = len(self._closed_trades) + (1 if self._open_trade else 0)
            consec_losses = 0
            # self._closed_trades is stored Newest-First via insert(0, closed_record)
            for tr in self._closed_trades:
                if float(tr.get("net_pnl_inr", 0.0)) < 0:
                    consec_losses += 1
                else:
                    break

            max_trades = self.get_max_trades_per_day()
            max_consec = self.get_max_consecutive_losses()

            locked = False
            reason = "ACTIVE — Within Daily Institutional Risk Limits"
            if consec_losses >= max_consec:
                locked = True
                reason = f"KILL-SWITCH ENGAGED: {consec_losses} Consecutive Losses Today (Capital Preservation Lock)"
            elif len(self._closed_trades) >= max_trades and self._open_trade is None:
                locked = True
                reason = f"MAX DAILY TRADES ({max_trades}/{max_trades}) COMPLETED"

            return {
                "kill_switch_engaged": locked,
                "reason": reason,
                "trades_taken_today": total_taken,
                "max_trades_per_day": max_trades,
                "consecutive_losses": consec_losses,
                "max_consecutive_losses": max_consec,
            }

    def _check_reentry_and_wave_guards(
        self, eval_result: Dict[str, Any], now_dt: datetime
    ) -> Tuple[bool, str]:
        """
        Enforces Institutional Guard 1 (15m Loss Cooldown + Failed Entry Spot Recovery across ALL setups)
        and Guard 2 (Universal Wave Target Completion + Pullback Exhaustion + 2-Consecutive SL Reset).
        Neutral Regime Immunity: Returns True, "NO_ACTIVE_DIRECTION" when bias is NEUTRAL.
        """
        tp = eval_result.get("trade_plan") or {}
        sc = eval_result.get("selected_contract") or {}
        et = eval_result.get("entry_trigger") or {}
        ms = eval_result.get("market_snapshot") or {}
        regime = eval_result.get("regime") or {}

        bias = str(regime.get("bias") or "").upper()
        fallback_opt = "CE" if ("BULL" in bias or "CALL" in bias) else ("PE" if ("BEAR" in bias or "PUT" in bias) else "")
        opt_type = str(tp.get("opt_type") or sc.get("opt_type") or fallback_opt).upper()

        if opt_type not in ("CE", "PE"):
            return True, "NO_ACTIVE_DIRECTION"

        trigger_type = str(
            et.get("trigger_type") or tp.get("trigger_type") or "WAITING_FOR_SETUP"
        ).upper()
        spot_ltp = float(ms.get("spot_ltp", 0.0) or 0.0)
        is_pullback = "PULLBACK" in trigger_type

        # Sort auto-closed trades chronologically
        auto_trades = sorted(
            [t for t in self._closed_trades if t.get("source") == "AUTO_QUANT_SIGNAL"],
            key=lambda x: str(x.get("exit_time") or x.get("entry_time") or ""),
        )
        if not auto_trades:
            return True, "FRESH_SESSION"

        # ------------------------------------------------------------------
        # GUARD 1A: 15-Minute Strict Hard-Loss Cooldown in Same Direction
        # (Excludes minor TIME_STOP_20MIN scratches > -0.40R, which use Guard 1D)
        # ------------------------------------------------------------------
        same_dir_trades = [t for t in auto_trades if str(t.get("opt_type")).upper() == opt_type]
        if same_dir_trades:
            last_same = same_dir_trades[-1]
            last_net_pnl = float(last_same.get("net_pnl_inr", 0.0))
            last_exit_reason = str(last_same.get("exit_reason", ""))
            last_r_mult = float(last_same.get("r_multiple", 0.0) or 0.0)

            try:
                last_exit_dt = datetime.fromisoformat(str(last_same["exit_time"]))
                if last_exit_dt.tzinfo is None:
                    last_exit_dt = last_exit_dt.replace(tzinfo=IST)
                mins_since_last_same = (now_dt - last_exit_dt).total_seconds() / 60.0
            except Exception:
                mins_since_last_same = 999.0

            is_minor_timestop_scratch = (
                "TIME_STOP_20MIN" in last_exit_reason and last_r_mult > -0.40
            )

            if last_net_pnl < 0 and not is_minor_timestop_scratch:
                if mins_since_last_same < 15.0:
                    return (
                        False,
                        f"GUARD_1_LOSS_COOLDOWN (1A): {opt_type} blocked for {15.0 - mins_since_last_same:.1f}m "
                        f"after losing trade {last_same.get('trade_id')} ({last_net_pnl:+.0f} INR)",
                    )

        # ------------------------------------------------------------------
        # GUARD 1B: Hard-Loss Spot Recovery (Excludes TIME_STOP_20MIN exits)
        # Applies when immediately preceding trade had a non-timestop hard loss:
        # ------------------------------------------------------------------
        last_overall = auto_trades[-1]
        if (
            str(last_overall.get("opt_type")).upper() == opt_type
            and float(last_overall.get("net_pnl_inr", 0.0)) < 0
            and "TIME_STOP_20MIN" not in str(last_overall.get("exit_reason", ""))
        ):
            failed_spot = float(last_overall.get("entry_spot", 0.0) or 0.0)
            if failed_spot > 0 and spot_ltp > 0:
                if opt_type == "CE" and spot_ltp < (failed_spot + 1.50):
                    return (
                        False,
                        f"GUARD_1_STRUCTURE_UNRECOVERED (1B): CE entry blocked — Spot ({spot_ltp:.1f}) "
                        f"has not recovered above failed entry spot ({failed_spot:.1f} + 1.5 buffer)",
                    )
                if opt_type == "PE" and spot_ltp > (failed_spot - 1.50):
                    return (
                        False,
                        f"GUARD_1_STRUCTURE_UNRECOVERED (1B): PE entry blocked — Spot ({spot_ltp:.1f}) "
                        f"has not broken below failed entry spot ({failed_spot:.1f} - 1.5 buffer)",
                    )

        # ------------------------------------------------------------------
        # GUARD 1C: Continuous 20-Minute Time-Stop Momentum Stall Filter (2x Trades)
        # Evaluated BEFORE Guard 1D so 15m cooldown is never masked by 5m cooldown!
        # ------------------------------------------------------------------
        if len(auto_trades) >= 2:
            last_1 = auto_trades[-1]
            last_2 = auto_trades[-2]

            same_side = (
                str(last_1.get("opt_type")).upper() == opt_type
                and str(last_2.get("opt_type")).upper() == opt_type
            )
            both_time_stopped = (
                "TIME_STOP_20MIN" in str(last_1.get("exit_reason", ""))
                and "TIME_STOP_20MIN" in str(last_2.get("exit_reason", ""))
            )

            if same_side and both_time_stopped:
                try:
                    last_2_exit = datetime.fromisoformat(str(last_2["exit_time"]))
                    last_1_entry = datetime.fromisoformat(str(last_1["entry_time"]))
                    last_1_exit = datetime.fromisoformat(str(last_1["exit_time"]))
                    if last_2_exit.tzinfo is None:
                        last_2_exit = last_2_exit.replace(tzinfo=IST)
                    if last_1_entry.tzinfo is None:
                        last_1_entry = last_1_entry.replace(tzinfo=IST)
                    if last_1_exit.tzinfo is None:
                        last_1_exit = last_1_exit.replace(tzinfo=IST)

                    gap_between_trades = (last_1_entry - last_2_exit).total_seconds() / 60.0
                    mins_since_last_exit = (now_dt - last_1_exit).total_seconds() / 60.0
                except Exception:
                    gap_between_trades = 999.0
                    mins_since_last_exit = 999.0

                # Must be a continuous stall (gap <= 20.0m, e.g. 12:36 -> 12:36 gap 0.0m)
                if 0.0 <= gap_between_trades <= 20.0:
                    spots_candidates = [
                        float(last_1.get("entry_spot", 0.0) or 0.0),
                        float(last_1.get("exit_spot", 0.0) or 0.0),
                        float(last_2.get("entry_spot", 0.0) or 0.0),
                        float(last_2.get("exit_spot", 0.0) or 0.0),
                    ]
                    valid_stall_spots = [s for s in spots_candidates if s > 0]
                    max_stall_spot = max(valid_stall_spots) if valid_stall_spots else 0.0
                    min_stall_spot = min(valid_stall_spots) if valid_stall_spots else 0.0

                    # 1. Mandatory 15m stall cooldown
                    if mins_since_last_exit < 15.0:
                        return (
                            False,
                            f"GUARD_1_MOMENTUM_STALL (1C): 2 continuous 20m time-stops in {opt_type} "
                            f"(gap {gap_between_trades:.1f}m) — Cooldown active for {15.0 - mins_since_last_exit:.1f}m",
                        )
                    # 2. Multi-Trade Structure Breakout Clearance (+3.00 pt buffer)
                    if opt_type == "CE" and spot_ltp > 0 and max_stall_spot > 0 and spot_ltp <= (max_stall_spot + 3.00):
                        return (
                            False,
                            f"GUARD_1_MOMENTUM_STALL (1C): CE Spot ({spot_ltp:.1f}) must break above "
                            f"stall high ({max_stall_spot:.1f} + 3.0 buffer) after 2 continuous time-stops",
                        )
                    if opt_type == "PE" and spot_ltp > 0 and min_stall_spot > 0 and spot_ltp >= (min_stall_spot - 3.00):
                        return (
                            False,
                            f"GUARD_1_MOMENTUM_STALL (1C): PE Spot ({spot_ltp:.1f}) must break below "
                            f"stall low ({min_stall_spot:.1f} - 3.0 buffer) after 2 continuous time-stops",
                        )

        # ------------------------------------------------------------------
        # GUARD 1D: Symmetric 20-Minute Time-Stop Settlement & Clearance (1x Trade)
        # Evaluated AFTER Guard 1C! Applies to ANY single TIME_STOP_20MIN exit!
        # ------------------------------------------------------------------
        if same_dir_trades:
            last_same = same_dir_trades[-1]
            last_exit_reason = str(last_same.get("exit_reason", ""))
            last_net_pnl = float(last_same.get("net_pnl_inr", 0.0))

            if "TIME_STOP_20MIN" in last_exit_reason:
                try:
                    last_exit_dt = datetime.fromisoformat(str(last_same["exit_time"]))
                    if last_exit_dt.tzinfo is None:
                        last_exit_dt = last_exit_dt.replace(tzinfo=IST)
                    mins_since_last_same = (now_dt - last_exit_dt).total_seconds() / 60.0
                except Exception:
                    mins_since_last_same = 999.0

                # 1. Mandatory 5.0-minute cooldown (1 full 5m candle settlement)
                if mins_since_last_same < 5.0:
                    return (
                        False,
                        f"GUARD_1_TIME_STOP_COOLDOWN (1D): {opt_type} blocked for {5.0 - mins_since_last_same:.1f}m "
                        f"(5m bar settlement) after 20m time-stop {last_same.get('trade_id')} ({last_net_pnl:+.0f} INR)",
                    )

                # 2. Single-Trade Stall Box Clearance (+3.00 pt buffer, including best_spot)
                ts_entry_spot = float(last_same.get("entry_spot", 0.0) or 0.0)
                ts_exit_spot = float(last_same.get("exit_spot", 0.0) or ts_entry_spot)
                ts_best_spot = float(last_same.get("best_spot", 0.0) or ts_exit_spot or ts_entry_spot)
                if spot_ltp > 0 and ts_entry_spot > 0:
                    if opt_type == "CE":
                        stall_high_spot = max(ts_entry_spot, ts_exit_spot, ts_best_spot)
                        if spot_ltp < (stall_high_spot + 3.00):
                            return (
                                False,
                                f"GUARD_1_TIME_STOP_CLEARANCE (1D): CE Spot ({spot_ltp:.1f}) must clear "
                                f"time-stop stall high ({stall_high_spot:.1f} + 3.0 buffer)",
                            )
                    elif opt_type == "PE":
                        valid_spots = [s for s in (ts_entry_spot, ts_exit_spot, ts_best_spot) if s > 0]
                        stall_low_spot = min(valid_spots) if valid_spots else ts_entry_spot
                        if spot_ltp > (stall_low_spot - 3.00):
                            return (
                                False,
                                f"GUARD_1_TIME_STOP_CLEARANCE (1D): PE Spot ({spot_ltp:.1f}) must break below "
                                f"time-stop stall low ({stall_low_spot:.1f} - 3.0 buffer)",
                            )

            # ------------------------------------------------------------------
            # GUARD 1E (v5.7): Post-Shield / Post-Trail Rejection Cooldown & Peak Clearance
            # ------------------------------------------------------------------
            is_shield_or_trail_exit = (
                "PRE_T1_SHIELD_SL_HIT" in last_exit_reason
                or "TRAILED_SL_HIT" in last_exit_reason
                or "TRAILED_45M_SL_HIT" in last_exit_reason
            )
            if is_shield_or_trail_exit:
                try:
                    last_exit_dt = datetime.fromisoformat(str(last_same["exit_time"]))
                    if last_exit_dt.tzinfo is None:
                        last_exit_dt = last_exit_dt.replace(tzinfo=IST)
                    mins_since_last_same = (now_dt - last_exit_dt).total_seconds() / 60.0
                except Exception:
                    mins_since_last_same = 999.0

                # 1. Mandatory 15.0-minute rejection cooldown (3 full 5m bars settlement)
                if mins_since_last_same < 15.0:
                    return (
                        False,
                        f"GUARD_1_REJECTION_COOLDOWN (1E): {opt_type} blocked for {15.0 - mins_since_last_same:.1f}m "
                        f"after trailed/shield rejection {last_same.get('trade_id')} ({last_net_pnl:+.0f} INR)",
                    )

                # 2. Structural Peak / Higher-Low Clearance (+3.00 pt Spot Buffer)
                sh_entry_spot = float(last_same.get("entry_spot", 0.0) or 0.0)
                sh_exit_spot = float(last_same.get("exit_spot", 0.0) or sh_entry_spot)
                sh_best_spot = float(last_same.get("best_spot", 0.0) or sh_exit_spot or sh_entry_spot)
                was_t1_booked = bool(last_same.get("t1_booked", False))
                # Pullback after a T1 winner checks Higher-Low/Lower-High vs prior entry_spot;
                # Pre-T1 Shield rejections or Breakout setups must clear the extreme best_spot peak!
                use_higher_low_ref = was_t1_booked and is_pullback

                if spot_ltp > 0 and sh_entry_spot > 0:
                    if opt_type == "CE":
                        ref_high_spot = (
                            sh_entry_spot
                            if use_higher_low_ref
                            else max(sh_entry_spot, sh_exit_spot, sh_best_spot)
                        )
                        if spot_ltp < (ref_high_spot + 3.00):
                            return (
                                False,
                                f"GUARD_1_PEAK_CLEARANCE (1E): CE Spot ({spot_ltp:.1f}) must clear "
                                f"prior rejection peak ({ref_high_spot:.1f} + 3.0 buffer)",
                            )
                    elif opt_type == "PE":
                        valid_spots = [s for s in (sh_entry_spot, sh_exit_spot, sh_best_spot) if s > 0]
                        ref_low_spot = (
                            sh_entry_spot
                            if use_higher_low_ref
                            else (min(valid_spots) if valid_spots else sh_entry_spot)
                        )
                        if spot_ltp > (ref_low_spot - 3.00):
                            return (
                                False,
                                f"GUARD_1_PEAK_CLEARANCE (1E): PE Spot ({spot_ltp:.1f}) must break below "
                                f"prior rejection low ({ref_low_spot:.1f} - 3.0 buffer)",
                            )

        # ------------------------------------------------------------------
        # GUARD 2: Wave Analysis across contiguous same-direction trades
        # ------------------------------------------------------------------
        wave_trades: List[Dict[str, Any]] = []
        for t in reversed(auto_trades):
            if str(t.get("opt_type")).upper() == opt_type:
                wave_trades.insert(0, t)
            else:
                break

        wave_wins = sum(1 for t in wave_trades if float(t.get("net_pnl_inr", 0.0)) > 0)
        wave_t1_wins = sum(1 for t in wave_trades if bool(t.get("t1_booked")) or float(t.get("r_multiple", 0.0)) >= 0.75)
        wave_major_moves = sum(
            1
            for t in wave_trades
            if bool(t.get("t1_booked"))
            or bool(t.get("pre_t1_shield_active"))
            or (
                "PRE_T1_SHIELD_SL_HIT" in str(t.get("exit_reason", ""))
                and not (bool(t.get("stage1b0_shield_active")) and not bool(t.get("pre_t1_shield_active")))
                and not (bool(t.get("stage0b_shield_active")) and not bool(t.get("pre_t1_shield_active")))
            )
            or float(t.get("r_multiple", 0.0) or 0.0) >= 0.75
        )
        wave_t2_hits = sum(1 for t in wave_trades if "TARGET_2_HIT" in str(t.get("exit_reason", "")))

        # Guard 2A: Pullback Wave Exhaustion (with Substring Immunity)
        if is_pullback and wave_trades:
            last_reason = str(wave_trades[-1].get("exit_reason", ""))
            last_pnl = float(wave_trades[-1].get("net_pnl_inr", 0.0))
            is_hard_loss = ("INITIAL_SL_HIT" in last_reason) and (last_pnl < 0)

            if wave_wins >= 2 or len(wave_trades) >= 3 or is_hard_loss:
                return (
                    False,
                    f"GUARD_2_WAVE_EXHAUSTED (2A): {opt_type} wave has {wave_wins}W/{len(wave_trades)}T "
                    f"— Pullbacks paused (requires fresh Breakout)",
                )

        # Guard 2B (v5.7): Universal Wave Target & Wave#3 Exhaustion Lock (Applies to ALL setups!)
        if wave_t1_wins >= 2 or (len(wave_trades) >= 2 and (wave_major_moves >= 1 or wave_t2_hits >= 1)):
            return (
                False,
                f"GUARD_2_WAVE_COMPLETED (2B): {opt_type} trend reached maximum institutional objectives "
                f"({len(wave_trades)} trades, {wave_major_moves} major moves / {wave_t2_hits} T2 hits) — Wave locked",
            )

        # Guard 2B-Wave3: If 2 prior same-direction trades occurred without a major move (e.g. 2x 20m time-stops),
        # require >= 15.0m cooldown AND full-wave best_spot + 3.00 pt clearance for Wave#3!
        if len(wave_trades) >= 2:
            last_w = wave_trades[-1]
            try:
                last_w_dt = datetime.fromisoformat(str(last_w["exit_time"]))
                if last_w_dt.tzinfo is None:
                    last_w_dt = last_w_dt.replace(tzinfo=IST)
                mins_since_w = (now_dt - last_w_dt).total_seconds() / 60.0
            except Exception:
                mins_since_w = 999.0

            if mins_since_w < 15.0:
                return (
                    False,
                    f"GUARD_2_WAVE3_COOLDOWN (2B): {opt_type} Wave#3 requires 15.0m reset after {len(wave_trades)} "
                    f"same-direction trades ({15.0 - mins_since_w:.1f}m remaining)",
                )

            if spot_ltp > 0:
                if opt_type == "CE":
                    w_spots = [
                        max(
                            float(t.get("entry_spot", 0.0) or 0.0),
                            float(t.get("exit_spot", 0.0) or 0.0),
                            float(t.get("best_spot", 0.0) or 0.0),
                        )
                        for t in wave_trades
                    ]
                    wave_high = max(w_spots) if w_spots else 0.0
                    if wave_high > 0 and spot_ltp < (wave_high + 3.00):
                        return (
                            False,
                            f"GUARD_2_WAVE3_CLEARANCE (2B): CE Spot ({spot_ltp:.1f}) must clear wave high "
                            f"({wave_high:.1f} + 3.0 buffer) for Wave#3 entry",
                        )
                elif opt_type == "PE":
                    w_spots = []
                    for t in wave_trades:
                        for s_key in ("entry_spot", "exit_spot", "best_spot"):
                            sv = float(t.get(s_key, 0.0) or 0.0)
                            if sv > 0:
                                w_spots.append(sv)
                    wave_low = min(w_spots) if w_spots else 0.0
                    if wave_low > 0 and spot_ltp > (wave_low - 3.00):
                        return (
                            False,
                            f"GUARD_2_WAVE3_CLEARANCE (2B): PE Spot ({spot_ltp:.1f}) must break below wave low "
                            f"({wave_low:.1f} - 3.0 buffer) for Wave#3 entry",
                        )

        # Guard 2C: 2-Consecutive Hard SL Reset Filter
        if len(wave_trades) >= 2:
            penultimate = wave_trades[-2]
            ultimate = wave_trades[-1]
            if (
                "INITIAL_SL_HIT" in str(penultimate.get("exit_reason", ""))
                and float(penultimate.get("net_pnl_inr", 0.0)) < 0
                and "INITIAL_SL_HIT" in str(ultimate.get("exit_reason", ""))
                and float(ultimate.get("net_pnl_inr", 0.0)) < 0
            ):
                try:
                    last_exit_dt = datetime.fromisoformat(str(ultimate["exit_time"]))
                    if last_exit_dt.tzinfo is None:
                        last_exit_dt = last_exit_dt.replace(tzinfo=IST)
                    mins_since = (now_dt - last_exit_dt).total_seconds() / 60.0
                except Exception:
                    mins_since = 999.0

                max_wave_spot = max(float(t.get("entry_spot", 0.0) or 0.0) for t in wave_trades)
                min_wave_spot = min(float(t.get("entry_spot", 999999.0) or 999999.0) for t in wave_trades)

                if mins_since < 45.0:
                    return (
                        False,
                        f"GUARD_2_CONSECUTIVE_SL_LOCK (2C): 2 consecutive initial SLs in {opt_type} wave — "
                        f"Requires 45m reset cooldown ({mins_since:.1f}/45.0m)",
                    )
                if opt_type == "CE" and spot_ltp < (max_wave_spot + 1.50):
                    return (
                        False,
                        f"GUARD_2_CONSECUTIVE_SL_LOCK (2C): CE Spot ({spot_ltp:.1f}) must break above "
                        f"wave high ({max_wave_spot:.1f} + 1.5 buffer) after 2 SL hits",
                    )
                if opt_type == "PE" and spot_ltp > (min_wave_spot - 1.50):
                    return (
                        False,
                        f"GUARD_2_CONSECUTIVE_SL_LOCK (2C): PE Spot ({spot_ltp:.1f}) must break below "
                        f"wave low ({min_wave_spot:.1f} - 1.5 buffer) after 2 SL hits",
                    )

        return True, "PASS"

    def process_quant_evaluation(
        self,
        eval_result: Dict[str, Any],
        now_dt: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Update any open paper trade with live option LTP, enforce SL/T1/T2/20m Time-Stop/15:15 EOD,
        and auto-enter a new paper trade if `EXECUTE_BUY` triggers during market hours.
        Continuous Guard Evaluation tracks active guard state on every evaluation tick.
        """
        if now_dt is None:
            now_dt = datetime.now(IST)
        elif now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=IST)

        with self._lock:
            self._check_rollover(now_dt)

            # 1. Update open position if one exists
            if self._open_trade is not None:
                self._update_open_trade_state(eval_result, now_dt)
                self._last_guard_blocked = False
                self._last_guard_reason = None
                return self.get_ledger_summary()

            # 2. Continuous Guard Evaluation whenever no trade is open
            ks = self.get_kill_switch_status()
            trade_plan = eval_result.get("trade_plan") or {}
            feed_mode = str(
                eval_result.get("feed_mode")
                or eval_result.get("market_snapshot", {}).get("feed_mode")
                or "DEGRADED"
            ).upper()

            if feed_mode == "FULL" and not ks["kill_switch_engaged"]:
                guard_ok, guard_reason = self._check_reentry_and_wave_guards(eval_result, now_dt)
                self._last_guard_blocked = not guard_ok
                self._last_guard_reason = None if guard_ok else guard_reason

                if (
                    self._auto_trade_enabled
                    and trade_plan.get("signal_state") == "EXECUTE_BUY"
                    and guard_ok
                ):
                    self.enter_paper_trade_from_eval(eval_result, source="AUTO_QUANT_SIGNAL", now_dt=now_dt)
                elif self._auto_trade_enabled and trade_plan.get("signal_state") == "EXECUTE_BUY" and not guard_ok:
                    logger.info("[LEDGER ANTI-WHIPSAW GUARD] Blocked Auto Entry: %s", guard_reason)
            else:
                self._last_guard_blocked = False
                self._last_guard_reason = None

            return self.get_ledger_summary()

    def enter_paper_trade_from_eval(
        self,
        eval_result: Dict[str, Any],
        source: str = "MANUAL_PAPER_TEST",
        now_dt: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        if now_dt is None:
            now_dt = datetime.now(IST)
        elif now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=IST)

        with self._lock:
            self._check_rollover(now_dt)
            if self._open_trade is not None:
                return {
                    "status": "already_open",
                    "message": f"Position already open in {self._open_trade['symbol']}. Close it first.",
                    "ledger": self.get_ledger_summary(),
                }

            sc = eval_result.get("selected_contract") or {}
            tp = eval_result.get("trade_plan") or {}
            sz = eval_result.get("position_sizing") or {}
            ms = eval_result.get("market_snapshot") or {}

            lots = int(sz.get("study_lots", 1) or 1)
            lot_size = int(sz.get("lot_size", 65) or 65)
            qty = lots * lot_size
            base_entry_prem = float(tp.get("entry_premium", sc.get("ltp", 100.0)))

            # Auto-Slice Iceberg decomposition (<= 27 lots / 1,755 qty per slice)
            max_slice_lots = max(1, MAX_NSE_EXECUTABLE_FREEZE_QTY // max(lot_size, 1))
            entry_slices = compute_iceberg_slices(lots, max_slice_lots)
            entry_legs = max(len(entry_slices), 1)
            is_iceberg = entry_legs > 1
            entry_prem = compute_weighted_slice_entry(base_entry_prem, entry_slices)

            t1_lots = 0 if lots == 1 else math.ceil(lots / 2)
            runner_lots = lots - t1_lots
            t1_slices = compute_iceberg_slices(t1_lots, max_slice_lots) if t1_lots > 0 else []
            runner_slices = compute_iceberg_slices(runner_lots, max_slice_lots) if runner_lots > 0 else []
            t1_legs = len(t1_slices)
            runner_legs = len(runner_slices)

            sl_prem = float(tp.get("sl_premium", max(entry_prem - 15.0, 2.0)))
            t1_prem = float(tp.get("t1_premium", entry_prem + 22.5))
            t2_prem = float(tp.get("t2_premium", entry_prem + 37.5))
            sl_pts = max(round(entry_prem - sl_prem, 2), 1.0)

            self._open_trade = {
                "trade_id": f"NPQ-{now_dt.strftime('%H%M%S')}-{uuid.uuid4().hex[:4].upper()}",
                "source": source,
                "entry_time": now_dt.isoformat(),
                "entry_time_str": now_dt.strftime("%H:%M:%S IST"),
                "symbol": tp.get("symbol") or sc.get("symbol") or "NIFTY OPT",
                "strike": int(tp.get("strike") or sc.get("strike") or 25000),
                "opt_type": str(tp.get("opt_type") or sc.get("opt_type") or "CE"),
                "moneyness": str(tp.get("moneyness") or sc.get("moneyness") or "ATM"),
                "lots": lots,
                "lot_size": lot_size,
                "qty": qty,
                "is_iceberg": is_iceberg,
                "entry_slices": entry_slices,
                "entry_legs": entry_legs,
                "t1_lots": t1_lots,
                "runner_lots": runner_lots,
                "t1_slices": t1_slices,
                "runner_slices": runner_slices,
                "t1_legs": t1_legs,
                "runner_legs": runner_legs,
                "sizing_status": sz.get("sizing_status", "OPTIMAL"),
                "entry_spot": float(ms.get("spot_ltp", 0.0)),
                "current_spot": float(ms.get("spot_ltp", 0.0)),
                "best_spot": float(ms.get("spot_ltp", 0.0)),
                "entry_premium": entry_prem,
                "current_ltp": entry_prem,
                "high_watermark": entry_prem,
                "initial_sl_premium": sl_prem,
                "current_sl_premium": sl_prem,
                "sl_points": sl_pts,
                "t1_premium": t1_prem,
                "t2_premium": t2_prem,
                "t1_booked": False,
                "t2_reached": False,
                "stage0a_shield_active": False,
                "stage0b_shield_active": False,
                "stage1b0_shield_active": False,
                "pre_t1_shield_active": False,
                "pre_t1_doorstep_active": False,
                "stage2_notified": False,
                "doorstep_notified": False,
                "sl_45m_tightened": False,
                "coiling_extension_active": False,
                "hold_minutes": 0.0,
                "time_stop_minutes": 20.0,
                "post_t1_stepup_minutes": self.get_post_t1_stepup_minutes(),
                "post_t1_max_hold_minutes": self.get_post_t1_max_hold_minutes(),
                "post_t1_lock_r": self.get_post_t1_lock_r(),
                "unrealized_pts": 0.0,
                "unrealized_r": 0.0,
                "gross_pnl_inr": 0.0,
                "est_charges_inr": float(sz.get("estimated_charges_inr", 60.0)),
                "est_slippage_inr": float(sz.get("estimated_slippage_inr", 30.0)),
                "net_pnl_inr": -round(float(sz.get("estimated_charges_inr", 60.0)), 2),
                "delta_at_entry": float(sc.get("delta", 0.55)),
                "iv_at_entry": float(sc.get("iv_pct", 14.0)),
                "trigger_type": (eval_result.get("entry_trigger") or {}).get("trigger_type", source),
            }
            self._save_atomic()
            if self.enable_notifications and source == "AUTO_QUANT_SIGNAL":
                try:
                    dispatch_alpha_entry_alert(self._open_trade, eval_result)
                except Exception as e:
                    logger.warning("Alpha entry alert dispatch error: %s", e)
            return {
                "status": "opened",
                "message": f"Paper Trade Opened: {self._open_trade['symbol']} ({lots} Lot / {qty} Qty) @ ₹{entry_prem:.2f}",
                "ledger": self.get_ledger_summary(),
            }

    def _update_open_trade_state(self, eval_result: Dict[str, Any], now_dt: datetime) -> None:
        if not self._open_trade:
            return

        tr = self._open_trade

        # GUARD 1: Never trigger SL, Target or Time-Stop on a synthetic DEGRADED bundle!
        feed_mode = str(
            eval_result.get("feed_mode")
            or eval_result.get("market_snapshot", {}).get("feed_mode")
            or "DEGRADED"
        ).upper()

        if feed_mode != "FULL":
            logger.warning(
                "[LEDGER GUARD 1] Skipping SL/Target evaluation on %s because market feed is currently in %s mode.",
                tr.get("symbol"),
                feed_mode,
            )
            return

        strike = int(tr["strike"])
        opt_type = str(tr["opt_type"]).upper()
        chain_window = eval_result.get("option_chain_window") or []

        live_ltp: Optional[float] = None
        for row in chain_window:
            if int(row.get("strike", 0)) == strike:
                val = float(row.get("ce_ltp" if opt_type == "CE" else "pe_ltp", 0.0) or 0.0)
                if val > 0:
                    live_ltp = round_to_nse_tick(val)
                break

        if live_ltp is None:
            sc = eval_result.get("selected_contract") or {}
            if int(sc.get("strike", 0)) == strike and str(sc.get("opt_type", "")).upper() == opt_type:
                live_ltp = float(sc.get("ltp", tr["current_ltp"]))
            else:
                live_ltp = float(tr.get("current_ltp", tr["entry_premium"]))

        entry_prem = float(tr["entry_premium"])
        prev_ltp = float(tr.get("current_ltp", entry_prem))
        spot_ltp = float(eval_result.get("market_snapshot", {}).get("spot_ltp", 0.0))
        entry_spot = float(tr.get("entry_spot", spot_ltp))

        # GUARD 2: Single-Tick Anomaly Filter (Reject sudden >30% crash if spot moved < 25 pts)
        if prev_ltp > 0 and live_ltp > 0:
            drop_pct = (prev_ltp - live_ltp) / prev_ltp
            spot_diff = abs(spot_ltp - entry_spot)
            if drop_pct > 0.30 and spot_diff < 25.0:
                logger.warning(
                    "[LEDGER GUARD 2] Freak tick rejected for %s: LTP dropped %.1f%% (₹%.2f -> ₹%.2f) "
                    "while spot diff is only %.1f pts. Retaining previous valid LTP ₹%.2f.",
                    tr.get("symbol"),
                    drop_pct * 100,
                    prev_ltp,
                    live_ltp,
                    spot_diff,
                    prev_ltp,
                )
                live_ltp = prev_ltp

        entry_dt = datetime.fromisoformat(tr["entry_time"])
        if entry_dt.tzinfo is None:
            entry_dt = entry_dt.replace(tzinfo=IST)
        hold_mins = max(0.0, (now_dt - entry_dt).total_seconds() / 60.0)

        entry_prem = float(tr["entry_premium"])
        sl_pts = max(float(tr["sl_points"]), 1.0)
        qty = int(tr["qty"])
        lots = int(tr["lots"])
        lot_size = int(tr["lot_size"])

        tr["current_ltp"] = live_ltp
        if spot_ltp > 0:
            tr["current_spot"] = spot_ltp
            prev_best_spot = float(tr.get("best_spot") or entry_spot or spot_ltp)
            if opt_type == "CE":
                tr["best_spot"] = max(prev_best_spot, spot_ltp)
            else:
                tr["best_spot"] = min(prev_best_spot, spot_ltp) if prev_best_spot > 0 else spot_ltp
        tr["high_watermark"] = max(float(tr.get("high_watermark", entry_prem)), live_ltp)
        tr["hold_minutes"] = round(hold_mins, 1)

        raw_pts_move = round(live_ltp - entry_prem, 2)
        raw_r_mult = round(raw_pts_move / sl_pts, 2)
        peak_pts_move = round(float(tr["high_watermark"]) - entry_prem, 2)
        peak_r_mult = round(peak_pts_move / sl_pts, 2)

        milestones_triggered: List[str] = []

        # Stage 1A: Check T1 (+1.5R) milestone -> Book ceil(lots/2) & Handover 50% Runner SL to Post-T1 Floor
        # Critical Catch: Do NOT carry Pre-T1 100%-lot Stage 1B-1/1C SL (+0.75R/+0.95R) onto the 50% Post-T1 Runner!
        # Since 50% is now banked in cash at +1.50R, setting the 50% Runner SL to +0.50R yields a +1.00R Blended Floor
        # while giving the Runner full 1.00R breathing room to survive post-T1 pullbacks and ride to T2 (+2.50R).
        if not tr.get("t1_booked") and live_ltp >= float(tr["t1_premium"]):
            tr["t1_booked"] = True
            base_cost_sl = round_to_nse_tick(entry_prem + 2.0)
            shield_floor_sl = round_to_nse_tick(entry_prem + (0.50 * sl_pts))
            tr["current_sl_premium"] = max(base_cost_sl, shield_floor_sl)
            milestones_triggered.append("T1_BOOKED")
        # Stage 1C (v5.8): Pre-T1 Doorstep Lock at +1.35R -> Lock max(Entry + 0.95R, HWM - max(0.38R, 6.50 pts))
        elif not tr.get("t1_booked") and peak_r_mult >= 1.35:
            c135_offset = max(0.38 * sl_pts, 6.50)
            raw_1c_sl = max(entry_prem + (0.95 * sl_pts), float(tr["high_watermark"]) - c135_offset)
            stage1c_sl = round_to_nse_tick(min(raw_1c_sl, float(tr["t1_premium"]) - 1.0))
            if stage1c_sl > float(tr["current_sl_premium"]):
                was_doorstep_1c = bool(tr.get("pre_t1_doorstep_active", False))
                tr["current_sl_premium"] = stage1c_sl
                tr["pre_t1_shield_active"] = True
                tr["pre_t1_doorstep_active"] = True
                if not was_doorstep_1c:
                    milestones_triggered.append("PRE_T1_DOORSTEP_135")
        # Stage 1B-1 (v5.8): Progressive Pre-T1 Chandelier Shield at +1.20R -> Lock max(Entry + 0.65R, HWM - max(0.45R, 8.50 pts))
        elif not tr.get("t1_booked") and peak_r_mult >= 1.20:
            c120_offset = max(0.45 * sl_pts, 8.50)
            shield_sl = round_to_nse_tick(
                max(entry_prem + (0.65 * sl_pts), float(tr["high_watermark"]) - c120_offset)
            )
            if shield_sl > float(tr["current_sl_premium"]):
                was_shield = bool(tr.get("pre_t1_shield_active", False))
                tr["current_sl_premium"] = shield_sl
                tr["pre_t1_shield_active"] = True
                if not was_shield:
                    milestones_triggered.append("PRE_T1_SHIELD")
        # Stage 1B-0 (v5.8): Pre-T1 +1.00R Green Floor Shield -> Lock max(Entry + 0.25R, HWM - max(0.55R, 10.00 pts))
        elif not tr.get("t1_booked") and peak_r_mult >= 1.00:
            c100_offset = max(0.55 * sl_pts, 10.00)
            stage1b0_sl = round_to_nse_tick(
                max(entry_prem + (0.25 * sl_pts), float(tr["high_watermark"]) - c100_offset)
            )
            if stage1b0_sl > float(tr["current_sl_premium"]):
                was_1b0 = bool(tr.get("stage1b0_shield_active", False))
                tr["current_sl_premium"] = stage1b0_sl
                tr["stage1b0_shield_active"] = True
                if not was_1b0:
                    milestones_triggered.append("STAGE_1B0_GREEN_SHIELD")
        # Stage 0B (v5.9 Pure R-Multiple): Halfway-to-T1 (+0.75R Peak) Cost-Plus Breakeven Shield -> locks min(Entry + ₹1.50, HWM - 8.00)
        elif not tr.get("t1_booked") and peak_r_mult >= 0.75:
            stage0b_floor = entry_prem - max(0.25 * sl_pts, 4.0)
            stage0b_sl = round_to_nse_tick(
                max(stage0b_floor, min(entry_prem + 1.50, float(tr["high_watermark"]) - 8.00))
            )
            if stage0b_sl > float(tr["current_sl_premium"]):
                was_0b = bool(tr.get("stage0b_shield_active", False))
                tr["current_sl_premium"] = stage0b_sl
                tr["stage0b_shield_active"] = True
                if not was_0b:
                    milestones_triggered.append("STAGE_0B_UTURN_SHIELD")
        # Stage 0A (v5.6): Pre-T1 Half-Loss U-Turn Shield (+0.45R Peak caps loss at -0.45R)
        elif not tr.get("t1_booked") and peak_r_mult >= 0.45:
            stage0a_sl = round_to_nse_tick(entry_prem - (0.45 * sl_pts))
            if stage0a_sl > float(tr["current_sl_premium"]):
                was_0a = bool(tr.get("stage0a_shield_active", False))
                tr["current_sl_premium"] = stage0a_sl
                tr["stage0a_shield_active"] = True
                if not was_0a:
                    milestones_triggered.append("STAGE_0A_UTURN_SHIELD")

        # Exact Lot-Weighted Live Blended P&L calculation (Safeguard 2: active across all price levels)
        t1_lots = int(tr.get("t1_lots") if tr.get("t1_lots") is not None else (0 if lots == 1 else math.ceil(lots / 2)))
        runner_lots = int(tr.get("runner_lots") if tr.get("runner_lots") is not None else (lots - t1_lots))

        if tr.get("t1_booked") and lots > 0:
            blended_live_ltp = round_to_nse_tick(
                (t1_lots * float(tr["t1_premium"]) + runner_lots * live_ltp) / lots
            )
            pts_move = round(blended_live_ltp - entry_prem, 2)
        else:
            blended_live_ltp = live_ltp
            pts_move = raw_pts_move

        r_mult = round(pts_move / sl_pts, 2)
        gross_pnl = round(pts_move * qty, 2)

        max_slice_lots = max(1, MAX_NSE_EXECUTABLE_FREEZE_QTY // max(lot_size, 1))
        entry_legs = int(tr.get("entry_legs") or len(compute_iceberg_slices(lots, max_slice_lots)) or 1)
        t1_legs = int(
            tr.get("t1_legs")
            if tr.get("t1_legs") is not None
            else (len(compute_iceberg_slices(t1_lots, max_slice_lots)) if t1_lots > 0 else 0)
        )
        runner_legs = int(
            tr.get("runner_legs")
            if tr.get("runner_legs") is not None
            else (len(compute_iceberg_slices(runner_lots, max_slice_lots)) if runner_lots > 0 else 0)
        )
        t1_booked_flag = bool(tr.get("t1_booked", False))
        final_exit_legs = runner_legs if t1_booked_flag else entry_legs
        total_executed_legs = entry_legs + (t1_legs if t1_booked_flag else 0) + final_exit_legs

        charges_info = compute_nse_option_statutory_charges(
            entry_prem, blended_live_ltp, lots, lot_size, total_executed_legs=total_executed_legs
        )
        slippage_inr = float(tr.get("est_slippage_inr", 30.0))
        net_pnl = round(gross_pnl - charges_info["total_charges"] - slippage_inr, 2)

        tr["unrealized_pts"] = pts_move
        tr["unrealized_r"] = r_mult
        tr["gross_pnl_inr"] = gross_pnl
        tr["est_charges_inr"] = charges_info["total_charges"]
        tr["net_pnl_inr"] = net_pnl

        # Stage 2: Step-Trailing SL for every +0.5R above +1.5R (at +2.0R raw, lock +1.0R)
        # Stage 2B Doorstep Lock (+2.20R -> lock +1.60R, dynamically scaling for +3R+)
        if tr.get("t1_booked") and raw_r_mult >= 2.0:
            if raw_r_mult >= 2.20:
                step_r = max(1.60, (int(raw_r_mult * 2) / 2.0) - 1.0)
            else:
                step_r = 1.00

            step_sl = round_to_nse_tick(entry_prem + (step_r * sl_pts))
            if step_sl > float(tr["current_sl_premium"]):
                tr["current_sl_premium"] = step_sl
                if raw_r_mult >= 2.20 and not tr.get("doorstep_notified"):
                    tr["doorstep_notified"] = True
                    tr["stage2_notified"] = True
                    milestones_triggered.append("DOORSTEP_220_TRAIL")
                elif not tr.get("stage2_notified"):
                    tr["stage2_notified"] = True
                    milestones_triggered.append("STAGE_2_TRAIL")

        # Stage 4 (v5.6): T2 Reached (+2.50R) -> Uncapped Parabolic Velocity Ratchet
        # Locks minimum floor at (T2 - ₹1.50) and trails high_watermark by 0.20R
        if tr.get("t1_booked") and (live_ltp >= float(tr["t2_premium"]) or tr.get("t2_reached")):
            was_t2_reached = bool(tr.get("t2_reached", False))
            tr["t2_reached"] = True
            t2_floor_sl = round_to_nse_tick(float(tr["t2_premium"]) - 1.50)
            vel_trail_sl = round_to_nse_tick(float(tr["high_watermark"]) - (0.20 * sl_pts))
            new_t2_sl = max(t2_floor_sl, vel_trail_sl)
            if new_t2_sl > float(tr["current_sl_premium"]):
                tr["current_sl_premium"] = new_t2_sl
            if not was_t2_reached:
                milestones_triggered.append("STAGE_4_T2_VELOCITY")

        # Stage 3: 45-Minute Post-T1 Trailing SL Step-Up (45m <= hold_mins < 60m)
        stepup_mins = float(tr.get("post_t1_stepup_minutes", self.get_post_t1_stepup_minutes()))
        max_hold_mins = float(tr.get("post_t1_max_hold_minutes", self.get_post_t1_max_hold_minutes()))
        base_lock_r = float(tr.get("post_t1_lock_r", self.get_post_t1_lock_r()))
        instant_45m_exit = False

        if hold_mins >= stepup_mins:
            if tr.get("t1_booked"):
                # Base lock: +0.5R (from .env) | Bonus lock: +1.0R if live_ltp >= T1
                lock_r = max(1.0, base_lock_r) if live_ltp >= float(tr["t1_premium"]) else base_lock_r
                target_45m_sl = round_to_nse_tick(entry_prem + (lock_r * sl_pts))
                if target_45m_sl > float(tr["current_sl_premium"]):
                    if live_ltp <= target_45m_sl:
                        # Price already decayed below +0.5R at 45m mark -> Exit at actual live_ltp (No Guard 3 inflation)
                        instant_45m_exit = True
                    else:
                        was_45m = bool(tr.get("sl_45m_tightened", False))
                        tr["current_sl_premium"] = target_45m_sl
                        tr["sl_45m_tightened"] = True
                        if not was_45m:
                            milestones_triggered.append("STAGE_3_45M_LOCK")
            else:
                # Non-T1 survivor at 45m (stayed >= +0.5R since 20m): at least lock breakeven Entry + ₹2.0
                be_sl = round_to_nse_tick(entry_prem + 2.0)
                if live_ltp > be_sl and be_sl > float(tr["current_sl_premium"]):
                    tr["current_sl_premium"] = be_sl

        # Evaluate Exit Triggers in strict priority order
        exit_reason: Optional[str] = None
        if instant_45m_exit:
            exit_reason = "TIME_STOP_45MIN_POST_T1 (< +0.5R Decay Exit)"
        elif live_ltp <= float(tr["current_sl_premium"]):
            if tr.get("t2_reached"):
                exit_reason = "TARGET_2_HIT (+2.5R)"
            elif tr.get("sl_45m_tightened"):
                # Keeps "SL_HIT" contiguous so Guard 3 slippage cap remains 100% active!
                exit_reason = "TRAILED_45M_SL_HIT (+0.5R/+1.0R Lock)"
            elif tr.get("pre_t1_doorstep_active") and not tr.get("t1_booked"):
                locked_r = round((float(tr["current_sl_premium"]) - entry_prem) / sl_pts, 2)
                exit_reason = f"PRE_T1_SHIELD_SL_HIT (+{locked_r:.2f}R Doorstep Lock after +{peak_r_mult:.2f}R Peak)"
            elif tr.get("pre_t1_shield_active") and not tr.get("t1_booked"):
                locked_r = round((float(tr["current_sl_premium"]) - entry_prem) / sl_pts, 2)
                exit_reason = f"PRE_T1_SHIELD_SL_HIT (+{locked_r:.2f}R Lock after +{peak_r_mult:.2f}R Peak)"
            elif tr.get("stage1b0_shield_active") and not tr.get("t1_booked"):
                locked_r = round((float(tr["current_sl_premium"]) - entry_prem) / sl_pts, 2)
                exit_reason = f"PRE_T1_SHIELD_SL_HIT (+{locked_r:.2f}R Green Lock after +{peak_r_mult:.2f}R Peak)"
            elif tr.get("stage0b_shield_active") and float(tr["current_sl_premium"]) >= entry_prem and not tr.get("t1_booked"):
                locked_r = round((float(tr["current_sl_premium"]) - entry_prem) / sl_pts, 2)
                exit_reason = f"PRE_T1_SHIELD_SL_HIT (+{locked_r:.2f}R Breakeven Lock after +{peak_r_mult:.2f}R Peak)"
            elif tr.get("coiling_extension_active") and float(tr["current_sl_premium"]) >= entry_prem and not tr.get("t1_booked"):
                exit_reason = "TIME_STOP_20MIN (30m Coiling Breakeven SL_HIT)"
            else:
                exit_reason = "TRAILED_SL_HIT" if tr.get("t1_booked") else "INITIAL_SL_HIT"
        elif hold_mins >= max_hold_mins:
            # Universal 60m Hard Cap: No trade (T1 or non-T1) ever stays open past 60 minutes
            if tr.get("t2_reached"):
                exit_reason = "TARGET_2_HIT (+2.5R)"
            else:
                exit_reason = (
                    "TIME_EXIT_60MIN_POST_T1 (60m Max Hold)"
                    if tr.get("t1_booked")
                    else "TIME_EXIT_60MIN_MAX_HOLD (60m Hard Cap)"
                )
        elif hold_mins >= float(tr.get("time_stop_minutes", 20.0)) and raw_r_mult < 0.50 and not tr.get("t1_booked"):
            # v5.7 Fix 4 / v5.9: Bounded 20m -> 30m Coiling Extension with Mandatory SL Tightening & High-Peak Guard
            extended_now = False
            if not tr.get("coiling_extension_active") and hold_mins < 30.0:
                trig_upper = str(tr.get("trigger_type", "")).upper()
                is_pb_setup = "PULLBACK" in trig_upper
                spot_in_favor = (
                    (spot_ltp > entry_spot)
                    if opt_type == "CE"
                    else (0.0 < spot_ltp < entry_spot)
                )
                prior_auto = [
                    t for t in self._closed_trades if t.get("source") == "AUTO_QUANT_SIGNAL"
                ]
                is_wave_1 = (
                    not prior_auto
                    or str(prior_auto[0].get("opt_type", "")).upper() != opt_type
                )

                if peak_r_mult >= 0.38 and spot_in_favor and raw_r_mult >= -0.25:
                    new_coil_sl: Optional[float] = None
                    if peak_r_mult >= 0.70:
                        new_coil_sl = round_to_nse_tick(entry_prem + 1.50)
                    elif (is_pb_setup or is_wave_1) and raw_pts_move >= 4.0:
                        new_coil_sl = round_to_nse_tick(entry_prem + 1.50)
                    elif is_wave_1 and (-0.25 <= raw_r_mult < 0.50):
                        new_coil_sl = round_to_nse_tick(entry_prem - (0.35 * sl_pts))

                    if new_coil_sl is not None and live_ltp > new_coil_sl:
                        tr["coiling_extension_active"] = True
                        tr["time_stop_minutes"] = 30.0
                        if new_coil_sl > float(tr["current_sl_premium"]):
                            tr["current_sl_premium"] = new_coil_sl
                        milestones_triggered.append("COILING_30M_EXTENSION")
                        extended_now = True

            if not extended_now:
                exit_reason = "TIME_STOP_20MIN (< +0.5R Theta Protection)"
        elif now_dt.time() >= dtime(15, 15) and entry_dt.time() < dtime(15, 15):
            exit_reason = (
                "TARGET_2_HIT (+2.5R)"
                if tr.get("t2_reached")
                else "EOD_1515_MANDATORY_SQUAREOFF"
            )

        # Dispatch any milestones BEFORE evaluating exit_reason so same-tick milestones are never swallowed!
        if self.enable_notifications and tr.get("source") == "AUTO_QUANT_SIGNAL" and milestones_triggered:
            tr_snapshot = dict(tr)
            for ms_type in milestones_triggered:
                try:
                    dispatch_alpha_milestone_alert(tr_snapshot, ms_type)
                except Exception as e:
                    logger.warning("Alpha milestone alert dispatch error (%s): %s", ms_type, e)

        if exit_reason:
            self._close_open_trade_internal(exit_ltp=live_ltp, exit_reason=exit_reason, now_dt=now_dt)
        else:
            self._save_atomic()

    def close_open_trade_manual(
        self,
        current_eval: Optional[Dict[str, Any]] = None,
        reason: str = "MANUAL_USER_EXIT",
        now_dt: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        if now_dt is None:
            now_dt = datetime.now(IST)
        elif now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=IST)

        with self._lock:
            if not self._open_trade:
                return {
                    "status": "no_open_trade",
                    "message": "No open paper trade to close.",
                    "ledger": self.get_ledger_summary(),
                }
            if current_eval:
                self._update_open_trade_state(current_eval, now_dt)
            if self._open_trade:
                exit_ltp = float(self._open_trade.get("current_ltp", self._open_trade["entry_premium"]))
                self._close_open_trade_internal(exit_ltp=exit_ltp, exit_reason=reason, now_dt=now_dt)
            return {
                "status": "closed",
                "message": "Open paper trade closed and recorded in session ledger.",
                "ledger": self.get_ledger_summary(),
            }

    def _close_open_trade_internal(self, exit_ltp: float, exit_reason: str, now_dt: datetime) -> None:
        if not self._open_trade:
            return
        tr = self._open_trade
        entry_prem = float(tr["entry_premium"])
        sl_pts = max(float(tr["sl_points"]), 1.0)
        qty = int(tr["qty"])
        lots = int(tr["lots"])
        lot_size = int(tr["lot_size"])

        # GUARD 3: Bound SL fill price to realistic exchange slippage (No phantom -3.58R loss)
        bounded_exit_ltp = exit_ltp
        if "SL_HIT" in exit_reason or tr.get("t2_reached"):
            active_sl = float(tr.get("current_sl_premium", exit_ltp))
            # Cap maximum slippage on SL execution to 1.50 pts (30 NSE ticks buffer) below active SL
            min_sl_fill = round_to_nse_tick(max(active_sl - 1.50, 0.05))
            bounded_exit_ltp = max(exit_ltp, min_sl_fill)

        # Exact Lot-Weighted Closed Trade Blending (2:1 for 3-Lot trades across all post-T1 exits including T2!)
        t1_lots = int(tr.get("t1_lots") if tr.get("t1_lots") is not None else (0 if lots == 1 else math.ceil(lots / 2)))
        runner_lots = int(tr.get("runner_lots") if tr.get("runner_lots") is not None else (lots - t1_lots))

        if tr.get("t1_booked") and lots > 0:
            effective_exit = round_to_nse_tick(
                (t1_lots * float(tr["t1_premium"]) + runner_lots * bounded_exit_ltp) / lots
            )
        else:
            effective_exit = round_to_nse_tick(bounded_exit_ltp)

        max_slice_lots = max(1, MAX_NSE_EXECUTABLE_FREEZE_QTY // max(lot_size, 1))
        entry_legs = int(tr.get("entry_legs") or len(compute_iceberg_slices(lots, max_slice_lots)) or 1)
        t1_legs = int(
            tr.get("t1_legs")
            if tr.get("t1_legs") is not None
            else (len(compute_iceberg_slices(t1_lots, max_slice_lots)) if t1_lots > 0 else 0)
        )
        runner_legs = int(
            tr.get("runner_legs")
            if tr.get("runner_legs") is not None
            else (len(compute_iceberg_slices(runner_lots, max_slice_lots)) if runner_lots > 0 else 0)
        )
        t1_booked_flag = bool(tr.get("t1_booked", False))
        final_exit_legs = runner_legs if t1_booked_flag else entry_legs
        total_executed_legs = entry_legs + (t1_legs if t1_booked_flag else 0) + final_exit_legs

        pts_move = round(effective_exit - entry_prem, 2)
        r_mult = round(pts_move / sl_pts, 2)
        gross_pnl = round(pts_move * qty, 2)
        charges_info = compute_nse_option_statutory_charges(
            entry_prem, effective_exit, lots, lot_size, total_executed_legs=total_executed_legs
        )
        slippage_inr = float(tr.get("est_slippage_inr", 30.0))
        net_pnl = round(gross_pnl - charges_info["total_charges"] - slippage_inr, 2)

        closed_record = {
            **tr,
            "exit_time": now_dt.isoformat(),
            "exit_time_str": now_dt.strftime("%H:%M:%S IST"),
            "exit_spot": float(tr.get("current_spot") or tr.get("entry_spot") or 0.0),
            "best_spot": float(tr.get("best_spot") or tr.get("current_spot") or tr.get("entry_spot") or 0.0),
            "exit_premium": effective_exit,
            "raw_last_ltp": exit_ltp,
            "realized_pts": pts_move,
            "r_multiple": r_mult,
            "gross_pnl_inr": gross_pnl,
            "charges_inr": charges_info["total_charges"],
            "slippage_inr": slippage_inr,
            "net_pnl_inr": net_pnl,
            "exit_reason": exit_reason,
            "final_exit_legs": final_exit_legs,
            "total_executed_legs": total_executed_legs,
        }
        self._closed_trades.insert(0, closed_record)
        self._open_trade = None
        self._save_atomic()
        if self.enable_notifications and closed_record.get("source") == "AUTO_QUANT_SIGNAL":
            try:
                summary_stats = self.get_ledger_summary().get("stats")
                dispatch_alpha_exit_alert(closed_record, summary_stats)
            except Exception as e:
                logger.warning("Alpha exit alert dispatch error: %s", e)

    def reset_today_ledger(self) -> Dict[str, Any]:
        with self._lock:
            self._open_trade = None
            self._closed_trades = []
            self._save_atomic()
            return self.get_ledger_summary()

    def purge_trade_by_id(self, trade_id: str) -> Dict[str, Any]:
        """
        Purge a specific corrupted trade by ID and refresh metrics atomically.
        """
        with self._lock:
            self._closed_trades = [t for t in self._closed_trades if t.get("trade_id") != trade_id]
            if self._open_trade and self._open_trade.get("trade_id") == trade_id:
                self._open_trade = None
            self._save_atomic()
            return self.get_ledger_summary()

    def get_ledger_summary(self) -> Dict[str, Any]:
        with self._lock:
            total_closed = len(self._closed_trades)
            wins = sum(1 for t in self._closed_trades if float(t.get("net_pnl_inr", 0.0)) > 0)
            losses = total_closed - wins
            win_rate = round((wins / total_closed) * 100.0, 1) if total_closed > 0 else 0.0

            gross_pnl = round(sum(float(t.get("gross_pnl_inr", 0.0)) for t in self._closed_trades), 2)
            total_charges = round(
                sum(float(t.get("charges_inr", 0.0)) + float(t.get("slippage_inr", 0.0)) for t in self._closed_trades),
                2,
            )
            net_realized_pnl = round(sum(float(t.get("net_pnl_inr", 0.0)) for t in self._closed_trades), 2)
            total_r = round(sum(float(t.get("r_multiple", 0.0)) for t in self._closed_trades), 2)

            auto_trades = sum(1 for t in self._closed_trades if t.get("source") == "AUTO_QUANT_SIGNAL")
            force_trades = total_closed - auto_trades
            auto_wins = sum(
                1 for t in self._closed_trades
                if t.get("source") == "AUTO_QUANT_SIGNAL" and float(t.get("net_pnl_inr", 0.0)) > 0
            )
            auto_win_rate = round((auto_wins / auto_trades) * 100.0, 1) if auto_trades > 0 else 0.0

            unrealized_net = float(self._open_trade.get("net_pnl_inr", 0.0)) if self._open_trade else 0.0

            return {
                "session_date": self._session_date,
                "auto_trade_enabled": self._auto_trade_enabled,
                "kill_switch": self.get_kill_switch_status(),
                "open_trade": self._open_trade,
                "closed_trades": self._closed_trades,
                "entry_guard_blocked": self._last_guard_blocked,
                "entry_guard_reason": self._last_guard_reason,
                "stats": {
                    "total_closed": total_closed,
                    "wins": wins,
                    "losses": losses,
                    "win_rate_pct": win_rate,
                    "auto_trades": auto_trades,
                    "force_trades": force_trades,
                    "auto_win_rate_pct": auto_win_rate,
                    "gross_realized_pnl_inr": gross_pnl,
                    "total_charges_and_slippage_inr": total_charges,
                    "net_realized_pnl_inr": net_realized_pnl,
                    "unrealized_net_pnl_inr": round(unrealized_net, 2),
                    "combined_net_pnl_inr": round(net_realized_pnl + unrealized_net, 2),
                    "cum_r_multiple": total_r,
                },
            }

    def _compute_summary_from_records(
        self,
        session_date: str,
        closed_trades: List[Dict[str, Any]],
        open_trade: Optional[Dict[str, Any]] = None,
        auto_trade_enabled: bool = True,
        is_live_session: bool = False,
    ) -> Dict[str, Any]:
        """Pure helper to compute identical Module 5 ledger summary schema for live or historical sessions."""
        total_closed = len(closed_trades)
        wins = sum(1 for t in closed_trades if float(t.get("net_pnl_inr", 0.0)) > 0)
        losses = total_closed - wins
        win_rate = round((wins / total_closed) * 100.0, 1) if total_closed > 0 else 0.0

        gross_pnl = round(sum(float(t.get("gross_pnl_inr", 0.0)) for t in closed_trades), 2)
        total_charges = round(
            sum(float(t.get("charges_inr", 0.0)) + float(t.get("slippage_inr", 0.0)) for t in closed_trades),
            2,
        )
        net_realized_pnl = round(sum(float(t.get("net_pnl_inr", 0.0)) for t in closed_trades), 2)
        total_r = round(sum(float(t.get("r_multiple", 0.0)) for t in closed_trades), 2)

        auto_trades = sum(1 for t in closed_trades if t.get("source") == "AUTO_QUANT_SIGNAL")
        force_trades = total_closed - auto_trades
        auto_wins = sum(
            1 for t in closed_trades
            if t.get("source") == "AUTO_QUANT_SIGNAL" and float(t.get("net_pnl_inr", 0.0)) > 0
        )
        auto_win_rate = round((auto_wins / auto_trades) * 100.0, 1) if auto_trades > 0 else 0.0

        unrealized_net = float(open_trade.get("net_pnl_inr", 0.0)) if open_trade else 0.0

        if is_live_session:
            kill_switch_info = self.get_kill_switch_status()
            guard_blocked = self._last_guard_blocked
            guard_reason = self._last_guard_reason
        else:
            max_trades = self.get_max_trades_per_day()
            max_consec_losses = self.get_max_consecutive_losses()
            consec_losses = 0
            for t in closed_trades:
                if float(t.get("net_pnl_inr", 0.0)) < 0:
                    consec_losses += 1
                else:
                    break
            engaged = False
            reason = f"ARCHIVE VIEW ({session_date}) — Historical Session Record"
            if consec_losses >= max_consec_losses:
                engaged = True
                reason = f"ARCHIVE ({session_date}): Kill-Switch Engaged ({consec_losses} Consecutive Losses)"
            elif total_closed >= max_trades:
                engaged = True
                reason = f"ARCHIVE ({session_date}): Max Daily Trades Reached ({total_closed}/{max_trades})"
            kill_switch_info = {
                "kill_switch_engaged": engaged,
                "reason": reason,
                "trades_taken_today": total_closed,
                "max_trades_per_day": max_trades,
                "consecutive_losses": consec_losses,
                "max_consecutive_losses": max_consec_losses,
                "realized_net_pnl_inr": net_realized_pnl,
            }
            guard_blocked = False
            guard_reason = None

        return {
            "session_date": session_date,
            "auto_trade_enabled": auto_trade_enabled,
            "kill_switch": kill_switch_info,
            "open_trade": open_trade,
            "closed_trades": closed_trades,
            "entry_guard_blocked": guard_blocked,
            "entry_guard_reason": guard_reason,
            "stats": {
                "total_closed": total_closed,
                "wins": wins,
                "losses": losses,
                "win_rate_pct": win_rate,
                "auto_trades": auto_trades,
                "force_trades": force_trades,
                "auto_win_rate_pct": auto_win_rate,
                "gross_realized_pnl_inr": gross_pnl,
                "total_charges_and_slippage_inr": total_charges,
                "net_realized_pnl_inr": net_realized_pnl,
                "unrealized_net_pnl_inr": round(unrealized_net, 2),
                "combined_net_pnl_inr": round(net_realized_pnl + unrealized_net, 2),
                "cum_r_multiple": total_r,
            },
        }

    def get_historical_ledger_summary(self, session_date: str) -> Dict[str, Any]:
        """
        Read-only fetch of any historical session ledger JSON without mutating live engine state.
        """
        import re

        clean_date = (session_date or "").strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", clean_date):
            raise ValueError(f"Invalid session_date format: {clean_date}. Expected YYYY-MM-DD.")

        with self._lock:
            self._check_rollover()
            if clean_date == self._session_date:
                return self.get_ledger_summary()

        fpath = self._ledger_file(clean_date)
        if not fpath.exists():
            raise FileNotFoundError(f"No ledger file found for session_date={clean_date}")

        data = json.loads(fpath.read_text(encoding="utf-8"))
        closed_trades = data.get("closed_trades") or []
        auto_enabled = bool(data.get("auto_trade_enabled", True))
        return self._compute_summary_from_records(
            session_date=clean_date,
            closed_trades=closed_trades,
            open_trade=None,
            auto_trade_enabled=auto_enabled,
            is_live_session=False,
        )

    def list_available_sessions(
        self,
        capital_inr: float = 2500000.0,
        from_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List all real trading sessions (plus live today_str always at Index 0 even on weekends/0-trade mornings)
        with per-session ROI % and cumulative multi-day scorecard (optionally filtered from `from_date` onwards).
        Excludes future dummy test files (date_str > today_str, e.g. 2099-*) and empty past files (date_str < today_str with 0 trades).
        """
        import re

        eff_capital = float(capital_inr) if (capital_inr and float(capital_inr) > 0) else 2500000.0
        clean_from_date: Optional[str] = None
        if from_date and isinstance(from_date, str):
            candidate = from_date.strip()
            if re.match(r"^\d{4}-\d{2}-\d{2}$", candidate):
                clean_from_date = candidate

        with self._lock:
            self._check_rollover()
            today_str = self._session_date
            live_summary = self.get_ledger_summary()

        sessions_map: Dict[str, Dict[str, Any]] = {}

        # Catch #1: Always include live today_str (even on Saturday/Sunday or 09:15 AM with 0 trades)
        live_stats = live_summary["stats"]
        live_net = float(live_stats["net_realized_pnl_inr"])
        sessions_map[today_str] = {
            "session_date": today_str,
            "is_today": True,
            "total_closed": int(live_stats["total_closed"]),
            "wins": int(live_stats["wins"]),
            "losses": int(live_stats["losses"]),
            "win_rate_pct": float(live_stats["win_rate_pct"]),
            "auto_trades": int(live_stats["auto_trades"]),
            "gross_realized_pnl_inr": float(live_stats["gross_realized_pnl_inr"]),
            "total_charges_and_slippage_inr": float(live_stats["total_charges_and_slippage_inr"]),
            "net_realized_pnl_inr": live_net,
            "roi_pct": round((live_net / eff_capital) * 100.0, 2),
            "cum_r_multiple": float(live_stats["cum_r_multiple"]),
        }

        if LEDGER_DIR.exists():
            for fpath in LEDGER_DIR.glob("ledger_*.json"):
                m = re.match(r"^ledger_(\d{4}-\d{2}-\d{2})\.json$", fpath.name)
                if not m:
                    continue
                d_str = m.group(1)
                # Skip future test dates (e.g. 2099-01-01, 2099-01-02) and today_str (already added from live state)
                if d_str >= today_str:
                    continue
                try:
                    raw = json.loads(fpath.read_text(encoding="utf-8"))
                    c_trades = raw.get("closed_trades") or []
                    # Skip past dates with 0 closed trades (e.g. 2026-10-28)
                    if len(c_trades) == 0:
                        continue
                    summary = self._compute_summary_from_records(
                        session_date=d_str,
                        closed_trades=c_trades,
                        open_trade=None,
                        auto_trade_enabled=bool(raw.get("auto_trade_enabled", True)),
                        is_live_session=False,
                    )
                    st = summary["stats"]
                    net_pnl = float(st["net_realized_pnl_inr"])
                    sessions_map[d_str] = {
                        "session_date": d_str,
                        "is_today": False,
                        "total_closed": int(st["total_closed"]),
                        "wins": int(st["wins"]),
                        "losses": int(st["losses"]),
                        "win_rate_pct": float(st["win_rate_pct"]),
                        "auto_trades": int(st["auto_trades"]),
                        "gross_realized_pnl_inr": float(st["gross_realized_pnl_inr"]),
                        "total_charges_and_slippage_inr": float(st["total_charges_and_slippage_inr"]),
                        "net_realized_pnl_inr": net_pnl,
                        "roi_pct": round((net_pnl / eff_capital) * 100.0, 2),
                        "cum_r_multiple": float(st["cum_r_multiple"]),
                    }
                except Exception as e:
                    logger.warning("Skipping unreadable historical ledger %s: %s", fpath, e)

        sorted_sessions = [sessions_map[k] for k in sorted(sessions_map.keys(), reverse=True)]

        # Cumulative scorecard across all sessions that have at least 1 closed trade (filtered by from_date if provided)
        traded_sessions = [
            s
            for s in sorted_sessions
            if s["total_closed"] > 0 and (clean_from_date is None or s["session_date"] >= clean_from_date)
        ]
        cum_trades = sum(s["total_closed"] for s in traded_sessions)
        cum_wins = sum(s["wins"] for s in traded_sessions)
        cum_losses = sum(s["losses"] for s in traded_sessions)
        cum_wr = round((cum_wins / cum_trades) * 100.0, 1) if cum_trades > 0 else 0.0
        cum_gross = round(sum(s["gross_realized_pnl_inr"] for s in traded_sessions), 2)
        cum_charges = round(sum(s["total_charges_and_slippage_inr"] for s in traded_sessions), 2)
        cum_net = round(sum(s["net_realized_pnl_inr"] for s in traded_sessions), 2)
        cum_roi = round((cum_net / eff_capital) * 100.0, 2)
        cum_r = round(sum(s["cum_r_multiple"] for s in traded_sessions), 2)

        return {
            "status": "ok",
            "live_session_date": today_str,
            "capital_inr": eff_capital,
            "sessions": sorted_sessions,
            "cumulative": {
                "from_date": clean_from_date,
                "total_sessions": len(traded_sessions),
                "total_trades": cum_trades,
                "wins": cum_wins,
                "losses": cum_losses,
                "win_rate_pct": cum_wr,
                "gross_realized_pnl_inr": cum_gross,
                "total_charges_and_slippage_inr": cum_charges,
                "net_realized_pnl_inr": cum_net,
                "cumulative_roi_pct": cum_roi,
                "cum_r_multiple": cum_r,
            },
        }


GLOBAL_NIFTY_OPTIONS_LEDGER = NiftyOptionsPaperLedger()
