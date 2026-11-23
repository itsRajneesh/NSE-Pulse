import sys
import os
from datetime import datetime, timezone, timedelta

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.v13_nifty_options_ledger import NiftyOptionsPaperLedger, IST
from app.v13_alpha_telegram import format_alpha_milestone_message

def test_upgrade_1_ratchet_multi_floor():
    print("--> Testing Upgrade 1: Multi-Floor T1 Ratchet...")
    ledger = NiftyOptionsPaperLedger(enable_notifications=False)
    ledger._session_date = "2099-01-01"
    
    # Simulate single-tick jump from +1.10R straight to +1.55R
    # Entry = 200.0, SL = 180.0 (sl_pts = 20.0), T1 = 230.0 (+1.5R)
    # Pre-T1 shield (+0.50R) would be 200 + 10.0 = 210.0
    # Base cost would be 200 + 2.0 = 202.0
    # In single-tick jump: price jumps from 220.0 (+1.0R) directly to 231.0 (+1.55R)
    open_trade = {
        "trade_id": "TEST-01",
        "entry_premium": 200.0,
        "current_sl_premium": 180.0, # Initial SL
        "sl_points": 20.0,
        "t1_premium": 230.0,
        "t2_premium": 250.0,
        "t1_booked": False,
        "lots": 10,
        "lot_size": 65,
        "qty": 650,
        "entry_time": "2026-11-05T09:30:00+05:30",
        "entry_time_str": "09:30:00 IST",
        "current_ltp": 200.0,
        "high_watermark": 200.0,
        "feed_mode": "FULL",
        "symbol": "NIFTY26N0923800CE",
        "strike": 23800,
        "opt_type": "CE"
    }
    ledger._open_trade = open_trade
    
    eval_result = {
        "feed_mode": "FULL",
        "option_chain_window": [{"strike": 23800, "ce_ltp": 231.0, "pe_ltp": 50.0}],
        "market_snapshot": {"spot_ltp": 23850.0, "feed_mode": "FULL"}
    }
    
    # Process tick at 231.0 (T1 hit via jump)
    now_dt = datetime.fromisoformat("2026-11-05T09:35:00+05:30")
    ledger._update_open_trade_state(eval_result, now_dt)
    
    tr = ledger._open_trade
    assert tr["t1_booked"] == True, "T1 should be booked"
    # Even though price jumped directly to 231.0, SL should be at least shield floor (210.0)
    assert tr["current_sl_premium"] >= 210.0, f"Expected SL >= 210.0, got {tr['current_sl_premium']}"
    print(f"    [PASS] Single-tick jump to +1.55R: SL locked at {tr['current_sl_premium']} (>= 210.0 floor)")

def test_upgrade_2_doorstep_and_dynamic_scaling():
    print("--> Testing Upgrade 2: Doorstep Trailing & State Sync...")
    ledger = NiftyOptionsPaperLedger(enable_notifications=False)
    ledger._session_date = "2099-01-01"
    
    # Entry 200.0, SL 180.0 (sl_pts = 20.0), T1 = 230.0 (+1.5R), T2 = 250.0 (+2.5R)
    # +2.20R = 200 + 44.0 = 244.0. Step SL should lock +1.60R = 200 + 32.0 = 232.0
    open_trade = {
        "trade_id": "TEST-02",
        "entry_premium": 200.0,
        "current_sl_premium": 210.0,
        "sl_points": 20.0,
        "t1_premium": 230.0,
        "t2_premium": 250.0,
        "t1_booked": True,
        "stage2_notified": False,
        "doorstep_notified": False,
        "lots": 10,
        "lot_size": 65,
        "qty": 650,
        "entry_time": "2026-11-05T09:30:00+05:30",
        "entry_time_str": "09:30:00 IST",
        "current_ltp": 230.0,
        "high_watermark": 230.0,
        "feed_mode": "FULL",
        "symbol": "NIFTY26N0923800CE",
        "strike": 23800,
        "opt_type": "CE"
    }
    ledger._open_trade = open_trade
    
    # Tick at +2.25R (245.0) - Doorstep zone
    eval_result = {
        "feed_mode": "FULL",
        "option_chain_window": [{"strike": 23800, "ce_ltp": 245.0, "pe_ltp": 50.0}],
        "market_snapshot": {"spot_ltp": 23880.0, "feed_mode": "FULL"}
    }
    now_dt = datetime.fromisoformat("2026-11-05T09:40:00+05:30")
    ledger._update_open_trade_state(eval_result, now_dt)
    
    tr = ledger._open_trade
    assert tr["doorstep_notified"] == True, "doorstep_notified should be True"
    assert tr["stage2_notified"] == True, "stage2_notified should also be True (synced)"
    assert tr["current_sl_premium"] == 232.0, f"Expected SL = 232.0 (+1.60R), got {tr['current_sl_premium']}"
    print(f"    [PASS] +2.25R Doorstep: SL locked at {tr['current_sl_premium']} (+1.60R) with state synced")

    # Verify Telegram formatting
    msg = format_alpha_milestone_message(tr, "DOORSTEP_220_TRAIL")
    assert "+2.20R DOORSTEP TRAIL LOCKED" in msg, "Telegram message format verification failed"
    assert "+1.60R Locked Above T1" in msg, "Telegram message body missing +1.60R lock line"
    print(f"    [PASS] Telegram milestone template verified perfectly")

def test_upgrade_3_guard_1c_gap_check():
    print("--> Testing Upgrade 3: Guard 1C Continuous Stall vs Gap...")
    ledger = NiftyOptionsPaperLedger(enable_notifications=False)
    ledger._session_date = "2099-01-01"
    now_dt = datetime.fromisoformat("2026-11-05T12:15:00+05:30")

    # Scenario A: Wednesday Style (Gap = 0.0m <= 20.0m)
    # Trade 1 exit 11:54, Trade 2 entry 11:54 -> exit 12:14
    # Stalled spot: 23770 / 23758
    wed_trades = [
        {
            "trade_id": "NPQ-1",
            "source": "AUTO_QUANT_SIGNAL",
            "opt_type": "PE",
            "entry_time": "2026-11-05T11:34:00+05:30",
            "exit_time": "2026-11-05T11:54:00+05:30",
            "exit_reason": "TIME_STOP_20MIN (< +0.5R Theta Protection)",
            "entry_spot": 23770.0,
            "net_pnl_inr": 1000.0
        },
        {
            "trade_id": "NPQ-2",
            "source": "AUTO_QUANT_SIGNAL",
            "opt_type": "PE",
            "entry_time": "2026-11-05T11:54:00+05:30", # gap = 0.0m
            "exit_time": "2026-11-05T12:14:00+05:30",
            "exit_reason": "TIME_STOP_20MIN (< +0.5R Theta Protection)",
            "entry_spot": 23758.0,
            "net_pnl_inr": 500.0
        }
    ]
    ledger._closed_trades = wed_trades
    eval_wed = {
        "trade_plan": {"opt_type": "PE", "trigger_type": "MOMENTUM_BOX_BREAKDOWN"},
        "market_snapshot": {"spot_ltp": 23758.0}
    }
    # Check at 12:15 (mins_since_last_exit = 1.0m < 15.0m)
    passed, reason = ledger._check_reentry_and_wave_guards(eval_wed, now_dt)
    assert not passed, "Wednesday back-to-back stall should be BLOCKED"
    assert "GUARD_1_MOMENTUM_STALL (1C)" in reason, f"Expected 1C block reason, got {reason}"
    print(f"    [PASS] Wednesday continuous stall (gap 0.0m) blocked: {reason}")

    # Scenario B: Tuesday Style (Gap = 29.0m > 20.0m)
    # Trade 1 exit 09:46, Trade 2 entry 10:15 -> exit 10:36
    tue_trades = [
        {
            "trade_id": "NPQ-T1",
            "source": "AUTO_QUANT_SIGNAL",
            "opt_type": "CE",
            "entry_time": "2026-11-05T09:26:00+05:30",
            "exit_time": "2026-11-05T09:46:00+05:30",
            "exit_reason": "TIME_STOP_20MIN (< +0.5R Theta Protection)",
            "entry_spot": 23800.0,
            "net_pnl_inr": -3000.0
        },
        {
            "trade_id": "NPQ-T2",
            "source": "AUTO_QUANT_SIGNAL",
            "opt_type": "CE",
            "entry_time": "2026-11-05T10:15:00+05:30", # gap = 29.0m!
            "exit_time": "2026-11-05T10:36:00+05:30",
            "exit_reason": "TIME_STOP_20MIN (< +0.5R Theta Protection)",
            "entry_spot": 23820.0,
            "net_pnl_inr": 20000.0
        }
    ]
    ledger._closed_trades = tue_trades
    eval_tue = {
        "trade_plan": {"opt_type": "CE", "trigger_type": "MOMENTUM_BOX_BREAKOUT"},
        "market_snapshot": {"spot_ltp": 23830.0}
    }
    # At 10:42:00 (6m after 10:36 exit), Guard 1C must NOT fire; at 10:52:00 (>15m Wave#3 reset) entry PASSES
    tue_now_early = datetime.fromisoformat("2026-11-05T10:42:00+05:30")
    _, reason_early = ledger._check_reentry_and_wave_guards(eval_tue, tue_now_early)
    assert "GUARD_1_MOMENTUM_STALL (1C)" not in reason_early, f"Guard 1C should not fire on 29m gap, got {reason_early}"
    tue_now = datetime.fromisoformat("2026-11-05T10:52:00+05:30")
    passed, reason = ledger._check_reentry_and_wave_guards(eval_tue, tue_now)
    assert passed, f"Tuesday trades with 29m gap should NOT be blocked by 1C, but got {reason}"
    print(f"    [PASS] Tuesday 29m gap allowed cleanly (Guard 1C did not fire): {reason}")

if __name__ == "__main__":
    print("==================================================")
    print("STARTING ALPHA v5.4 COMPREHENSIVE TEST SUITE")
    print("==================================================")
    test_upgrade_1_ratchet_multi_floor()
    test_upgrade_2_doorstep_and_dynamic_scaling()
    test_upgrade_3_guard_1c_gap_check()
    print("==================================================")
    print("ALL TESTS PASSED WITH 100% SUCCESS! (EXIT CODE 0)")
    print("==================================================")

    import pathlib
    test_file = pathlib.Path("backend/app/data/nifty_options_quant/ledger_2099-01-01.json")
    if test_file.exists():
        try:
            test_file.unlink()
        except Exception:
            pass
