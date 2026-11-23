from __future__ import annotations
import os

from collections import defaultdict
import time

import numpy as np
import pandas as pd
import yfinance as yf

from app.config import NIFTY_500_STOCKS
from app.market_context import build_market_context
from app.v13_engine import discover_v13_setups

SIGNAL_START = "09:45"
SIGNAL_END = "15:00"
OPENING_RANGE_START = "09:15"
OPENING_RANGE_END = "09:30"

# Keep Yahoo requests conservative to reduce rate-limit / memory problems.
DOWNLOAD_CHUNK_SIZE = 20

WIN_OUTCOMES = {"T1_FIRST", "T2_FIRST"}
LOSS_OUTCOMES = {"SL_FIRST"}


def normalize_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    out = df.copy()
    idx = pd.DatetimeIndex(out.index)

    if idx.tz is None:
        idx = idx.tz_localize("Asia/Kolkata")
    else:
        idx = idx.tz_convert("Asia/Kolkata")

    out.index = idx
    return out.sort_index()


def get_sessions(df: pd.DataFrame) -> list[pd.Timestamp]:
    if df is None or df.empty:
        return []
    return sorted(pd.DatetimeIndex(df.index.normalize()).unique())


def session_slice(df: pd.DataFrame, session: pd.Timestamp) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    return df[df.index.normalize() == session]


def get_previous_session_close(
    benchmark_df: pd.DataFrame,
    session_date: pd.Timestamp,
) -> float | None:
    if benchmark_df is None or benchmark_df.empty:
        return None

    cache = benchmark_df.attrs.get("previous_session_close_cache")
    if cache is None:
        cache = {}
        sessions = get_sessions(benchmark_df)
        for i in range(1, len(sessions)):
            prev_session = sessions[i - 1]
            current_session = sessions[i]
            prev_df = session_slice(benchmark_df, prev_session)
            if not prev_df.empty:
                cache[current_session] = float(prev_df["Close"].iloc[-1])
        benchmark_df.attrs["previous_session_close_cache"] = cache

    return cache.get(session_date)


def change_at_time(
    benchmark_df: pd.DataFrame,
    session_date: pd.Timestamp,
    cutoff_time: pd.Timestamp,
) -> float | None:
    """Historical benchmark change using only information available at cutoff."""
    if benchmark_df is None or benchmark_df.empty:
        return None

    previous_close = get_previous_session_close(benchmark_df, session_date)
    if previous_close is None or previous_close <= 0:
        return None

    cache = benchmark_df.attrs.get("session_data_cache")
    if cache is None:
        cache = {
            session: session_slice(benchmark_df, session)
            for session in get_sessions(benchmark_df)
        }
        benchmark_df.attrs["session_data_cache"] = cache

    day_df = cache.get(session_date)
    if day_df is None or day_df.empty:
        return None

    available = day_df[day_df.index <= cutoff_time]
    if available.empty:
        return None

    current_price = float(available["Close"].iloc[-1])
    return (current_price / previous_close - 1.0) * 100.0


def build_historical_context(
    nifty_df: pd.DataFrame,
    sector_df: pd.DataFrame | None,
    session_date: pd.Timestamp,
    cutoff_time: pd.Timestamp,
):
    nifty_change = change_at_time(nifty_df, session_date, cutoff_time)
    if nifty_change is None:
        return None

    sector_change = 0.0
    if sector_df is not None and not sector_df.empty:
        value = change_at_time(sector_df, session_date, cutoff_time)
        if value is not None:
            sector_change = value

    return build_market_context(
        nifty_change_pct=nifty_change,
        sector_change_pct=sector_change,
    )


def get_sector_benchmark_symbol(sector: str) -> str | None:
    from app.config import SECTOR_BENCHMARKS
    return SECTOR_BENCHMARKS.get(sector)


def extract_ticker_df(downloaded: pd.DataFrame, symbol: str) -> pd.DataFrame | None:
    if downloaded is None or downloaded.empty:
        return None

    ticker = f"{symbol}.NS"

    try:
        if isinstance(downloaded.columns, pd.MultiIndex):
            level0 = downloaded.columns.get_level_values(0)
            level1 = downloaded.columns.get_level_values(1)

            if ticker in level0:
                df = downloaded[ticker].copy()
            elif symbol in level0:
                df = downloaded[symbol].copy()
            elif ticker in level1:
                df = downloaded.xs(ticker, axis=1, level=1).copy()
            elif symbol in level1:
                df = downloaded.xs(symbol, axis=1, level=1).copy()
            else:
                return None
        else:
            df = downloaded.copy()

        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(df.columns):
            return None

        return normalize_datetime_index(df)
    except Exception:
        return None


def download_stock_chunk(symbols: list[str]) -> dict[str, pd.DataFrame]:
    tickers = [f"{symbol}.NS" for symbol in symbols]
    print(f"\nDownloading chunk: {len(symbols)} stocks...")

    try:
        downloaded = yf.download(
            tickers=tickers,
            period="60d",
            interval="15m",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    except Exception as exc:
        print(f"Chunk download failed: {exc}")
        return {}

    result: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        df = extract_ticker_df(downloaded, symbol)
        if df is not None and not df.empty:
            result[symbol] = df

    print(f"Usable stocks in chunk: {len(result)}/{len(symbols)}")
    return result


def download_single_benchmark(symbol: str) -> pd.DataFrame | None:
    try:
        df = yf.download(
            tickers=symbol,
            period="60d",
            interval="15m",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        if df is None or df.empty:
            return None

        if isinstance(df.columns, pd.MultiIndex):
            # Yahoo can return either (Price, Ticker) or (Ticker, Price).
            if f"{symbol}.NS" in df.columns.get_level_values(1):
                df = df.xs(f"{symbol}.NS", axis=1, level=1)
            elif symbol in df.columns.get_level_values(1):
                df = df.xs(symbol, axis=1, level=1)
            else:
                df = df.droplevel(-1, axis=1)

        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(df.columns):
            return None

        return normalize_datetime_index(df)
    except Exception as exc:
        print(f"Benchmark download failed for {symbol}: {exc}")
        return None


def is_inside_signal_window(timestamp: pd.Timestamp) -> bool:
    current = timestamp.time()
    return pd.Timestamp(SIGNAL_START).time() <= current <= pd.Timestamp(SIGNAL_END).time()


def calculate_actual_levels(setup, actual_entry: float):
    """Recalculate SL/T1/T2 from the actual entry used by the trade."""

    actual_entry = float(actual_entry)

    # Reject invalid / missing entry prices.
    if not np.isfinite(actual_entry):
        return None

    if setup.signal_type == "BULLISH":
        opening_range_low = float(setup.opening_range_low)
        vwap = float(setup.vwap)
        atr14 = float(setup.atr14)

        if not (
            np.isfinite(opening_range_low)
            and np.isfinite(vwap)
            and np.isfinite(atr14)
            and atr14 > 0
        ):
            return None

        stop_loss = min(opening_range_low, vwap)

        if not np.isfinite(stop_loss) or stop_loss >= actual_entry:
            stop_loss = actual_entry - atr14

        risk = actual_entry - stop_loss

        if not np.isfinite(risk) or risk <= 0:
            return None

        target_1 = actual_entry + risk * 1.5
        target_2 = actual_entry + risk * 2.5

    else:
        opening_range_high = float(setup.opening_range_high)
        vwap = float(setup.vwap)
        atr14 = float(setup.atr14)

        if not (
            np.isfinite(opening_range_high)
            and np.isfinite(vwap)
            and np.isfinite(atr14)
            and atr14 > 0
        ):
            return None

        stop_loss = max(opening_range_high, vwap)

        if not np.isfinite(stop_loss) or stop_loss <= actual_entry:
            stop_loss = actual_entry + atr14

        risk = stop_loss - actual_entry

        if not np.isfinite(risk) or risk <= 0:
            return None

        target_1 = actual_entry - risk * 1.5
        target_2 = actual_entry - risk * 2.5

    if not (
        np.isfinite(stop_loss)
        and np.isfinite(target_1)
        and np.isfinite(target_2)
    ):
        return None

    return {
        "entry": actual_entry,
        "stop_loss": float(stop_loss),
        "target_1": float(target_1),
        "target_2": float(target_2),
        "risk": float(risk),
    }


def test_confirmed_trade(
    session_df: pd.DataFrame,
    entry_time: pd.Timestamp,
    direction: str,
    entry_price: float,
    stop_loss: float,
    target_1: float,
    target_2: float,
):
    """Confirmed: entry is the next candle open; outcome is same-day only."""

    future = session_df[session_df.index >= entry_time]

    if future.empty:
        return {
            "triggered": True,
            "trigger_time": entry_time,
            "outcome": "NO_FUTURE_CANDLE",
            "realized_r": 0.0,
            "outcome_time": None,
        }

    if direction == "BULLISH":
        for ts, row in future.iterrows():
            high, low = float(row["High"]), float(row["Low"])

            if low <= stop_loss:
                return {
                    "triggered": True,
                    "trigger_time": entry_time,
                    "outcome": "SL_FIRST",
                    "realized_r": -1.0,
                    "outcome_time": ts,
                }

            if high >= target_2:
                return {
                    "triggered": True,
                    "trigger_time": entry_time,
                    "outcome": "T2_FIRST",
                    "realized_r": 2.5,
                    "outcome_time": ts,
                }

            if high >= target_1:
                return {
                    "triggered": True,
                    "trigger_time": entry_time,
                    "outcome": "T1_FIRST",
                    "realized_r": 1.5,
                    "outcome_time": ts,
                }

    else:
        for ts, row in future.iterrows():
            high, low = float(row["High"]), float(row["Low"])

            if high >= stop_loss:
                return {
                    "triggered": True,
                    "trigger_time": entry_time,
                    "outcome": "SL_FIRST",
                    "realized_r": -1.0,
                    "outcome_time": ts,
                }

            if low <= target_2:
                return {
                    "triggered": True,
                    "trigger_time": entry_time,
                    "outcome": "T2_FIRST",
                    "realized_r": 2.5,
                    "outcome_time": ts,
                }

            if low <= target_1:
                return {
                    "triggered": True,
                    "trigger_time": entry_time,
                    "outcome": "T1_FIRST",
                    "realized_r": 1.5,
                    "outcome_time": ts,
                }

    # Trade remained open until the end of the trading session.
    # Close it at the latest same-day candle having a valid Close.
    valid_future = future[pd.to_numeric(future["Close"], errors="coerce").notna()]

    if valid_future.empty:
        return {
            "triggered": True,
            "trigger_time": entry_time,
            "outcome": "EOD_INVALID",
            "realized_r": 0.0,
            "outcome_time": None,
        }

    last_ts = valid_future.index[-1]
    last_close = float(valid_future.iloc[-1]["Close"])

    if direction == "BULLISH":
        risk = entry_price - stop_loss
        if not np.isfinite(risk) or risk <= 0:
            return {
                "triggered": True,
                "trigger_time": entry_time,
                "outcome": "EOD_INVALID",
                "realized_r": 0.0,
                "outcome_time": last_ts,
            }
        realized_r = (last_close - entry_price) / risk
    else:
        risk = stop_loss - entry_price
        if not np.isfinite(risk) or risk <= 0:
            return {
                "triggered": True,
                "trigger_time": entry_time,
                "outcome": "EOD_INVALID",
                "realized_r": 0.0,
                "outcome_time": last_ts,
            }
        realized_r = (entry_price - last_close) / risk

    if not np.isfinite(realized_r):
        return {
            "triggered": True,
            "trigger_time": entry_time,
            "outcome": "EOD_INVALID",
            "realized_r": 0.0,
            "outcome_time": last_ts,
        }

    return {
        "triggered": True,
        "trigger_time": entry_time,
        "outcome": "EOD_EXIT",
        "realized_r": float(realized_r),
        "outcome_time": last_ts,
    }


def test_developing_trade(
    session_df: pd.DataFrame,
    signal_time: pd.Timestamp,
    direction: str,
    entry_price: float,
    stop_loss: float,
    target_1: float,
    target_2: float,
):
    """Developing: entry only occurs on a later same-day OR break."""
    future = session_df[session_df.index > signal_time]
    if future.empty:
        return {"triggered": False, "trigger_time": None, "outcome": "NO_TRIGGER", "realized_r": 0.0, "outcome_time": None}

    for ts, row in future.iterrows():
        high, low = float(row["High"]), float(row["Low"])
        triggered = high >= entry_price if direction == "BULLISH" else low <= entry_price
        if not triggered:
            continue

        remaining = session_df[session_df.index >= ts]
        if direction == "BULLISH":
            for outcome_ts, outcome_row in remaining.iterrows():
                outcome_high, outcome_low = float(outcome_row["High"]), float(outcome_row["Low"])
                if outcome_low <= stop_loss:
                    return {"triggered": True, "trigger_time": ts, "outcome": "SL_FIRST", "realized_r": -1.0, "outcome_time": outcome_ts}
                if outcome_high >= target_2:
                    return {"triggered": True, "trigger_time": ts, "outcome": "T2_FIRST", "realized_r": 2.5, "outcome_time": outcome_ts}
                if outcome_high >= target_1:
                    return {"triggered": True, "trigger_time": ts, "outcome": "T1_FIRST", "realized_r": 1.5, "outcome_time": outcome_ts}
        else:
            for outcome_ts, outcome_row in remaining.iterrows():
                outcome_high, outcome_low = float(outcome_row["High"]), float(outcome_row["Low"])
                if outcome_high >= stop_loss:
                    return {"triggered": True, "trigger_time": ts, "outcome": "SL_FIRST", "realized_r": -1.0, "outcome_time": outcome_ts}
                if outcome_low <= target_2:
                    return {"triggered": True, "trigger_time": ts, "outcome": "T2_FIRST", "realized_r": 2.5, "outcome_time": outcome_ts}
                if outcome_low <= target_1:
                    return {"triggered": True, "trigger_time": ts, "outcome": "T1_FIRST", "realized_r": 1.5, "outcome_time": outcome_ts}

        # Entry was triggered, but neither SL nor target was hit.
        # Exit at the latest same-day candle having a valid Close.
        valid_remaining = remaining[
            pd.to_numeric(remaining["Close"], errors="coerce").notna()
        ]

        if valid_remaining.empty:
            return {
                "triggered": True,
                "trigger_time": ts,
                "outcome": "EOD_INVALID",
                "realized_r": 0.0,
                "outcome_time": None,
            }

        last_ts = valid_remaining.index[-1]
        last_close = float(valid_remaining.iloc[-1]["Close"])

        if direction == "BULLISH":
            risk = entry_price - stop_loss
            if not np.isfinite(risk) or risk <= 0:
                return {
                    "triggered": True,
                    "trigger_time": ts,
                    "outcome": "EOD_INVALID",
                    "realized_r": 0.0,
                    "outcome_time": last_ts,
                }

            realized_r = (last_close - entry_price) / risk

        else:
            risk = stop_loss - entry_price
            if not np.isfinite(risk) or risk <= 0:
                return {
                    "triggered": True,
                    "trigger_time": ts,
                    "outcome": "EOD_INVALID",
                    "realized_r": 0.0,
                    "outcome_time": last_ts,
                }

            realized_r = (entry_price - last_close) / risk

        if not np.isfinite(realized_r):
            return {
                "triggered": True,
                "trigger_time": ts,
                "outcome": "EOD_INVALID",
                "realized_r": 0.0,
                "outcome_time": last_ts,
            }

        return {
            "triggered": True,
            "trigger_time": ts,
            "outcome": "EOD_EXIT",
            "realized_r": float(realized_r),
            "outcome_time": last_ts,
        }

    return {"triggered": False, "trigger_time": None, "outcome": "NO_TRIGGER", "realized_r": 0.0, "outcome_time": None}


def setup_stage(setup) -> str:
    setup_type = str(
        getattr(setup, "setup_type", "")
    ).upper()

    if setup_type.startswith("CONFIRMED_"):
        return "CONFIRMED"

    if setup_type.startswith("DEVELOPING_"):
        return "DEVELOPING"

    return "UNKNOWN"


def time_bucket(timestamp: pd.Timestamp) -> str:
    total = timestamp.hour * 60 + timestamp.minute
    if total < 600:
        return "09:45-10:00"
    if total < 660:
        return "10:00-11:00"
    if total < 720:
        return "11:00-12:00"
    if total < 840:
        return "12:00-14:00"
    return "14:00-15:00"


def max_drawdown(values: list[float]) -> float:
    if not values:
        return 0.0
    equity = np.cumsum(values)
    peak = np.maximum.accumulate(np.insert(equity, 0, 0.0))[1:]
    return float((peak - equity).max())


def closed_trades(trades: list[dict]) -> list[dict]:
    return [
        t for t in trades
        if (
            t["outcome"] in WIN_OUTCOMES
            or t["outcome"] in LOSS_OUTCOMES
            or t["outcome"] == "EOD_EXIT"
        )
    ]


def print_group_analysis(trades: list[dict], field: str, title: str, minimum_trades: int = 5):
    print(f"\n{title}")
    print("-" * 100)
    groups = defaultdict(list)
    for trade in closed_trades(trades):
        groups[trade[field]].append(trade)

    rows = []
    for key, group in groups.items():
        if len(group) < minimum_trades:
            continue
        wins = sum(t["outcome"] in WIN_OUTCOMES for t in group)
        total_r = sum(t["realized_r"] for t in group)
        rows.append((key, len(group), wins, wins / len(group) * 100, total_r / len(group), total_r))

    rows.sort(key=lambda x: x[5], reverse=True)
    if not rows:
        print(f"No groups with at least {minimum_trades} closed trades.")
        return

    for key, count, wins, wr, avg_r, total_r in rows:
        print(f"{str(key):<24} | Trades {count:>4} | W {wins:>4} | WR {wr:>6.2f}% | AvgR {avg_r:+.3f} | TotalR {total_r:+.2f}")


def print_score_analysis(trades: list[dict]):
    buckets = [("65-69",65,70),("70-74",70,75),("75-79",75,80),("80-84",80,85),("85-89",85,90),("90-94",90,95),("95-100",95,101)]
    print("\nSCORE BUCKET ANALYSIS â€” CLOSED TRADES")
    print("-" * 100)
    for name, low, high in buckets:
        group = [t for t in closed_trades(trades) if low <= t["score"] < high]
        if not group:
            continue
        wins = sum(t["outcome"] in WIN_OUTCOMES for t in group)
        total_r = sum(t["realized_r"] for t in group)
        print(f"{name:<10} | Trades {len(group):>4} | W {wins:>4} | WR {wins/len(group)*100:>6.2f}% | AvgR {total_r/len(group):+.3f} | TotalR {total_r:+.2f}")


def print_matrix(trades: list[dict]):
    print("\nSCORE Ã— TIME Ã— DIRECTION â€” CLOSED TRADES")
    print("-" * 120)
    buckets = [("65-69",65,70),("70-74",70,75),("75-79",75,80),("80-84",80,85),("85-89",85,90),("90-94",90,95),("95-100",95,101)]
    closed = closed_trades(trades)
    groups = defaultdict(list)
    for t in closed:
        score_name = next((name for name,lo,hi in buckets if lo <= t["score"] < hi), "OTHER")
        groups[(score_name, t["time_bucket"], t["direction"])].append(t)

    rows = []
    for key, group in groups.items():
        if len(group) < 5:
            continue
        wins = sum(t["outcome"] in WIN_OUTCOMES for t in group)
        total_r = sum(t["realized_r"] for t in group)
        rows.append((*key, len(group), wins, wins/len(group)*100, total_r/len(group), total_r))
    rows.sort(key=lambda x: x[-1], reverse=True)

    if not rows:
        print("No combinations with at least 5 closed trades.")
        return
    for score, tb, direction, count, wins, wr, avg_r, total_r in rows:
        print(f"{score:<8} | {tb:<13} | {direction:<8} | Trades {count:>4} | W {wins:>3} | WR {wr:>6.2f}% | AvgR {avg_r:+.3f} | TotalR {total_r:+.2f}")


def print_summary(trades: list[dict], stats: dict):
    closed = closed_trades(trades)
    wins = [t for t in closed if t["outcome"] in WIN_OUTCOMES]
    losses = [t for t in closed if t["outcome"] in LOSS_OUTCOMES]
    eod_exits = [t for t in closed if t["outcome"] == "EOD_EXIT"]

    open_trades = [t for t in trades if t["outcome"] == "OPEN"]
    no_trigger = [t for t in trades if t["outcome"] == "NO_TRIGGER"]
    no_future_candle = [
        t for t in trades
        if t["outcome"] == "NO_FUTURE_CANDLE"
    ]
    eod_invalid = [
        t for t in trades
        if t["outcome"] == "EOD_INVALID"
    ]

    total_r = sum(t["realized_r"] for t in closed)
    avg_r = total_r / len(closed) if closed else 0.0
    wr = len(wins) / len(closed) * 100 if closed else 0.0

    # A trade is triggered when an entry actually occurs.
    # EOD_INVALID is also triggered, but excluded from closed-trade performance.
    triggered = (
        len(closed)
        + len(open_trades)
        + len(no_future_candle)
        + len(eod_invalid)
    )

    print("\n" + "=" * 100)
    print("NIFTY 500 V6 â€” ACTUAL ENTRY + SAME-DAY EOD OUTCOME SUMMARY")
    print("=" * 100)
    print(f"Stocks with data    : {stats['stocks_with_data']}/{len(NIFTY_500_STOCKS)}")
    print(f"Stocks no data      : {stats['stocks_without_data']}")
    print(f"Evaluation errors   : {stats['evaluation_errors']}")
    
    # NEW FIX: Print DMA Rejection Metrics directly in summary
    print(f"DMA Missing         : {stats['missing_dma']}")
    print(f"DMA Rejected        : {stats['dma_rejected']}")
    print(f"B2 Velocity Rejected: {stats['b2_rejected']}")
    
    print(f"Lifecycle Blocked   : {stats['lifecycle_blocked']}")
    print(f"Qualified setups    : {stats['qualified_setups']}")
    print(f"Triggered trades    : {triggered}")
    print(f"Closed trades       : {len(closed)}")
    print(f"Wins                : {len(wins)}")
    print(f"Losses              : {len(losses)}")
    print(f"EOD exits           : {len(eod_exits)}")
    print(f"EOD invalid         : {len(eod_invalid)}")
    print(f"OPEN                : {len(open_trades)}")
    print(f"NO_TRIGGER          : {len(no_trigger)}")
    print(f"No-future-candle    : {len(no_future_candle)}")
    print(f"Closed-trade WR     : {wr:.2f}%")
    print(f"Average closed R    : {avg_r:+.3f}R")
    print(f"Total closed R      : {total_r:+.2f}R")
    print(
        f"Max drawdown        : "
        f"{max_drawdown([t['realized_r'] for t in closed]):.2f}R"
    )
    print(
        f"Trigger rate        : "
        f"{triggered / len(trades) * 100:.2f}%"
        if trades
        else "Trigger rate        : 0.00%"
    )
    print("=" * 100)

    print_group_analysis(trades, "stage", "STAGE ANALYSIS")
    print_group_analysis(trades, "direction", "DIRECTION ANALYSIS")
    print_group_analysis(trades, "time_bucket", "TIME Ã— STAGE/DIRECTION INPUT ANALYSIS")
    print_score_analysis(trades)
    print_matrix(trades)

    print("\nEARLIEST SETUP ANALYSIS")
    print("-" * 100)
    if trades:
        timestamps = [t["signal_time"] for t in trades]
        earliest = min(timestamps)
        print(f"Earliest qualified setup : {earliest}")
        print(f"Setups before 10:00       : {sum(t.time() < pd.Timestamp('10:00').time() for t in timestamps)}")
        print(f"Setups before 11:00       : {sum(t.time() < pd.Timestamp('11:00').time() for t in timestamps)}")



def download_daily_stock_chunk(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Download daily OHLCV history needed for point-in-time SMA50/SMA200."""
    tickers = [f"{symbol}.NS" for symbol in symbols]
    print(f"\nDownloading DAILY chunk: {len(symbols)} stocks...")

    try:
        downloaded = yf.download(
            tickers=tickers,
            period="1y",
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    except Exception as exc:
        print(f"Daily chunk download failed: {exc}")
        return {}

    result: dict[str, pd.DataFrame] = {}

    for symbol in symbols:
        df = extract_ticker_df(downloaded, symbol)

        if df is not None and not df.empty:
            df = normalize_datetime_index(df)
            result[symbol] = df

    print(f"Usable DAILY stocks in chunk: {len(result)}/{len(symbols)}")
    return result


def calculate_point_in_time_dma(
    daily_df: pd.DataFrame,
    signal_time: pd.Timestamp,
) -> tuple[float | None, float | None, float | None]:
    """
    Calculate daily close, SMA50 and SMA200 using only daily candles
    available on or before the signal date.
    """
    if daily_df is None or daily_df.empty:
        return None, None, None

    # IMPORTANT:
    # For an intraday signal, today's daily candle is not complete yet.
    # Therefore only use fully completed daily candles BEFORE the signal date.
    history = daily_df[
        daily_df.index.normalize() < signal_time.normalize()
    ].copy()

    if history.empty or "Close" not in history.columns:
        return None, None, None

    close = pd.to_numeric(history["Close"], errors="coerce").dropna()

    if len(close) < 200:
        return None, None, None

    sma50 = float(close.rolling(50).mean().iloc[-1])
    sma200 = float(close.rolling(200).mean().iloc[-1])
    daily_close = float(close.iloc[-1])

    if not all(pd.notna(x) for x in (daily_close, sma50, sma200)):
        return None, None, None

    return daily_close, sma50, sma200


def run_nifty500_backtest():
    print("\n" + "=" * 100)
    print("NIFTY 500 V13 BACKTEST")
    print("=" * 100)
    print("Methodology:")
    print("  â€¢ Full NIFTY 500 universe")
    print("  â€¢ Historical 15m Yahoo data")
    print("  â€¢ Historical NIFTY + sector context at signal time")
    print("  â€¢ Confirmed entry = NEXT CANDLE OPEN")
    print("  â€¢ Developing entry = FUTURE OPENING-RANGE BREAK")
    print("  â€¢ SL/T1/T2 recalculated from ACTUAL entry")
    print("  â€¢ Same-day outcome only")
    print("  â€¢ Same-candle conflict = SL first")

    limit_raw = os.getenv("BACKTEST_LIMIT", "").strip()
    try:
        backtest_limit = int(limit_raw) if limit_raw else len(NIFTY_500_STOCKS)
    except ValueError:
        backtest_limit = len(NIFTY_500_STOCKS)

    backtest_limit = max(1, min(backtest_limit, len(NIFTY_500_STOCKS)))
    stocks = NIFTY_500_STOCKS[:backtest_limit]
    print(f"\nUniverse size: {len(stocks)} stocks")

    print("\nDownloading NIFTY benchmark...")
    nifty_df = download_single_benchmark("^NSEI")
    if nifty_df is None or nifty_df.empty:
        print("ERROR: Could not download NIFTY benchmark.")
        return
    print(f"NIFTY rows: {len(nifty_df)}")
    print(f"NIFTY sessions: {len(get_sessions(nifty_df))}")

    sector_symbols: dict[str, str] = {}
    for stock in stocks:
        sector = stock.get("sector")
        if not sector:
            continue
        benchmark = get_sector_benchmark_symbol(sector)
        if benchmark:
            sector_symbols[sector] = benchmark

    print(f"\nSector benchmarks needed: {len(sector_symbols)}")
    sector_data: dict[str, pd.DataFrame] = {}
    for sector, benchmark in sector_symbols.items():
        print(f"Downloading sector benchmark: {sector} -> {benchmark}")
        df = download_single_benchmark(benchmark)
        if df is not None and not df.empty:
            sector_data[sector] = df
        time.sleep(0.4)
    print(f"Usable sector benchmarks: {len(sector_data)}/{len(sector_symbols)}")

    trades: list[dict] = []
    stats = defaultdict(int)

    symbols = [stock["symbol"] for stock in stocks]
    stock_by_symbol = {stock["symbol"]: stock for stock in stocks}

    for chunk_start in range(0, len(symbols), DOWNLOAD_CHUNK_SIZE):
        chunk_symbols = symbols[chunk_start:chunk_start + DOWNLOAD_CHUNK_SIZE]
        chunk_data = download_stock_chunk(chunk_symbols)
        daily_chunk_data = download_daily_stock_chunk(chunk_symbols)

        for symbol in chunk_symbols:
            stock = stock_by_symbol[symbol]
            name = stock["name"]
            sector = stock.get("sector", "")
            df = chunk_data.get(symbol)
            daily_df = daily_chunk_data.get(symbol)

            if df is None or df.empty:
                stats["stocks_without_data"] += 1
                continue

            stats["stocks_with_data"] += 1
            sessions = get_sessions(df)
            if len(sessions) < 2:
                continue

            print(f"\nScanning {symbol} | {name} | {sector}")

            for session_date in sessions[1:]:
                session_df = session_slice(df, session_date)
                if session_df.empty:
                    continue

                signal_times = [ts for ts in session_df.index if is_inside_signal_window(ts)]

                for signal_time in signal_times:
                    historical_df = df[df.index <= signal_time].copy()
                    if historical_df.empty:
                        continue

                    dma_close, dma_sma50, dma_sma200 = calculate_point_in_time_dma(
                        daily_df=daily_df,
                        signal_time=signal_time,
                    )

                    if dma_close is None or dma_sma50 is None or dma_sma200 is None:
                        stats["missing_dma"] += 1   # FIX 1
                        continue

                    context = build_historical_context(
                        nifty_df=nifty_df,
                        sector_df=sector_data.get(sector),
                        session_date=session_date,
                        cutoff_time=signal_time,
                    )
                    if context is None:
                        stats["missing_context"] += 1
                        continue

                    try:
                        v13_setups = discover_v13_setups(
                            symbol=symbol,
                            name=name,
                            sector=sector,
                            df=historical_df,
                            context=context,
                        )
                    except Exception:
                        stats["evaluation_errors"] += 1
                        continue

                    # V13 evaluates bullish and bearish independently.
                    for setup in (
                        v13_setups.get("bullish"),
                        v13_setups.get("bearish"),
                    ):
                        if setup is None:
                            continue

                        stage = setup_stage(setup)

                        if stage not in {"CONFIRMED", "DEVELOPING"}:
                            continue

                        setup_direction = setup.signal_type
                        # B2 HARD GATE — TRUE VELOCITY DIRECTION
                        # Bullish setups require positive 5D velocity.
                        # Bearish setups require negative 5D velocity.
                        true_velocity = float(setup.true_velocity)

                        if setup_direction == "BULLISH":
                            velocity_pass = true_velocity > 0.0
                        elif setup_direction == "BEARISH":
                            velocity_pass = true_velocity < 0.0
                        else:
                            velocity_pass = False

                        if not velocity_pass:
                            stats["b2_rejected"] += 1
                            continue

                        # B1 HARD GATE
                        if setup_direction == "BULLISH":
                            dma_pass = (
                                dma_close > dma_sma50
                                and dma_close > dma_sma200
                            )
                        elif setup_direction == "BEARISH":
                            dma_pass = (
                                dma_close < dma_sma50
                                and dma_close < dma_sma200
                            )
                        else:
                            dma_pass = False

                        if not dma_pass:
                            stats["dma_rejected"] += 1
                            continue

                        # V13 score = setup quality score, NOT probability.
                        try:
                            setup_score = float(setup.score)
                        except (TypeError, ValueError):
                            continue

                        if setup_score < 72.0:
                            continue

                        direction = setup.signal_type

                        # -------------------------------------------------
                        # LIFECYCLE CONTROL
                        # Same stock + same direction:
                        # block a new setup while the previous trade is
                        # still active.
                        #
                        # We use outcome_time instead of outcome type.
                        # The trade simulator calculates the complete
                        # outcome before appending the trade to `trades`,
                        # so the outcome timestamp is the correct way to
                        # determine whether the previous trade overlaps
                        # the current signal.
                        #
                        # Opposite direction remains allowed as a possible
                        # genuine reversal.
                        # -------------------------------------------------
                        current_session_date = session_date.strftime("%Y-%m-%d")

                        existing_active = any(
                            trade.get("symbol") == symbol
                            and str(trade.get("date")) == current_session_date
                            and str(trade.get("direction", "")).upper()
                                == str(direction).upper()
                            and bool(trade.get("triggered"))
                            and trade.get("outcome_time") is not None
                            and trade.get("outcome_time") >= signal_time
                            for trade in trades
                        )

                        if existing_active:
                            stats["lifecycle_blocked"] += 1
                            continue

                        if stage == "CONFIRMED":
                            future_same_day = session_df[
                                session_df.index > signal_time
                            ]

                            if future_same_day.empty:
                                continue

                            entry_time = future_same_day.index[0]
                            actual_entry = float(
                                future_same_day.iloc[0]["Open"]
                            )

                            levels = calculate_actual_levels(
                                setup,
                                actual_entry,
                            )

                            if levels is None:
                                continue

                            outcome = test_confirmed_trade(
                                session_df=session_df,
                                entry_time=entry_time,
                                direction=direction,
                                entry_price=levels["entry"],
                                stop_loss=levels["stop_loss"],
                                target_1=levels["target_1"],
                                target_2=levels["target_2"],
                            )

                        else:
                            levels = calculate_actual_levels(
                                setup,
                                float(setup.entry_price),
                            )

                            if levels is None:
                                continue

                            outcome = test_developing_trade(
                                session_df=session_df,
                                signal_time=signal_time,
                                direction=direction,
                                entry_price=levels["entry"],
                                stop_loss=levels["stop_loss"],
                                target_1=levels["target_1"],
                                target_2=levels["target_2"],
                            )

                        trade = {
                            "symbol": symbol,
                            "name": name,
                            "sector": sector,
                            "date": session_date.strftime("%Y-%m-%d"),
                            "signal_time": signal_time,
                            "time_bucket": time_bucket(signal_time),
                            "stage": stage,
                            "direction": direction,
                            "setup_type": setup.setup_type,
                            "score": setup_score,
                            "ltp": float(setup.ltp),
                            "rel_vol": float(setup.rel_vol),
                            "vwap": float(setup.vwap),
                            "atr14": float(setup.atr14),
                            "ema20": float(setup.ema20),
                            "rsi14": float(setup.rsi14),
                            "true_velocity": float(setup.true_velocity),
                            "opening_range_high": float(setup.opening_range_high),
                            "opening_range_low": float(setup.opening_range_low),
                            "previous_day_high": float(setup.previous_day_high),
                            "previous_day_low": float(setup.previous_day_low),
                            "breakout_distance_atr": float(setup.breakout_distance_atr),
                            "dma_close": float(dma_close),
                            "dma_sma50": float(dma_sma50),
                            "dma_sma200": float(dma_sma200),
                            "entry_price": levels["entry"],
                            "stop_loss": levels["stop_loss"],
                            "target_1": levels["target_1"],
                            "target_2": levels["target_2"],
                            "risk": levels["risk"],
                            "risk_reward_t1": setup.risk_reward_t1,
                            "risk_reward_t2": setup.risk_reward_t2,
                            "outcome": outcome["outcome"],
                            "realized_r": float(outcome["realized_r"]),
                            "triggered": bool(outcome["triggered"]),
                            "trigger_time": outcome["trigger_time"],
                            "outcome_time": outcome["outcome_time"],
                        }

                        trades.append(trade)
                        stats["qualified_setups"] += 1

                        print(
                            f"  {session_date.strftime('%Y-%m-%d')} "
                            f"{signal_time.strftime('%H:%M')} | "
                            f"{stage:<10} | "
                            f"{direction:<7} | "
                            f"Score {trade['score']:5.1f} | "
                            f"Velocity {trade['true_velocity']:+.2f} | "
                            f"Entry {trade['entry_price']:.2f} | "
                            f"SL {trade['stop_loss']:.2f} | "
                            f"T1 {trade['target_1']:.2f} | "
                            f"T2 {trade['target_2']:.2f} | "
                            f"{trade['outcome']:<10} | "
                            f"{trade['realized_r']:+.1f}R"
                        )
        
        # FIX 5: Memory cleanup for both dataframes
        del chunk_data
        del daily_chunk_data
        print(f"\nProgress: {min(chunk_start + DOWNLOAD_CHUNK_SIZE, len(symbols))}/{len(symbols)} stocks")

    print_summary(trades, stats)

    # Optional CSV export for deeper analysis.
    if trades:
        out = pd.DataFrame(trades)
        path = "backtest_nifty500_v13_results.csv"
        out.to_csv(path, index=False)
        print(f"\nDetailed results saved to: {path}")


if __name__ == "__main__":
    run_nifty500_backtest()









