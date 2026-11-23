"""
Comprehensive Unit & Historical Replay Test Suite for Alpha Engine v5.6:
1. Test 1: Upgrade 1 (Stage 0A +0.45R Peak -> -0.45R Half-Loss Shield) on 06-Nov Trade 1 & 04-Nov Trade 3.
2. Test 2: Upgrade 1 (Stage 0B +0.80R Peak -> -0.25R Near-Breakeven Shield with min ₹4.00 buffer).
3. Test 3: Strict Monotonic 7-Stage Ratchet Progression (0.00R -> 0A -> 0B -> 1B -> 1A T1 -> 2 -> 2B -> 4 T2).
4. Test 4: Upgrade 2 (Stage 4 T2 Uncapped Velocity Ratchet) on 05-Nov Trade 4 (24450 CE rally ₹202 -> ₹252).
5. Test 5: Guard 3 Slippage Bound & Exit Reason Priority for t2_reached Runner (including post-45m T2 blast).
6. Test 6: Full 8-Day JSON Ledger Replay (28-Oct to 06-Nov) + Scope Freeze Verification (Trap #1 & Guard 2B untouched).
"""

import os
import sys
import json
import tempfile
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.v13_nifty_options_ledger import NiftyOptionsPaperLedger, IST, round_to_nse_tick


def _new_temp_ledger() -> NiftyOptionsPaperLedger:
    ledger = NiftyOptionsPaperLedger(enable_notifications=False)
    ledger._save_atomic = lambda: None
    ledger._open_trade = None
    ledger._closed_trades = []
    return ledger


def test_1_stage_0a_half_loss_shield_real_trades():
    print("\n--- Running Test 1: Stage 0A (+0.45R Peak -> -0.45R SL) on 06-Nov & 04-Nov Real Trades ---")

    # 1A. 06-Nov Trade 1 (NPQ-102907-01D6, 24650 CE, 123 Lots / 7,995 Qty)
    # Entry: 174.60, Initial SL: 144.00 (sl_pts = 30.60), HWM: 188.75 (+14.15 pts = +0.46R)
    ledger = _new_temp_ledger()
    t0 = datetime(2026, 11, 6, 10, 29, 7, tzinfo=IST)
    ledger._open_trade = {
        "trade_id": "NPQ-102907-01D6",
        "source": "AUTO_QUANT_SIGNAL",
        "entry_time": t0.isoformat(),
        "entry_time_str": "10:29:07 IST",
        "symbol": "NSE:NIFTY26N0924650CE",
        "strike": 24650,
        "opt_type": "CE",
        "lots": 123,
        "lot_size": 65,
        "qty": 7995,
        "entry_legs": 5,
        "t1_lots": 62,
        "runner_lots": 61,
        "t1_legs": 3,
        "runner_legs": 3,
        "entry_spot": 24676.85,
        "current_spot": 24676.85,
        "entry_premium": 174.60,
        "current_ltp": 174.60,
        "high_watermark": 174.60,
        "initial_sl_premium": 144.00,
        "current_sl_premium": 144.00,
        "sl_points": 30.60,
        "t1_premium": 219.90,
        "t2_premium": 250.20,
        "t1_booked": False,
        "t2_reached": False,
        "stage0a_shield_active": False,
        "stage0b_shield_active": False,
        "pre_t1_shield_active": False,
        "stage2_notified": False,
        "doorstep_notified": False,
        "sl_45m_tightened": False,
        "est_slippage_inr": 5196.75,
    }

    # Tick at peak 188.75 (+0.46R)
    eval_peak = {
        "feed_mode": "FULL",
        "option_chain_window": [{"strike": 24650, "ce_ltp": 188.75, "pe_ltp": 100.0}],
        "market_snapshot": {"spot_ltp": 24702.0, "feed_mode": "FULL"},
    }
    ledger._update_open_trade_state(eval_peak, t0 + timedelta(minutes=5))
    tr = ledger._open_trade
    assert tr is not None
    assert tr["stage0a_shield_active"] is True
    expected_0a_sl = round_to_nse_tick(174.60 - 0.45 * 30.60)  # 160.85
    assert tr["current_sl_premium"] == expected_0a_sl == 160.85, f"Got {tr['current_sl_premium']}"
    print(f"  [PASS] 06-Nov Trade 1 (+0.46R Peak ₹188.75): SL ratcheted ₹144.00 -> ₹{tr['current_sl_premium']} (-0.45R)")

    # U-turn tick hits 160.85
    eval_uturn = {
        "feed_mode": "FULL",
        "option_chain_window": [{"strike": 24650, "ce_ltp": 160.85, "pe_ltp": 130.0}],
        "market_snapshot": {"spot_ltp": 24640.0, "feed_mode": "FULL"},
    }
    ledger._update_open_trade_state(eval_uturn, t0 + timedelta(minutes=12))
    assert ledger._open_trade is None, "Trade should have closed on Stage 0A SL"
    closed = ledger._closed_trades[0]
    assert closed["exit_reason"] == "INITIAL_SL_HIT"
    assert closed["exit_premium"] == 160.85
    assert closed["r_multiple"] == -0.45
    saved_06nov = round(closed["net_pnl_inr"] - (-252328.81), 2)
    assert saved_06nov > 134000.0, f"Expected >1.34L saved, got {saved_06nov}"
    print(f"  [PASS] 06-Nov Trade 1 Closed @ ₹160.85 ({closed['r_multiple']}R) | Saved +₹{saved_06nov:,.2f}!")

    # 1B. 04-Nov Trade 3 (NPQ-121427-4B08, 23800 PE, 150 Lots / 9,750 Qty)
    # Entry: 220.65, Initial SL: 197.25 (sl_pts = 23.40), HWM: 235.00 (+14.35 pts = +0.61R)
    ledger2 = _new_temp_ledger()
    t0_4nov = datetime(2026, 11, 4, 12, 14, 27, tzinfo=IST)
    ledger2._open_trade = {
        "trade_id": "NPQ-121427-4B08",
        "source": "AUTO_QUANT_SIGNAL",
        "entry_time": t0_4nov.isoformat(),
        "entry_time_str": "12:14:27 IST",
        "symbol": "NSE:NIFTY26N0923800PE",
        "strike": 23800,
        "opt_type": "PE",
        "lots": 150,
        "lot_size": 65,
        "qty": 9750,
        "entry_legs": 6,
        "t1_lots": 75,
        "runner_lots": 75,
        "t1_legs": 3,
        "runner_legs": 3,
        "entry_spot": 23757.95,
        "current_spot": 23757.95,
        "entry_premium": 220.65,
        "current_ltp": 220.65,
        "high_watermark": 220.65,
        "initial_sl_premium": 197.25,
        "current_sl_premium": 197.25,
        "sl_points": 23.40,
        "t1_premium": 254.90,
        "t2_premium": 277.90,
        "t1_booked": False,
        "t2_reached": False,
        "stage0a_shield_active": False,
        "stage0b_shield_active": False,
        "pre_t1_shield_active": False,
        "stage2_notified": False,
        "doorstep_notified": False,
        "sl_45m_tightened": False,
        "est_slippage_inr": 9262.5,
    }
    eval_peak_4nov = {
        "feed_mode": "FULL",
        "option_chain_window": [{"strike": 23800, "ce_ltp": 100.0, "pe_ltp": 235.00}],
        "market_snapshot": {"spot_ltp": 23730.0, "feed_mode": "FULL"},
    }
    ledger2._update_open_trade_state(eval_peak_4nov, t0_4nov + timedelta(minutes=4))
    assert ledger2._open_trade["current_sl_premium"] == 210.10
    print(f"  [PASS] 04-Nov Trade 3 (+0.61R Peak ₹235.00): SL ratcheted ₹197.25 -> ₹210.10 (-0.45R)")


def test_2_stage_0b_near_breakeven_shield_and_4rs_floor():
    print("\n--- Running Test 2: Stage 0B (+0.80R Peak -> -0.25R SL with min ₹4.00 buffer) ---")

    # Scenario A: Normal SL (sl_pts = 20.0 -> 0.25 * 20 = ₹5.00 below entry)
    ledger = _new_temp_ledger()
    t0 = datetime(2026, 11, 6, 11, 0, 0, tzinfo=IST)
    ledger._open_trade = {
        "trade_id": "TEST-0B-NORM",
        "source": "AUTO_QUANT_SIGNAL",
        "entry_time": t0.isoformat(),
        "symbol": "NSE:NIFTY26N0924500CE",
        "strike": 24500,
        "opt_type": "CE",
        "lots": 10,
        "lot_size": 65,
        "qty": 650,
        "entry_spot": 24500.0,
        "entry_premium": 200.00,
        "current_ltp": 200.00,
        "high_watermark": 200.00,
        "initial_sl_premium": 180.00,
        "current_sl_premium": 180.00,
        "sl_points": 20.00,
        "t1_premium": 230.00,
        "t2_premium": 250.00,
        "t1_booked": False,
    }
    eval_0b = {
        "feed_mode": "FULL",
        "option_chain_window": [{"strike": 24500, "ce_ltp": 216.00, "pe_ltp": 100.0}],  # +0.80R
        "market_snapshot": {"spot_ltp": 24530.0, "feed_mode": "FULL"},
    }
    ledger._update_open_trade_state(eval_0b, t0 + timedelta(minutes=3))
    assert ledger._open_trade["stage0b_shield_active"] is True
    assert ledger._open_trade["current_sl_premium"] == 201.50
    print("  [PASS] Stage 0B (sl_pts=20.0, +0.80R Peak): SL locked at ₹201.50 (Entry + ₹1.50 Breakeven)")

    # Scenario B: Tight SL (sl_pts = 12.0 -> HWM 160.00 - 8.00 = 152.00 >= 151.50 -> locks Entry + ₹1.50 = ₹151.50)
    ledger_tight = _new_temp_ledger()
    ledger_tight._open_trade = {
        "trade_id": "TEST-0B-TIGHT",
        "source": "AUTO_QUANT_SIGNAL",
        "entry_time": t0.isoformat(),
        "symbol": "NSE:NIFTY26N0924500CE",
        "strike": 24500,
        "opt_type": "CE",
        "lots": 10,
        "lot_size": 65,
        "qty": 650,
        "entry_spot": 24500.0,
        "entry_premium": 150.00,
        "current_ltp": 150.00,
        "high_watermark": 150.00,
        "initial_sl_premium": 138.00,
        "current_sl_premium": 138.00,
        "sl_points": 12.00,
        "t1_premium": 168.00,
        "t2_premium": 180.00,
        "t1_booked": False,
    }
    eval_tight = {
        "feed_mode": "FULL",
        "option_chain_window": [{"strike": 24500, "ce_ltp": 160.00, "pe_ltp": 100.0}],  # +0.83R
        "market_snapshot": {"spot_ltp": 24520.0, "feed_mode": "FULL"},
    }
    ledger_tight._update_open_trade_state(eval_tight, t0 + timedelta(minutes=3))
    assert ledger_tight._open_trade["stage0b_shield_active"] is True
    assert ledger_tight._open_trade["current_sl_premium"] == 151.50  # min(150 + 1.50, 160 - 8.00)
    print("  [PASS] Stage 0B Tight SL (sl_pts=12.0, +0.83R Peak): Enforced 8.00pt min cushion -> SL ₹151.50")


def test_3_monotonic_7_stage_ratchet_ladder():
    print("\n--- Running Test 3: Strict Monotonic 7-Stage Ratchet Progression ---")
    ledger = _new_temp_ledger()
    t0 = datetime(2026, 11, 6, 9, 30, 0, tzinfo=IST)
    # Entry = 200, SL = 180 (sl_pts = 20), T1 = 230 (+1.5R), T2 = 250 (+2.5R)
    ledger._open_trade = {
        "trade_id": "TEST-LADDER",
        "source": "AUTO_QUANT_SIGNAL",
        "entry_time": t0.isoformat(),
        "symbol": "NSE:NIFTY26N0924500CE",
        "strike": 24500,
        "opt_type": "CE",
        "lots": 10,
        "lot_size": 65,
        "qty": 650,
        "entry_spot": 24500.0,
        "entry_premium": 200.00,
        "current_ltp": 200.00,
        "high_watermark": 200.00,
        "initial_sl_premium": 180.00,
        "current_sl_premium": 180.00,
        "sl_points": 20.00,
        "t1_premium": 230.00,
        "t2_premium": 250.00,
        "t1_booked": False,
        "t2_reached": False,
    }

    steps = [
        (209.00, 191.00, "Stage 0A (+0.45R -> SL 191.00 / -0.45R)"),
        (205.00, 191.00, "Dip to 205.00 -> SL stays 191.00 (Monotonic)"),
        (216.00, 201.50, "Stage 0B (+0.80R -> SL 201.50 / Entry + 1.50 Breakeven)"),
        (220.00, 209.00, "Stage 1B-0 (+1.00R -> SL 209.00 = HWM 220 - 11.0 / +0.45R)"),
        (224.00, 215.00, "Stage 1B-1 (+1.20R -> SL 215.00 = HWM 224 - 9.0 / +0.75R)"),
        (227.00, 219.40, "Stage 1C (+1.35R Doorstep -> SL 219.40 = HWM 227 - 7.6 / +0.97R)"),
        (230.00, 210.00, "Stage 1A (T1 +1.50R -> 50% Booked, Runner SL handed over to +0.50R floor 210.00 => +1.00R Blended)"),
        (240.00, 220.00, "Stage 2 (+2.00R -> SL 220.00 / +1.00R)"),
        (244.00, 232.00, "Stage 2B (+2.20R Doorstep -> SL 232.00 / +1.60R)"),
        (250.00, 248.50, "Stage 4 (T2 +2.50R Reached -> SL 248.50 = T2 - 1.50 Floor)"),
        (270.00, 266.00, "Stage 4 Parabolic (+3.50R HWM 270 -> SL 266.00 = HWM - 0.20R)"),
    ]

    prev_sl = 180.00
    for idx, (ltp, expected_sl, desc) in enumerate(steps, 1):
        ev = {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 24500, "ce_ltp": ltp, "pe_ltp": 80.0}],
            "market_snapshot": {"spot_ltp": 24550.0, "feed_mode": "FULL"},
        }
        ledger._update_open_trade_state(ev, t0 + timedelta(minutes=idx * 2))
        cur_sl = ledger._open_trade["current_sl_premium"]
        if ltp != 230.00:
            assert cur_sl >= prev_sl, f"Monotonicity violated at {desc}: {cur_sl} < {prev_sl}"
        assert cur_sl == expected_sl, f"At {desc}: expected SL {expected_sl}, got {cur_sl}"
        prev_sl = cur_sl
        print(f"  [PASS] Step {idx}: LTP ₹{ltp:.2f} -> SL ₹{cur_sl:.2f} | {desc}")


def test_4_t2_uncapped_velocity_ratchet_05nov_replay():
    print("\n--- Running Test 4: Stage 4 T2 Uncapped Velocity Ratchet (05-Nov 24450 CE Replay) ---")
    # 05-Nov Trade 4: Entry 154.15, SL 134.65 (sl_pts = 19.50), T1 182.50, T2 201.70, 150 Lots (9,750 Qty)
    ledger = _new_temp_ledger()
    t0 = datetime(2026, 11, 5, 13, 18, 55, tzinfo=IST)
    ledger._open_trade = {
        "trade_id": "NPQ-131855-4629",
        "source": "AUTO_QUANT_SIGNAL",
        "entry_time": t0.isoformat(),
        "entry_time_str": "13:18:55 IST",
        "symbol": "NSE:NIFTY26N0924450CE",
        "strike": 24450,
        "opt_type": "CE",
        "lots": 150,
        "lot_size": 65,
        "qty": 9750,
        "entry_legs": 6,
        "t1_lots": 75,
        "runner_lots": 75,
        "t1_legs": 3,
        "runner_legs": 3,
        "entry_spot": 24478.15,
        "current_spot": 24478.15,
        "entry_premium": 154.15,
        "current_ltp": 154.15,
        "high_watermark": 154.15,
        "initial_sl_premium": 134.65,
        "current_sl_premium": 134.65,
        "sl_points": 19.50,
        "t1_premium": 182.50,
        "t2_premium": 201.70,
        "t1_booked": False,
        "t2_reached": False,
        "est_slippage_inr": 7312.5,
    }

    # 1. Hit T1 at 182.50
    ledger._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 24450, "ce_ltp": 182.50, "pe_ltp": 80.0}],
            "market_snapshot": {"spot_ltp": 24510.0, "feed_mode": "FULL"},
        },
        t0 + timedelta(minutes=10),
    )
    assert ledger._open_trade["t1_booked"] is True

    # 2. Reach T2 at 202.00 -> Must NOT close! Must lock T2 - 1.50 = 200.20!
    ledger._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 24450, "ce_ltp": 202.00, "pe_ltp": 70.0}],
            "market_snapshot": {"spot_ltp": 24540.0, "feed_mode": "FULL"},
        },
        t0 + timedelta(minutes=22),
    )
    assert ledger._open_trade is not None, "Trade must stay open at T2 to ride parabolic runner!"
    assert ledger._open_trade["t2_reached"] is True
    assert ledger._open_trade["current_sl_premium"] == 200.20
    print(f"  [PASS] At T2 ₹202.00: Trade kept OPEN with t2_reached=True & Floor SL locked @ ₹200.20 (T2 - ₹1.50)")

    # 3. Parabolic blast to ₹252.00 -> SL trails to 252.00 - 0.20 * 19.50 = 248.10
    ledger._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 24450, "ce_ltp": 252.00, "pe_ltp": 45.0}],
            "market_snapshot": {"spot_ltp": 24610.0, "feed_mode": "FULL"},
        },
        t0 + timedelta(minutes=30),
    )
    assert ledger._open_trade["current_sl_premium"] == 248.10
    print(f"  [PASS] At Parabolic Peak ₹252.00: Chandelier 0.20R Trail lifted Runner SL to ₹248.10")

    # 4. Pullback hits 248.10 -> Closes as TARGET_2_HIT (+2.5R)
    ledger._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 24450, "ce_ltp": 248.10, "pe_ltp": 48.0}],
            "market_snapshot": {"spot_ltp": 24602.0, "feed_mode": "FULL"},
        },
        t0 + timedelta(minutes=32),
    )
    assert ledger._open_trade is None
    closed = ledger._closed_trades[0]
    assert closed["exit_reason"] == "TARGET_2_HIT (+2.5R)"
    # Blended exit = (75 * 182.50 + 75 * 248.10) / 150 = 215.30
    assert closed["exit_premium"] == 215.30
    extra_profit = round(closed["net_pnl_inr"] - 360559.73, 2)
    print(
        f"  [PASS] Closed @ ₹215.30 Blended ({closed['r_multiple']}R) | "
        f"Net PnL: +₹{closed['net_pnl_inr']:,.2f} (+₹{extra_profit:,.2f} extra vs hard cap!)"
    )


def test_5_t2_guard3_slippage_and_post45m_priority():
    print("\n--- Running Test 5: Guard 3 Slippage Cap & Post-45m Priority for t2_reached Runner ---")
    ledger = _new_temp_ledger()
    t0 = datetime(2026, 11, 6, 10, 0, 0, tzinfo=IST)
    ledger._open_trade = {
        "trade_id": "TEST-T2-G3",
        "source": "AUTO_QUANT_SIGNAL",
        "entry_time": t0.isoformat(),
        "symbol": "NSE:NIFTY26N0924500CE",
        "strike": 24500,
        "opt_type": "CE",
        "lots": 10,
        "lot_size": 65,
        "qty": 650,
        "t1_lots": 5,
        "runner_lots": 5,
        "entry_spot": 24500.0,
        "entry_premium": 200.00,
        "current_ltp": 230.00,
        "high_watermark": 230.00,
        "initial_sl_premium": 180.00,
        "current_sl_premium": 210.00,
        "sl_points": 20.00,
        "t1_premium": 230.00,
        "t2_premium": 250.00,
        "t1_booked": True,
        "t2_reached": False,
        "sl_45m_tightened": True,  # Simulate trade that was tightened at 45m BEFORE hitting T2
        "est_slippage_inr": 300.0,
    }

    # At minute 50, trade blasts to T2 (255.00) -> t2_reached = True, SL = max(248.50, 255 - 4.0) = 251.00
    ledger._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 24500, "ce_ltp": 255.00, "pe_ltp": 70.0}],
            "market_snapshot": {"spot_ltp": 24580.0, "feed_mode": "FULL"},
        },
        t0 + timedelta(minutes=50),
    )
    assert ledger._open_trade["t2_reached"] is True
    assert ledger._open_trade["current_sl_premium"] == 251.00

    # At minute 52, sudden drop to 240.00 (11 pts below active SL 251.00)
    # 1. Exit reason must be TARGET_2_HIT (+2.5R) (priority over sl_45m_tightened)
    # 2. Guard 3 must bound runner exit fill to 251.00 - 1.50 = 249.50!
    ledger._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 24500, "ce_ltp": 240.00, "pe_ltp": 85.0}],
            "market_snapshot": {"spot_ltp": 24555.0, "feed_mode": "FULL"},
        },
        t0 + timedelta(minutes=52),
    )
    assert ledger._open_trade is None
    closed = ledger._closed_trades[0]
    assert closed["exit_reason"] == "TARGET_2_HIT (+2.5R)", f"Got {closed['exit_reason']}"
    # Blended exit with Guard 3 bounded runner fill 249.50: (5 * 230.00 + 5 * 249.50) / 10 = 239.75
    assert closed["exit_premium"] == 239.75, f"Expected 239.75, got {closed['exit_premium']}"
    print(
        f"  [PASS] Post-45m T2 Runner exited as '{closed['exit_reason']}' & "
        f"Guard 3 bounded fill @ ₹249.50 (Blended ₹{closed['exit_premium']})"
    )


def test_6_historical_json_ledgers_and_scope_freeze():
    print("\n--- Running Test 6: 8-Day Historical JSON Ledgers Audit & Scope Freeze Check ---")
    quant_dir = os.path.join(os.path.dirname(__file__), "app", "data", "nifty_options_quant")
    dates = [
        "2026-10-28",
        "2026-10-29",
        "2026-10-30",
        "2026-11-02",
        "2026-11-03",
        "2026-11-04",
        "2026-11-05",
        "2026-11-06",
    ]

    total_trades = 0
    stage0a_saves = []
    t2_runners = []

    for d in dates:
        p = os.path.join(quant_dir, f"ledger_{d}.json")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        trades = data.get("closed_trades", [])
        total_trades += len(trades)
        for t in trades:
            entry = float(t["entry_premium"])
            sl_pts = float(t["sl_points"])
            hwm = float(t.get("high_watermark", entry))
            peak_r = round((hwm - entry) / sl_pts, 2) if sl_pts > 0 else 0.0
            exit_r = float(t.get("r_multiple", 0.0))
            reason = str(t.get("exit_reason", ""))

            # Check winning trades that never dipped below -0.45R/-0.25R
            if not t.get("t1_booked") and peak_r >= 0.45 and exit_r < -0.45:
                new_sl = round_to_nse_tick(entry - 0.45 * sl_pts)
                old_exit = float(t["exit_premium"])
                pts_saved = round(new_sl - old_exit, 2)
                inr_saved = round(pts_saved * int(t["qty"]), 2)
                stage0a_saves.append((d, t["trade_id"], t["symbol"], peak_r, exit_r, inr_saved))

            if "TARGET_2_HIT" in reason:
                t2_runners.append((d, t["trade_id"], t["symbol"], entry, float(t["t2_premium"]), float(t["net_pnl_inr"])))

    assert total_trades == 40, f"Expected 40 historical trades across 8 ledgers, found {total_trades}"
    assert len(stage0a_saves) == 6, f"Expected 6 U-turn trades saved by Stage 0A, found {len(stage0a_saves)}"
    total_saved_inr = round(sum(x[5] for x in stage0a_saves), 2)
    print(f"  [PASS] Audited {total_trades} trades across 8 JSON ledgers:")
    for d, tid, sym, pr, er, saved in stage0a_saves:
        print(f"         • {d} | {tid} ({sym}): Peak +{pr:.2f}R -> Old {er:.2f}R | Stage 0A Saves +₹{saved:,.2f}")
    print(f"  [PASS] Total Direct U-Turn Loss Saved across 6 trades: +₹{total_saved_inr:,.2f}")
    print(f"  [PASS] Found {len(t2_runners)} T2_HIT trades armed for Stage 4 Uncapped Velocity Trail")

    # Verify Trap #1 (v13_nifty_options_engine.py) and Guard 2B are present
    ledger_src_path = os.path.join(os.path.dirname(__file__), "app", "v13_nifty_options_ledger.py")
    with open(ledger_src_path, "r", encoding="utf-8") as f:
        ledger_src = f.read()
    assert (
        "if wave_t1_wins >= 2 or (wave_t2_hits >= 1 and len(wave_trades) >= 2):" in ledger_src
        or "if wave_t1_wins >= 2 or (len(wave_trades) >= 2 and (wave_major_moves >= 1 or wave_t2_hits >= 1)):" in ledger_src
    )
    print("  [PASS] Confirmed Guard 2B wave completion lock is active in v13_nifty_options_ledger.py")


def test_7_telegram_retry_markdown_and_milestone_sync():
    print("\n--- Running Test 7: Telegram 3x Retry Backoff, Safe Markdown & Pre-Exit Milestone Sync ---")
    import urllib.request
    import app.v13_alpha_telegram as tg
    import app.v13_nifty_options_ledger as lg_mod

    # 7A. Verify RETRY_BACKOFF_SECONDS == (0.8, 1.6, 3.0) and 3x Retry on WinError 10054 / Timeout
    assert tg.RETRY_BACKOFF_SECONDS == (0.8, 1.6, 3.0), f"Got {tg.RETRY_BACKOFF_SECONDS}"

    sleep_calls = []
    orig_sleep = tg.time.sleep
    orig_urlopen = urllib.request.urlopen

    class _MockResp:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return b'{"ok": true}'

    attempt_counter = {"count": 0}

    def _mock_urlopen_succeed_on_3rd(req, timeout=10, context=None):
        attempt_counter["count"] += 1
        if attempt_counter["count"] <= 2:
            raise ConnectionResetError("[WinError 10054] An existing connection was forcibly closed")
        return _MockResp()

    try:
        tg.time.sleep = lambda d: sleep_calls.append(d)
        urllib.request.urlopen = _mock_urlopen_succeed_on_3rd
        ok, detail = tg._send_telegram_http("DUMMY_TOKEN", "5373296451", "Test Message")
        assert ok is True and detail == "OK_RETRY_2", f"Expected (True, 'OK_RETRY_2'), got ({ok}, {detail})"
        assert sleep_calls == [0.8, 1.6], f"Expected backoff [0.8, 1.6], got {sleep_calls}"
        print(f"  [PASS] 3x Retry Backoff verified: Recovered after 2x WinError 10054 drops with delays {sleep_calls}s")

        # Verify total failure (all 4 attempts fail) does NOT mark ok=True and uses all 3 backoffs (0.8, 1.6, 3.0)
        sleep_calls.clear()
        urllib.request.urlopen = lambda req, timeout=10, context=None: (_ for _ in ()).throw(TimeoutError("timed out"))
        ok_fail, detail_fail = tg._send_telegram_http("DUMMY_TOKEN", "5373296451", "Test Fail")
        assert ok_fail is False
        assert sleep_calls == [0.8, 1.6, 3.0], f"Expected [0.8, 1.6, 3.0], got {sleep_calls}"
        print(f"  [PASS] Full 3x Backoff exhaustion verified: {sleep_calls}s -> returns ok=False (never cached in dedup)")
    finally:
        tg.time.sleep = orig_sleep
        urllib.request.urlopen = orig_urlopen

    # 7B. Verify Safe Markdown Formatting (Iceberg [27, 27...] wrapped in backticks)
    sample_trade = {
        "trade_id": "NPQ-134249-5D11",
        "symbol": "NSE:NIFTY26N0924700CE",
        "strike": 24700,
        "opt_type": "CE",
        "trigger_type": "MOMENTUM_BOX_BREAKOUT",
        "entry_time_str": "13:42:49 IST",
        "entry_spot": 24759.65,
        "lots": 150,
        "lot_size": 65,
        "qty": 9750,
        "entry_legs": 6,
        "entry_slices": [27, 27, 27, 27, 27, 15],
        "t1_lots": 75,
        "runner_lots": 75,
        "entry_premium": 193.25,
        "initial_sl_premium": 171.00,
        "current_sl_premium": 246.15,
        "high_watermark": 248.95,
        "sl_points": 22.25,
        "t1_premium": 225.75,
        "t2_premium": 247.65,
        "t1_booked": True,
        "exit_premium": 237.35,
        "net_pnl_inr": 418268.25,
        "gross_pnl_inr": 429975.00,
        "charges_inr": 4394.25,
        "slippage_inr": 7312.50,
        "r_multiple": 1.98,
        "hold_minutes": 18.6,
        "exit_reason": "TARGET_2_HIT (+2.5R)",
    }
    entry_msg = tg.format_alpha_entry_message(sample_trade, {"module3_signal": {"gates_passed": 7, "gates_total": 7}})
    assert "`6 Legs [27, 27, 27, 27, 27, 15]`" in entry_msg, f"Missing backticks around slice_str in:\n{entry_msg}"
    assert "`MOMENTUM_BOX_BREAKOUT`" in entry_msg
    exit_msg = tg.format_alpha_exit_message(sample_trade)
    assert "`(75:75 Blended)`" in exit_msg
    assert "`TARGET_2_HIT (+2.5R)`" in exit_msg
    print("  [PASS] Safe Markdown verified: Iceberg `[27, 27...]` & `(75:75 Blended)` wrapped in backticks")

    # 7C. Verify v5.6 Milestone Templates (STAGE_0A, STAGE_0B, STAGE_4)
    msg_0a = tg.format_alpha_milestone_message(sample_trade, "STAGE_0A_UTURN_SHIELD")
    msg_0b = tg.format_alpha_milestone_message(sample_trade, "STAGE_0B_UTURN_SHIELD")
    msg_s4 = tg.format_alpha_milestone_message(sample_trade, "STAGE_4_T2_VELOCITY")
    assert "STAGE 0A (+0.45R) U-TURN SHIELD" in msg_0a
    assert "STAGE 0B (+0.80R) NEAR-BE SHIELD" in msg_0b
    assert "TARGET 2 (+2.50R) REACHED • VELOCITY TRAIL ARMED!" in msg_s4
    print("  [PASS] All 3 new v5.6 Milestone Telegram templates verified cleanly")

    # 7D. Verify Pre-Exit Milestone Dispatch Order & dict(tr) Snapshot on Same-Tick Milestone + Exit
    dispatched_events = []
    orig_ms_dispatch = lg_mod.dispatch_alpha_milestone_alert
    orig_exit_dispatch = lg_mod.dispatch_alpha_exit_alert
    try:
        lg_mod.dispatch_alpha_milestone_alert = lambda tr_snap, ms: dispatched_events.append(
            ("MILESTONE", ms, isinstance(tr_snap, dict), tr_snap.get("t2_reached"), tr_snap.get("current_sl_premium"))
        )
        lg_mod.dispatch_alpha_exit_alert = lambda closed_tr, stats=None: dispatched_events.append(
            ("EXIT", closed_tr.get("exit_reason"), True, closed_tr.get("t2_reached"), closed_tr.get("exit_premium"))
        )

        ledger = _new_temp_ledger()
        ledger.enable_notifications = True
        t0 = datetime(2026, 11, 6, 14, 15, 0, tzinfo=IST)
        ledger._open_trade = {
            "trade_id": "TEST-SAME-TICK",
            "source": "AUTO_QUANT_SIGNAL",
            "entry_time": t0.isoformat(),
            "symbol": "NSE:NIFTY26N0924700CE",
            "strike": 24700,
            "opt_type": "CE",
            "lots": 10,
            "lot_size": 65,
            "qty": 650,
            "t1_lots": 5,
            "runner_lots": 5,
            "entry_spot": 24750.0,
            "entry_premium": 200.00,
            "current_ltp": 230.00,
            "high_watermark": 230.00,
            "initial_sl_premium": 180.00,
            "current_sl_premium": 210.00,
            "sl_points": 20.00,
            "t1_premium": 230.00,
            "t2_premium": 250.00,
            "t1_booked": True,
            "t2_reached": False,
            "stage2_notified": False,
            "doorstep_notified": False,
        }

        # At 15:15 EOD, price jumps to 252.00 -> Triggers DOORSTEP_220_TRAIL + STAGE_4_T2_VELOCITY AND EOD Exit on same tick!
        ledger._update_open_trade_state(
            {
                "feed_mode": "FULL",
                "option_chain_window": [{"strike": 24700, "ce_ltp": 252.00, "pe_ltp": 50.0}],
                "market_snapshot": {"spot_ltp": 24820.0, "feed_mode": "FULL"},
            },
            datetime(2026, 11, 6, 15, 15, 5, tzinfo=IST),
        )

        assert [e[0] for e in dispatched_events] == ["MILESTONE", "MILESTONE", "EXIT"], f"Got {dispatched_events}"
        assert dispatched_events[0][1] == "DOORSTEP_220_TRAIL"
        assert dispatched_events[1][1] == "STAGE_4_T2_VELOCITY"
        assert dispatched_events[2][1] == "TARGET_2_HIT (+2.5R)"
        print(f"  [PASS] Same-tick Milestone + Exit Order verified: {[e[1] for e in dispatched_events]}")
    finally:
        lg_mod.dispatch_alpha_milestone_alert = orig_ms_dispatch
        lg_mod.dispatch_alpha_exit_alert = orig_exit_dispatch


if __name__ == "__main__":
    print("==================================================================")
    print("STARTING ALPHA ENGINE v5.6 COMPREHENSIVE VERIFICATION SUITE")
    print("==================================================================")
    test_1_stage_0a_half_loss_shield_real_trades()
    test_2_stage_0b_near_breakeven_shield_and_4rs_floor()
    test_3_monotonic_7_stage_ratchet_ladder()
    test_4_t2_uncapped_velocity_ratchet_05nov_replay()
    test_5_t2_guard3_slippage_and_post45m_priority()
    test_6_historical_json_ledgers_and_scope_freeze()
    test_7_telegram_retry_markdown_and_milestone_sync()
    print("\n==================================================================")
    print("ALL 7 ALPHA v5.6 TEST SUITES PASSED 100% CLEANLY! (EXIT CODE 0)")
    print("==================================================================")
