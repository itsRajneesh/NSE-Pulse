"""
V13.1 RETEST -> RECLAIM -> HOLD validation
RESEARCH ONLY. Does not modify v13_engine.py.

Uses the existing V13.1 candidate rule:
BULLISH + True Velocity > 0 + Breakout Distance 0.50-1.25 ATR + RelVol <= 1.50x

Buckets:
A NO_RETEST
B RETEST_NO_RECLAIM
C RETEST_RECLAIM_NO_HOLD
D RETEST_RECLAIM_HOLD

Definitions:
- Retest: after trigger, Low <= OR high.
- Reclaim: after retest, a later Close > OR high.
- Hold: after reclaim, within the next 3 five-minute candles, price does not
  produce a Close <= OR high AND at least one subsequent Close remains > OR high.
This is deliberately descriptive, not an engine rule.

Only matched Yahoo 5m data is analyzed.
"""

from pathlib import Path
import time
import math
import pandas as pd
import numpy as np
import yfinance as yf

BASE = Path(__file__).resolve().parent
CSV = BASE / "backtest_nifty500_v13_results.csv"
OUT = BASE / "v13_1_retest_reclaim_hold_validation.csv"

START = pd.Timestamp("2026-07-01")
END = pd.Timestamp("2026-09-13")


def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else np.nan
    except Exception:
        return np.nan


def load_candidates():
    df = pd.read_csv(CSV)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["signal_time"] = (
        pd.to_datetime(df["signal_time"], errors="coerce", utc=True)
        .dt.tz_convert("Asia/Kolkata")
        .dt.tz_localize(None)
    )
    for c in [
        "true_velocity", "breakout_distance_atr", "rel_vol",
        "entry_price", "stop_loss", "target_1", "opening_range_high",
        "realized_r"
    ]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    mask = (
        (df["date"] >= START)
        & (df["date"] < END)
        & (df["direction"].astype(str).str.upper() == "BULLISH")
        & (df["true_velocity"] > 0)
        & (df["breakout_distance_atr"].between(0.50, 1.25, inclusive="both"))
        & (df["rel_vol"] <= 1.50)
        & (df["outcome"].astype(str).isin(["SL_FIRST", "T1_FIRST", "T2_FIRST"]))
    )
    return df.loc[mask].sort_values(["signal_time", "symbol"]).reset_index(drop=True)


def download(symbol, day):
    ticker = str(symbol).strip().upper()
    if not ticker.endswith(".NS"):
        ticker += ".NS"

    d = pd.Timestamp(day).normalize()
    print(f"Downloading {ticker}: {d.date()} -> {(d + pd.Timedelta(days=1)).date()}")

    try:
        x = yf.download(
            ticker,
            start=d.strftime("%Y-%m-%d"),
            end=(d + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            interval="5m",
            auto_adjust=False,
            progress=False,
            prepost=False,
            threads=False,
        )
    except Exception as e:
        print(f"  ERROR: {e}")
        return pd.DataFrame()

    if x is None or x.empty:
        print("  No 5m data returned.")
        return pd.DataFrame()

    if isinstance(x.columns, pd.MultiIndex):
        try:
            if ticker in x.columns.get_level_values(-1):
                x = x.xs(ticker, axis=1, level=-1)
            elif ticker in x.columns.get_level_values(0):
                x = x.xs(ticker, axis=1, level=0)
        except Exception:
            pass

    required = ["Open", "High", "Low", "Close"]
    if any(c not in x.columns for c in required):
        return pd.DataFrame()

    x = x[[c for c in required if c in x.columns]].copy()
    x.index = pd.to_datetime(x.index, errors="coerce")
    x = x[~x.index.isna()].copy()

    if x.index.tz is not None:
        x.index = x.index.tz_convert("Asia/Kolkata").tz_localize(None)

    return x[
        (x.index >= d + pd.Timedelta(hours=9, minutes=15))
        & (x.index <= d + pd.Timedelta(hours=15, minutes=30))
    ].copy()


def classify(candles, signal_time, or_high):
    pos = candles.index.searchsorted(signal_time)
    if pos >= len(candles) or not np.isfinite(or_high):
        return {"bucket": "UNKNOWN"}

    trigger_time = candles.index[pos]
    after = candles[candles.index > trigger_time].head(36).copy()
    if after.empty:
        return {"bucket": "UNKNOWN"}

    low = pd.to_numeric(after["Low"], errors="coerce")
    close = pd.to_numeric(after["Close"], errors="coerce")

    retest_mask = low <= or_high
    if not bool(retest_mask.any()):
        return {
            "bucket": "NO_RETEST",
            "retest_time": None,
            "reclaim_time": None,
            "hold_time": None,
            "hold_broken": False,
        }

    ri = int(np.where(retest_mask.to_numpy())[0][0])
    retest_time = after.index[ri]
    later = after.iloc[ri + 1:].copy()

    if later.empty:
        return {
            "bucket": "RETEST_NO_RECLAIM",
            "retest_time": str(retest_time),
            "reclaim_time": None,
            "hold_time": None,
            "hold_broken": False,
        }

    later_close = pd.to_numeric(later["Close"], errors="coerce")
    reclaim_mask = later_close > or_high

    if not bool(reclaim_mask.any()):
        return {
            "bucket": "RETEST_NO_RECLAIM",
            "retest_time": str(retest_time),
            "reclaim_time": None,
            "hold_time": None,
            "hold_broken": False,
        }

    ci = int(np.where(reclaim_mask.to_numpy())[0][0])
    reclaim_time = later.index[ci]

    post = later.iloc[ci + 1:].head(3).copy()
    post_close = pd.to_numeric(post["Close"], errors="coerce")

    # Need at least one subsequent candle to assess hold.
    if post.empty:
        return {
            "bucket": "RETEST_RECLAIM_NO_HOLD",
            "retest_time": str(retest_time),
            "reclaim_time": str(reclaim_time),
            "hold_time": None,
            "hold_broken": False,
        }

    broken = bool((post_close <= or_high).any())

    # "Hold" = no OR-high closing failure across next 3 candles
    # and at least one subsequent close is still above OR high.
    hold = (not broken) and bool((post_close > or_high).any())

    return {
        "bucket": "RETEST_RECLAIM_HOLD" if hold else "RETEST_RECLAIM_NO_HOLD",
        "retest_time": str(retest_time),
        "reclaim_time": str(reclaim_time),
        "hold_time": str(post.index[0]) if hold else None,
        "hold_broken": broken,
    }


def main():
    cand = load_candidates()

    print()
    print("=" * 112)
    print("V13.1 RETEST -> RECLAIM -> HOLD VALIDATION")
    print("=" * 112)
    print(f"Candidate trades : {len(cand)}")
    print(f"Window           : {START.date()} -> {END.date()}")
    print()
    print("NO_RETEST | RETEST_NO_RECLAIM | RETEST_RECLAIM_NO_HOLD | RETEST_RECLAIM_HOLD")

    cache = {}
    rows = []

    for _, r in cand.iterrows():
        symbol = str(r["symbol"]).strip()
        day = pd.Timestamp(r["date"]).normalize()
        key = (symbol, str(day.date()))

        if key not in cache:
            cache[key] = download(symbol, day)
            time.sleep(0.15)

        candles = cache[key]

        base = {
            "symbol": symbol,
            "date": str(day.date()),
            "signal_time": str(r["signal_time"]),
            "outcome": str(r["outcome"]),
            "realized_r": num(r["realized_r"]),
            "matched": False,
        }

        if candles.empty:
            rows.append(base)
            continue

        base["matched"] = True
        base["entry_price"] = num(r["entry_price"])
        base["target_1"] = num(r["target_1"])
        base["or_high"] = num(r["opening_range_high"])

        base.update(
            classify(
                candles,
                pd.Timestamp(r["signal_time"]),
                base["or_high"],
            )
        )

        # Post-reclaim excursion over the next 30 minutes.
        if base.get("reclaim_time"):
            rt = pd.Timestamp(base["reclaim_time"])
            post = candles[
                (candles.index > rt)
                & (candles.index <= rt + pd.Timedelta(minutes=30))
            ].copy()
            if not post.empty:
                base["post_reclaim_max_high"] = float(
                    pd.to_numeric(post["High"], errors="coerce").max()
                )
                base["post_reclaim_min_low"] = float(
                    pd.to_numeric(post["Low"], errors="coerce").min()
                )
                if np.isfinite(base["entry_price"]) and base["entry_price"] != 0:
                    base["post_reclaim_max_high_pct"] = (
                        base["post_reclaim_max_high"] / base["entry_price"] - 1
                    ) * 100
                else:
                    base["post_reclaim_max_high_pct"] = np.nan
            else:
                base["post_reclaim_max_high"] = np.nan
                base["post_reclaim_min_low"] = np.nan
                base["post_reclaim_max_high_pct"] = np.nan
        else:
            base["post_reclaim_max_high"] = np.nan
            base["post_reclaim_min_low"] = np.nan
            base["post_reclaim_max_high_pct"] = np.nan

        rows.append(base)

    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)

    m = df[df["matched"] == True].copy()

    print()
    print("DATA COVERAGE")
    print("-" * 112)
    print(f"Candidate trades : {len(df)}")
    print(f"5m matched       : {len(m)}")
    print(f"5m missing       : {len(df) - len(m)}")

    print()
    print("BUCKET PERFORMANCE MATRIX")
    print("-" * 112)
    print(
        f"{'BUCKET':28s} {'N':>4s} {'TARGET':>8s} {'SL':>6s} "
        f"{'TARGET %':>10s} {'SL %':>7s} {'Avg R':>10s} "
        f"{'Total R':>10s} {'Avg T1 min':>12s}"
    )
    print("-" * 112)

    for bucket in [
        "NO_RETEST",
        "RETEST_NO_RECLAIM",
        "RETEST_RECLAIM_NO_HOLD",
        "RETEST_RECLAIM_HOLD",
    ]:
        x = m[m["bucket"] == bucket]
        n = len(x)
        if not n:
            print(f"{bucket:28s} {0:4d}")
            continue

        target = x["outcome"].isin(["T1_FIRST", "T2_FIRST"])
        sl = x["outcome"].eq("SL_FIRST")
        t1 = pd.to_numeric(x.loc[target, "signal_time"], errors="coerce")  # placeholder
        # T1 timing is not directly available in source CSV; report only if
        # target trades have a reclaim timestamp and target outcome.
        avg_r = float(x["realized_r"].mean())
        total_r = float(x["realized_r"].sum())

        # Time from signal to reclaim is a structural timing proxy.
        rt = pd.to_datetime(x["reclaim_time"], errors="coerce")
        st = pd.to_datetime(x["signal_time"], errors="coerce")
        avg_reclaim = ((rt - st).dt.total_seconds() / 60).mean()

        print(
            f"{bucket:28s} {n:4d} {int(target.sum()):8d} {int(sl.sum()):6d} "
            f"{target.mean()*100:9.1f}% {sl.mean()*100:6.1f}% "
            f"{avg_r:10.4f} {total_r:10.2f} {avg_reclaim:12.1f}"
        )

    print()
    print("OUTCOME COUNTS BY BUCKET")
    print("-" * 112)
    print(pd.crosstab(m["bucket"], m["outcome"]).to_string())

    print()
    print("IMPORTANT")
    print("-" * 112)
    print("The final column is average minutes to RECLAIM, not time to T1.")
    print("A bucket is descriptive only; no trading rule is promoted from this sample.")
    print("Yahoo 5m history limitations mean matched coverage is partial.")

    print(f"Saved: {OUT.name}")


if __name__ == "__main__":
    main()
