"""
NSE Screener Configuration: Nifty 500 constituents, market timings, and quantitative thresholds.
"""
import os
import json
from datetime import time
import pytz

IST_TZ = pytz.timezone('Asia/Kolkata')

# NSE Market Timings (IST)
MARKET_OPEN_TIME = time(9, 15)
MARKET_CLOSE_TIME = time(15, 30)

# Strategy Thresholds
DEFAULT_PRICE_CHANGE_THRESHOLD = 1.5  # % (+1.5% Bullish, -1.5% Bearish)
DEFAULT_REL_VOL_THRESHOLD = 1.5       # Relative Volume >= 1.5x
DEFAULT_EMA_PERIOD = 20
DEFAULT_RSI_PERIOD = 14
DEFAULT_RSI_BULLISH_THRESHOLD = 50.0
DEFAULT_RSI_BEARISH_THRESHOLD = 50.0
DEFAULT_VOL_LOOKBACK_DAYS = 10

# In-Memory Cache TTL Settings
CACHE_TTL_LIVE = 60       # 60 seconds TTL during active market
CACHE_TTL_CLOSED = 300    # 5 minutes TTL during off-market

# Load NIFTY 500 Constituents
DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "nifty500.json")

if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        NIFTY_500_STOCKS = json.load(f)
else:
    # Fallback to empty list if data file is missing
    NIFTY_500_STOCKS = []

# Backward compatibility alias
NIFTY_50_STOCKS = NIFTY_500_STOCKS[:50] if len(NIFTY_500_STOCKS) >= 50 else NIFTY_500_STOCKS

# Extracted Sectors across all 500 constituents
SECTORS = sorted(list(set(s["sector"] for s in NIFTY_500_STOCKS if s.get("sector"))))
