"""
Comprehensive Unit Test Suite for Alpha Engine v5.5:
1. Test 1: Morning Red Time-Stop (-0.12R scratch) -> 5m settlement + Spot clearance allows 11:30 breakout.
2. Test 2: Mid-Day Green Time-Stop (+0.22R) -> Blocks 0.23s re-entry churn and enforces max(entry, exit) + 3.0.
3. Test 3: 2x Continuous Time-Stops (40m Stall) -> Guard 1C triggers immediately at t=1m (never masked by 1D).
4. Test 4: Tuesday (03-Nov) Non-Continuous Time-Stops (gap 29m) -> Guard 1C does NOT false-trigger.
5. Test 5: Hard Stop-Loss (INITIAL_SL_HIT, -1.0R) -> Guard 1A 15m cooldown + Guard 1B spot recovery.
6. Test 6: Gate A UI & Engine timing string alignment -> Shows (09:25-14:15 IST).
"""

import sys
import os
from datetime import datetime, time as dtime, timezone, timedelta
import zoneinfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.v13_nifty_options_ledger import NiftyOptionsPaperLedger, IST
from app.v13_nifty_options_engine import evaluate_nifty_options_quant_pipeline

def create_mock_eval(spot_ltp=24400.0, opt_type="CE"):
    return {
        "feed_mode": "FULL",
        "regime": {"bias": "BULLISH_TREND"},
        "market_snapshot": {"spot_ltp": spot_ltp, "feed_mode": "FULL"},
        "trade_plan": {
            "signal_state": "EXECUTE_BUY",
            "opt_type": opt_type,
            "strike": 24400,
            "symbol": f"NSE:NIFTY26N0924400{opt_type}",
            "entry_premium": 150.0,
            "sl_premium": 130.0,
            "t1_premium": 180.0,
            "t2_premium": 200.0,
        },
        "selected_contract": {
            "symbol": f"NSE:NIFTY26N0924400{opt_type}",
            "strike": 24400,
            "opt_type": opt_type,
            "ltp": 150.0,
        },
        "entry_trigger": {"trigger_type": "MOMENTUM_BOX_BREAKOUT"},
    }

def test_1_morning_red_time_stop():
    print("\n--- Running Test 1: Morning Red Time-Stop (-0.12R Scratch) ---")
    ledger = NiftyOptionsPaperLedger(enable_notifications=False)
    ledger._session_date = "2026-11-05"

    # Trade 1: Entry 11:04:23, Exit 11:24:23, -0.12R, Entry Spot 24376.75, Exit Spot 24375.0
    t1_entry = datetime(2026, 11, 5, 11, 4, 23, tzinfo=IST)
    t1_exit = datetime(2026, 11, 5, 11, 24, 23, tzinfo=IST)

    mock_trade_1 = {
        "trade_id": "NPQ-110423-8915",
        "source": "AUTO_QUANT_SIGNAL",
        "opt_type": "CE",
        "entry_time": t1_entry.isoformat(),
        "exit_time": t1_exit.isoformat(),
        "entry_spot": 24376.75,
        "exit_spot": 24375.0,
        "entry_premium": 164.30,
        "exit_premium": 162.00,
        "r_multiple": -0.12,
        "net_pnl_inr": -32967.07,
        "exit_reason": "TIME_STOP_20MIN (< +0.5R Theta Protection)",
    }
    ledger._closed_trades = [mock_trade_1]

    # At 11:27:00 (2.6m since exit < 5m) -> Guard 1D must block
    t_check_1 = datetime(2026, 11, 5, 11, 27, 0, tzinfo=IST)
    eval_1 = create_mock_eval(spot_ltp=24390.0, opt_type="CE")
    ok, reason = ledger._check_reentry_and_wave_guards(eval_1, now_dt=t_check_1)
    assert not ok, f"Expected block at 11:27, got ok={ok}"
    assert "GUARD_1_TIME_STOP_COOLDOWN (1D)" in reason, f"Expected Guard 1D cooldown, got {reason}"
    print(f"  [PASS] At 11:27 (<5m): Blocked by Guard 1D: {reason}")

    # At 11:34:00 (9.6m since exit > 5m) and Spot = 24409.70 (> 24376.75 + 3.0) -> ALLOWED!
    t_check_2 = datetime(2026, 11, 5, 11, 34, 0, tzinfo=IST)
    eval_2 = create_mock_eval(spot_ltp=24409.70, opt_type="CE")
    ok, reason = ledger._check_reentry_and_wave_guards(eval_2, now_dt=t_check_2)
    assert ok, f"Expected PASS at 11:34 with spot 24409.70, got blocked: {reason}"
    print(f"  [PASS] At 11:34 (>5m & Spot 24,409.70): ALLOWED (Breakout Captured): {reason}")

def test_2_midday_green_time_stop_churn():
    print("\n--- Running Test 2: Mid-Day Green Time-Stop Churn (+0.22R) ---")
    ledger = NiftyOptionsPaperLedger(enable_notifications=False)
    ledger._session_date = "2026-11-05"

    # Trade 2: Entry 12:16:29, Exit 12:36:29.472, +0.22R, Entry Spot 24419.0, Exit Spot 24437.5
    t2_entry = datetime(2026, 11, 5, 12, 16, 29, tzinfo=IST)
    t2_exit = datetime(2026, 11, 5, 12, 36, 29, 472888, tzinfo=IST)

    mock_trade_2 = {
        "trade_id": "NPQ-121629-E16C",
        "source": "AUTO_QUANT_SIGNAL",
        "opt_type": "CE",
        "entry_time": t2_entry.isoformat(),
        "exit_time": t2_exit.isoformat(),
        "entry_spot": 24419.0,
        "exit_spot": 24437.5,
        "entry_premium": 156.05,
        "exit_premium": 159.25,
        "r_multiple": 0.22,
        "net_pnl_inr": 20731.62,
        "exit_reason": "TIME_STOP_20MIN (< +0.5R Theta Protection)",
    }
    ledger._closed_trades = [mock_trade_2]

    # At 12:36:29.700 (0.23 seconds later) -> Must be BLOCKED by Guard 1D!
    t_churn = datetime(2026, 11, 5, 12, 36, 29, 700530, tzinfo=IST)
    eval_churn = create_mock_eval(spot_ltp=24437.5, opt_type="CE")
    ok, reason = ledger._check_reentry_and_wave_guards(eval_churn, now_dt=t_churn)
    assert not ok, f"Expected block at 0.23s churn tick, got ok={ok}"
    assert "GUARD_1_TIME_STOP_COOLDOWN (1D)" in reason, f"Expected Guard 1D, got: {reason}"
    print(f"  [PASS] At 12:36:29.700 (0.23s later): 100% BLOCKED by Guard 1D: {reason}")

    # At 12:42:00 (5.5m later), but Spot = 24438.0 (<= max(24419, 24437.5) + 3.0 = 24440.5) -> Still BLOCKED!
    t_post_5m = datetime(2026, 11, 5, 12, 42, 0, tzinfo=IST)
    eval_post_5m = create_mock_eval(spot_ltp=24438.0, opt_type="CE")
    ok, reason = ledger._check_reentry_and_wave_guards(eval_post_5m, now_dt=t_post_5m)
    assert not ok, f"Expected block due to spot clearance, got ok={ok}"
    assert "GUARD_1_TIME_STOP_CLEARANCE (1D)" in reason, f"Expected Guard 1D clearance, got: {reason}"
    print(f"  [PASS] At 12:42 (>5m but Spot inside stall box 24,438.0): BLOCKED by Guard 1D: {reason}")

    # At 12:42:00 with Spot = 24442.0 (> 24440.5) -> ALLOWED!
    eval_clear = create_mock_eval(spot_ltp=24442.0, opt_type="CE")
    ok, reason = ledger._check_reentry_and_wave_guards(eval_clear, now_dt=t_post_5m)
    assert ok, f"Expected PASS with spot 24442.0, got blocked: {reason}"
    print(f"  [PASS] At 12:42 (>5m & Spot cleared stall box 24,442.0): ALLOWED: {reason}")

def test_3_2x_continuous_time_stops_guard_1c_priority():
    print("\n--- Running Test 3: 2x Continuous Time-Stops (Guard 1C Priority - Zero Masking) ---")
    ledger = NiftyOptionsPaperLedger(enable_notifications=False)
    ledger._session_date = "2026-11-05"

    t2_entry = datetime(2026, 11, 5, 12, 16, 29, tzinfo=IST)
    t2_exit = datetime(2026, 11, 5, 12, 36, 29, 472888, tzinfo=IST)
    t3_entry = datetime(2026, 11, 5, 12, 36, 29, 700530, tzinfo=IST)
    t3_exit = datetime(2026, 11, 5, 12, 56, 29, 752311, tzinfo=IST)

    trade_2 = {
        "trade_id": "NPQ-121629-E16C",
        "source": "AUTO_QUANT_SIGNAL",
        "opt_type": "CE",
        "entry_time": t2_entry.isoformat(),
        "exit_time": t2_exit.isoformat(),
        "entry_spot": 24419.0,
        "exit_spot": 24437.5,
        "exit_reason": "TIME_STOP_20MIN (< +0.5R Theta Protection)",
        "net_pnl_inr": 20731.62,
        "r_multiple": 0.22,
    }
    trade_3 = {
        "trade_id": "NPQ-123629-4563",
        "source": "AUTO_QUANT_SIGNAL",
        "opt_type": "CE",
        "entry_time": t3_entry.isoformat(),
        "exit_time": t3_exit.isoformat(),
        "entry_spot": 24437.5,
        "exit_spot": 24435.0,
        "exit_reason": "TIME_STOP_20MIN (< +0.5R Theta Protection)",
        "net_pnl_inr": -35315.93,
        "r_multiple": -0.18,
    }
    ledger._closed_trades = [trade_3, trade_2]

    # At 12:57:30 (1.0m after Trade 3 exit): Must IMMEDIATELY return Guard 1C (15m lock), NOT Guard 1D!
    t_stall_check = datetime(2026, 11, 5, 12, 57, 30, tzinfo=IST)
    eval_stall = create_mock_eval(spot_ltp=24436.0, opt_type="CE")
    ok, reason = ledger._check_reentry_and_wave_guards(eval_stall, now_dt=t_stall_check)
    assert not ok, f"Expected block at t=1m, got ok={ok}"
    assert "GUARD_1_MOMENTUM_STALL (1C)" in reason, f"CRITICAL: Expected Guard 1C, but got masked by: {reason}"
    assert "14.0m" in reason or "14." in reason, f"Expected ~14m remaining on 15m lock, got: {reason}"
    print(f"  [PASS] At 12:57:30 (t=1m): Guard 1C is NOT masked by 1D! Returned: {reason}")

def test_4_tuesday_non_continuous_time_stops():
    print("\n--- Running Test 4: Tuesday (03-Nov) Non-Continuous Time-Stops (gap 29m) ---")
    ledger = NiftyOptionsPaperLedger(enable_notifications=False)
    ledger._session_date = "2026-11-03"

    t1_entry = datetime(2026, 11, 3, 9, 26, 8, tzinfo=IST)
    t1_exit = datetime(2026, 11, 3, 9, 46, 8, tzinfo=IST)
    t2_entry = datetime(2026, 11, 3, 10, 15, 10, tzinfo=IST)
    t2_exit = datetime(2026, 11, 3, 10, 36, 18, tzinfo=IST)

    trade_1 = {
        "trade_id": "NPQ-092608-TEST",
        "source": "AUTO_QUANT_SIGNAL",
        "opt_type": "CE",
        "entry_time": t1_entry.isoformat(),
        "exit_time": t1_exit.isoformat(),
        "entry_spot": 24200.0,
        "exit_spot": 24210.0,
        "exit_reason": "TIME_STOP_20MIN (< +0.5R Theta Protection)",
        "net_pnl_inr": -25000.0,
        "r_multiple": -0.10,
    }
    trade_2 = {
        "trade_id": "NPQ-101510-TEST",
        "source": "AUTO_QUANT_SIGNAL",
        "opt_type": "CE",
        "entry_time": t2_entry.isoformat(),
        "exit_time": t2_exit.isoformat(),
        "entry_spot": 24250.0,
        "exit_spot": 24255.0,
        "exit_reason": "TIME_STOP_20MIN (< +0.5R Theta Protection)",
        "net_pnl_inr": 15000.0,
        "r_multiple": 0.15,
    }
    ledger._closed_trades = [trade_2, trade_1]

    # At 10:45:00 (8.7m after Trade 2 exit > 5m) and Spot = 24260.0 (> 24255 + 3.0)
    # Gap between Trade 1 exit (09:46) and Trade 2 entry (10:15) was 29.0m (> 20.0m)
    # Guard 1C MUST NOT FIRE! (In v5.7, Guard 2B Wave#3 requires 15m cooldown -> passes at 10:52:00)
    t_check_tue = datetime(2026, 11, 3, 10, 45, 0, tzinfo=IST)
    eval_tue = create_mock_eval(spot_ltp=24260.0, opt_type="CE")
    ok_early, reason_early = ledger._check_reentry_and_wave_guards(eval_tue, now_dt=t_check_tue)
    assert "GUARD_1_MOMENTUM_STALL (1C)" not in reason_early, f"Guard 1C should not fire on 29m gap, got {reason_early}"
    t_check_tue_15m = datetime(2026, 11, 3, 10, 52, 0, tzinfo=IST)
    ok, reason = ledger._check_reentry_and_wave_guards(eval_tue, now_dt=t_check_tue_15m)
    assert ok, f"Expected PASS on Tuesday after 15m Wave#3 reset because gap 29m > 20m, but got blocked: {reason}"
    print(f"  [PASS] On Tuesday (29m gap): Guard 1C did NOT fire, and entry ALLOWED after 15m Wave#3 reset: {reason}")

def test_5_hard_sl_hit():
    print("\n--- Running Test 5: Hard SL Hit (INITIAL_SL_HIT, -1.0R) ---")
    ledger = NiftyOptionsPaperLedger(enable_notifications=False)
    ledger._session_date = "2026-11-05"

    t_entry = datetime(2026, 11, 5, 10, 0, 0, tzinfo=IST)
    t_exit = datetime(2026, 11, 5, 10, 5, 0, tzinfo=IST)

    hard_sl_trade = {
        "trade_id": "NPQ-100000-HARD",
        "source": "AUTO_QUANT_SIGNAL",
        "opt_type": "CE",
        "entry_time": t_entry.isoformat(),
        "exit_time": t_exit.isoformat(),
        "entry_spot": 24350.0,
        "exit_spot": 24320.0,
        "exit_reason": "INITIAL_SL_HIT",
        "net_pnl_inr": -195000.0,
        "r_multiple": -1.0,
    }
    ledger._closed_trades = [hard_sl_trade]

    # At 10:10 (5m since loss < 15m) -> Guard 1A MUST BLOCK for 15m!
    t_check_hard = datetime(2026, 11, 5, 10, 10, 0, tzinfo=IST)
    eval_hard = create_mock_eval(spot_ltp=24360.0, opt_type="CE")
    ok, reason = ledger._check_reentry_and_wave_guards(eval_hard, now_dt=t_check_hard)
    assert not ok, f"Expected block at 5m on hard SL, got: {ok}"
    assert "GUARD_1_LOSS_COOLDOWN (1A)" in reason, f"Expected Guard 1A, got: {reason}"
    print(f"  [PASS] At 10:10 (5m after Hard SL): Blocked by Guard 1A: {reason}")

    # At 10:21 (16m since loss > 15m), but Spot = 24345.0 (< failed_spot 24350.0 + 1.50) -> Guard 1B MUST BLOCK!
    t_check_rec = datetime(2026, 11, 5, 10, 21, 0, tzinfo=IST)
    eval_unrec = create_mock_eval(spot_ltp=24345.0, opt_type="CE")
    ok, reason = ledger._check_reentry_and_wave_guards(eval_unrec, now_dt=t_check_rec)
    assert not ok, f"Expected block at 16m due to unrecovered spot, got: {ok}"
    assert "GUARD_1_STRUCTURE_UNRECOVERED (1B)" in reason, f"Expected Guard 1B, got: {reason}"
    print(f"  [PASS] At 10:21 (>15m but Spot unrecovered 24,345.0): Blocked by Guard 1B: {reason}")

    # At 10:21 with Spot = 24355.0 (> 24351.5) -> ALLOWED!
    eval_rec = create_mock_eval(spot_ltp=24355.0, opt_type="CE")
    ok, reason = ledger._check_reentry_and_wave_guards(eval_rec, now_dt=t_check_rec)
    assert ok, f"Expected PASS with recovered spot 24355.0, got blocked: {reason}"
    print(f"  [PASS] At 10:21 (>15m & Spot recovered 24,355.0): ALLOWED: {reason}")

def test_6_gate_a_string_alignment():
    print("\n--- Running Test 6: Gate A Engine Timing String Alignment ---")
    mock_bundle = {
        "spot_ltp": 24500.0,
        "futures_ltp": 24510.0,
        "india_vix": 14.5,
        "option_chain": [
            {"strike": 24500, "is_atm": True, "ce_ltp": 120.0, "pe_ltp": 110.0, "ce_oi": 10000, "pe_oi": 12000, "ce_symbol": "NSE:NIFTY26N0924500CE", "pe_symbol": "NSE:NIFTY26N0924500PE", "ce_delta": 0.52, "pe_delta": -0.48, "ce_iv": 13.5, "pe_iv": 13.5, "ce_bid": 119.5, "ce_ask": 120.5, "ce_spread_pct": 0.8, "ce_volume": 50000, "ce_chg_oi": 1000, "pe_bid": 109.5, "pe_ask": 110.5, "pe_spread_pct": 0.9, "pe_volume": 45000, "pe_chg_oi": 1200, "ce_gamma": 0.001, "ce_theta_hr": -0.8, "pe_gamma": 0.001, "pe_theta_hr": -0.8}
        ],
    }

    eval_out = evaluate_nifty_options_quant_pipeline(
        market_bundle=mock_bundle,
        now_dt=datetime(2026, 11, 5, 14, 30, 0, tzinfo=IST) # Post-14:15
    )

    gates = eval_out.get("regime_gates", {}).get("gates", [])
    gate_a = [g for g in gates if g.get("id") == "GATE_A_TIME"][0]
    gate_name = gate_a.get("name", "")
    assert "09:25–14:15 IST" in gate_name or "09:25-14:15 IST" in gate_name, f"Expected 14:15 in gate name, got: {gate_name}"
    print(f"  [PASS] Gate A name verified: {gate_name}")

    gate_detail = gate_a.get("detail", "")
    assert "14:15" in gate_detail, f"Expected 14:15 in gate detail, got: {gate_detail}"
    print(f"  [PASS] Gate A detail verified: {gate_detail}")

    # Also verify source file has 0 occurrences of old 14:45 cutoff in engine
    engine_path = os.path.join(os.path.dirname(__file__), "app", "v13_nifty_options_engine.py")
    with open(engine_path, "r", encoding="utf-8") as f:
        src = f.read()
    assert "14:45" not in src, "Found stale 14:45 string in v13_nifty_options_engine.py!"
    print("  [PASS] Confirmed 0 stale occurrences of '14:45' in v13_nifty_options_engine.py")

if __name__ == "__main__":
    test_1_morning_red_time_stop()
    test_2_midday_green_time_stop_churn()
    test_3_2x_continuous_time_stops_guard_1c_priority()
    test_4_tuesday_non_continuous_time_stops()
    test_5_hard_sl_hit()
    test_6_gate_a_string_alignment()
    print("\n==================================================================")
    print("ALL 6 TESTS IN ALPHA ENGINE v5.5 COMPREHENSIVE MATRIX PASSED 100%!")
    print("==================================================================")
