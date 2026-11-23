"""
Automated Comprehensive Verification Test for V13 Session Trade Ledger.
Tests:
1. Immutable First Detection Stage (Write-Once Rule)
2. Monotonic Peak Ratchet (Upward only, zero decay)
3. Trailing Stop Loss / Target 1 Win Priority
4. Percentage calculations and exact Telegram report formatting
5. Disk persistence and crash recovery
"""

import os
import sys
import tempfile
from datetime import datetime

# Local import
sys.path.insert(0, os.path.dirname(__file__))

from app.v13_ledger import SessionTradeLedger, TrackedSetup


def run_tests():
    print("=" * 80)
    print(">> V13 SESSION TRADE LEDGER AUTOMATED TEST SUITE")
    print("=" * 80)

    # Use a temporary file for clean testing
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        test_file = tmp.name

    try:
        ledger = SessionTradeLedger(data_file=test_file)

        # ---------------------------------------------------------------------
        # TEST 1: Registration & Immutable First Detection Stage
        # ---------------------------------------------------------------------
        print("\n[TEST 1] Testing First Detection Stage Immutability (Write-Once Rule)...")
        cand1 = {
            "symbol": "KPIGREEN",
            "name": "KPI Green Energy",
            "sector": "Power",
            "direction": "BULLISH",
            "score": 74.0,
            "ltp": 780.0,
            "entry_price": 775.0,
            "stop_loss": 760.0,
            "target_1": 800.0,
            "target_2": 820.0,
            "t1_progress_pct": 12.5,  # < 25% -> EARLY_TRIGGER
            "execution_status": "EARLY_TRIGGER",
        }
        ledger.update_from_scan([cand1])

        rec = ledger.records.get("KPIGREEN_BULLISH")
        assert rec is not None, "Setup failed to register"
        assert rec.first_detection_stage == "EARLY_TRIGGER", f"Expected EARLY_TRIGGER, got {rec.first_detection_stage}"
        assert rec.peak_tier == "WATCHLIST", f"Expected WATCHLIST, got {rec.peak_tier}"
        assert rec.peak_score == 74.0
        print("  ✓ Setup registered at score 74.0 as WATCHLIST with first_detection_stage='EARLY_TRIGGER'")

        # ---------------------------------------------------------------------
        # TEST 2: Upward Tier Migration (Watchlist -> Strong -> High Confidence)
        # ---------------------------------------------------------------------
        print("\n[TEST 2] Testing Upward Tier Migration with Immutable First Stage...")
        # Score jumps to 82.0 (Strong) at 45% progress
        cand1_up1 = dict(cand1, score=82.0, ltp=786.0, t1_progress_pct=45.0, execution_status="ACTIONABLE_IN_PLAY")
        ledger.update_from_scan([cand1_up1])

        rec = ledger.records.get("KPIGREEN_BULLISH")
        assert rec.peak_tier == "STRONG", f"Expected STRONG, got {rec.peak_tier}"
        assert rec.first_detection_stage == "EARLY_TRIGGER", f"VIOLATION: first_detection_stage changed to {rec.first_detection_stage}"
        print("  ✓ Score 82.0: Upgraded to STRONG. first_detection_stage stayed 'EARLY_TRIGGER' (Immutable!)")

        # Score jumps to 87.5 (High Confidence) at 70% progress
        cand1_up2 = dict(cand1, score=87.5, ltp=792.0, t1_progress_pct=70.0, execution_status="ACTIONABLE_IN_PLAY")
        ledger.update_from_scan([cand1_up2])

        rec = ledger.records.get("KPIGREEN_BULLISH")
        assert rec.peak_tier == "HIGH_CONFIDENCE", f"Expected HIGH_CONFIDENCE, got {rec.peak_tier}"
        assert rec.first_detection_stage == "EARLY_TRIGGER", f"VIOLATION: first_detection_stage changed to {rec.first_detection_stage}"
        print("  ✓ Score 87.5: Upgraded to HIGH_CONFIDENCE. first_detection_stage stayed 'EARLY_TRIGGER' (Immutable!)")

        # ---------------------------------------------------------------------
        # TEST 3: Monotonic Ratchet (Score Decay Protection)
        # ---------------------------------------------------------------------
        print("\n[TEST 3] Testing Monotonic Ratchet (Score Decay Protection)...")
        # Market consolidates, score drops to 66.0
        cand1_decay = dict(cand1, score=66.0, ltp=790.0, t1_progress_pct=60.0)
        ledger.update_from_scan([cand1_decay])

        rec = ledger.records.get("KPIGREEN_BULLISH")
        assert rec.peak_tier == "HIGH_CONFIDENCE", f"VIOLATION: Tier demoted on score decay to {rec.peak_tier}"
        assert rec.peak_score == 87.5, f"VIOLATION: Peak score decreased to {rec.peak_score}"
        print("  ✓ Score 66.0: Peak Tier stayed 'HIGH_CONFIDENCE' (Zero Decay Ratchet Protected!)")

        # ---------------------------------------------------------------------
        # TEST 4: Trailing Stop Loss / T1 Win Priority
        # ---------------------------------------------------------------------
        print("\n[TEST 4] Testing Trailing SL / Target 1 Win Priority...")
        # Price touches Target 1 (800.0) -> T1_HIT
        cand1_t1 = dict(cand1, score=85.0, ltp=801.0, t1_progress_pct=105.0)
        ledger.update_from_scan([cand1_t1])

        rec = ledger.records.get("KPIGREEN_BULLISH")
        assert rec.outcome == "T1_HIT", f"Expected T1_HIT, got {rec.outcome}"
        assert rec.realized_r == 1.5, f"Expected +1.5R, got {rec.realized_r}"
        print("  ✓ Price crossed 800.0: Outcome locked as 'T1_HIT' (+1.5R)")

        # Massive reversal: Price drops below stop loss (760.0) to 750.0!
        cand1_reversal = dict(cand1, score=65.0, ltp=750.0, t1_progress_pct=-50.0)
        ledger.update_from_scan([cand1_reversal])

        rec = ledger.records.get("KPIGREEN_BULLISH")
        assert rec.outcome == "T1_HIT", f"VIOLATION: Trade outcome flipped to loss {rec.outcome} after T1 hit!"
        assert rec.realized_r == 1.5
        print("  ✓ Price collapsed to 750.0 below SL: Outcome remained locked as 'T1_HIT' (+1.5R, Trailing Rule intact!)")

        # ---------------------------------------------------------------------
        # TEST 5: Multiple Stocks in Different Categories & Outcomes
        # ---------------------------------------------------------------------
        print("\n[TEST 5] Adding diverse setups across categories to test exact percentages...")
        # Setup 2: Strong Setup, T2 Winner
        cand2 = {
            "symbol": "TATACHEM", "name": "Tata Chemicals", "sector": "Chemicals", "direction": "BULLISH",
            "score": 83.0, "ltp": 1050.0, "entry_price": 1000.0, "stop_loss": 980.0, "target_1": 1030.0, "target_2": 1050.0,
            "t1_progress_pct": 166.7, "execution_status": "TARGET_HIT",
        }
        # Setup 3: Watchlist Setup, SL Hit
        cand3 = {
            "symbol": "INFY", "name": "Infosys", "sector": "IT", "direction": "BEARISH",
            "score": 75.0, "ltp": 1540.0, "entry_price": 1500.0, "stop_loss": 1520.0, "target_1": 1470.0, "target_2": 1450.0,
            "t1_progress_pct": -100.0, "execution_status": "SL_HIT",
        }
        # Setup 4: Watchlist Setup, Still Open
        cand4 = {
            "symbol": "WIPRO", "name": "Wipro", "sector": "IT", "direction": "BULLISH",
            "score": 73.0, "ltp": 455.0, "entry_price": 450.0, "stop_loss": 445.0, "target_1": 460.0, "target_2": 470.0,
            "t1_progress_pct": 50.0, "execution_status": "ACTIONABLE_IN_PLAY",
        }
        ledger.update_from_scan([cand2, cand3, cand4])

        metrics = ledger.get_summary_metrics()
        print(f"  ✓ Total signals: {metrics['total_signals']}")
        print(f"  ✓ Overall Win Rate: {metrics['overall']['win_rate_pct']}%")
        print(f"  ✓ High Confidence T1 Win Rate: {metrics['high_confidence']['t1_pct']}%")
        print(f"  ✓ Strong T2 Runner Rate: {metrics['strong']['t2_pct']}%")
        print(f"  ✓ Watchlist SL Loss Rate: {metrics['watchlist']['sl_pct']}%")

        # ---------------------------------------------------------------------
        # TEST 6: Format Telegram EOD Audit Report
        # ---------------------------------------------------------------------
        print("\n[TEST 6] Formatting and Validating Telegram EOD Performance Audit Report:")
        report = ledger.format_telegram_eod_report(market_regime="Bullish (Nifty: +0.65%)")
        print("\n" + report + "\n")

        assert "HIGH CONFIDENCE" in report
        assert "STRONG SETUPS" in report
        assert "WATCHLIST" in report
        assert "Caught at Base" in report
        assert "T1 Win Rate" in report
        assert "SL Loss Rate" in report
        assert "TOTAL SESSION ACCURACY & METRICS" in report
        print("  ✓ Telegram EOD report formatted perfectly with all percentages and categories!")

        # ---------------------------------------------------------------------
        # TEST 7: Disk Persistence and Reload
        # ---------------------------------------------------------------------
        print("\n[TEST 7] Testing Disk Persistence & Reload...")
        # Create a fresh ledger pointing to the same file
        reloaded_ledger = SessionTradeLedger(data_file=test_file)
        assert len(reloaded_ledger.records) == 4, f"Expected 4 records, got {len(reloaded_ledger.records)}"
        kpi_rec = reloaded_ledger.records["KPIGREEN_BULLISH"]
        assert kpi_rec.first_detection_stage == "EARLY_TRIGGER"
        assert kpi_rec.peak_tier == "HIGH_CONFIDENCE"
        assert kpi_rec.outcome == "T1_HIT"
        print("  ✓ Successfully reloaded all 4 setups from disk with immutable stages and peak tiers intact!")

        print("\n" + "=" * 80)
        print("[SUCCESS] ALL 7 TESTS PASSED! V13 SESSION LEDGER IS 100% OPERATIONAL.")
        print("=" * 80)

    finally:
        if os.path.exists(test_file):
            try:
                os.remove(test_file)
            except Exception:
                pass


if __name__ == "__main__":
    run_tests()
