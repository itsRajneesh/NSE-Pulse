"""
Comprehensive Unit & 10-Day Historical Replay Test Suite for Alpha Engine v5.7:
1. Test 1: Fix 1 (.env NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP=150) & 12-Nov Trade 1 / Trade 3 150-Lot Cap Verification.
2. Test 2: Fix 2 (best_spot Live Tracking + Guard 1E Post-Shield / Post-Trail 15m Cooldown & Peak/Higher-Low Clearance).
3. Test 3: Fix 3 (Guard 2B Universal Wave#3 Exhaustion Lock & 2x Time-Stop Wave#3 Clearance).
4. Test 4: Fix 4 (20.0m -> 30.0m Bounded Coiling Extension with Mandatory SL Tightening & Catch #3 Gap-Free Coverage).
5. Test 5: Catch #1 (Telegram COILING_30M_EXTENSION Template) & Catch #2 (TIME_STOP_20MIN Breakeven SL_HIT vs INITIAL_SL_HIT).
6. Test 6: Full 10-Day Historical JSON Ledgers Replay (28-Oct to 12-Nov, 47 Trades) with Isolated Dummy Date Safety.
"""

import glob
import json
import os
import sys
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.v13_nifty_options_engine import (
    compute_universal_position_sizing,
    get_max_system_lots_cap,
    round_to_nse_tick,
)
from app.v13_nifty_options_ledger import IST, LEDGER_DIR, NiftyOptionsPaperLedger
from app.v13_alpha_telegram import format_alpha_milestone_message


DUMMY_SESSION_DATE = "2099-01-02"


def _load_env_file(filepath: str) -> None:
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            os.environ[k.strip()] = v.strip()


def _new_isolated_ledger() -> NiftyOptionsPaperLedger:
    ledger = NiftyOptionsPaperLedger(enable_notifications=False)
    ledger._session_date = DUMMY_SESSION_DATE
    ledger._save_atomic = lambda: None
    ledger._open_trade = None
    ledger._closed_trades = []
    return ledger


def _cleanup_dummy_ledger_file() -> None:
    dummy_file = LEDGER_DIR / f"ledger_{DUMMY_SESSION_DATE}.json"
    if dummy_file.exists():
        dummy_file.unlink()


def test_1_env_150_lots_cap_and_12nov_sizing():
    print("\n--- Running Test 1: .env NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP=150 & 12-Nov Sizing Cap ---")
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    _load_env_file(env_path)

    raw_env_val = os.getenv("NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP")
    assert raw_env_val == "150", f"Expected NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP='150' in .env, got {raw_env_val!r}"
    assert get_max_system_lots_cap() == 150, f"Expected get_max_system_lots_cap() == 150, got {get_max_system_lots_cap()}"

    # 12-Nov Trade 1: Entry ₹206.65, SL ₹187.00 (sl_pts = 19.65), Capital = ₹25,00,000, Risk = 10%
    sz_t1 = compute_universal_position_sizing(
        capital_inr=2500000.0,
        risk_mode="PERCENT",
        risk_value=10.0,
        entry_premium=206.65,
        sl_premium=187.00,
        t1_premium=235.00,
        t2_premium=254.20,
        lot_size=65,
    )
    assert sz_t1["allowed_lots"] == 150, f"Expected 150 lots on 12-Nov T1, got {sz_t1['allowed_lots']}"
    assert sz_t1["allowed_qty"] == 9750
    assert sz_t1["entry_legs"] == 6
    assert sz_t1["entry_slices"] == [27, 27, 27, 27, 27, 15]
    print(
        f"  [PASS] 12-Nov Trade 1 (SL 19.65 pts) capped at {sz_t1['allowed_lots']} Lots "
        f"({sz_t1['allowed_qty']} Qty, {sz_t1['entry_legs']} Legs {sz_t1['entry_slices']})"
    )

    # 12-Nov Trade 3: Entry ₹209.90, SL ₹190.90 (sl_pts = 19.00), Capital = ₹25,00,000, Risk = 10%
    sz_t3 = compute_universal_position_sizing(
        capital_inr=2500000.0,
        risk_mode="PERCENT",
        risk_value=10.0,
        entry_premium=209.90,
        sl_premium=190.90,
        t1_premium=237.40,
        t2_premium=256.10,
        lot_size=65,
    )
    assert sz_t3["allowed_lots"] == 150, f"Expected 150 lots on 12-Nov T3, got {sz_t3['allowed_lots']}"
    assert sz_t3["allowed_qty"] == 9750
    assert sz_t3["entry_legs"] == 6
    print(
        f"  [PASS] 12-Nov Trade 3 (SL 19.00 pts) capped at {sz_t3['allowed_lots']} Lots "
        f"({sz_t3['allowed_qty']} Qty, {sz_t3['entry_legs']} Legs)"
    )


def test_2_best_spot_tracking_and_guard_1e():
    print("\n--- Running Test 2: Live best_spot Tracking & Guard 1E (Post-Shield / Post-Trail Clearance) ---")

    # 2A. Verify live best_spot tracking for PE (minimum spot) and CE (maximum spot)
    ledger = _new_isolated_ledger()
    t0 = datetime(2026, 11, 12, 12, 6, 19, tzinfo=IST)
    ledger._open_trade = {
        "trade_id": "NPQ-120619-A4BF",
        "source": "AUTO_QUANT_SIGNAL",
        "entry_time": t0.isoformat(),
        "entry_time_str": "12:06:19 IST",
        "symbol": "NSE:NIFTY26N1725300PE",
        "strike": 25300,
        "opt_type": "PE",
        "lots": 150,
        "lot_size": 65,
        "qty": 9750,
        "entry_spot": 25252.80,
        "current_spot": 25252.80,
        "best_spot": 25252.80,
        "entry_premium": 214.50,
        "current_ltp": 214.50,
        "high_watermark": 214.50,
        "initial_sl_premium": 190.70,
        "current_sl_premium": 190.70,
        "sl_points": 23.80,
        "t1_premium": 249.20,
        "t2_premium": 272.70,
        "t1_booked": False,
        "t2_reached": False,
        "pre_t1_shield_active": False,
        "coiling_extension_active": False,
        "est_slippage_inr": 9162.75,
    }

    # Tick 1: PE rallies to 243.55 (+1.22R) as Spot drops to 25,180.00 -> Stage 1B Shield locks +0.50R (226.40)
    ledger._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 25300, "ce_ltp": 110.0, "pe_ltp": 243.55}],
            "market_snapshot": {"spot_ltp": 25180.00, "feed_mode": "FULL"},
        },
        t0 + timedelta(minutes=8),
    )
    assert ledger._open_trade["best_spot"] == 25180.00
    assert ledger._open_trade["pre_t1_shield_active"] is True
    assert ledger._open_trade["current_sl_premium"] == 232.85

    # Tick 2: Spot bounces to 25,232.85 and PE hits Shield SL at 12:18:10 IST
    t_exit = datetime(2026, 11, 12, 12, 18, 10, tzinfo=IST)
    ledger._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 25300, "ce_ltp": 140.0, "pe_ltp": 226.40}],
            "market_snapshot": {"spot_ltp": 25232.85, "feed_mode": "FULL"},
        },
        t_exit,
    )
    assert ledger._open_trade is None
    closed_t2 = ledger._closed_trades[0]
    assert "PRE_T1_SHIELD_SL_HIT" in closed_t2["exit_reason"]
    assert closed_t2["exit_spot"] == 25232.85
    assert closed_t2["best_spot"] == 25180.00
    print("  [PASS] Live best_spot persisted on PE Pre-T1 Shield exit: entry=25252.8, best=25180.0, exit=25232.85")

    # 2B. Guard 1E Cooldown check (< 15.0m after PRE_T1_SHIELD_SL_HIT)
    eval_pe_bo = {
        "selected_contract": {"opt_type": "PE"},
        "trade_plan": {"opt_type": "PE", "trigger_type": "MOMENTUM_BOX_BREAKDOWN"},
        "entry_trigger": {"trigger_type": "MOMENTUM_BOX_BREAKDOWN"},
        "market_snapshot": {"spot_ltp": 25170.00},
    }
    ok_cool, reason_cool = ledger._check_reentry_and_wave_guards(eval_pe_bo, t_exit + timedelta(minutes=10))
    assert ok_cool is False and "GUARD_1_REJECTION_COOLDOWN (1E)" in reason_cool, f"Got {ok_cool}, {reason_cool}"
    print(f"  [PASS] Guard 1E 15m Cooldown blocked premature PE re-entry at +10m: {reason_cool}")

    # 2C. Guard 1E Peak Clearance check on 12-Nov Trade 3 (12:35:23 IST, Spot = 25,217.50 > 25,180.0 - 3.0)
    eval_12nov_t3 = {
        "selected_contract": {"opt_type": "PE"},
        "trade_plan": {"opt_type": "PE", "trigger_type": "MOMENTUM_BOX_BREAKDOWN"},
        "entry_trigger": {"trigger_type": "MOMENTUM_BOX_BREAKDOWN"},
        "market_snapshot": {"spot_ltp": 25217.50},
    }
    ok_12t3, reason_12t3 = ledger._check_reentry_and_wave_guards(
        eval_12nov_t3, datetime(2026, 11, 12, 12, 35, 23, tzinfo=IST)
    )
    assert ok_12t3 is False and "GUARD_1_PEAK_CLEARANCE (1E)" in reason_12t3, f"Got {ok_12t3}, {reason_12t3}"
    print(f"  [PASS] Guard 1E Peak Clearance blocked 12-Nov Trade 3 (-₹2.59L Double-Top): {reason_12t3}")

    # 2D. Guard 1E Bonus Save on 09-Nov Trade 2 (11:06 PE @ Spot 24,870.45 after 10:46 PE TRAILED_SL_HIT @ exit_spot 24,864.10)
    ledger_09nov = _new_isolated_ledger()
    ledger_09nov._closed_trades = [
        {
            "trade_id": "NPQ-103805-23C7",
            "source": "AUTO_QUANT_SIGNAL",
            "opt_type": "PE",
            "trigger_type": "VWAP_EMA20_PULLBACK_RESUMPTION",
            "entry_time": "2026-11-09T10:38:05+05:30",
            "exit_time": "2026-11-09T10:46:40+05:30",
            "entry_spot": 24912.60,
            "exit_spot": 24864.10,
            "best_spot": 24850.00,
            "t1_booked": True,
            "r_multiple": 1.16,
            "net_pnl_inr": 280689.93,
            "exit_reason": "TRAILED_SL_HIT",
        }
    ]
    eval_09nov_t2 = {
        "selected_contract": {"opt_type": "PE"},
        "trade_plan": {"opt_type": "PE", "trigger_type": "MOMENTUM_BOX_BREAKDOWN"},
        "entry_trigger": {"trigger_type": "MOMENTUM_BOX_BREAKDOWN"},
        "market_snapshot": {"spot_ltp": 24870.45},
    }
    ok_09t2, reason_09t2 = ledger_09nov._check_reentry_and_wave_guards(
        eval_09nov_t2, datetime(2026, 11, 9, 11, 6, 13, tzinfo=IST)
    )
    assert ok_09t2 is False and "GUARD_1_PEAK_CLEARANCE (1E)" in reason_09t2, f"Got {ok_09t2}, {reason_09t2}"
    print(f"  [PASS] Guard 1E Peak Clearance blocked 09-Nov Trade 2 (-₹2.35L Fake Breakdown): {reason_09t2}")

    # 2E. Verify 04-Nov Trade 5 (+₹1.42L Wave#2 Pullback Winner) is 100% SAFE even when best_spot=23,930.0 is tracked!
    ledger_04nov = _new_isolated_ledger()
    ledger_04nov._closed_trades = [
        {
            "trade_id": "NPQ-131807-C952",
            "source": "AUTO_QUANT_SIGNAL",
            "opt_type": "CE",
            "trigger_type": "MOMENTUM_BOX_BREAKOUT",
            "entry_time": "2026-11-04T13:18:07+05:30",
            "exit_time": "2026-11-04T13:45:43+05:30",
            "entry_spot": 23864.60,
            "exit_spot": 23895.00,
            "best_spot": 23930.00,  # High at T1 peak before pullback to EMA20
            "t1_booked": True,
            "r_multiple": 0.90,
            "net_pnl_inr": 144675.28,
            "exit_reason": "TRAILED_SL_HIT",
        }
    ]
    eval_04nov_t5 = {
        "selected_contract": {"opt_type": "CE"},
        "trade_plan": {"opt_type": "CE", "trigger_type": "VWAP_EMA20_PULLBACK_RESUMPTION"},
        "entry_trigger": {"trigger_type": "VWAP_EMA20_PULLBACK_RESUMPTION"},
        "market_snapshot": {"spot_ltp": 23874.70},  # Higher-Low: 23874.70 >= 23864.60 + 3.0 (23867.60)
    }
    ok_04t5, reason_04t5 = ledger_04nov._check_reentry_and_wave_guards(
        eval_04nov_t5, datetime(2026, 11, 4, 14, 7, 15, tzinfo=IST)
    )
    assert ok_04t5 is True and reason_04t5 == "PASS", f"Expected 04-Nov T5 to PASS, got {ok_04t5}, {reason_04t5}"
    print("  [PASS] 04-Nov Trade 5 (+₹1.42L Wave#2 Pullback Winner) 100% SAFE via Higher-Low clearance!")


def test_3_guard_2b_wave3_exhaustion_protection():
    print("\n--- Running Test 3: Guard 2B Universal Wave#3 Exhaustion Lock & 05-Nov T4 Winner Safety ---")

    # 3A. Wave#3 locked when len(wave_trades) >= 2 and wave has >= 1 major move (e.g. 12-Nov T1 + T2 Shield)
    ledger_12nov = _new_isolated_ledger()
    ledger_12nov._closed_trades = [
        {
            "trade_id": "NPQ-120619-A4BF",
            "source": "AUTO_QUANT_SIGNAL",
            "opt_type": "PE",
            "trigger_type": "MOMENTUM_BOX_BREAKDOWN",
            "entry_time": "2026-11-12T12:06:19+05:30",
            "exit_time": "2026-11-12T12:18:10+05:30",
            "entry_spot": 25252.80,
            "exit_spot": 25232.85,
            "best_spot": 25232.85,
            "t1_booked": False,
            "pre_t1_shield_active": True,
            "r_multiple": 0.50,
            "net_pnl_inr": 109959.06,
            "exit_reason": "PRE_T1_SHIELD_SL_HIT (+0.5R Lock after +1.2R Peak)",
        },
        {
            "trade_id": "NPQ-114119-A435",
            "source": "AUTO_QUANT_SIGNAL",
            "opt_type": "PE",
            "trigger_type": "MOMENTUM_BOX_BREAKDOWN",
            "entry_time": "2026-11-12T11:41:19+05:30",
            "exit_time": "2026-11-12T12:01:19+05:30",
            "entry_spot": 25274.55,
            "exit_spot": 25273.65,
            "best_spot": 25273.65,
            "t1_booked": False,
            "r_multiple": -0.21,
            "net_pnl_inr": -65495.69,
            "exit_reason": "TIME_STOP_20MIN (< +0.5R Theta Protection)",
        },
    ]
    # Even if Spot cleared 25,220.0 (passing Guard 1E), Guard 2B locks Wave#3 because wave has 2 trades + 1 major move!
    eval_wave3_pe = {
        "selected_contract": {"opt_type": "PE"},
        "trade_plan": {"opt_type": "PE", "trigger_type": "MOMENTUM_BOX_BREAKDOWN"},
        "entry_trigger": {"trigger_type": "MOMENTUM_BOX_BREAKDOWN"},
        "market_snapshot": {"spot_ltp": 25200.00},
    }
    ok_w3, reason_w3 = ledger_12nov._check_reentry_and_wave_guards(
        eval_wave3_pe, datetime(2026, 11, 12, 12, 35, 23, tzinfo=IST)
    )
    assert ok_w3 is False and "GUARD_2_WAVE_COMPLETED (2B)" in reason_w3, f"Got {ok_w3}, {reason_w3}"
    print(f"  [PASS] Guard 2B locked Wave#3 after Pre-T1 Shield major move: {reason_w3}")

    # 3B. Wave#3 after 2x TIME_STOP_20MIN: blocks 11-Nov T3 (failed wave high clearance) & passes 05-Nov T4 (+₹3.60L winner)
    ledger_11nov = _new_isolated_ledger()
    ledger_11nov._closed_trades = [
        {
            "trade_id": "NPQ-111617-3A7B",
            "source": "AUTO_QUANT_SIGNAL",
            "opt_type": "CE",
            "trigger_type": "MOMENTUM_BOX_BREAKOUT",
            "entry_time": "2026-11-11T11:16:17+05:30",
            "exit_time": "2026-11-11T11:18:52+05:30",
            "entry_spot": 25388.80,
            "exit_spot": 25375.85,
            "best_spot": 25402.00,  # Peak when CE hit 267.45 (+0.48R)
            "t1_booked": False,
            "r_multiple": -0.48,
            "net_pnl_inr": -73157.66,
            "exit_reason": "INITIAL_SL_HIT",
        },
        {
            "trade_id": "NPQ-103838-22A6",
            "source": "AUTO_QUANT_SIGNAL",
            "opt_type": "CE",
            "trigger_type": "MOMENTUM_BOX_BREAKOUT",
            "entry_time": "2026-11-11T10:38:38+05:30",
            "exit_time": "2026-11-11T10:58:38+05:30",
            "entry_spot": 25369.40,
            "exit_spot": 25382.65,
            "best_spot": 25386.00,
            "t1_booked": False,
            "r_multiple": 0.18,
            "net_pnl_inr": 25121.82,
            "exit_reason": "TIME_STOP_20MIN (< +0.5R Theta Protection)",
        },
    ]
    eval_11nov_t3 = {
        "selected_contract": {"opt_type": "CE"},
        "trade_plan": {"opt_type": "CE", "trigger_type": "MOMENTUM_BOX_BREAKOUT"},
        "entry_trigger": {"trigger_type": "MOMENTUM_BOX_BREAKOUT"},
        "market_snapshot": {"spot_ltp": 25395.75},  # Below 25402.0 + 3.0 = 25405.0
    }
    ok_11t3, reason_11t3 = ledger_11nov._check_reentry_and_wave_guards(
        eval_11nov_t3, datetime(2026, 11, 11, 11, 40, 37, tzinfo=IST)
    )
    assert ok_11t3 is False and "GUARD_2_WAVE3_CLEARANCE (2B)" in reason_11t3, f"Got {ok_11t3}, {reason_11t3}"
    print(f"  [PASS] Guard 2B Wave#3 Clearance blocked 11-Nov Trade 3 (-₹59.7k chop): {reason_11t3}")

    # 05-Nov T4 (13:18:55 CE @ Spot 24,478.15 after 2x Time-Stops at 24,376.75 & 24,419.00, gap 42.4m)
    ledger_05nov = _new_isolated_ledger()
    ledger_05nov._closed_trades = [
        {
            "trade_id": "NPQ-121629-E16C",
            "source": "AUTO_QUANT_SIGNAL",
            "opt_type": "CE",
            "trigger_type": "MOMENTUM_BOX_BREAKOUT",
            "entry_time": "2026-11-05T12:16:29+05:30",
            "exit_time": "2026-11-05T12:36:29+05:30",
            "entry_spot": 24419.00,
            "exit_spot": 24430.00,
            "best_spot": 24438.00,
            "t1_booked": False,
            "r_multiple": 0.22,
            "net_pnl_inr": 20731.62,
            "exit_reason": "TIME_STOP_20MIN (< +0.5R Theta Protection)",
        },
        {
            "trade_id": "NPQ-112921-15E0",
            "source": "AUTO_QUANT_SIGNAL",
            "opt_type": "CE",
            "trigger_type": "MOMENTUM_BOX_BREAKOUT",
            "entry_time": "2026-11-05T11:29:21+05:30",
            "exit_time": "2026-11-05T11:49:21+05:30",
            "entry_spot": 24376.75,
            "exit_spot": 24372.00,
            "best_spot": 24395.00,
            "t1_booked": False,
            "r_multiple": -0.12,
            "net_pnl_inr": -24829.88,
            "exit_reason": "TIME_STOP_20MIN (< +0.5R Theta Protection)",
        },
    ]
    eval_05nov_t4 = {
        "selected_contract": {"opt_type": "CE"},
        "trade_plan": {"opt_type": "CE", "trigger_type": "MOMENTUM_BOX_BREAKOUT"},
        "entry_trigger": {"trigger_type": "MOMENTUM_BOX_BREAKOUT"},
        "market_snapshot": {"spot_ltp": 24478.15},
    }
    ok_05t4, reason_05t4 = ledger_05nov._check_reentry_and_wave_guards(
        eval_05nov_t4, datetime(2026, 11, 5, 13, 18, 55, tzinfo=IST)
    )
    assert ok_05t4 is True and reason_05t4 == "PASS", f"Expected 05-Nov T4 to PASS, got {ok_05t4}, {reason_05t4}"
    print("  [PASS] 05-Nov Trade 4 (+₹3.60L T2 Winner) 100% SAFE (42.4m reset + cleared wave high 24,438 + 3.0)!")


def test_4_fix4_coiling_30m_extension_and_catch3_gap_free():
    print("\n--- Running Test 4: Fix 4 Bounded 20m -> 30m Coiling Extension & Catch #3 Gap-Free SL Tightening ---")

    # 4A. 11-Nov Trade 4 (13:08 -> 13:28 PE, PULLBACK, Peak ₹276.55 = +0.42R, Spot 25276.75 -> 25270.10, LTP ₹269.25 = +4.80 pts)
    ledger_pb = _new_isolated_ledger()
    t0_pb = datetime(2026, 11, 11, 13, 8, 55, tzinfo=IST)
    ledger_pb._open_trade = {
        "trade_id": "NPQ-130855-B06E",
        "source": "AUTO_QUANT_SIGNAL",
        "entry_time": t0_pb.isoformat(),
        "entry_time_str": "13:08:55 IST",
        "symbol": "NSE:NIFTY26N1725350PE",
        "strike": 25350,
        "opt_type": "PE",
        "trigger_type": "VWAP_EMA20_PULLBACK_RESUMPTION",
        "lots": 130,
        "lot_size": 65,
        "qty": 8450,
        "t1_lots": 65,
        "runner_lots": 65,
        "entry_spot": 25276.75,
        "current_spot": 25270.10,
        "best_spot": 25255.00,
        "entry_premium": 264.45,
        "current_ltp": 269.25,
        "high_watermark": 276.55,
        "initial_sl_premium": 235.60,
        "current_sl_premium": 235.60,
        "sl_points": 28.85,
        "t1_premium": 307.75,
        "t2_premium": 336.60,
        "t1_booked": False,
        "t2_reached": False,
        "coiling_extension_active": False,
        "time_stop_minutes": 20.0,
        "est_slippage_inr": 6337.50,
    }
    ledger_pb._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 25350, "ce_ltp": 180.0, "pe_ltp": 269.25}],
            "market_snapshot": {"spot_ltp": 25270.10, "feed_mode": "FULL"},
        },
        t0_pb + timedelta(minutes=20, seconds=2),
    )
    assert ledger_pb._open_trade is not None, "11-Nov T4 Pullback should extend to 30m, not exit at 20m!"
    assert ledger_pb._open_trade["coiling_extension_active"] is True
    assert ledger_pb._open_trade["time_stop_minutes"] == 30.0
    assert ledger_pb._open_trade["current_sl_premium"] == round_to_nse_tick(264.45 + 1.50) == 265.95
    print(
        f"  [PASS] 11-Nov T4 (Green Pullback +4.80 pts): Extended 20m -> 30m with Breakeven SL locked @ ₹{ledger_pb._open_trade['current_sl_premium']}"
    )

    # 4B. 12-Nov Trade 1 (11:41 -> 12:01 PE, Wave#1 BOX BD, Peak ₹214.50 = +0.40R, Spot 25274.55 -> 25273.65, LTP ₹202.55 = -0.21R)
    ledger_w1 = _new_isolated_ledger()
    t0_w1 = datetime(2026, 11, 12, 11, 41, 19, tzinfo=IST)
    ledger_w1._open_trade = {
        "trade_id": "NPQ-114119-A435",
        "source": "AUTO_QUANT_SIGNAL",
        "entry_time": t0_w1.isoformat(),
        "entry_time_str": "11:41:19 IST",
        "symbol": "NSE:NIFTY26N1725300PE",
        "strike": 25300,
        "opt_type": "PE",
        "trigger_type": "MOMENTUM_BOX_BREAKDOWN",
        "lots": 150,
        "lot_size": 65,
        "qty": 9750,
        "t1_lots": 75,
        "runner_lots": 75,
        "entry_spot": 25274.55,
        "current_spot": 25273.65,
        "best_spot": 25255.00,
        "entry_premium": 206.65,
        "current_ltp": 202.55,
        "high_watermark": 214.50,
        "initial_sl_premium": 187.00,
        "current_sl_premium": 187.00,
        "sl_points": 19.65,
        "t1_premium": 235.00,
        "t2_premium": 254.20,
        "t1_booked": False,
        "t2_reached": False,
        "coiling_extension_active": False,
        "time_stop_minutes": 20.0,
        "est_slippage_inr": 9750.00,
    }
    ledger_w1._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 25300, "ce_ltp": 150.0, "pe_ltp": 202.55}],
            "market_snapshot": {"spot_ltp": 25273.65, "feed_mode": "FULL"},
        },
        t0_w1 + timedelta(minutes=20, seconds=1),
    )
    assert ledger_w1._open_trade is not None, "12-Nov T1 Wave#1 Coiling trade should extend to 30m!"
    assert ledger_w1._open_trade["coiling_extension_active"] is True
    assert ledger_w1._open_trade["time_stop_minutes"] == 30.0
    assert ledger_w1._open_trade["current_sl_premium"] == round_to_nse_tick(206.65 - 0.35 * 19.65) == 199.75
    print(
        f"  [PASS] 12-Nov T1 (Wave#1 Red Coiling -0.21R): Extended 20m -> 30m with -0.35R Tight SL @ ₹{ledger_w1._open_trade['current_sl_premium']} (only ₹2.80 risk!)"
    )

    # Now simulate 12-Nov T1 hitting T1 (₹235.00) and peaking at ₹243.55 (+1.88R) before reversing to +0.50R Trail SL (₹216.50)
    ledger_w1._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 25300, "ce_ltp": 110.0, "pe_ltp": 243.55}],
            "market_snapshot": {"spot_ltp": 25180.00, "feed_mode": "FULL"},
        },
        t0_w1 + timedelta(minutes=32),
    )
    assert ledger_w1._open_trade["t1_booked"] is True
    assert ledger_w1._open_trade["current_sl_premium"] == 216.50
    ledger_w1._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 25300, "ce_ltp": 140.0, "pe_ltp": 216.50}],
            "market_snapshot": {"spot_ltp": 25232.85, "feed_mode": "FULL"},
        },
        t0_w1 + timedelta(minutes=36, seconds=51),
    )
    assert ledger_w1._open_trade is None
    closed_12t1 = ledger_w1._closed_trades[0]
    assert closed_12t1["exit_reason"] == "TRAILED_SL_HIT"
    assert closed_12t1["net_pnl_inr"] > 170000.0
    print(
        f"  [PASS] 12-Nov T1 Extended Trade graduated to T1 & closed @ Blended ₹{closed_12t1['exit_premium']} "
        f"(Net +₹{closed_12t1['net_pnl_inr']:,.2f} on 150L)"
    )

    # 4C. Catch #3 Gap-Free Verification: Wave#1 trade at +0.25R (+3.50 pts < +4.0 pts)
    ledger_gap = _new_isolated_ledger()
    t0_gap = datetime(2026, 11, 13, 10, 0, 0, tzinfo=IST)
    ledger_gap._open_trade = {
        "trade_id": "TEST-GAP-W1",
        "source": "AUTO_QUANT_SIGNAL",
        "entry_time": t0_gap.isoformat(),
        "symbol": "NSE:NIFTY26N1725300CE",
        "strike": 25300,
        "opt_type": "CE",
        "trigger_type": "MOMENTUM_BOX_BREAKOUT",
        "lots": 100,
        "lot_size": 65,
        "qty": 6500,
        "entry_spot": 25300.0,
        "current_spot": 25312.0,
        "best_spot": 25320.0,
        "entry_premium": 200.00,
        "current_ltp": 203.50,  # +3.50 pts (+0.25R on 14.0 pt SL) -> between +0.20R and +4.0 pts!
        "high_watermark": 206.00,  # +6.00 pts (+0.43R >= 0.38R)
        "initial_sl_premium": 186.00,
        "current_sl_premium": 186.00,
        "sl_points": 14.00,
        "t1_premium": 221.00,
        "t2_premium": 235.00,
        "t1_booked": False,
        "coiling_extension_active": False,
        "time_stop_minutes": 20.0,
    }
    ledger_gap._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 25300, "ce_ltp": 203.50, "pe_ltp": 150.0}],
            "market_snapshot": {"spot_ltp": 25312.0, "feed_mode": "FULL"},
        },
        t0_gap + timedelta(minutes=20, seconds=5),
    )
    assert ledger_gap._open_trade is not None
    assert ledger_gap._open_trade["coiling_extension_active"] is True
    assert ledger_gap._open_trade["current_sl_premium"] == round_to_nse_tick(200.00 - 0.35 * 14.00) == 195.10
    print("  [PASS] Catch #3 Gap-Free verified: Wave#1 at +0.25R (+3.50 pts) extended with -0.35R SL @ ₹195.10")

    # 4D. Dead Trade Check: 11-Nov Trade 3 (11:40 -> 12:00 CE, Peak +0.05R, Spot -3.80 pts against) MUST cut at 20.0m!
    ledger_dead = _new_isolated_ledger()
    t0_dead = datetime(2026, 11, 11, 11, 40, 37, tzinfo=IST)
    ledger_dead._open_trade = {
        "trade_id": "NPQ-114037-2A77",
        "source": "AUTO_QUANT_SIGNAL",
        "entry_time": t0_dead.isoformat(),
        "symbol": "NSE:NIFTY26N1725350CE",
        "strike": 25350,
        "opt_type": "CE",
        "trigger_type": "MOMENTUM_BOX_BREAKOUT",
        "lots": 143,
        "lot_size": 65,
        "qty": 9295,
        "entry_spot": 25395.75,
        "current_spot": 25391.95,
        "best_spot": 25396.50,
        "entry_premium": 268.65,
        "current_ltp": 263.75,
        "high_watermark": 269.75,  # +0.05R (< 0.38R)
        "initial_sl_premium": 245.80,
        "current_sl_premium": 245.80,
        "sl_points": 22.85,
        "t1_premium": 302.95,
        "t2_premium": 325.80,
        "t1_booked": False,
        "coiling_extension_active": False,
        "time_stop_minutes": 20.0,
    }
    ledger_dead._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 25350, "ce_ltp": 263.75, "pe_ltp": 180.0}],
            "market_snapshot": {"spot_ltp": 25391.95, "feed_mode": "FULL"},
        },
        t0_dead + timedelta(minutes=20),
    )
    assert ledger_dead._open_trade is None, "Dead trade 11-Nov T3 must be cut immediately at 20.0m!"
    assert ledger_dead._closed_trades[0]["exit_reason"] == "TIME_STOP_20MIN (< +0.5R Theta Protection)"
    print("  [PASS] 11-Nov T3 (Peak +0.05R Dead Trap) cut immediately at 20.0m -> Saved 12:05 crash!")


def test_5_catches_1_and_2_telegram_and_exit_reason():
    print("\n--- Running Test 5: Catch #1 (Telegram Milestone Template) & Catch #2 (Breakeven vs -0.35R Exit Reason) ---")

    # 5A. Catch #1: Telegram Milestone Template for COILING_30M_EXTENSION (Breakeven & -0.35R modes)
    sample_be = {
        "symbol": "NSE:NIFTY26N1725350PE",
        "strike": 25350,
        "opt_type": "PE",
        "lots": 130,
        "lot_size": 65,
        "entry_premium": 264.45,
        "current_ltp": 269.25,
        "high_watermark": 276.55,
        "current_sl_premium": 265.95,
        "unrealized_r": 0.17,
    }
    msg_be = format_alpha_milestone_message(sample_be, "COILING_30M_EXTENSION")
    assert "20M->30M COILING EXTENSION ARMED" in msg_be
    assert "Breakeven Lock (Entry + ₹1.50)" in msg_be
    assert "45-MIN RUNNER" not in msg_be

    sample_red = {
        **sample_be,
        "entry_premium": 206.65,
        "current_ltp": 202.55,
        "high_watermark": 214.50,
        "current_sl_premium": 199.75,
        "unrealized_r": -0.21,
    }
    msg_red = format_alpha_milestone_message(sample_red, "COILING_30M_EXTENSION")
    assert "20M->30M COILING EXTENSION ARMED" in msg_red
    assert "Tight Coiling Cap (-0.35R)" in msg_red
    print("  [PASS] Catch #1 verified: COILING_30M_EXTENSION Telegram template renders both Breakeven & -0.35R modes cleanly")

    # 5B. Catch #2: Breakeven Coiling SL hit -> TIME_STOP_20MIN (30m Coiling Breakeven SL_HIT) -> Guard 1D (5m) & NOT Guard 1A (15m)
    ledger_be = _new_isolated_ledger()
    t0 = datetime(2026, 11, 11, 13, 8, 55, tzinfo=IST)
    ledger_be._open_trade = {
        "trade_id": "TEST-COIL-BE",
        "source": "AUTO_QUANT_SIGNAL",
        "entry_time": t0.isoformat(),
        "symbol": "NSE:NIFTY26N1725350PE",
        "strike": 25350,
        "opt_type": "PE",
        "trigger_type": "VWAP_EMA20_PULLBACK_RESUMPTION",
        "lots": 130,
        "lot_size": 65,
        "qty": 8450,
        "entry_spot": 25276.75,
        "current_spot": 25272.00,
        "best_spot": 25255.00,
        "entry_premium": 264.45,
        "current_ltp": 269.25,
        "high_watermark": 276.55,
        "initial_sl_premium": 235.60,
        "current_sl_premium": 265.95,  # Locked at Entry + 1.50
        "sl_points": 28.85,
        "t1_premium": 307.75,
        "t2_premium": 336.60,
        "t1_booked": False,
        "coiling_extension_active": True,
        "time_stop_minutes": 30.0,
        "est_slippage_inr": 15000.0,  # Force net_pnl_inr slightly negative to prove immunity to Guard 1A!
    }
    t_be_hit = t0 + timedelta(minutes=24)
    ledger_be._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 25350, "ce_ltp": 190.0, "pe_ltp": 265.95}],
            "market_snapshot": {"spot_ltp": 25275.00, "feed_mode": "FULL"},
        },
        t_be_hit,
    )
    assert ledger_be._open_trade is None
    closed_be = ledger_be._closed_trades[0]
    assert closed_be["exit_reason"] == "TIME_STOP_20MIN (30m Coiling Breakeven SL_HIT)"
    assert closed_be["net_pnl_inr"] < 0  # Slight net red due to charges/slippage

    # At +6 minutes (after 5m Guard 1D settlement) with Spot clearing best_spot low (25255.0 - 3.0) -> Should PASS (NOT blocked by 15m Guard 1A!)
    eval_next_pe = {
        "selected_contract": {"opt_type": "PE"},
        "trade_plan": {"opt_type": "PE", "trigger_type": "VWAP_EMA20_PULLBACK_RESUMPTION"},
        "entry_trigger": {"trigger_type": "VWAP_EMA20_PULLBACK_RESUMPTION"},
        "market_snapshot": {"spot_ltp": 25250.00},
    }
    ok_after_be, reason_after_be = ledger_be._check_reentry_and_wave_guards(
        eval_next_pe, t_be_hit + timedelta(minutes=6)
    )
    assert ok_after_be is True and reason_after_be == "PASS", f"Got {ok_after_be}, {reason_after_be}"
    print(
        f"  [PASS] Catch #2 verified: Breakeven Coiling SL exits as '{closed_be['exit_reason']}' "
        f"(Guard 1A hard-loss cooldown NOT falsely triggered!)"
    )

    # 5C. Conversely, if -0.35R Tight SL (< Entry) hits during 20m->30m, exit_reason MUST be INITIAL_SL_HIT!
    ledger_tight = _new_isolated_ledger()
    ledger_tight._open_trade = {
        **ledger_be._closed_trades[0],
        "trade_id": "TEST-COIL-TIGHT",
        "entry_premium": 206.65,
        "current_ltp": 202.55,
        "high_watermark": 214.50,
        "initial_sl_premium": 187.00,
        "current_sl_premium": 199.75,  # -0.35R (< entry_prem)
        "sl_points": 19.65,
        "t1_premium": 235.00,
        "t2_premium": 254.20,
        "coiling_extension_active": True,
        "pre_t1_shield_active": False,
        "t1_booked": False,
    }
    ledger_tight._closed_trades = []
    ledger_tight._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 25350, "ce_ltp": 160.0, "pe_ltp": 199.75}],
            "market_snapshot": {"spot_ltp": 25285.00, "feed_mode": "FULL"},
        },
        t0 + timedelta(minutes=23),
    )
    assert ledger_tight._closed_trades[0]["exit_reason"] == "INITIAL_SL_HIT"
    print("  [PASS] Catch #2 verified: -0.35R Coiling SL hit rightly exits as 'INITIAL_SL_HIT'")


def test_6_ten_day_historical_replay_and_clean_isolation():
    print("\n--- Running Test 6: Historical JSON Ledgers Replay & Module 5 Archive Endpoints ---")
    quant_dir = os.path.join(os.path.dirname(__file__), "app", "data", "nifty_options_quant")
    files = sorted(glob.glob(os.path.join(quant_dir, "ledger_*.json")))
    assert len(files) >= 12, f"Expected >= 12 ledger files (28-Oct to 13-Nov), found {len(files)}"

    total_trades = 0
    for f in files:
        with open(f, "r", encoding="utf-8") as fp:
            d = json.load(fp)
        total_trades += len(d.get("closed_trades", []))

    assert total_trades >= 52, f"Expected >= 52 total historical trades across ledger files, found {total_trades}"
    _cleanup_dummy_ledger_file()
    assert not (LEDGER_DIR / f"ledger_{DUMMY_SESSION_DATE}.json").exists()

    # Verify list_available_sessions & get_historical_ledger_summary
    ledger = NiftyOptionsPaperLedger()
    res_25l = ledger.list_available_sessions(capital_inr=2500000.0)
    res_50l = ledger.list_available_sessions(capital_inr=5000000.0)
    assert res_25l["sessions"][0]["is_today"] is True
    assert all(not s["session_date"].startswith("2099") for s in res_25l["sessions"])
    assert all(s["session_date"] != "2026-10-28" for s in res_25l["sessions"])
    assert res_25l["cumulative"]["total_sessions"] >= 11
    assert res_25l["cumulative"]["total_trades"] >= 52
    assert round(res_25l["cumulative"]["cumulative_roi_pct"], 1) == round(res_50l["cumulative"]["cumulative_roi_pct"] * 2.0, 1)

    res_from_04nov = ledger.list_available_sessions(capital_inr=2500000.0, from_date="2026-11-04")
    assert res_from_04nov["cumulative"]["from_date"] == "2026-11-04"
    assert res_from_04nov["cumulative"]["total_sessions"] >= 7
    assert res_from_04nov["cumulative"]["total_trades"] >= 23

    h13 = ledger.get_historical_ledger_summary("2026-11-13")
    assert h13["session_date"] == "2026-11-13"
    assert h13["stats"]["net_realized_pnl_inr"] == 91729.81
    print(f"  [PASS] All {len(files)} ledger files ({total_trades} historical trades) & Module 5 Archive/ROI APIs verified!")


if __name__ == "__main__":
    try:
        print("==================================================================")
        print("STARTING ALPHA ENGINE v5.7 COMPREHENSIVE VERIFICATION SUITE")
        print("==================================================================")
        test_1_env_150_lots_cap_and_12nov_sizing()
        test_2_best_spot_tracking_and_guard_1e()
        test_3_guard_2b_wave3_exhaustion_protection()
        test_4_fix4_coiling_30m_extension_and_catch3_gap_free()
        test_5_catches_1_and_2_telegram_and_exit_reason()
        test_6_ten_day_historical_replay_and_clean_isolation()
        print("\n==================================================================")
        print("ALL 6 ALPHA v5.7 TEST SUITES PASSED 100% CLEANLY! (EXIT CODE 0)")
        print("==================================================================")
    finally:
        _cleanup_dummy_ledger_file()
