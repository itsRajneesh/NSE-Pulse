"""
High-Performance NSE Nifty 500 Data Fetcher:
Implements multi-threaded parallel chunk batching via yfinance,
in-memory TTL caching, and multi-criteria hierarchical ranking.
"""
import time
import threading
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
_SCREENER_LOCK = threading.Lock()

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
            threads=False,
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


def fetch_nifty500_parallel(stocks: List[Dict[str, Any]], chunk_size: int = 40, max_workers: int = 2) -> Dict[str, pd.DataFrame]:
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

def fetch_nifty500_low_memory(stocks, chunk_size=20):
    """
    Memory-safe Nifty 500 downloader for low-RAM hosting.

    Downloads one small chunk at a time and yields each stock's
    DataFrame immediately instead of keeping all 500 DataFrames
    in memory at once.
    """
    all_tickers = []

    for stock in stocks:
        symbol = stock["symbol"] if isinstance(stock, dict) else stock
        ticker = symbol if symbol.endswith(".NS") else f"{symbol}.NS"
        all_tickers.append(ticker)

    for start in range(0, len(all_tickers), chunk_size):
        chunk = all_tickers[start:start + chunk_size]

        print(
            f"Downloading chunk "
            f"{start + 1}-{min(start + chunk_size, len(all_tickers))} "
            f"of {len(all_tickers)}..."
        )

        chunk_data = _download_ticker_chunk(chunk)

        for yf_tick, df in chunk_data.items():
            symbol = yf_tick.replace(".NS", "")
            yield symbol, df

        # Release chunk references before moving to the next chunk
        del chunk_data


def run_screener(
    mode: str = "live",
    sector_filter: Optional[str] = None
) -> ScreenerResponse:
    """
    Executes the stock screener across all Nifty 500 constituents.

    Uses chunk-by-chunk downloading to keep memory usage low on
    Render Free (512 MB RAM).

    A global lock prevents multiple simultaneous 500-stock scans.
    """

    current_timestamp = time.time()
    market_status = get_market_status(forced_mode=mode)

    ttl = CACHE_TTL_LIVE if market_status.is_open else CACHE_TTL_CLOSED
    cache_key = f"{mode}_{sector_filter}"

    # ---------------------------------------------------------
    # RETURN CACHED DATA IF STILL FRESH
    # ---------------------------------------------------------
    if (
        _CACHE["screener_data"] is not None
        and _CACHE.get("cache_key") == cache_key
        and (current_timestamp - _CACHE["cache_time"]) < ttl
    ):
        cached_resp: ScreenerResponse = _CACHE["screener_data"]

        cached_resp.market_status.market_time_ist = (
            get_ist_now().strftime(
                "%d %b %Y, %I:%M:%S %p IST"
            )
        )

        return cached_resp

    # ---------------------------------------------------------
    # PREVENT SIMULTANEOUS SCREENER RUNS
    # ---------------------------------------------------------
    with _SCREENER_LOCK:

        # Check cache again after acquiring the lock.
        # Another request may have completed the scan while
        # this request was waiting for the lock.
        current_timestamp = time.time()

        if (
            _CACHE["screener_data"] is not None
            and _CACHE.get("cache_key") == cache_key
            and (current_timestamp - _CACHE["cache_time"]) < ttl
        ):
            cached_resp: ScreenerResponse = _CACHE["screener_data"]

            cached_resp.market_status.market_time_ist = (
                get_ist_now().strftime(
                    "%d %b %Y, %I:%M:%S %p IST"
                )
            )

            return cached_resp

        # -----------------------------------------------------
        # LOW-MEMORY SCANNING
        # -----------------------------------------------------
        stocks_data: List[StockSignal] = []
        last_session_str = ""

        print(
            f"Starting low-memory screener scan "
            f"for {len(NIFTY_500_STOCKS)} stocks..."
        )

        # IMPORTANT:
        # Do NOT convert this generator into dict().
        #
        # Each chunk is downloaded and processed before the
        # next chunk is downloaded.
        for sym, df_15m in fetch_nifty500_low_memory(
            NIFTY_500_STOCKS,
            chunk_size=20
        ):

            # -------------------------------------------------
            # FIND STOCK METADATA
            # -------------------------------------------------
            stock_info = next(
                (
                    stock
                    for stock in NIFTY_500_STOCKS
                    if stock["symbol"] == sym
                ),
                None
            )

            if not stock_info:
                continue

            name = stock_info["name"]
            sec = stock_info["sector"]

            # -------------------------------------------------
            # SECTOR FILTER
            # -------------------------------------------------
            if (
                sector_filter
                and sector_filter.lower() != "all"
                and sec.lower() != sector_filter.lower()
            ):
                continue

            # -------------------------------------------------
            # VALIDATE DATA
            # -------------------------------------------------
            if (
                df_15m is None
                or df_15m.empty
                or len(df_15m) < 5
            ):
                continue

            try:
                # ---------------------------------------------
                # LAST AVAILABLE TRADING SESSION
                # ---------------------------------------------
                if not last_session_str:
                    last_dt = df_15m.index[-1]

                    if hasattr(last_dt, "strftime"):
                        last_session_str = last_dt.strftime(
                            "%d %b %Y, %I:%M %p IST"
                        )
                    else:
                        last_session_str = str(last_dt)

                # ---------------------------------------------
                # CALCULATE STOCK SIGNAL
                # ---------------------------------------------
                signal = evaluate_stock_signal(
                    symbol=sym,
                    name=name,
                    sector=sec,
                    df_15m=df_15m
                )

                stocks_data.append(signal)

            except Exception as e:
                print(
                    f"Signal evaluation failed for {sym}: {e}"
                )

            finally:
                # Release the current DataFrame reference.
                del df_15m

        # -----------------------------------------------------
        # UPDATE LAST SESSION DATE
        # -----------------------------------------------------
        if last_session_str:
            _CACHE["last_session_date"] = last_session_str
            market_status = get_market_status(
                forced_mode=mode
            )

        # -----------------------------------------------------
        # MULTI-CRITERIA HIERARCHICAL RANKING
        #
        # 1. Active signals first
        # 2. Relative volume descending
        # 3. Absolute price change descending
        # -----------------------------------------------------
        stocks_data.sort(
            key=lambda s: (
                1 if s.is_active_signal else 0,
                s.rel_vol,
                abs(s.price_change_pct)
            ),
            reverse=True
        )

        # -----------------------------------------------------
        # SUMMARY COUNTS
        # -----------------------------------------------------
        total_scanned = len(stocks_data)

        bullish_count = sum(
            1
            for s in stocks_data
            if s.signal_type == SignalType.BULLISH
        )

        bearish_count = sum(
            1
            for s in stocks_data
            if s.signal_type == SignalType.BEARISH
        )

        neutral_count = sum(
            1
            for s in stocks_data
            if s.signal_type == SignalType.NEUTRAL
        )

        active_signals_count = (
            bullish_count + bearish_count
        )

        # -----------------------------------------------------
        # MARKET SENTIMENT
        # -----------------------------------------------------
        if (bullish_count + bearish_count) > 0:

            bullish_ratio = round(
                (
                    bullish_count
                    / (bullish_count + bearish_count)
                ) * 100.0,
                1
            )

        else:
            pos_count = sum(
                1
                for s in stocks_data
                if s.price_change_pct > 0
            )

            bullish_ratio = round(
                (
                    pos_count
                    / max(1, total_scanned)
                ) * 100.0,
                1
            )

        if bullish_ratio >= 60.0:
            market_sentiment = "Bullish Dominance"

        elif bullish_ratio <= 40.0:
            market_sentiment = "Bearish Pressure"

        else:
            market_sentiment = "Neutral / Balanced"

        # -----------------------------------------------------
        # BUILD RESPONSE
        # -----------------------------------------------------
        response = ScreenerResponse(
            total_scanned=total_scanned,
            active_signals_count=active_signals_count,
            bullish_count=bullish_count,
            bearish_count=bearish_count,
            neutral_count=neutral_count,
            bullish_ratio=bullish_ratio,
            market_sentiment=market_sentiment,
            market_status=market_status,
            last_refreshed=get_ist_now().strftime(
                "%I:%M:%S %p IST"
            ),
            stocks=stocks_data
        )

        # -----------------------------------------------------
        # CACHE FINAL RESULT
        # -----------------------------------------------------
        _CACHE["screener_data"] = response
        _CACHE["cache_time"] = current_timestamp
        _CACHE["cache_key"] = cache_key

        print(
            f"Screener scan complete: "
            f"{total_scanned} stocks processed, "
            f"{active_signals_count} active signals."
        )

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
        # Fetch history on demand.
        # We intentionally do NOT keep the DataFrame in the global
        # cache to avoid increasing Render memory usage.
        try:
            t = yf.Ticker(f"{symbol}.NS")
            df = t.history(
                period="5d",
                interval="15m"
            )

            if not df.empty:
                matched = next(
                    (
                        s for s in NIFTY_500_STOCKS
                        if s["symbol"] == symbol
                    ),
                    None
                )

                name = matched["name"] if matched else symbol
                sec = matched["sector"] if matched else "NSE"

                cached = {
                    "df": df,
                    "name": name,
                    "sector": sec
                }

        except Exception as e:
            print(
                f"History fetch failed for {symbol}: {e}"
            )
            return None

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
