"""
V13.1 Retest -> Reclaim Isolation Test
--------------------------------------
RESEARCH ONLY. v13_engine.py is NOT modified.

Buckets:
1) NO_RETEST
2) RETEST_NO_RECLAIM
3) RETEST_RECLAIM

Universe:
BULLISH + TV > 0 + BD 0.50-1.25 ATR + RelVol <= 1.50x
Outcomes limited to SL_FIRST/T1_FIRST/T2_FIRST.
July 1 -> Sep 12, 2026.

Important:
- Retest/reclaim is post-trigger information, so this is a confirmation-study,
  NOT a claim that the original entry should be delayed.
- Yahoo 5m history is limited; July trades may be unavailable.
"""

from pathlib import Path
import time
import math
import pandas as pd
import numpy as np
import yfinance as yf

BASE = Path(__file__).resolve().parent
CSV = BASE / "backtest_nifty500_v13_results.csv"
OUT = BASE / "v13_1_retest_reclaim_isolation.csv"

START = pd.Timestamp("2026-07-01")
END = pd.Timestamp("2026-09-13")


def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else np.nan
    except Exception:
        return np.nan


def load():
    df = pd.read_csv(CSV)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["signal_time"] = pd.to_datetime(
        df["signal_time"], errors="coerce", utc=True
    ).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)

    for c in [
        "true_velocity", "breakout_distance_atr", "rel_vol",
        "entry_price", "stop_loss", "opening_range_high",
        "atr14", "realized_r"
    ]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    mask = (
        (df["date"] >= START)
        & (df["date"] < END)
        & (df["direction"].astype(str).str.upper() == "BULLISH")
        & (df["true_velocity"] > 0)
        & (df["breakout_distance_atr"] >= 0.50)
        & (df["breakout_distance_atr"] <= 1.25)
        & (df["rel_vol"] <= 1.50)
        & (df["outcome"].astype(str).isin(["SL_FIRST", "T1_FIRST", "T2_FIRST"]))
    )
    return df.loc[mask].sort_values(["signal_time", "symbol"]).reset_index(drop=True)


def download(symbol, day):
    ticker = str(symbol).upper().strip()
    if not ticker.endswith(".NS"):
        ticker += ".NS"

    start = pd.Timestamp(day).normalize()
    end = start + pd.Timedelta(days=1)

    print(f"Downloading {ticker}: {start.date()} -> {end.date()}")

    try:
        x = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
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

    need = ["Open", "High", "Low", "Close"]
    if any(c not in x.columns for c in need):
        return pd.DataFrame()

    keep = need + (["Volume"] if "Volume" in x.columns else [])
    x = x[keep].copy()
    x.index = pd.to_datetime(x.index, errors="coerce")
    x = x[~x.index.isna()].copy()

    if x.index.tz is not None:
        x.index = x.index.tz_convert("Asia/Kolkata").tz_localize(None)

    d = pd.Timestamp(day).normalize()
    return x[
        (x.index >= d + pd.Timedelta(hours=9, minutes=15))
        & (x.index <= d + pd.Timedelta(hours=15, minutes=30))
    ].copy()


def first_trigger(candles, signal_time):
    pos = candles.index.searchsorted(signal_time)
    if pos >= len(candles):
        return None, None
    return candles.iloc[pos], candles.index[pos]


def classify(candles, trigger_time, or_high):
    """
    Retest definition:
      After trigger, price returns to OR high or below it.
    Reclaim definition:
      After a retest, a later 5m close moves strictly back above OR high.

    We also record whether the OR level was broken and whether reclaim occurred
    after that retest, preserving temporal order.
    """
    after = candles[candles.index > trigger_time].copy()
    after = after.head(36)  # first 3 hours, enough for structural classification

    if after.empty or not np.isfinite(or_high):
        return {
            "bucket": "UNKNOWN",
            "retest_seen": False,
            "retest_time": None,
            "reclaim_seen": False,
            "reclaim_time": None,
            "broken_after_retest": False,
        }

    low = pd.to_numeric(after["Low"], errors="coerce")
    close = pd.to_numeric(after["Close"], errors="coerce")

    # First actual retest: low touches OR high or crosses below it.
    retest_mask = low <= or_high
    if not bool(retest_mask.any()):
        return {
            "bucket": "NO_RETEST",
            "retest_seen": False,
            "retest_time": None,
            "reclaim_seen": False,
            "reclaim_time": None,
            "broken_after_retest": False,
        }

    idx = np.where(retest_mask.to_numpy())[0][0]
    retest_time = after.index[idx]

    later = after.iloc[idx + 1:]
    later_close = pd.to_numeric(later["Close"], errors="coerce")

    reclaim_mask = later_close > or_high
    reclaim_seen = bool(reclaim_mask.any())

    if reclaim_seen:
        reclaim_idx = np.where(reclaim_mask.to_numpy())[0][0]
        reclaim_time = later.index[reclaim_idx]
    else:
        reclaim_time = None

    broken_after = bool((later_close < or_high).any())

    if reclaim_seen:
        bucket = "RETEST_RECLAIM"
    else:
        bucket = "RETEST_NO_RECLAIM"

    return {
        "bucket": bucket,
        "retest_seen": True,
        "retest_time": str(retest_time),
        "reclaim_seen": reclaim_seen,
        "reclaim_time": str(reclaim_time) if reclaim_time is not None else None,
        "broken_after_retest": broken_after,
    }


def time_to_t1(candles, trigger_time, entry, target1):
    after = candles[candles.index > trigger_time]
    if after.empty:
        return np.nan

    hi = pd.to_numeric(after["High"], errors="coerce")
    hit = hi >= target1
    if not bool(hit.any()):
        return np.nan

    i = np.where(hit.to_numpy())[0][0]
    return float((after.index[i] - trigger_time).total_seconds() / 60.0)


def main():
    cand = load()

    print()
    print("=" * 112)
    print("V13.1 RETEST -> RECLAIM ISOLATION TEST")
    print("=" * 112)
    print(f"Candidate trades : {len(cand)}")
    print(f"Window           : {START.date()} -> {END.date()}")
    print()
    print("Buckets: NO_RETEST | RETEST_NO_RECLAIM | RETEST_RECLAIM")
    print("Retest = price returns to/touches OR high after trigger.")
    print("Reclaim = later 5m close strictly above OR high.")
    print("This is a confirmation-study; it does NOT assume delayed entry.")

    cache = {}
    rows = []

    for _, r in cand.iterrows():
        symbol = str(r["symbol"]).strip()
        day = pd.Timestamp(r["date"]).normalize()
        key = (symbol, str(day.date()))

        if key not in cache:
            cache[key] = download(symbol, day)
            time.sleep(0.15)

        c = cache[key]

        out = {
            "symbol": symbol,
            "date": str(day.date()),
            "signal_time": str(r["signal_time"]),
            "outcome": str(r["outcome"]),
            "realized_r": num(r["realized_r"]),
            "matched": False,
        }

        if c.empty:
            rows.append(out)
            continue

        entry = num(r["entry_price"])
        stop = num(r["stop_loss"])
        target1 = num(r.get("target_1", np.nan))
        risk = abs(entry - stop)
        or_high = num(r["opening_range_high"])

        trigger, trigger_time = first_trigger(c, pd.Timestamp(r["signal_time"]))

        if trigger is None or not np.isfinite(risk) or risk <= 0:
            rows.append(out)
            continue

        out["matched"] = True
        out["trigger_time"] = str(trigger_time)
        out["entry_price"] = entry
        out["risk"] = risk
        out["or_high"] = or_high

        cls = classify(c, trigger_time, or_high)
        out.update(cls)

        out["minutes_to_retest"] = np.nan
        if cls["retest_time"]:
            rt = pd.Timestamp(cls["retest_time"])
            out["minutes_to_retest"] = float(
                (rt - trigger_time).total_seconds() / 60.0
            )

        out["minutes_to_reclaim"] = np.nan
        if cls["reclaim_time"]:
            rc = pd.Timestamp(cls["reclaim_time"])
            out["minutes_to_reclaim"] = float(
                (rc - trigger_time).total_seconds() / 60.0
            )

        if np.isfinite(target1):
            out["minutes_to_t1"] = time_to_t1(
                c, trigger_time, entry, target1
            )
        else:
            out["minutes_to_t1"] = np.nan

        rows.append(out)

    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)

    m = df[df["matched"] == True].copy()

    print()
    print("DATA COVERAGE")
    print("-" * 112)
    print(f"Candidate trades : {len(df)}")
    print(f"5m matched       : {len(m)}")
    print(f"5m missing       : {len(df) - len(m)}")

    if m.empty:
        print(f"Saved: {OUT.name}")
        return

    print()
    print("BUCKET PERFORMANCE MATRIX")
    print("-" * 112)
    print(
        f"{'BUCKET':24s} {'N':>4s} {'TARGET':>9s} {'SL':>7s} "
        f"{'TARGET %':>10s} {'SL %':>7s} {'Avg R':>10s} "
        f"{'Total R':>10s} {'Avg T1 min':>12s}"
    )
    print("-" * 112)

    total_targets = int(m["outcome"].isin(["T1_FIRST", "T2_FIRST"]).sum())
    total_sl = int(m["outcome"].eq("SL_FIRST").sum())

    for bucket in ["NO_RETEST", "RETEST_NO_RECLAIM", "RETEST_RECLAIM"]:
        x = m[m["bucket"] == bucket]
        n = len(x)
        if n == 0:
            print(f"{bucket:24s} {0:4d}")
            continue

        tn = int(x["outcome"].isin(["T1_FIRST", "T2_FIRST"]).sum())
        sn = int(x["outcome"].eq("SL_FIRST").sum())
        avg_r = float(x["realized_r"].mean())
        total_r = float(x["realized_r"].sum())
        t1 = pd.to_numeric(x["minutes_to_t1"], errors="coerce").dropna()
        avg_t1 = float(t1.mean()) if len(t1) else np.nan

        print(
            f"{bucket:24s} {n:4d} {tn:9d} {sn:7d} "
            f"{(tn/n*100):9.1f}% {(sn/n*100):6.1f}% "
            f"{avg_r:10.4f} {total_r:10.2f} {avg_t1:12.1f}"
        )

    print()
    print("OUTCOME COUNTS BY BUCKET")
    print("-" * 112)
    pivot = pd.crosstab(m["bucket"], m["outcome"])
    print(pivot.to_string())

    print()
    print("RETEST TIMING")
    print("-" * 112)
    ret = m[m["bucket"].isin(["RETEST_NO_RECLAIM", "RETEST_RECLAIM"])].copy()
    if not ret.empty:
        print(
            ret.groupby("bucket")["minutes_to_retest"]
            .agg(["count", "mean", "median"])
            .to_string()
        )
        print()
        print(
            "Reclaim timing (minutes from trigger):"
        )
        print(
            ret.loc[ret["reclaim_seen"], "minutes_to_reclaim"]
            .agg(["count", "mean", "median"])
            .to_string()
        )

    print()
    print("INTERPRETATION")
    print("-" * 112)
    print("Do NOT promote RETEST_RECLAIM to an engine rule from this sample alone.")
    print("The key test is whether the bucket separation survives across dates,")
    print("not merely whether one bucket contains the current winners.")

    print(f"Saved: {OUT.name}")


if __name__ == "__main__":
    main()
