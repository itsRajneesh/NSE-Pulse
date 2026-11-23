"""
V13.1 Pre-Entry Follow-Through Quality Audit
--------------------------------------------
RESEARCH ONLY. Does NOT modify v13_engine.py.

Tests raw 5-minute microstructure around the V13.1 candidate set.

Candidate:
BULLISH + True Velocity > 0 + breakout distance 0.50-1.25 ATR
+ RelVol <= 1.50x
+ outcomes SL_FIRST / T1_FIRST / T2_FIRST
+ July 1 through September 12, 2026.

The audit compares TARGET (T1/T2) vs SL outcomes.

Features:
1. Breakout candle body/range
2. Breakout candle CLV
3. Breakout candle range relative to ATR/risk
4. Volume expansion where 5m volume is available
5. OR hold/rejection after trigger
6. Retest behaviour
7. Immediate continuation after trigger
8. First 5m / 10m follow-through

IMPORTANT:
- Yahoo 5m history may be unavailable for older July dates.
- This script is diagnostic only.
"""

from pathlib import Path
import time
import math
import pandas as pd
import numpy as np
import yfinance as yf

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "backtest_nifty500_v13_results.csv"
OUT = BASE / "v13_1_preentry_followthrough_audit.csv"

START_DATE = pd.Timestamp("2026-07-01")
END_DATE = pd.Timestamp("2026-09-13")


def num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else np.nan
    except Exception:
        return np.nan


def load_candidates():
    df = pd.read_csv(RESULTS)

    required = [
        "symbol", "date", "signal_time", "direction",
        "true_velocity", "breakout_distance_atr", "rel_vol",
        "entry_price", "stop_loss", "opening_range_high",
        "opening_range_low", "atr14", "realized_r", "outcome"
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing CSV columns: {missing}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["signal_time"] = pd.to_datetime(
        df["signal_time"], errors="coerce", utc=True
    ).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)

    for c in [
        "true_velocity", "breakout_distance_atr", "rel_vol",
        "entry_price", "stop_loss", "opening_range_high",
        "opening_range_low", "atr14", "realized_r"
    ]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    mask = (
        (df["date"] >= START_DATE)
        & (df["date"] < END_DATE)
        & (df["direction"].astype(str).str.upper() == "BULLISH")
        & (df["true_velocity"] > 0)
        & (df["breakout_distance_atr"] >= 0.50)
        & (df["breakout_distance_atr"] <= 1.25)
        & (df["rel_vol"] <= 1.50)
        & (df["outcome"].astype(str).isin(
            ["SL_FIRST", "T1_FIRST", "T2_FIRST"]
        ))
    )
    return df.loc[mask].sort_values(
        ["signal_time", "symbol"]
    ).reset_index(drop=True)


def download_day(symbol, day):
    ticker = str(symbol).strip().upper()
    if not ticker.endswith(".NS"):
        ticker += ".NS"

    start = pd.Timestamp(day).normalize()
    end = start + pd.Timedelta(days=1)

    print(f"Downloading {ticker}: {start.date()} -> {end.date()}")

    try:
        data = yf.download(
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

    if data is None or data.empty:
        print("  No 5m data returned.")
        return pd.DataFrame()

    if isinstance(data.columns, pd.MultiIndex):
        try:
            if ticker in data.columns.get_level_values(-1):
                data = data.xs(ticker, axis=1, level=-1)
            elif ticker in data.columns.get_level_values(0):
                data = data.xs(ticker, axis=1, level=0)
        except Exception:
            pass

    needed = ["Open", "High", "Low", "Close"]
    if any(c not in data.columns for c in needed):
        print("  OHLC columns missing.")
        return pd.DataFrame()

    keep = needed + (["Volume"] if "Volume" in data.columns else [])
    data = data[keep].copy()

    data.index = pd.to_datetime(data.index, errors="coerce")
    data = data[~data.index.isna()].copy()

    if data.index.tz is not None:
        data.index = data.index.tz_convert(
            "Asia/Kolkata"
        ).tz_localize(None)

    day = pd.Timestamp(day).normalize()
    return data[
        (data.index >= day + pd.Timedelta(hours=9, minutes=15))
        & (data.index <= day + pd.Timedelta(hours=15, minutes=30))
    ].copy()


def get_window(candles, start, end):
    return candles[
        (candles.index >= start)
        & (candles.index <= end)
    ].copy()


def candle_features(c):
    if c is None or len(c) == 0:
        return {}

    o = num(c["Open"])
    h = num(c["High"])
    l = num(c["Low"])
    cl = num(c["Close"])

    rng = h - l
    body = abs(cl - o)

    if not np.isfinite(rng) or rng <= 0:
        return {
            "body_pct_range": np.nan,
            "clv": np.nan,
            "upper_wick_pct": np.nan,
            "lower_wick_pct": np.nan,
            "range": np.nan,
            "body": np.nan,
        }

    return {
        "body_pct_range": body / rng * 100.0,
        "clv": ((cl - l) / rng) * 2.0 - 1.0,
        "upper_wick_pct": (h - max(o, cl)) / rng * 100.0,
        "lower_wick_pct": (min(o, cl) - l) / rng * 100.0,
        "range": rng,
        "body": body,
    }


def continuation_metrics(after, entry, risk, or_high):
    if after.empty:
        return {}

    close = pd.to_numeric(after["Close"], errors="coerce")
    high = pd.to_numeric(after["High"], errors="coerce")
    low = pd.to_numeric(after["Low"], errors="coerce")

    valid = close.notna()
    close = close[valid]
    high = high[valid]
    low = low[valid]

    if close.empty:
        return {}

    # Bullish continuation.
    first_close_r = float((close.iloc[0] - entry) / risk)
    last_close_r = float((close.iloc[-1] - entry) / risk)
    max_high_r = float((high.max() - entry) / risk)
    max_low_r = float((low.min() - entry) / risk)

    # Did price close back below the OR high?
    below_or = close < or_high
    # Longest consecutive closes below OR high.
    max_below = 0
    cur = 0
    for x in below_or.tolist():
        if bool(x):
            cur += 1
            max_below = max(max_below, cur)
        else:
            cur = 0

    # First 2/3 candles direction.
    dirs = []
    for _, r in after.head(3).iterrows():
        o, cl = num(r["Open"]), num(r["Close"])
        dirs.append(1 if cl > o else (-1 if cl < o else 0))

    return {
        "first_close_r": first_close_r,
        "last_close_r": last_close_r,
        "max_high_r": max_high_r,
        "max_low_r": max_low_r,
        "hold_or_first_close": bool(close.iloc[0] >= or_high),
        "hold_or_all_first3": bool((close.head(3) >= or_high).all()),
        "max_consecutive_below_or": max_below,
        "first_candle_bull": dirs[0] > 0 if dirs else False,
        "first2_bull_count": int(sum(x > 0 for x in dirs[:2])),
        "first3_bull_count": int(sum(x > 0 for x in dirs[:3])),
    }


def main():
    candidates = load_candidates()

    print()
    print("=" * 112)
    print("V13.1 PRE-ENTRY FOLLOW-THROUGH QUALITY AUDIT")
    print("=" * 112)
    print(f"Candidate trades : {len(candidates)}")
    print(f"Window           : {START_DATE.date()} -> {END_DATE.date()}")
    print()

    cache = {}
    rows = []

    for _, row in candidates.iterrows():
        symbol = str(row["symbol"]).strip()
        day = pd.Timestamp(row["date"]).normalize()
        signal_time = pd.Timestamp(row["signal_time"])

        key = (symbol, str(day.date()))
        if key not in cache:
            cache[key] = download_day(symbol, day)
            time.sleep(0.15)

        candles = cache[key]

        rec = {
            "symbol": symbol,
            "date": str(day.date()),
            "signal_time": str(signal_time),
            "outcome": str(row["outcome"]),
            "realized_r": num(row["realized_r"]),
            "matched": False,
        }

        if candles.empty:
            rows.append(rec)
            continue

        entry = num(row["entry_price"])
        stop = num(row["stop_loss"])
        risk = abs(entry - stop)
        or_high = num(row["opening_range_high"])
        atr = num(row["atr14"])

        if not np.isfinite(entry) or not np.isfinite(risk) or risk <= 0:
            rows.append(rec)
            continue

        # Signal candle: the 5m candle containing the signal timestamp.
        pos = candles.index.searchsorted(signal_time)
        if pos >= len(candles):
            rows.append(rec)
            continue

        trigger = candles.iloc[pos]
        trigger_time = candles.index[pos]

        # Pre-trigger context: last 3 candles before signal/trigger.
        pre = candles[
            (candles.index < trigger_time)
            & (candles.index >= trigger_time - pd.Timedelta(minutes=15))
        ].tail(3)

        # First 5/10/15 minutes after trigger.
        after5 = get_window(
            candles,
            trigger_time + pd.Timedelta(minutes=5),
            trigger_time + pd.Timedelta(minutes=10),
        )
        after10 = get_window(
            candles,
            trigger_time + pd.Timedelta(minutes=5),
            trigger_time + pd.Timedelta(minutes=15),
        )
        after15 = get_window(
            candles,
            trigger_time + pd.Timedelta(minutes=5),
            trigger_time + pd.Timedelta(minutes=20),
        )

        # OR hold/retest window starts from trigger.
        post30 = get_window(
            candles,
            trigger_time + pd.Timedelta(minutes=5),
            trigger_time + pd.Timedelta(minutes=35),
        )

        tf = candle_features(trigger)

        rec["matched"] = True
        rec["trigger_time"] = str(trigger_time)
        rec["trigger_open"] = num(trigger["Open"])
        rec["trigger_high"] = num(trigger["High"])
        rec["trigger_low"] = num(trigger["Low"])
        rec["trigger_close"] = num(trigger["Close"])
        rec.update({f"trigger_{k}": v for k, v in tf.items()})

        if np.isfinite(atr) and atr > 0:
            rec["trigger_range_atr"] = tf.get("range", np.nan) / atr
            rec["trigger_body_atr"] = tf.get("body", np.nan) / atr
        else:
            rec["trigger_range_atr"] = np.nan
            rec["trigger_body_atr"] = np.nan

        # Breakout quality: close relative to OR high and entry.
        rec["close_above_or_risk"] = (
            (num(trigger["Close"]) - or_high) / risk
            if np.isfinite(or_high) else np.nan
        )
        rec["high_above_or_risk"] = (
            (num(trigger["High"]) - or_high) / risk
            if np.isfinite(or_high) else np.nan
        )

        # Pre-trigger candle direction / compression.
        if not pre.empty:
            po = pd.to_numeric(pre["Open"], errors="coerce")
            pc = pd.to_numeric(pre["Close"], errors="coerce")
            rec["pre3_bull_count"] = int((pc > po).sum())
            rec["pre3_bear_count"] = int((pc < po).sum())
            rec["pre3_mean_body_pct"] = float(
                (
                    (pc - po).abs()
                    / (
                        pd.to_numeric(pre["High"], errors="coerce")
                        - pd.to_numeric(pre["Low"], errors="coerce")
                    ).replace(0, np.nan)
                    * 100
                ).mean()
            )
        else:
            rec["pre3_bull_count"] = np.nan
            rec["pre3_bear_count"] = np.nan
            rec["pre3_mean_body_pct"] = np.nan

        # Volume expansion around trigger.
        if "Volume" in candles.columns:
            vol = pd.to_numeric(candles["Volume"], errors="coerce")
            prior_vol = vol[
                (candles.index < trigger_time)
                & (candles.index >= trigger_time - pd.Timedelta(minutes=30))
            ].dropna()

            trigger_vol = num(trigger.get("Volume", np.nan))
            if not prior_vol.empty and np.isfinite(trigger_vol):
                rec["trigger_volume_vs_prior30"] = (
                    trigger_vol / float(prior_vol.median())
                    if float(prior_vol.median()) > 0 else np.nan
                )
            else:
                rec["trigger_volume_vs_prior30"] = np.nan
        else:
            rec["trigger_volume_vs_prior30"] = np.nan

        for name, after in [
            ("5m", after5),
            ("10m", after10),
            ("15m", after15),
            ("30m", post30),
        ]:
            cm = continuation_metrics(
                after, entry, risk, or_high
            ) if np.isfinite(or_high) else {}

            for k, v in cm.items():
                rec[f"{name}_{k}"] = v

        # Retest:
        # After breakout, did price come back to OR high and then reclaim it?
        if np.isfinite(or_high) and not post30.empty:
            lows = pd.to_numeric(post30["Low"], errors="coerce")
            closes = pd.to_numeric(post30["Close"], errors="coerce")
            retest = lows <= or_high

            rec["retest_seen_30m"] = bool(retest.any())

            if retest.any():
                first_retest_pos = np.where(retest.to_numpy())[0][0]
                after_retest = closes.iloc[first_retest_pos:]
                rec["retest_reclaim"] = bool(
                    (after_retest > or_high).any()
                )
                rec["retest_broken"] = bool(
                    (after_retest < or_high).any()
                )
            else:
                rec["retest_reclaim"] = False
                rec["retest_broken"] = False
        else:
            rec["retest_seen_30m"] = False
            rec["retest_reclaim"] = False
            rec["retest_broken"] = False

        rows.append(rec)

    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)

    matched = df[df["matched"] == True].copy()

    print()
    print("DATA COVERAGE")
    print("-" * 112)
    print(f"Candidate trades : {len(df)}")
    print(f"Raw 5m matched   : {len(matched)}")
    print(f"Raw 5m missing   : {len(df) - len(matched)}")

    if matched.empty:
        print(f"Saved: {OUT.name}")
        return

    target = matched["outcome"].isin(["T1_FIRST", "T2_FIRST"])
    sl = matched["outcome"].eq("SL_FIRST")

    print()
    print("OUTCOME COUNTS")
    print("-" * 112)
    print(matched["outcome"].value_counts().to_string())

    def group_stats(col):
        x = matched[[col, "outcome"]].copy()
        x[col] = pd.to_numeric(x[col], errors="coerce")
        x = x.dropna(subset=[col])
        if x.empty:
            return None

        t = x.loc[x["outcome"].isin(["T1_FIRST", "T2_FIRST"]), col]
        s = x.loc[x["outcome"].eq("SL_FIRST"), col]

        return {
            "target_n": len(t),
            "target_mean": float(t.mean()) if len(t) else np.nan,
            "target_median": float(t.median()) if len(t) else np.nan,
            "sl_n": len(s),
            "sl_mean": float(s.mean()) if len(s) else np.nan,
            "sl_median": float(s.median()) if len(s) else np.nan,
        }

    features = [
        "trigger_body_pct_range",
        "trigger_clv",
        "trigger_upper_wick_pct",
        "trigger_lower_wick_pct",
        "trigger_range_atr",
        "trigger_body_atr",
        "close_above_or_risk",
        "high_above_or_risk",
        "pre3_bull_count",
        "pre3_bear_count",
        "pre3_mean_body_pct",
        "trigger_volume_vs_prior30",
        "5m_first_close_r",
        "5m_max_low_r",
        "5m_max_high_r",
        "5m_hold_or_first_close",
        "5m_first_candle_bull",
        "10m_first_close_r",
        "10m_max_low_r",
        "10m_max_high_r",
        "10m_hold_or_all_first3",
        "10m_max_consecutive_below_or",
        "10m_first2_bull_count",
        "15m_first_close_r",
        "15m_max_low_r",
        "15m_max_high_r",
        "15m_max_consecutive_below_or",
        "30m_max_low_r",
        "30m_max_high_r",
        "retest_seen_30m",
        "retest_reclaim",
        "retest_broken",
    ]

    print()
    print("TARGET vs SL FEATURE COMPARISON")
    print("-" * 112)
    print(
        f"{'FEATURE':34s} {'TARGET n':>9s} {'TARGET mean':>13s} "
        f"{'SL n':>8s} {'SL mean':>13s}"
    )
    print("-" * 112)

    rows_summary = []

    for f in features:
        if f not in matched.columns:
            continue

        st = group_stats(f)
        if st is None:
            continue

        print(
            f"{f:34s} "
            f"{st['target_n']:9d} "
            f"{st['target_mean']:13.4f} "
            f"{st['sl_n']:8d} "
            f"{st['sl_mean']:13.4f}"
        )

        rows_summary.append({
            "feature": f,
            **st,
        })

    print()
    print("FOLLOW-THROUGH THRESHOLD DIAGNOSTICS")
    print("-" * 112)

    # These are descriptive only, NOT proposed hard rules.
    tests = [
        ("CLV >= 0.50", "trigger_clv", lambda s: s >= 0.50),
        ("CLV >= 0.70", "trigger_clv", lambda s: s >= 0.70),
        ("Body >= 50% range", "trigger_body_pct_range", lambda s: s >= 50),
        ("Body >= 70% range", "trigger_body_pct_range", lambda s: s >= 70),
        ("Close above OR by >=0.10R", "close_above_or_risk", lambda s: s >= 0.10),
        ("Close above OR by >=0.25R", "close_above_or_risk", lambda s: s >= 0.25),
        ("5m close > 0R", "5m_first_close_r", lambda s: s > 0),
        ("5m close > +0.10R", "5m_first_close_r", lambda s: s > 0.10),
        ("10m close > 0R", "10m_first_close_r", lambda s: s > 0),
        ("10m close > +0.10R", "10m_first_close_r", lambda s: s > 0.10),
        ("10m holds OR first3", "10m_hold_or_all_first3", lambda s: s == True),
        ("Retest + reclaim", "retest_reclaim", lambda s: s == True),
        ("Retest broken", "retest_broken", lambda s: s == True),
    ]

    for label, col, fn in tests:
        if col not in matched.columns:
            continue

        vals = matched[col]
        try:
            flag = fn(vals)
        except Exception:
            continue

        flag = flag.fillna(False).astype(bool)
        n = int(flag.sum())
        target_n = int((flag & target).sum())
        sl_n = int((flag & sl).sum())

        target_rate = target_n / int(target.sum()) * 100 if int(target.sum()) else np.nan
        sl_rate = sl_n / int(sl.sum()) * 100 if int(sl.sum()) else np.nan

        print(
            f"{label:32s} | flagged={n:2d} | "
            f"target retained={target_rate:5.1f}% | "
            f"SL represented={sl_rate:5.1f}%"
        )

    print()
    print("IMPORTANT")
    print("-" * 112)
    print("These diagnostics do not justify a hard filter by themselves.")
    print("Look for directionally stable separation, not a single lucky threshold.")
    print(f"Saved: {OUT.name}")


if __name__ == "__main__":
    main()
