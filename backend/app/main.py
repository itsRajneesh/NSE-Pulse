"""
FastAPI Main Application for NSE Nifty 500 Intraday Screener & Trade Signal Generator.
"""
import threading
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List

from .config import SECTORS
from .models import ScreenerResponse, StockHistoryResponse, MarketStatus
from .data_fetcher import run_screener, get_stock_history_and_indicators, get_market_status, _CACHE

app = FastAPI(
    title="NSE Intraday Screener & Trade Signal Generator API",
    description="High-performance screening microservice for Nifty 500 stocks with 20 EMA, 14 RSI, RelVol, and dynamic trade levels.",
    version="2.0.0"
)

# Enable CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    """Pre-warm screener cache in a background thread so port binds immediately."""
    try:
        t = threading.Thread(target=run_screener, kwargs={"mode": "live"}, daemon=True)
        t.start()
    except Exception as e:
        print(f"Startup pre-warm notice: {e}")


@app.get("/")
def root():
    return {
        "service": "NSE Intraday Screener & Trade Signal Generator API",
        "status": "online",
        "market": "National Stock Exchange of India (NSE)",
        "index": "Nifty 500",
        "universe_size": 500,
        "endpoints": ["/api/screener", "/api/market-status", "/api/stocks/{symbol}/history", "/api/sectors"]
    }


@app.get("/api/health")
def health_check():
    return {"status": "healthy"}


@app.get("/api/market-status", response_model=MarketStatus)
def market_status_endpoint(mode: Optional[str] = Query(None, description="'live' or 'simulation'")):
    """Returns the current Indian Standard Time (IST) and market open/close state."""
    return get_market_status(forced_mode=mode)


@app.get("/api/sectors", response_model=List[str])
def get_sectors():
    """Returns the list of unique sectors/industries across Nifty 500."""
    return SECTORS


@app.get("/api/screener", response_model=ScreenerResponse)
def get_screener_data(
    mode: str = Query("live", description="Data mode: 'live' or 'simulation'"),
    sector: Optional[str] = Query(None, description="Filter by sector name"),
    force_refresh: bool = Query(False, description="Bypass cache and recalculate")
):
    """
    Scans all 500 constituents of Nifty 500 on the 15m timeframe.
    Evaluates:
    1. Volatility & Momentum (Change >= +1.5% or <= -1.5%)
    2. Relative Volume (RelVol >= 1.5)
    3. Trend Confirmation (Price vs 20 EMA and RSI > 50 / < 50)
    Ranks stocks by:
    1. Active Signals First
    2. RelVol (Descending)
    3. |Price Change %| (Descending)
    """
    if force_refresh:
        _CACHE["screener_data"] = None
        _CACHE["cache_time"] = 0

    return run_screener(mode=mode, sector_filter=sector)


@app.get("/api/stocks/{symbol}/history", response_model=StockHistoryResponse)
def get_stock_history(symbol: str):
    """
    Returns 15m OHLCV candle series, 20 EMA line points, RSI points,
    and trade levels for TradingView Lightweight Charts rendering.
    """
    data = get_stock_history_and_indicators(symbol)
    if not data:
        raise HTTPException(status_code=404, detail=f"Stock data for symbol '{symbol}' not found")
    return data
