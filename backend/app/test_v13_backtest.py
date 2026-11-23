"""
V13 HISTORICAL BACKTEST
- Bullish and Bearish are evaluated independently.
- Does NOT modify app.v13_engine.
- Uses progressive historical data to avoid look-ahead.
- Uses point-in-time NIFTY + sector context.
- Uses candidate Entry/SL/T1/T2.
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from app.v13_engine import discover_v13_setups
from app.market_context import (
    build_market_context,
    get_sector_benchmark_ticker,
)
from app.config import NIFTY_500_STOCKS


OUT_CSV = Path("v13_backtest_results.csv")
CHUNK_SIZE = 20
MIN_BARS_AFTER_OR = 1

# The existing Yahoo 15m history available to the project is roughly 60 sessions.
# Keep this configurable, but do not request more than Yahoo 15m can provide.
PERIOD = "60d"
INTERVAL = "15m"


def _stock_fields(item):
    """Support the common dict/tuple formats used by stock lists."""
    if isinstance(item, dict):
        symbol = item.get("symbol") or item.get("ticker")
        name = item.get("name") or symbol
        sector = item.get("sector") or "Unknown"
        return symbol, name, sector

    if isinstance(item, (tuple, list)):
        if len(item) >= 3:
            return item[0], item[1], item[2]
        if len(item) == 2:
            return item[0], item[1], "Unknown"
        return item[0], item[0], "Unknown"

    return str(item), str(item), "Unknown"


def _clean_symbol(symbol: str) -> str:
    return symbol if symbol.endswith(".NS") else f"{symbol}.NS"


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    rename = {}
    for c in df.columns:
        rename[c] = str(c).strip().lower()
    df = df.rename(columns=rename)

    required = ["open", "high", "low", "close"]
    if not all(c in df.columns for c in required):
        return pd.DataFrame()

    df = df.copy()
    df.index = pd.to_datetime(df.index)

    # Make timezone explicit/consistent with NSE session timestamps.
    if getattr(df.index, "tz", None) is None:
        df.index = df.index.tz_localize("Asia/Kolkata")
    else:
        df.index = df.index.tz_convert("Asia/Kolkata")

    return df.sort_index()


def _download_one(ticker: str) -> pd.DataFrame:
    try:
        df = yf.download(
            ticker,
            period=PERIOD,
            interval=INTERVAL,
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        return _normalize_ohlcv(df)
    except Exception:
        return pd.DataFrame()


def _download_benchmarks(sectors):
    print("Downloading NIFTY + sector benchmark history...")

    benchmarks = {"__NIFTY__": "^NSEI"}

    for sector in sorted(set(sectors)):
        try:
            ticker = get_sector_benchmark_ticker(sector)
        except Exception:
            ticker = ""

        if ticker:
            benchmarks[sector] = ticker

    out = {}
    for key, ticker in benchmarks.items():
        print(f"  {key}: {ticker}")
        df = _download_one(ticker)
        if not df.empty:
            out[key] = df

    return out


def _session_dates(df: pd.DataFrame):
    if df.empty:
        return []
    return sorted(pd.Index(df.index.date).unique())


def _bars_for_date(df: pd.DataFrame, date):
    if df.empty:
        return df.iloc[0:0]
    return df[df.index.date == date].copy()


def _benchmark_context(benchmark_data, sector, signal_ts):
    """
    Point-in-time context:
      current benchmark close at signal timestamp
      versus previous available trading session close.

    This intentionally does NOT use the current day's final close.
    """
    nifty = benchmark_data.get("__NIFTY__")
    if nifty is None or nifty.empty:
        return None

    day = signal_ts.date()
    nifty_day = _bars_for_date(nifty, day)
    prior_days = [d for d in _session_dates(nifty) if d < day]
    if nifty_day.empty or not prior_days:
        return None

    prior_day = prior_days[-1]
    prior = _bars_for_date(nifty, prior_day)

    current = nifty_day[nifty_day.index <= signal_ts]
    if current.empty or prior.empty:
        return None

    current_close = float(current["close"].iloc[-1])
    previous_close = float(prior["close"].iloc[-1])

    if not math.isfinite(current_close) or not math.isfinite(previous_close):
        return None
    if previous_close == 0:
        return None

    nifty_change = (current_close / previous_close - 1.0) * 100.0

    sector_df = benchmark_data.get(sector)
    if sector_df is None or sector_df.empty:
        sector_change = 0.0
    else:
        sector_day = _bars_for_date(sector_df, day)
        sector_dates = [d for d in _session_dates(sector_df) if d < day]
        if sector_day.empty or not sector_dates:
            sector_change = 0.0
        else:
            sector_prior = _bars_for_date(sector_df, sector_dates[-1])
            sector_current = sector_day[sector_day.index <= signal_ts]
            if sector_current.empty or sector_prior.empty:
                sector_change = 0.0
            else:
                sc = float(sector_current["close"].iloc[-1])
                sp = float(sector_prior["close"].iloc[-1])
                sector_change = (sc / sp - 1.0) * 100.0 if sp else 0.0

    return build_market_context(
        nifty_change_pct=nifty_change,
        sector_change_pct=sector_change,
    )


def _time_bucket(ts):
    t = ts.time()
    if t < pd.Timestamp("10:00").time():
        return "09:30-10:00"
    if t < pd.Timestamp("11:00").time():
        return "10:00-11:00"
    if t < pd.Timestamp("12:00").time():
        return "11:00-12:00"
    if t < pd.Timestamp("14:00").time():
        return "12:00-14:00"
    return "14:00-15:30"


def _outcome(candidate, future_bars):
    """
    Outcome starts AFTER the signal bar.

    For confirmed setups, the candidate's Entry is the actual trigger level.
    For a future bar:
      - first check whether entry is touched;
      - once triggered, evaluate SL/T1/T2;
      - if SL and target are both inside one candle, SL wins conservatively.
    """
    direction = str(candidate.signal_type).upper()

    entry = float(candidate.entry_price)
    sl = float(candidate.stop_loss)
    t1 = float(candidate.target_1)
    t2 = float(candidate.target_2)

    if not all(math.isfinite(x) for x in (entry, sl, t1, t2)):
        return "INVALID", False, None, None

    triggered = False
    trigger_time = None

    for ts, row in future_bars.iterrows():
        o = float(row["open"])
        h = float(row["high"])
        l = float(row["low"])

        if not triggered:
            if direction == "BULLISH":
                # A long trigger requires price to trade at/above entry.
                if h < entry:
                    continue
            else:
                # A short trigger requires price to trade at/below entry.
                if l > entry:
                    continue

            triggered = True
            trigger_time = ts

        if direction == "BULLISH":
            sl_hit = l <= sl
            t2_hit = h >= t2
            t1_hit = h >= t1

            if sl_hit:
                return "SL_FIRST", True, trigger_time, ts
            if t2_hit:
                return "T2_FIRST", True, trigger_time, ts
            if t1_hit:
                return "T1_FIRST", True, trigger_time, ts

        else:
            sl_hit = h >= sl
            t2_hit = l <= t2
            t1_hit = l <= t1

            if sl_hit:
                return "SL_FIRST", True, trigger_time, ts
            if t2_hit:
                return "T2_FIRST", True, trigger_time, ts
            if t1_hit:
                return "T1_FIRST", True, trigger_time, ts

    return ("OPEN" if triggered else "NO_TRIGGER"), triggered, trigger_time, None


def _r_multiple(candidate, outcome):
    if outcome == "SL_FIRST":
        return -1.0
    if outcome == "T1_FIRST":
        return 1.5
    if outcome == "T2_FIRST":
        return 2.5
    return np.nan


def _already_taken(used, symbol, date, direction):
    return (symbol, date, direction) in used


def main():
    stocks = [_stock_fields(x) for x in NIFTY_500_STOCKS]
    sectors = [x[2] for x in stocks]

    print("=" * 100)
    print("V13 HISTORICAL BACKTEST — INDEPENDENT BULLISH / BEARISH")
    print("=" * 100)
    print("Current V13 engine/scoring: UNCHANGED")
    print("Look-ahead: progressively sliced stock data + point-in-time benchmark context")
    print(f"Yahoo history: {PERIOD} / {INTERVAL}")
    print()

    benchmark_data = _download_benchmarks(sectors)
    print(f"Benchmark histories available: {len(benchmark_data)}")
    print()

    all_rows = []
    used = set()

    for start in range(0, len(stocks), CHUNK_SIZE):
        chunk = stocks[start:start + CHUNK_SIZE]
        print(
            f"Processing stocks {start + 1}-{min(start + CHUNK_SIZE, len(stocks))}"
            f" of {len(stocks)}..."
        )

        for symbol, name, sector in chunk:
            ticker = _clean_symbol(symbol)
            df = _download_one(ticker)

            if df.empty:
                continue

            dates = _session_dates(df)

            for date in dates:
                day = _bars_for_date(df, date)
                if day.empty:
                    continue

                # Need an opening range and at least one later bar.
                day_times = list(day.index)
                after_or_positions = [
                    i for i, ts in enumerate(day_times)
                    if ts.time() >= pd.Timestamp("09:30").time()
                ]
                if not after_or_positions:
                    continue

                for pos in after_or_positions:
                    if pos < MIN_BARS_AFTER_OR:
                        continue

                    signal_ts = day_times[pos]

                    # Only data that existed at signal time is passed to V13.
                    historical_df = df[df.index <= signal_ts].copy()

                    context = _benchmark_context(
                        benchmark_data=benchmark_data,
                        sector=sector,
                        signal_ts=signal_ts,
                    )

                    if context is None:
                        continue

                    try:
                        discovered = discover_v13_setups(
                            symbol=symbol,
                            name=name,
                            sector=sector,
                            df=historical_df,
                            context=context,
                        )
                    except Exception:
                        continue

                    # IMPORTANT: each direction is handled independently.
                    for direction in ("bullish", "bearish"):
                        candidate = discovered.get(direction)

                        if candidate is None:
                            continue

                        candidate_date = signal_ts.date()
                        candidate_key = (
                            symbol,
                            candidate_date,
                            direction.upper(),
                        )

                        # First qualified setup per stock/session/direction.
                        if candidate_key in used:
                            continue

                        # Ensure candidate signal time corresponds to the
                        # progressively evaluated bar.
                        if getattr(candidate, "signal_time", None):
                            try:
                                cts = pd.Timestamp(candidate.signal_time)
                                if cts.tzinfo is None:
                                    cts = cts.tz_localize("Asia/Kolkata")
                                else:
                                    cts = cts.tz_convert("Asia/Kolkata")
                                if cts > signal_ts:
                                    continue
                            except Exception:
                                pass

                        future = day[day.index > signal_ts]
                        outcome, triggered, trigger_time, outcome_time = _outcome(
                            candidate, future
                        )

                        r = _r_multiple(candidate, outcome)

                        all_rows.append(
                            {
                                "symbol": candidate.symbol,
                                "name": candidate.name,
                                "sector": candidate.sector,
                                "date": str(date),
                                "signal_time": str(signal_ts),
                                "time_bucket": _time_bucket(signal_ts),
                                "direction": direction.upper(),
                                "signal_type": candidate.signal_type,
                                "setup_type": candidate.setup_type,
                                "score": float(candidate.score),
                                "action": candidate.action,
                                "entry_price": float(candidate.entry_price),
                                "stop_loss": float(candidate.stop_loss),
                                "target_1": float(candidate.target_1),
                                "target_2": float(candidate.target_2),
                                "risk": float(candidate.risk_amount),
                                "rel_vol": float(candidate.rel_vol),
                                "r_multiple": r,
                                "outcome": outcome,
                                "triggered": triggered,
                                "trigger_time": str(trigger_time) if trigger_time else "",
                                "outcome_time": str(outcome_time) if outcome_time else "",
                                "nifty_direction": getattr(context, "nifty_direction", "NEUTRAL"),
                                "nifty_change_pct": float(getattr(context, "nifty_change_pct", 0.0)),
                                "sector_direction": getattr(context, "sector_direction", "NEUTRAL"),
                                "sector_change_pct": float(getattr(context, "sector_change_pct", 0.0)),
                            }
                        )

                        used.add(candidate_key)

    result = pd.DataFrame(all_rows)

    if result.empty:
        print("\nNO QUALIFIED V13 HISTORICAL SETUPS FOUND.")
        return

    result.to_csv(OUT_CSV, index=False)

    print()
    print("=" * 100)
    print("BACKTEST SUMMARY")
    print("=" * 100)

    for direction in ("BULLISH", "BEARISH"):
        x = result[result.direction == direction].copy()
        closed = x[x.outcome.isin(["SL_FIRST", "T1_FIRST", "T2_FIRST"])].copy()

        print(f"\n{direction}")
        print("-" * 60)
        print(f"Qualified setups : {len(x)}")
        print(f"Triggered        : {int(x.triggered.sum())}")
        print(f"Closed trades    : {len(closed)}")

        if not closed.empty:
            wins = int(closed.r_multiple.gt(0).sum())
            wr = wins / len(closed) * 100.0
            avg_r = float(closed.r_multiple.mean())
            total_r = float(closed.r_multiple.sum())

            eq = closed.r_multiple.cumsum()
            dd = eq - eq.cummax()
            max_dd = float(dd.min())

            print(f"Win rate         : {wr:.2f}%")
            print(f"Avg closed R     : {avg_r:.3f}R")
            print(f"Total closed R   : {total_r:.2f}R")
            print(f"Max drawdown     : {max_dd:.2f}R")
        else:
            print("No closed trades.")

        print("\nScore buckets:")
        bins = [0, 60, 70, 75, 80, 85, 90, 101]
        labels = ["<60", "60-69", "70-74", "75-79", "80-84", "85-89", "90+"]
        x["score_bucket"] = pd.cut(
            x.score, bins=bins, labels=labels, right=False
        )

        for bucket in labels:
            b = x[x.score_bucket == bucket]
            c = b[b.outcome.isin(["SL_FIRST", "T1_FIRST", "T2_FIRST"])]
            if not c.empty:
                wins = int(c.r_multiple.gt(0).sum())
                wr = wins / len(c) * 100.0
                print(
                    f"  {bucket:>6}: trades={len(c):4d} "
                    f"WR={wr:6.2f}% avgR={c.r_multiple.mean():7.3f} "
                    f"totalR={c.r_multiple.sum():8.2f}"
                )

        print("\nTime buckets:")
        for bucket in [
            "09:30-10:00",
            "10:00-11:00",
            "11:00-12:00",
            "12:00-14:00",
            "14:00-15:30",
        ]:
            b = x[x.time_bucket == bucket]
            c = b[b.outcome.isin(["SL_FIRST", "T1_FIRST", "T2_FIRST"])]
            if not c.empty:
                wins = int(c.r_multiple.gt(0).sum())
                wr = wins / len(c) * 100.0
                print(
                    f"  {bucket}: trades={len(c):4d} "
                    f"WR={wr:6.2f}% avgR={c.r_multiple.mean():7.3f} "
                    f"totalR={c.r_multiple.sum():8.2f}"
                )

    print()
    print("=" * 100)
    print(f"CSV saved: {OUT_CSV.resolve()}")
    print("=" * 100)


if __name__ == "__main__":
    main()
