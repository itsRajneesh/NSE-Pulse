"""
High-Performance NSE Nifty 500 Data Fetcher:
Implements multi-threaded parallel chunk batching via yfinance,
in-memory TTL caching, and multi-criteria hierarchical ranking.
"""
import time
import math
from datetime import datetime, time as dtime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytz
import pandas as pd
import numpy as np
import yfinance as yf
from typing import Dict, List, Optional, Tuple, Any

from .config import (
    NIFTY_500_STOCKS, IST_TZ, MARKET_OPEN_TIME, MARKET_CLOSE_TIME,
    CACHE_TTL_LIVE, CACHE_TTL_CLOSED
)
from .models import (
    StockSignal, SignalType, ScreenerResponse, MarketStatus,
    Candle, StockHistoryResponse, TradeParameters, TechnicalIndicators
)
from .screener import evaluate_stock_signal
from .indicators import calculate_ema, calculate_rsi

# Cache storage
_CACHE = {
    "screener_data": None,
    "cache_time": 0,
    "stock_histories": {},
    "last_session_date": ""
}


def get_ist_now() -> datetime:
    """Returns current datetime in Indian Standard Time (IST)."""
    return datetime.now(IST_TZ)


def get_market_status(forced_mode: Optional[str] = None) -> MarketStatus:
    """
    Determines whether the NSE market is currently open or closed.
    NSE Regular Hours: 09:15 AM - 03:30 PM IST, Monday (0) to Friday (4).
    """
    ist_now = get_ist_now()
    current_time = ist_now.time()
    weekday = ist_now.weekday()

    is_weekday = 0 <= weekday <= 4
    is_trading_hours = MARKET_OPEN_TIME <= current_time <= MARKET_CLOSE_TIME
    is_open = is_weekday and is_trading_hours

    last_date = _CACHE.get("last_session_date") or ist_now.strftime("%d %b %Y")

    if is_open:
        msg = "NSE Market Live (Trading Active)"
    else:
        if not is_weekday:
            msg = f"Market Closed (Weekend) - Real Last Session Data ({last_date})"
        elif current_time < MARKET_OPEN_TIME:
            msg = f"Pre-Market (Opens 09:15 AM) - Real Last Session Data ({last_date})"
        else:
            msg = f"Market Closed - Real Last Session Data ({last_date})"

    time_str = ist_now.strftime("%d %b %Y, %I:%M:%S %p IST")
    mode = forced_mode if forced_mode else "live"

    return MarketStatus(
        is_open=is_open,
        session_message=msg,
        market_time_ist=time_str,
        mode=mode
    )


def _download_ticker_chunk(chunk_tickers: List[str]) -> Dict[str, pd.DataFrame]:
    """Downloads 15m candle data for a batch of tickers using yfinance."""
    chunk_data = {}
    if not chunk_tickers:
        return chunk_data

    try:
        downloaded = yf.download(
            tickers=chunk_tickers,
            period="5d",
            interval="15m",
            group_by="ticker",
            threads=True,
            progress=False
        )

        # If single ticker downloaded, columns may not have ticker multi-level index
        if len(chunk_tickers) == 1:
            sym = chunk_tickers[0]
            df = downloaded.dropna(how="all").dropna(subset=["Close", "High", "Low", "Open"])
            if not df.empty and len(df) >= 5:
                chunk_data[sym] = df
            return chunk_data

        for tick in chunk_tickers:
            if tick in downloaded.columns.levels[0]:
                df = downloaded[tick].dropna(how="all").copy()
                df = df.dropna(subset=["Close", "High", "Low", "Open"])
                if not df.empty and len(df) >= 5:
                    chunk_data[tick] = df
    except Exception as e:
        print(f"Warning: Chunk download error for {len(chunk_tickers)} tickers: {e}")

    return chunk_data


def fetch_nifty500_parallel(stocks: List[Dict[str, Any]], chunk_size: int = 80, max_workers: int = 6) -> Dict[str, pd.DataFrame]:
    """
    High-performance parallel batch downloader for Nifty 500 stocks.
    Chunks the 500 constituents into batches and downloads concurrently.
    """
    ticker_to_symbol = {s["yf_ticker"]: s["symbol"] for s in stocks}
    all_tickers = list(ticker_to_symbol.keys())

    # Split into chunks of chunk_size
    chunks = [all_tickers[i:i + chunk_size] for i in range(0, len(all_tickers), chunk_size)]
    combined_data: Dict[str, pd.DataFrame] = {}

    start_time = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_chunk = {executor.submit(_download_ticker_chunk, chunk): chunk for chunk in chunks}
        for future in as_completed(future_to_chunk):
            try:
                res = future.result()
                for yf_tick, df in res.items():
                    sym = ticker_to_symbol.get(yf_tick, yf_tick.replace(".NS", ""))
                    combined_data[sym] = df
            except Exception as exc:
                print(f"Error processing chunk result: {exc}")

    elapsed = time.time() - start_time
    print(f"Successfully downloaded {len(combined_data)} / {len(stocks)} stocks in {elapsed:.2f}s")
    return combined_data


def run_screener(mode: str = "live", sector_filter: Optional[str] = None) -> ScreenerResponse:
    """
    Executes the stock screener across all Nifty 500 constituents.
    Results are cached with a 60-second TTL to avoid API rate limits.
    """
    current_timestamp = time.time()
    market_status = get_market_status(forced_mode=mode)

    ttl = CACHE_TTL_LIVE if market_status.is_open else CACHE_TTL_CLOSED
    cache_key = f"{mode}_{sector_filter}"

    # Return cached data if fresh
    if (
        _CACHE["screener_data"] is not None
        and _CACHE.get("cache_key") == cache_key
        and (current_timestamp - _CACHE["cache_time"]) < ttl
    ):
        cached_resp: ScreenerResponse = _CACHE["screener_data"]
        cached_resp.market_status.market_time_ist = get_ist_now().strftime("%d %b %Y, %I:%M:%S %p IST")
        return cached_resp

    stocks_data: List[StockSignal] = []

    # Parallel download across all 500 stocks
    live_dfs = fetch_nifty500_parallel(NIFTY_500_STOCKS)

    # Determine last completed trading session date for display
    last_session_str = ""
    for sym, df in live_dfs.items():
        if not df.empty:
            last_dt = df.index[-1]
            last_session_str = last_dt.strftime("%d %b %Y, %I:%M %p IST") if hasattr(last_dt, 'strftime') else str(last_dt)
            break
    if last_session_str:
        _CACHE["last_session_date"] = last_session_str
        market_status = get_market_status(forced_mode=mode)

    # Evaluate each stock
    for stock_info in NIFTY_500_STOCKS:
        sym = stock_info["symbol"]
        name = stock_info["name"]
        sec = stock_info["sector"]
        base_p = stock_info.get("base_price", 500.0)

        if sector_filter and sector_filter.lower() != "all" and sec.lower() != sector_filter.lower():
            continue

        df_15m = live_dfs.get(sym)

        if df_15m is None or len(df_15m) < 5:
            # Skip unresolvable stocks or provide neutral placeholder
            continue

        _CACHE["stock_histories"][sym] = {
            "df": df_15m,
            "name": name,
            "sector": sec
        }

        signal = evaluate_stock_signal(
            symbol=sym,
            name=name,
            sector=sec,
            df_15m=df_15m
        )
        stocks_data.append(signal)

    # Multi-Criteria Hierarchical Ranking:
    # 1. Primary: Active Signals First (is_active_signal == True)
    # 2. Secondary: RelVol (Relative Volume) in descending order
    # 3. Tertiary: abs(Price Change %) in descending order
    stocks_data.sort(
        key=lambda s: (
            1 if s.is_active_signal else 0,
            s.rel_vol,
            abs(s.price_change_pct)
        ),
        reverse=True
    )

    total_scanned = len(stocks_data)
    bullish_count = sum(1 for s in stocks_data if s.signal_type == SignalType.BULLISH)
    bearish_count = sum(1 for s in stocks_data if s.signal_type == SignalType.BEARISH)
    neutral_count = sum(1 for s in stocks_data if s.signal_type == SignalType.NEUTRAL)
    active_signals_count = bullish_count + bearish_count

    # Calculate Market Sentiment breadth across all scanned stocks
    if (bullish_count + bearish_count) > 0:
        bullish_ratio = round((bullish_count / (bullish_count + bearish_count)) * 100.0, 1)
    else:
        pos_count = sum(1 for s in stocks_data if s.price_change_pct > 0)
        bullish_ratio = round((pos_count / max(1, total_scanned)) * 100.0, 1)

    if bullish_ratio >= 60.0:
        market_sentiment = "Bullish Dominance"
    elif bullish_ratio <= 40.0:
        market_sentiment = "Bearish Pressure"
    else:
        market_sentiment = "Neutral / Balanced"

    response = ScreenerResponse(
        total_scanned=total_scanned,
        active_signals_count=active_signals_count,
        bullish_count=bullish_count,
        bearish_count=bearish_count,
        neutral_count=neutral_count,
        bullish_ratio=bullish_ratio,
        market_sentiment=market_sentiment,
        market_status=market_status,
        last_refreshed=get_ist_now().strftime("%I:%M:%S %p IST"),
        stocks=stocks_data
    )

    _CACHE["screener_data"] = response
    _CACHE["cache_time"] = current_timestamp
    _CACHE["cache_key"] = cache_key

    return response


def get_stock_history_and_indicators(symbol: str) -> Optional[StockHistoryResponse]:
    """
    Retrieves the exact 15m candlestick data, 20 EMA overlay line series,
    and RSI(14) series for interactive TradingView Lightweight Charts drawer.
    Supports any of the 500 stocks.
    """
    symbol = symbol.upper().replace(".NS", "")
    cached = _CACHE["stock_histories"].get(symbol)

    if not cached:
        # Try direct fetch if not yet in cache
        t = yf.Ticker(f"{symbol}.NS")
        df = t.history(period="5d", interval="15m")
        if not df.empty:
            # Find name and sector from registry
            matched = next((s for s in NIFTY_500_STOCKS if s["symbol"] == symbol), None)
            name = matched["name"] if matched else symbol
            sec = matched["sector"] if matched else "NSE"
            cached = {"df": df, "name": name, "sector": sec}
            _CACHE["stock_histories"][symbol] = cached

    if not cached:
        return None

    df_15m: pd.DataFrame = cached["df"].copy()
    name: str = cached["name"]
    sector: str = cached["sector"]

    ema_series = calculate_ema(df_15m['Close'], period=20)
    rsi_series = calculate_rsi(df_15m['Close'], period=14)

    candles: List[Candle] = []
    ema_points = []
    rsi_points = []

    for idx, (dt, row) in enumerate(df_15m.iterrows()):
        time_str = dt.strftime("%Y-%m-%d %H:%M") if hasattr(dt, 'strftime') else str(dt)

        candles.append(Candle(
            timestamp=time_str,
            open=round(float(row['Open']), 2),
            high=round(float(row['High']), 2),
            low=round(float(row['Low']), 2),
            close=round(float(row['Close']), 2),
            volume=int(row['Volume'])
        ))

        ema_val = ema_series.iloc[idx]
        if not pd.isna(ema_val):
            ema_points.append({
                "time": time_str,
                "value": round(float(ema_val), 2)
            })

        rsi_val = rsi_series.iloc[idx]
        if not pd.isna(rsi_val):
            rsi_points.append({
                "time": time_str,
                "value": round(float(rsi_val), 2)
            })

    signal = evaluate_stock_signal(symbol, name, sector, df_15m)

    return StockHistoryResponse(
        symbol=symbol,
        name=name,
        sector=sector,
        timeframe="15m",
        candles=candles,
        ema20_series=ema_points,
        rsi_series=rsi_points,
        trade_params=signal.trade_params,
        signal_type=signal.signal_type
    )
