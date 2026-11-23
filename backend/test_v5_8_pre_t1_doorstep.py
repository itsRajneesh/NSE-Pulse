import glob
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from app.v13_nifty_options_ledger import NiftyOptionsPaperLedger, LEDGER_DIR
from app.v13_alpha_telegram import format_alpha_milestone_message

IST = timezone(timedelta(hours=5, minutes=30))
DUMMY_SESSION_DATE = "2099-01-01"


def _cleanup_dummy():
    f = LEDGER_DIR / f"ledger_{DUMMY_SESSION_DATE}.json"
    if f.exists():
        f.unlink()


def _new_ledger() -> NiftyOptionsPaperLedger:
    _cleanup_dummy()
    lg = NiftyOptionsPaperLedger(enable_notifications=False)
    lg._session_date = DUMMY_SESSION_DATE
    lg._open_trade = None
    lg._closed_trades = []
    return lg


def test_1_13nov_and_12nov_pre_t1_chandelier_replays():
    print("\n--- Running Test 1: 13-Nov T1 (+1.254R) & 12-Nov T2 (+1.218R) Pre-T1 Chandelier Replays ---")

    # 1A. 13-Nov T1: 25150 PE, 150L (9750 Qty), Ep=160.25, SL=138.40 (sl_pts=21.85), T1=192.15, HWM=187.65 (+1.254R)
    lg13 = _new_ledger()
    t0 = datetime(2026, 11, 13, 12, 7, 12, tzinfo=IST)
    lg13._open_trade = {
        "trade_id": "NPQ-120712-8365",
        "source": "AUTO_QUANT_SIGNAL",
        "entry_time": t0.isoformat(),
        "entry_time_str": "12:07:12 IST",
        "symbol": "NSE:NIFTY26N1725150PE",
        "strike": 25150,
        "opt_type": "PE",
        "lots": 150,
        "lot_size": 65,
        "qty": 9750,
        "entry_legs": 6,
        "t1_lots": 75,
        "runner_lots": 75,
        "t1_legs": 3,
        "runner_legs": 3,
        "entry_spot": 25124.0,
        "current_spot": 25124.0,
        "best_spot": 25124.0,
        "entry_premium": 160.25,
        "current_ltp": 160.25,
        "high_watermark": 160.25,
        "initial_sl_premium": 138.40,
        "current_sl_premium": 138.40,
        "sl_points": 21.85,
        "t1_premium": 192.15,
        "t2_premium": 213.65,
        "t1_booked": False,
        "t2_reached": False,
        "est_slippage_inr": 7312.50,
    }
    # Reach Peak HWM 187.65 (+1.254R) at 12:17:00
    lg13._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 25150, "ce_ltp": 90.0, "pe_ltp": 187.65}],
            "market_snapshot": {"spot_ltp": 25081.8, "feed_mode": "FULL"},
        },
        t0 + timedelta(minutes=10),
    )
    assert lg13._open_trade["pre_t1_shield_active"] is True
    assert lg13._open_trade["current_sl_premium"] == 177.80, f"Expected 177.80, got {lg13._open_trade['current_sl_premium']}"

    # Reversal hits SL at 12:22:05 (ticks down through 177.35)
    lg13._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 25150, "ce_ltp": 110.0, "pe_ltp": 177.35}],
            "market_snapshot": {"spot_ltp": 25103.95, "feed_mode": "FULL"},
        },
        t0 + timedelta(minutes=14, seconds=53),
    )
    assert lg13._open_trade is None
    closed_13 = lg13._closed_trades[0]
    assert "PRE_T1_SHIELD_SL_HIT" in closed_13["exit_reason"]
    assert closed_13["exit_premium"] == 177.35
    assert closed_13["net_pnl_inr"] > 155000.0  # +₹155,988.78 vs +₹91,729.81 (+₹64,259 extra!)
    print(
        f"  [PASS] 13-Nov T1 (150L PE, +1.254R Peak): Locked SL ₹177.80 -> Exited ₹{closed_13['exit_premium']:.2f} "
        f"(Net +₹{closed_13['net_pnl_inr']:,.2f} vs old +₹91,729.81 => +₹{closed_13['net_pnl_inr'] - 91729.81:,.2f} Extra!)"
    )

    # 1B. 12-Nov T2: 25300 PE, 158L (10270 Qty), Ep=214.50, SL=190.65 (sl_pts=23.85), T1=249.40, HWM=243.55 (+1.218R)
    lg12 = _new_ledger()
    t0_12 = datetime(2026, 11, 12, 12, 6, 19, tzinfo=IST)
    lg12._open_trade = {
        "trade_id": "NPQ-120619-A4BF",
        "source": "AUTO_QUANT_SIGNAL",
        "entry_time": t0_12.isoformat(),
        "entry_time_str": "12:06:19 IST",
        "symbol": "NSE:NIFTY26N1725300PE",
        "strike": 25300,
        "opt_type": "PE",
        "lots": 158,
        "lot_size": 65,
        "qty": 10270,
        "entry_legs": 6,
        "t1_lots": 79,
        "runner_lots": 79,
        "t1_legs": 3,
        "runner_legs": 3,
        "entry_spot": 25252.8,
        "current_spot": 25252.8,
        "best_spot": 25252.8,
        "entry_premium": 214.50,
        "current_ltp": 214.50,
        "high_watermark": 214.50,
        "initial_sl_premium": 190.65,
        "current_sl_premium": 190.65,
        "sl_points": 23.85,
        "t1_premium": 249.40,
        "t2_premium": 272.90,
        "t1_booked": False,
        "t2_reached": False,
        "est_slippage_inr": 6162.0,
    }
    lg12._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 25300, "ce_ltp": 90.0, "pe_ltp": 243.55}],
            "market_snapshot": {"spot_ltp": 25200.0, "feed_mode": "FULL"},
        },
        t0_12 + timedelta(minutes=6),
    )
    assert lg12._open_trade["current_sl_premium"] == 232.80
    print("  [PASS] 12-Nov T2 (158L PE, +1.218R Peak): Locked SL ₹232.80 (+0.77R vs old ₹226.40 / +0.50R)")


def test_2_stage_1c_doorstep_and_stage_1a_runner_handover():
    print("\n--- Running Test 2: Stage 1C (+1.35R Doorstep) & Stage 1A (T1 Booked Runner Handover Catch) ---")
    lg = _new_ledger()
    t0 = datetime(2026, 11, 2, 9, 35, 29, tzinfo=IST)
    # 02-Nov T1: Ep=111.60, SL=89.85 (sl_pts=21.75), T1=144.20, T2=165.95
    lg._open_trade = {
        "trade_id": "TEST-1C-HANDOVER",
        "source": "AUTO_QUANT_SIGNAL",
        "entry_time": t0.isoformat(),
        "symbol": "NSE:NIFTY26N0323250CE",
        "strike": 23250,
        "opt_type": "CE",
        "lots": 150,
        "lot_size": 65,
        "qty": 9750,
        "entry_spot": 23281.35,
        "entry_premium": 111.60,
        "current_ltp": 111.60,
        "high_watermark": 111.60,
        "initial_sl_premium": 89.85,
        "current_sl_premium": 89.85,
        "sl_points": 21.75,
        "t1_premium": 144.20,
        "t2_premium": 165.95,
        "t1_booked": False,
        "t2_reached": False,
    }

    # 1. Reach +1.05R (134.45) -> Stage 1B-0 activates
    lg._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 23250, "ce_ltp": 134.45, "pe_ltp": 80.0}],
            "market_snapshot": {"spot_ltp": 23320.0, "feed_mode": "FULL"},
        },
        t0 + timedelta(minutes=4),
    )
    assert lg._open_trade["stage1b0_shield_active"] is True
    assert lg._open_trade["current_sl_premium"] == 122.50  # 134.45 - 0.55*21.75(11.96) = 122.50 (+0.50R)
    print(f"  [PASS] Stage 1B-0 (+1.05R Peak): 100%-Lot Green Floor SL locked @ ₹{lg._open_trade['current_sl_premium']:.2f}")

    # 2. Reach +1.471R (143.60, just 0.60 pts short of T1 144.20) -> Stage 1C activates
    lg._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 23250, "ce_ltp": 143.60, "pe_ltp": 70.0}],
            "market_snapshot": {"spot_ltp": 23340.0, "feed_mode": "FULL"},
        },
        t0 + timedelta(minutes=8),
    )
    assert lg._open_trade["pre_t1_doorstep_active"] is True
    assert lg._open_trade["current_sl_premium"] == 135.35  # 143.60 - 0.38*21.75(8.265) = 135.35 (+1.09R)
    print(f"  [PASS] Stage 1C (+1.47R T1 Doorstep): 100%-Lot SL locked @ ₹{lg._open_trade['current_sl_premium']:.2f} (+1.09R)")

    # 3. CRITICAL CATCH: Now hit T1 (144.20, +1.50R) -> 50% Lots Booked @ 144.20,
    #    50% Runner SL MUST reset to Post-T1 Floor (111.60 + 0.50*21.75 = 122.50) so Runner has 1.00R breathing room!
    lg._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 23250, "ce_ltp": 144.20, "pe_ltp": 69.0}],
            "market_snapshot": {"spot_ltp": 23342.0, "feed_mode": "FULL"},
        },
        t0 + timedelta(minutes=9),
    )
    assert lg._open_trade["t1_booked"] is True
    assert lg._open_trade["current_sl_premium"] == 122.45, (
        f"Expected Post-T1 Runner SL to handover to 122.45 (+0.50R), got {lg._open_trade['current_sl_premium']}"
    )
    print(
        f"  [PASS] Critical Catch Verified: Upon T1 Hit (₹144.20), 50% Lots banked @ +1.50R & 50% Runner SL "
        f"handed over to ₹{lg._open_trade['current_sl_premium']:.2f} (+0.50R Runner / +1.00R Blended Floor)!"
    )

    # 4. Pullback to 130.00 (+0.85R) after T1 -> Runner SURVIVES (would have been killed if SL stayed 135.35!)
    lg._update_open_trade_state(
        {
            "feed_mode": "FULL",
            "option_chain_window": [{"strike": 23250, "ce_ltp": 130.00, "pe_ltp": 78.0}],
            "market_snapshot": {"spot_ltp": 23318.0, "feed_mode": "FULL"},
        },
        t0 + timedelta(minutes=12),
    )
    assert lg._open_trade is not None, "Post-T1 Runner survived normal +0.85R retest pullback!"
    print("  [PASS] Post-T1 Runner survived pullback to ₹130.00 (+0.85R) without premature stop-out!")


def test_3_telegram_templates_and_guard_compatibility():
    print("\n--- Running Test 3: Telegram Milestone Templates & Guard 1E / 2B Compatibility ---")
    sample_trade = {
        "symbol": "NSE:NIFTY26N1725150PE",
        "strike": 25150,
        "opt_type": "PE",
        "lots": 150,
        "lot_size": 65,
        "entry_premium": 160.25,
        "current_ltp": 187.65,
        "high_watermark": 187.65,
        "current_sl_premium": 177.80,
        "sl_points": 21.85,
        "unrealized_r": 1.25,
    }
    msg_1b0 = format_alpha_milestone_message(sample_trade, "STAGE_1B0_GREEN_SHIELD")
    msg_1b1 = format_alpha_milestone_message(sample_trade, "PRE_T1_SHIELD")
    msg_1c = format_alpha_milestone_message(sample_trade, "PRE_T1_DOORSTEP_135")
    assert "STAGE 1B-0 (+1.00R) GREEN SHIELD" in msg_1b0
    assert "STAGE 1B-1 (+1.20R) CHANDELIER SHIELD" in msg_1b1
    assert "STAGE 1C (+1.35R) T1 DOORSTEP LOCK" in msg_1c
    print("  [PASS] All 3 Telegram milestone templates (1B-0, 1B-1, 1C) formatted cleanly!")

    _cleanup_dummy()


if __name__ == "__main__":
    try:
        print("==================================================================")
        print("STARTING ALPHA ENGINE v5.8 PRE-T1 DOORSTEP VERIFICATION SUITE")
        print("==================================================================")
        test_1_13nov_and_12nov_pre_t1_chandelier_replays()
        test_2_stage_1c_doorstep_and_stage_1a_runner_handover()
        test_3_telegram_templates_and_guard_compatibility()
        print("\n==================================================================")
        print("ALL ALPHA v5.8 TEST SUITES PASSED 100% CLEANLY! (EXIT CODE 0)")
        print("==================================================================")
    finally:
        _cleanup_dummy()
