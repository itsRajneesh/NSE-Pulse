"""
NSE Trading Calendar & Holiday Intelligence Engine.
Provides official trading holiday checks, next trading day calculation,
and advance holiday notifications for UI banners and Telegram EOD reports.
"""
from __future__ import annotations

import os
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple, Any
import pytz

IST_TZ = pytz.timezone("Asia/Kolkata")
HOLIDAYS_FILE = os.path.join(os.path.dirname(__file__), "data", "nse_holidays.json")

# Built-in fallback database to guarantee fail-safe operation
DEFAULT_NSE_HOLIDAYS: Dict[str, str] = {
    "2025-01-26": "Republic Day",
    "2025-02-26": "Mahashivratri",
    "2025-03-14": "Holi",
    "2025-03-31": "Id-Ul-Fitr (Ramzan Id)",
    "2025-04-10": "Mahavir Jayanti",
    "2025-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2025-04-18": "Good Friday",
    "2025-05-01": "Maharashtra Day",
    "2025-06-07": "Bakri Id",
    "2025-08-15": "Independence Day",
    "2025-08-27": "Ganesh Chaturthi",
    "2025-10-02": "Mahatma Gandhi Jayanti",
    "2025-10-21": "Dussehra",
    "2025-11-01": "Diwali Balipratipada",
    "2025-11-05": "Guru Nanak Jayanti",
    "2025-12-25": "Christmas",
    "2026-01-26": "Republic Day",
    "2026-02-15": "Mahashivratri",
    "2026-03-03": "Holi",
    "2026-03-20": "Id-Ul-Fitr (Ramzan Id)",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-27": "Bakri Id (Id-Ul-Zuha)",
    "2026-06-25": "Muharram",
    "2026-08-15": "Independence Day",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-10": "Diwali Balipratipada",
    "2026-11-24": "Guru Nanak Jayanti",
    "2026-12-25": "Christmas",
}


def load_nse_holidays() -> Dict[str, str]:
    """Load holidays from JSON file with in-memory fallback."""
    if os.path.exists(HOLIDAYS_FILE):
        try:
            with open(HOLIDAYS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return {**DEFAULT_NSE_HOLIDAYS, **data}
        except Exception:
            pass
    return dict(DEFAULT_NSE_HOLIDAYS)


NSE_HOLIDAYS = load_nse_holidays()


def is_nse_holiday(dt: Optional[datetime] = None) -> Tuple[bool, Optional[str]]:
    """
    Check if the given datetime (or current IST time) falls on an NSE trading holiday.
    Returns (True, "Mahatma Gandhi Jayanti") or (False, None).
    """
    check_dt = dt or datetime.now(IST_TZ)
    date_str = check_dt.strftime("%Y-%m-%d")
    holiday_name = NSE_HOLIDAYS.get(date_str)
    return bool(holiday_name), holiday_name


def get_next_trading_day(dt: Optional[datetime] = None) -> Tuple[datetime, str]:
    """
    Compute the next active trading day skipping both weekends (Sat/Sun) and NSE holidays.
    Returns (next_datetime, formatted_string) e.g. (datetime(2026, 10, 5), "Monday, 05 Oct 2026").
    """
    cur = dt or datetime.now(IST_TZ)
    step = timedelta(days=1)
    nxt = cur + step

    # Maximum lookahead 14 days to prevent runaway loops
    for _ in range(14):
        # 0=Monday ... 4=Friday, 5=Saturday, 6=Sunday
        is_weekend = nxt.weekday() >= 5
        nxt_date_str = nxt.strftime("%Y-%m-%d")
        is_holiday = nxt_date_str in NSE_HOLIDAYS

        if not is_weekend and not is_holiday:
            formatted = nxt.strftime("%A, %d %b %Y")
            return nxt, formatted

        nxt = nxt + step

    return nxt, nxt.strftime("%A, %d %b %Y")


def get_upcoming_holiday_notice(dt: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """
    Check if the immediate next calendar trading day is an NSE holiday.
    For example:
    - On Thursday before a Friday holiday: Flags tomorrow (Friday).
    - On Friday before a Monday holiday: Flags upcoming Monday.
    Returns metadata dict if an upcoming holiday exists, else None.
    """
    cur = dt or datetime.now(IST_TZ)
    cur_weekday = cur.weekday()

    # Look ahead 1 day (or up to Monday if today is Friday)
    days_to_check = 1
    if cur_weekday == 4:  # Friday -> look ahead to Monday (3 days)
        days_to_check = 3
    elif cur_weekday == 5:  # Saturday -> look ahead to Monday (2 days)
        days_to_check = 2

    target_dt = cur + timedelta(days=days_to_check)
    target_date_str = target_dt.strftime("%Y-%m-%d")

    holiday_name = NSE_HOLIDAYS.get(target_date_str)
    if holiday_name:
        _, next_session_str = get_next_trading_day(target_dt)
        return {
            "holiday_date": target_date_str,
            "holiday_day": target_dt.strftime("%A"),
            "holiday_name": holiday_name,
            "is_tomorrow": days_to_check == 1,
            "target_formatted": target_dt.strftime("%A, %d %b %Y"),
            "next_session_formatted": next_session_str,
        }

    return None


def format_holiday_telegram_notice(dt: Optional[datetime] = None) -> Optional[str]:
    """
    Format a high-visibility Telegram Markdown block warning traders about an upcoming holiday.
    Appended to EOD reports.
    """
    notice = get_upcoming_holiday_notice(dt)
    if not notice:
        return None

    when_str = "tomorrow" if notice["is_tomorrow"] else f"on {notice['holiday_day']}"
    box = (
        "=================================================\n"
        "📢 *UPCOMING MARKET HOLIDAY NOTICE*\n"
        "=================================================\n"
        f"⚠️ *NSE & BSE will remain strictly CLOSED {when_str}* ({notice['holiday_day']}, {notice['holiday_date']}) on account of:\n\n"
        f"🚩 *{notice['holiday_name'].upper()}*\n\n"
        "🏛️ Segments Closed: Equity, Derivatives (F&O) & Currency\n"
        f"🗓️ Next Trading Session: *{notice['next_session_formatted']}* at 09:15 AM IST\n"
        "================================================="
    )
    return box


def is_last_trading_day_of_week(dt: Optional[datetime] = None) -> bool:
    """
    Returns True if the given datetime represents the final trading session of the calendar week.
    - If today is Friday (weekday == 4): It's the standard final day of the week (if not a holiday).
    - If today is Monday-Thursday (0 <= weekday < 4):
      Checks if all remaining weekdays of this current week (up to Friday) are official NSE holidays.
      E.g., on Thursday 01 Oct 2026, since Friday 02 Oct is Gandhi Jayanti, Thursday is the final trading day!
    - If today itself is a holiday or weekend: Returns False.
    """
    cur = dt or datetime.now(IST_TZ)
    cur_date_str = cur.strftime("%Y-%m-%d")
    weekday = cur.weekday()

    # Weekends (Sat=5, Sun=6) or today being an official holiday cannot be the active last trading day
    if weekday >= 5 or cur_date_str in NSE_HOLIDAYS:
        return False

    # If today is Friday and not a holiday, it is the last trading day of the week
    if weekday == 4:
        return True

    # If today is Monday (0), Tuesday (1), Wednesday (2), or Thursday (3):
    # Check all future weekdays in this same week (weekday+1 through 4)
    for next_offset in range(1, 5 - weekday):
        nxt_day = cur + timedelta(days=next_offset)
        nxt_date_str = nxt_day.strftime("%Y-%m-%d")
        # If any upcoming weekday in this week is NOT a holiday, then today is NOT the last trading day
        if nxt_date_str not in NSE_HOLIDAYS:
            return False

    # All remaining weekdays this week are holidays! Today is the final trading day of the week
    return True
