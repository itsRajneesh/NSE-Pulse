"""
NSE Screener Configuration: Nifty 500 constituents, market timings, and quantitative thresholds.
"""
import os
import json
from datetime import time
import pytz

try:
    from dotenv import load_dotenv
    # Load backend/.env if present, otherwise root .env
    env_backend = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_backend):
        load_dotenv(env_backend, override=True)
    else:
        load_dotenv(override=True)
except ImportError:
    pass

IST_TZ = pytz.timezone('Asia/Kolkata')

# NSE Market Timings (IST)
MARKET_OPEN_TIME = time(9, 15)
MARKET_CLOSE_TIME = time(15, 30)

# EOD / Session Rollover Timing (IST)
# Configurable via EOD_RESET_TIME in .env (Format: "HH:MM", e.g. "09:00", "08:30", "08:45")
EOD_RESET_TIME_STR = os.getenv("EOD_RESET_TIME", "09:00").strip()
try:
    _r_h, _r_m = [int(x) for x in EOD_RESET_TIME_STR.split(":")]
    _parsed_reset_time = time(_r_h, _r_m)
    # Market safety guard: Reset cannot happen during active market hours (09:15 to 15:30)
    if time(9, 15) <= _parsed_reset_time <= time(15, 30):
        EOD_RESET_TIME = time(9, 0)
        EOD_RESET_TIME_STR = "09:00"
    else:
        EOD_RESET_TIME = _parsed_reset_time
except Exception:
    EOD_RESET_TIME = time(9, 0)
    EOD_RESET_TIME_STR = "09:00"


# Strategy Thresholds
DEFAULT_PRICE_CHANGE_THRESHOLD = 1.5  # % (+1.5% Bullish, -1.5% Bearish)
DEFAULT_REL_VOL_THRESHOLD = 1.5       # Relative Volume >= 1.5x
DEFAULT_EMA_PERIOD = 20
DEFAULT_RSI_PERIOD = 14
DEFAULT_RSI_BULLISH_THRESHOLD = 50.0
DEFAULT_RSI_BEARISH_THRESHOLD = 50.0
DEFAULT_VOL_LOOKBACK_DAYS = 10

# NIFTY 50 Options Quant: Dynamic Max Outlay Protection (% of capital)
try:
    _env_outlay = float(os.getenv("NIFTY_OPTIONS_MAX_OUTLAY_PCT", "30").strip())
    DEFAULT_NIFTY_OPTIONS_MAX_OUTLAY_PCT = (_env_outlay / 100.0) if _env_outlay > 1.0 else _env_outlay
    DEFAULT_NIFTY_OPTIONS_MAX_OUTLAY_PCT = max(0.05, min(DEFAULT_NIFTY_OPTIONS_MAX_OUTLAY_PCT, 1.0))
except Exception:
    DEFAULT_NIFTY_OPTIONS_MAX_OUTLAY_PCT = 0.30

# In-Memory Cache TTL Settings
CACHE_TTL_LIVE = 60       # 60 seconds TTL during active market
CACHE_TTL_CLOSED = 300    # 5 minutes TTL during off-market

# Load Stock Universe (Default: 1,468 Stocks >= 1,000 Cr Market Cap)
NIFTY_500_FILE = os.path.join(os.path.dirname(__file__), "data", "nifty500.json")
UNIVERSE_1000CR_FILE = os.path.join(os.path.dirname(__file__), "data", "universe_1000cr.json")

NIFTY_500_SYMBOLS = set()
if os.path.exists(NIFTY_500_FILE):
    try:
        with open(NIFTY_500_FILE, "r", encoding="utf-8") as f:
            NIFTY_500_SYMBOLS = {s["symbol"] for s in json.load(f)}
    except Exception:
        pass

DATA_FILE = UNIVERSE_1000CR_FILE if os.path.exists(UNIVERSE_1000CR_FILE) else NIFTY_500_FILE

if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        _raw_stocks = json.load(f)
        for s in _raw_stocks:
            s["is_nifty500"] = s.get("symbol") in NIFTY_500_SYMBOLS
        NIFTY_500_STOCKS = _raw_stocks
else:
    NIFTY_500_STOCKS = []

# Aliases for clarity and backward compatibility
UNIVERSE_STOCKS = NIFTY_500_STOCKS
CORE_NIFTY_500_STOCKS = [s for s in NIFTY_500_STOCKS if s.get("is_nifty500")]
NIFTY_50_STOCKS = NIFTY_500_STOCKS[:50] if len(NIFTY_500_STOCKS) >= 50 else NIFTY_500_STOCKS

# Extracted Sectors across all universe constituents
SECTORS = sorted(list(set(s["sector"] for s in NIFTY_500_STOCKS if s.get("sector"))))


# V5 sector benchmark mapping for Yahoo Finance
SECTOR_BENCHMARKS = {
    "Automobile and Auto Components": "^CNXAUTO",
    "Financial Services": "^NSEBANK",
    "Information Technology": "^CNXIT",
    "Healthcare": "^CNXPHARMA",
    "Fast Moving Consumer Goods": "^CNXFMCG",
    "Metals & Mining": "^CNXMETAL",
    "Realty": "^CNXREALTY",
    "Media Entertainment & Publication": "^CNXMEDIA",
    "Oil Gas & Consumable Fuels": "^CNXENERGY",
}

# -------------------------------------------------------------
# 100% Free Telegram Live Alerts Bot Configuration
# -------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_raw_chat_id = os.getenv("TELEGRAM_CHAT_IDS", "").strip() or os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_CHAT_IDS = [cid.strip() for cid in _raw_chat_id.split(",") if cid.strip()]
TELEGRAM_CHAT_ID = TELEGRAM_CHAT_IDS[0] if TELEGRAM_CHAT_IDS else ""
try:
    TELEGRAM_MIN_SCORE = float(str(os.getenv("TELEGRAM_MIN_SCORE", "75.0")).replace("%", "").strip())
except (ValueError, TypeError):
    TELEGRAM_MIN_SCORE = 75.0

try:
    TELEGRAM_MAX_T1_PROGRESS = float(str(os.getenv("TELEGRAM_MAX_T1_PROGRESS", "25.0")).replace("%", "").strip())
except (ValueError, TypeError):
    TELEGRAM_MAX_T1_PROGRESS = 25.0

TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "true").lower() in ("true", "1", "yes")

# -------------------------------------------------------------
# Real-Time Conviction Rating & "Take Trade" Stamp (Toggleable)
# -------------------------------------------------------------
ENABLE_CONVICTION_RATING = os.getenv("ENABLE_CONVICTION_RATING", "true").lower() in ("true", "1", "yes")

# -------------------------------------------------------------
# Dedicated NSE Live Movers 20-EMA VIP Telegram Alerts
# -------------------------------------------------------------
TELEGRAM_LIVE_MOVERS_ENABLED = os.getenv("TELEGRAM_LIVE_MOVERS_ENABLED", "true").lower() in ("true", "1", "yes")
TELEGRAM_LIVE_MOVERS_BOT_TOKEN = os.getenv("TELEGRAM_LIVE_MOVERS_BOT_TOKEN", "").strip()
_raw_lm_chat = os.getenv("TELEGRAM_LIVE_MOVERS_CHAT_ID", "").strip() or os.getenv("TELEGRAM_LIVE_MOVERS_CHAT_IDS", "").strip()
TELEGRAM_LIVE_MOVERS_CHAT_IDS = [cid.strip() for cid in _raw_lm_chat.split(",") if cid.strip()]
try:
    TELEGRAM_LIVE_MOVERS_MIN_SCORE = float(str(os.getenv("TELEGRAM_LIVE_MOVERS_MIN_SCORE", "65.0")).replace("%", "").strip())
except (ValueError, TypeError):
    TELEGRAM_LIVE_MOVERS_MIN_SCORE = 65.0

try:
    TELEGRAM_LIVE_MOVERS_COOLDOWN_MINUTES = float(str(os.getenv("TELEGRAM_LIVE_MOVERS_COOLDOWN_MINUTES", "90.0")).strip())
except (ValueError, TypeError):
    TELEGRAM_LIVE_MOVERS_COOLDOWN_MINUTES = 90.0

# -------------------------------------------------------------
# NIFTY-PULSE QUANT: Daily Paper Trade Limits & Forward Testing Controls
# -------------------------------------------------------------
try:
    NIFTY_OPTIONS_MAX_TRADES_PER_DAY = int(str(os.getenv("NIFTY_OPTIONS_MAX_TRADES_PER_DAY", "20")).strip())
except (ValueError, TypeError):
    NIFTY_OPTIONS_MAX_TRADES_PER_DAY = 20

try:
    NIFTY_OPTIONS_MAX_CONSECUTIVE_LOSSES = int(str(os.getenv("NIFTY_OPTIONS_MAX_CONSECUTIVE_LOSSES", "3")).strip())
except (ValueError, TypeError):
    NIFTY_OPTIONS_MAX_CONSECUTIVE_LOSSES = 3

try:
    NIFTY_OPTIONS_POST_T1_STEPUP_MINUTES = float(str(os.getenv("NIFTY_OPTIONS_POST_T1_STEPUP_MINUTES", "45")).strip())
except (ValueError, TypeError):
    NIFTY_OPTIONS_POST_T1_STEPUP_MINUTES = 45.0

try:
    NIFTY_OPTIONS_POST_T1_MAX_HOLD_MINUTES = float(str(os.getenv("NIFTY_OPTIONS_POST_T1_MAX_HOLD_MINUTES", "60")).strip())
except (ValueError, TypeError):
    NIFTY_OPTIONS_POST_T1_MAX_HOLD_MINUTES = 60.0

try:
    NIFTY_OPTIONS_POST_T1_LOCK_R = float(str(os.getenv("NIFTY_OPTIONS_POST_T1_LOCK_R", "0.5")).strip())
except (ValueError, TypeError):
    NIFTY_OPTIONS_POST_T1_LOCK_R = 0.5

# -------------------------------------------------------------
# ⚡ ALPHA QUANT: Dedicated NIFTY 50 Options Telegram Bot
# -------------------------------------------------------------
TELEGRAM_ALPHA_ENABLED = os.getenv("TELEGRAM_ALPHA_ENABLED", "true").lower() in ("true", "1", "yes")
TELEGRAM_ALPHA_BOT_TOKEN = os.getenv("TELEGRAM_ALPHA_BOT_TOKEN", "").strip()
_raw_alpha_chat = (
    os.getenv("TELEGRAM_ALPHA_CHAT_ID", "").strip()
    or os.getenv("TELEGRAM_ALPHA_CHAT_IDS", "").strip()
)
TELEGRAM_ALPHA_CHAT_IDS = [cid.strip() for cid in _raw_alpha_chat.split(",") if cid.strip()]
TELEGRAM_ALPHA_NOTIFY_ENTRIES = os.getenv("TELEGRAM_ALPHA_NOTIFY_ENTRIES", "true").lower() in ("true", "1", "yes")
TELEGRAM_ALPHA_NOTIFY_EXITS = os.getenv("TELEGRAM_ALPHA_NOTIFY_EXITS", "true").lower() in ("true", "1", "yes")
TELEGRAM_ALPHA_NOTIFY_MILESTONES = os.getenv("TELEGRAM_ALPHA_NOTIFY_MILESTONES", "true").lower() in ("true", "1", "yes")
TELEGRAM_ALPHA_NOTIFY_KILLSWITCH = os.getenv("TELEGRAM_ALPHA_NOTIFY_KILLSWITCH", "true").lower() in ("true", "1", "yes")



