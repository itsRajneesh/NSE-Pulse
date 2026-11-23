"""
Test script to dispatch a live simulated V13 Daily EOD Performance Audit directly to Telegram.
Validates end-to-end phone notification delivery and formatting.
"""

import os
import sys
import time

# Set utf-8 encoding for Windows console
os.environ["PYTHONIOENCODING"] = "utf-8"

from app.v13_ledger import SessionTradeLedger
from app.telegram_bot import send_telegram_text, get_telegram_config, _ALERT_QUEUE

def run_live_dispatch_test():
    print("=" * 70)
    print(">> TESTING LIVE TELEGRAM EOD PERFORMANCE AUDIT DISPATCH")
    print("=" * 70)

    # 1. Check configuration
    enabled, bot_token, chat_ids, min_score = get_telegram_config()
    print(f"Telegram Enabled : {enabled}")
    print(f"Bot Token Active : {'Yes (Length: ' + str(len(bot_token)) + ')' if bot_token else 'No'}")
    print(f"Target Chat IDs  : {chat_ids}")

    if not enabled or not bot_token or not chat_ids:
        print("\n[ERROR] Telegram is not configured in backend/.env!")
        return

    # 2. Build realistic session ledger with diverse outcomes
    test_file = os.path.join(os.path.dirname(__file__), "data", "test_temp_ledger.json")
    if os.path.exists(test_file):
        os.remove(test_file)

    ledger = SessionTradeLedger(data_file=test_file)

    # Setup 1: High Confidence caught at Base, T1 Win (+1.5R)
    ledger.update_from_scan([{
        "symbol": "TATACHEM", "name": "Tata Chemicals", "sector": "Chemicals",
        "score": 88.5, "price": 1085.0, "entry": 1050.0, "stop_loss": 1020.0,
        "target_1": 1080.0, "target_2": 1110.0, "t1_progress_pct": 116.7,
        "execution_status": "EARLY_TRIGGER", "first_detection_stage": "EARLY_TRIGGER"
    }])

    # Setup 2: Strong setup caught Early, Deep Runner T2 Hit (+2.5R)
    ledger.update_from_scan([{
        "symbol": "KPIGREEN", "name": "KPI Green Energy", "sector": "Renewables",
        "score": 83.0, "price": 825.0, "entry": 750.0, "stop_loss": 720.0,
        "target_1": 780.0, "target_2": 820.0, "t1_progress_pct": 180.0,
        "execution_status": "EARLY_TRIGGER", "first_detection_stage": "EARLY_TRIGGER"
    }])

    # Setup 3: Strong setup, Actionable play, Target 1 Hit (+1.5R)
    ledger.update_from_scan([{
        "symbol": "DIXON", "name": "Dixon Tech", "sector": "Electronics",
        "score": 81.5, "price": 13400.0, "entry": 13100.0, "stop_loss": 12900.0,
        "target_1": 13350.0, "target_2": 13600.0, "t1_progress_pct": 105.0,
        "execution_status": "ACTIONABLE_IN_PLAY", "first_detection_stage": "ACTIONABLE_IN_PLAY"
    }])

    # Setup 4: Watchlist setup, False breakout stopped out (-1.0R)
    ledger.update_from_scan([{
        "symbol": "INFY", "name": "Infosys", "sector": "IT",
        "score": 74.5, "price": 1880.0, "entry": 1920.0, "stop_loss": 1900.0,
        "target_1": 1950.0, "target_2": 1980.0, "t1_progress_pct": -200.0,
        "execution_status": "ACTIONABLE_IN_PLAY", "first_detection_stage": "ACTIONABLE_IN_PLAY"
    }])

    # Setup 5: High Confidence setup, Open / In-Play at 65% progression
    ledger.update_from_scan([{
        "symbol": "HDFCBANK", "name": "HDFC Bank", "sector": "Banking",
        "score": 86.0, "price": 1665.0, "entry": 1650.0, "stop_loss": 1630.0,
        "target_1": 1675.0, "target_2": 1700.0, "t1_progress_pct": 65.0,
        "execution_status": "EARLY_TRIGGER", "first_detection_stage": "EARLY_TRIGGER"
    }])

    # 3. Generate Telegram Report
    report = ledger.format_telegram_eod_report(market_regime="Bullish (Nifty: +0.54%)")
    print("\n[PREVIEW OF AUDIT MESSAGE TO BE DISPATCHED]:\n")
    print(report)
    print("\n" + "-" * 70)

    # 4. Dispatch to Telegram
    print(f"Queuing report to {len(chat_ids)} Telegram chat(s)...")
    success = send_telegram_text(report)
    if not success:
        print("[ERROR] send_telegram_text returned False.")
        return

    print("Waiting for queue worker to deliver message(s) via Telegram API...")
    # Wait for queue to drain
    _ALERT_QUEUE.join()
    time.sleep(1.0)
    print("\n[SUCCESS] Telegram dispatch completed! Please check your Telegram app.")

    # Cleanup temp file
    if os.path.exists(test_file):
        try:
            os.remove(test_file)
        except Exception:
            pass

if __name__ == "__main__":
    run_live_dispatch_test()
