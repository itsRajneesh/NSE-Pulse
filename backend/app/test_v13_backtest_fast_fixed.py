"""
V13 FAST HISTORICAL BACKTEST
============================
Important:
- V13 engine/scoring is NOT modified.
- Bullish and Bearish are evaluated independently.
- Uses the project's existing low-memory NIFTY-500 fetcher.
- Uses progressive intraday slices to avoid look-ahead.
- Uses point-in-time NIFTY/sector context.
- Saves results only after the full run.

Run:
    python -m app.test_v13_backtest_fast
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from app.config import NIFTY_500_STOCKS, SECTOR_BENCHMARKS
from app.data_fetcher import fetch_nifty500_low_memory
from app.v13_engine import discover_v13_setups
from app.market_context import build_market_context


CHUNK_SIZE = 20
OUT_CSV = Path("v13_backtest_results_fast.csv")

# V13 needs the opening range first.  We evaluate at every available bar
# from 09:30 onward, but only until the FIRST candidate per
# stock/session/direction is found. This removes huge redundant work.
START_TIME = pd.Timestamp("09:30").time()


def stock_parts(stock):
    """Read the project's existing stock-list dict format safely."""
    if isinstance(stock, dict):
        symbol = stock.get("symbol") or stock.get("ticker")
        name = stock.get("name") or symbol
        sector = stock.get("sector") or "Unknown"
    else:
        symbol = stock[0]
        name = stock[1] if len(stock) > 1 else symbol
        sector = stock[2] if len(stock) > 2 else "Unknown"
    return str(symbol), str(name), str(sector)


def normalize_df(df):
    if df is None or getattr(df, "empty", True):
        return pd.DataFrame()

    df = df.copy()

    if isinstance(df.columns, pd.MultiIndex):
        # If the fetcher returns one-symbol data with a MultiIndex,
        # flatten it.
        df.columns = df.columns.get_level_values(-1)

    rename = {c: str(c).strip().lower() for c in df.columns}
    df.rename(columns=rename, inplace=True)

    required = {"open", "high", "low", "close"}
    if not required.issubset(df.columns):
        return pd.DataFrame()

    df.index = pd.to_datetime(df.index)

    try:
        if df.index.tz is None:
            df.index = df.index.tz_localize("Asia/Kolkata")
        else:
            df.index = df.index.tz_convert("Asia/Kolkata")
    except Exception:
        pass

    return df.sort_index()


def extract_fetch_result(raw):
    """
    Convert common fetcher return shapes into:
        {symbol: DataFrame}

    The existing project has changed fetcher internals across versions,
    so this deliberately accepts dict/list/tuple forms.
    """
    if isinstance(raw, dict):
        result = {}
        for key, value in raw.items():
            if isinstance(value, pd.DataFrame):
                result[str(key).replace(".NS", "")] = normalize_df(value)
            elif isinstance(value, dict):
                df = value.get("data") or value.get("df")
                if isinstance(df, pd.DataFrame):
                    result[str(key).replace(".NS", "")] = normalize_df(df)
        return result

    result = {}
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, dict):
                symbol = item.get("symbol") or item.get("ticker")
                df = item.get("data") or item.get("df")
                if symbol and isinstance(df, pd.DataFrame):
                    result[str(symbol).replace(".NS", "")] = normalize_df(df)
    return result


def session_dates(df):
    return sorted(pd.Index(df.index.date).unique())


def day_df(df, date):
    return df[df.index.date == date].copy()


def _close_before_or_at(df, ts):
    x = df[df.index <= ts]
    if x.empty:
        return None
    return float(x["close"].iloc[-1])


def _previous_session_close(df, date):
    dates = session_dates(df)
    prior = [d for d in dates if d < date]
    if not prior:
        return None
    x = day_df(df, prior[-1])
    if x.empty:
        return None
    return float(x["close"].iloc[-1])


def build_point_in_time_context(
    signal_ts,
    sector,
    nifty_df,
    sector_benchmarks,
):
    """
    Signal-time benchmark move versus previous session close.
    No current-day final close is used.
    """
    if nifty_df is None or nifty_df.empty:
        return None

    date = signal_ts.date()

    n_now = _close_before_or_at(nifty_df, signal_ts)
    n_prev = _previous_session_close(nifty_df, date)
    if n_now is None or n_prev in (None, 0):
        return None

    nifty_change = (n_now / n_prev - 1.0) * 100.0

    ticker = SECTOR_BENCHMARKS.get(sector)
    s_df = sector_benchmarks.get(sector)

    if not ticker or s_df is None or s_df.empty:
        sector_change = 0.0
    else:
        s_now = _close_before_or_at(s_df, signal_ts)
        s_prev = _previous_session_close(s_df, date)
        if s_now is None or s_prev in (None, 0):
            sector_change = 0.0
        else:
            sector_change = (s_now / s_prev - 1.0) * 100.0

    return build_market_context(
        nifty_change_pct=nifty_change,
        sector_change_pct=sector_change,
    )


def bucket(ts):
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


def outcome(candidate, future):
    direction = str(candidate.signal_type).upper()

    entry = float(candidate.entry_price)
    sl = float(candidate.stop_loss)
    t1 = float(candidate.target_1)
    t2 = float(candidate.target_2)

    if not all(math.isfinite(x) for x in (entry, sl, t1, t2)):
        return "INVALID", False, None, None

    triggered = False
    trigger_time = None

    for ts, row in future.iterrows():
        h = float(row["high"])
        l = float(row["low"])

        if not triggered:
            if direction == "BULLISH":
                if h < entry:
                    continue
            else:
                if l > entry:
                    continue
            triggered = True
            trigger_time = ts

        if direction == "BULLISH":
            # Conservative intrabar rule: SL wins if SL and target
            # are both touched in the same candle.
            if l <= sl:
                return "SL_FIRST", True, trigger_time, ts
            if h >= t2:
                return "T2_FIRST", True, trigger_time, ts
            if h >= t1:
                return "T1_FIRST", True, trigger_time, ts
        else:
            if h >= sl:
                return "SL_FIRST", True, trigger_time, ts
            if l <= t2:
                return "T2_FIRST", True, trigger_time, ts
            if l <= t1:
                return "T1_FIRST", True, trigger_time, ts

    return ("OPEN" if triggered else "NO_TRIGGER"), triggered, trigger_time, None


def r_multiple(outcome_name):
    return {
        "SL_FIRST": -1.0,
        "T1_FIRST": 1.5,
        "T2_FIRST": 2.5,
    }.get(outcome_name, np.nan)


def main():
    stocks = [(s["symbol"], s["name"], s["sector"]) for s in NIFTY_500_STOCKS]

    print("=" * 100)
    print("V13 FAST HISTORICAL BACKTEST — INDEPENDENT BULLISH / BEARISH")
    print("=" * 100)
    print("V13 engine/scoring: UNCHANGED")
    print("Data fetch: existing fetch_nifty500_low_memory()")
    print("Look-ahead: progressive stock slices + point-in-time benchmark context")
    print()

    # Existing project fetcher. This is the major speed improvement:
    # stock data is fetched once per chunk instead of once per historical
    # session/checkpoint.
    # IMPORTANT: the existing project fetcher yields (symbol, DataFrame)
    # pairs. It is NOT a dict. This is the same interface used by the
    # already-working test_v13_full_scan.py.
    stock_data = {}

    for sym, df_15m in fetch_nifty500_low_memory(
        NIFTY_500_STOCKS,
        chunk_size=CHUNK_SIZE,
    ):
        if df_15m is not None and not df_15m.empty:
            stock_data[str(sym).replace(".NS", "")] = normalize_df(df_15m)

    print(f"Stock datasets received: {len(stock_data)}")
    if not stock_data:
        print("ERROR: existing fetcher returned no usable DataFrames.")
        return

    # Benchmarks are downloaded ONCE and then reused for every stock/session.
    # This avoids repeated network calls during the historical loop.
    import yfinance as yf
    from app.market_context import get_sector_benchmark_ticker

    def download_benchmark(ticker):
        try:
            x = yf.download(
                ticker,
                period="60d",
                interval="15m",
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            return normalize_df(x)
        except Exception:
            return pd.DataFrame()

    print("Preparing benchmark histories...")
    nifty_df = download_benchmark("^NSEI")
    sector_benchmarks = {}

    for sector in sorted(set(s for _, _, s in stocks)):
        try:
            ticker = get_sector_benchmark_ticker(sector)
        except Exception:
            ticker = ""
        if not ticker:
            continue
        sdf = download_benchmark(ticker)
        if not sdf.empty:
            sector_benchmarks[sector] = sdf

    print(f"Sector benchmark datasets: {len(sector_benchmarks)}")
    print()

    # Build the stock metadata lookup once. This avoids an O(500) search for
    # every fetched stock.
    stock_meta = {
        str(s["symbol"]).replace(".NS", ""): s
        for s in NIFTY_500_STOCKS
    }

    rows = []
    scanned = 0

    for symbol, df in stock_data.items():
        stock_info = stock_meta.get(symbol)
        if not stock_info or df.empty:
            continue

        name = stock_info["name"]
        sector = stock_info["sector"]

        scanned += 1
        dates = session_dates(df)

        # Per stock/session we stop evaluating a direction once its first
        # candidate has been found. Bullish and Bearish have separate flags.
        for date in dates:
            day = day_df(df, date)
            if day.empty:
                continue

            bull_done = False
            bear_done = False

            for i, signal_ts in enumerate(day.index):
                if signal_ts.time() < START_TIME:
                    continue

                if bull_done and bear_done:
                    break

                # Progressive slice: V13 only sees bars available at signal time.
                hist = df[df.index <= signal_ts].copy()
                if hist.empty:
                    continue

                context = build_point_in_time_context(
                    signal_ts=signal_ts,
                    sector=sector,
                    nifty_df=nifty_df,
                    sector_benchmarks=sector_benchmarks,
                )
                if context is None:
                    continue

                try:
                    found = discover_v13_setups(
                        symbol=symbol,
                        name=name,
                        sector=sector,
                        df=hist,
                        context=context,
                    )
                except Exception:
                    # One bad stock/checkpoint must not abort a 500-stock run.
                    continue

                future = day[day.index > signal_ts]

                # ---------------- BULLISH ----------------
                if not bull_done:
                    candidate = found.get("bullish")
                    if candidate is not None:
                        out, trig, trig_ts, out_ts = outcome(candidate, future)
                        rows.append({
                            "symbol": candidate.symbol,
                            "name": candidate.name,
                            "sector": candidate.sector,
                            "date": str(date),
                            "signal_time": str(signal_ts),
                            "time_bucket": bucket(signal_ts),
                            "direction": "BULLISH",
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
                            "outcome": out,
                            "triggered": trig,
                            "trigger_time": str(trig_ts) if trig_ts else "",
                            "outcome_time": str(out_ts) if out_ts else "",
                            "r_multiple": r_multiple(out),
                            "nifty_direction": context.nifty_direction,
                            "nifty_change_pct": context.nifty_change_pct,
                            "sector_direction": context.sector_direction,
                            "sector_change_pct": context.sector_change_pct,
                        })
                        bull_done = True

                # ---------------- BEARISH ----------------
                if not bear_done:
                    candidate = found.get("bearish")
                    if candidate is not None:
                        out, trig, trig_ts, out_ts = outcome(candidate, future)
                        rows.append({
                            "symbol": candidate.symbol,
                            "name": candidate.name,
                            "sector": candidate.sector,
                            "date": str(date),
                            "signal_time": str(signal_ts),
                            "time_bucket": bucket(signal_ts),
                            "direction": "BEARISH",
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
                            "outcome": out,
                            "triggered": trig,
                            "trigger_time": str(trig_ts) if trig_ts else "",
                            "outcome_time": str(out_ts) if out_ts else "",
                            "r_multiple": r_multiple(out),
                            "nifty_direction": context.nifty_direction,
                            "nifty_change_pct": context.nifty_change_pct,
                            "sector_direction": context.sector_direction,
                            "sector_change_pct": context.sector_change_pct,
                        })
                        bear_done = True

        if scanned % 20 == 0:
            print(f"Processed {scanned}/{len(stock_data)} stocks...")

    result = pd.DataFrame(rows)

    print()
    print("=" * 100)
    print("V13 BACKTEST RESULTS")
    print("=" * 100)

    if result.empty:
        print("NO QUALIFIED SETUPS FOUND.")
        return

    result.to_csv(OUT_CSV, index=False)

    for direction in ("BULLISH", "BEARISH"):
        x = result[result.direction == direction]
        closed = x[x.outcome.isin(["SL_FIRST", "T1_FIRST", "T2_FIRST"])]

        print()
        print(direction)
        print("-" * 70)
        print(f"Qualified setups : {len(x)}")
        print(f"Triggered        : {int(x.triggered.sum())}")
        print(f"Closed trades    : {len(closed)}")

        if closed.empty:
            print("No closed trades.")
        else:
            wins = int((closed.r_multiple > 0).sum())
            wr = wins / len(closed) * 100
            avg_r = closed.r_multiple.mean()
            total_r = closed.r_multiple.sum()
            eq = closed.r_multiple.cumsum()
            dd = eq - eq.cummax()

            print(f"Win rate         : {wr:.2f}%")
            print(f"Avg closed R     : {avg_r:.3f}R")
            print(f"Total closed R   : {total_r:.2f}R")
            print(f"Max drawdown     : {dd.min():.2f}R")

            print("\nScore buckets:")
            bins = [0, 60, 70, 75, 80, 85, 90, 101]
            labels = ["<60", "60-69", "70-74", "75-79", "80-84", "85-89", "90+"]
            temp = closed.copy()
            temp["score_bucket"] = pd.cut(
                temp.score, bins=bins, labels=labels, right=False
            )

            for label in labels:
                b = temp[temp.score_bucket == label]
                if b.empty:
                    continue
                bwr = (b.r_multiple > 0).mean() * 100
                print(
                    f"  {label:>6}: trades={len(b):4d} "
                    f"WR={bwr:6.2f}% avgR={b.r_multiple.mean():7.3f} "
                    f"totalR={b.r_multiple.sum():8.2f}"
                )

            print("\nTime buckets:")
            for tb in [
                "09:30-10:00",
                "10:00-11:00",
                "11:00-12:00",
                "12:00-14:00",
                "14:00-15:30",
            ]:
                b = closed[closed.time_bucket == tb]
                if b.empty:
                    continue
                bwr = (b.r_multiple > 0).mean() * 100
                print(
                    f"  {tb}: trades={len(b):4d} "
                    f"WR={bwr:6.2f}% avgR={b.r_multiple.mean():7.3f} "
                    f"totalR={b.r_multiple.sum():8.2f}"
                )

    print()
    print("=" * 100)
    print(f"CSV saved: {OUT_CSV.resolve()}")
    print("=" * 100)


if __name__ == "__main__":
    main()
