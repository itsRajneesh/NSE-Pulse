"""
Test script for Telegram Live Alerts Bot.
Run this to send a test breakout alert to verify connection:
python test_telegram.py
"""

import sys
import os

# Ensure console supports utf-8 emojis on Windows
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# Add backend directory to sys.path
sys.path.insert(0, os.path.dirname(__file__))

from app.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_CHAT_IDS, TELEGRAM_ENABLED, TELEGRAM_MIN_SCORE
from app.telegram_bot import format_telegram_message, _send_telegram_http, get_telegram_config

def main():
    print("=== NSE-PULSE V13: Telegram Alerts Bot Test ===")
    enabled, bot_token, chat_ids, min_score = get_telegram_config()

    print(f"TELEGRAM_ENABLED: {enabled}")
    print(f"TELEGRAM_MIN_SCORE: {min_score}")
    print(f"TELEGRAM_BOT_TOKEN: {'[CONFIGURED]' if bot_token else '[NOT SET - Add to backend/.env]'}")
    print(f"TELEGRAM_CHAT_IDS ({len(chat_ids)}): {', '.join(chat_ids) if chat_ids else '[NOT SET - Add to backend/.env]'}")
    print("------------------------------------------------")

    sample_signal = {
        "symbol": "TATAMOTORS",
        "name": "Tata Motors Ltd.",
        "sector": "Automobile and Auto Components",
        "is_nifty500": True,
        "direction": "BULLISH",
        "score": 86.5,
        "ltp": 420.50,
        "price": 420.50,
        "risk": {
            "entry": 420.00,
            "stop_loss": 414.00,
            "target_1": 429.00,
            "target_2": 435.00,
            "risk_amount": 6.00,
        },
        "indicators": {
            "rel_vol": 4.18,
            "ema20": 416.20,
            "vwap": 418.50,
            "rsi14": 64.2,
        },
        "confirmation": {
            "reasons": ["Confirmed opening range breakout", "Very strong relative volume (4.18x)"]
        }
    }

    formatted_msg = format_telegram_message(sample_signal)
    print("SAMPLE FORMATTED MESSAGE:\n")
    print(formatted_msg)
    print("\n------------------------------------------------")

    if not bot_token or not chat_ids:
        print("\n[INFO] Bot Token ya Chat ID configure nahi hai.")
        print("Apne backend/.env file me TELEGRAM_BOT_TOKEN aur TELEGRAM_CHAT_ID enter karein.")
        print("Telegram bot setup guide:")
        print("1. Telegram par @BotFather ko /newbot bolkar token lein.")
        print("2. @userinfobot ko start karke apna Chat ID lein.")
        print("3. Dono ko backend/.env me dalein aur yeh script dobara run karein!")
        return

    print(f"Sending live test alert to {len(chat_ids)} recipient(s) via Telegram API...")
    for idx, cid in enumerate(chat_ids, 1):
        print(f"  [{idx}/{len(chat_ids)}] Dispatching to Chat ID {cid}...", end=" ")
        success = _send_telegram_http(bot_token, cid, formatted_msg)
        if success:
            print("[SUCCESS] 🎉 Sent!")
        else:
            print("[ERROR] ❌ Failed! Please verify Chat ID or ensure user has clicked /start on the bot.")

if __name__ == "__main__":
    main()
