"""
V13.1 Combined July-September Guard Impact Test
-----------------------------------------------
Research-only script. DOES NOT modify v13_engine.py.

Purpose:
1) Select V13.1 candidate trades:
   BULLISH + True Velocity > 0 + breakout distance 0.50-1.25 ATR
   + relative volume <= 1.50
2) Inspect 5-minute candles around each trade.
3) Compare:
   - Baseline V13.1 realized R
   - A/B/E guard at +10m
   - A/B/E guard at +15m
   - A/B/E warning at +10m + confirmation at +15m
4) If a guard confirms, simulated exit is the close of the confirmation candle.
5) If raw 5m data is unavailable, the trade is reported as unavailable.
6) Existing v13_1_raw_candle_microstructure_audit.csv is reused when possible.

Guard definitions:
A = MAE <= -0.20R AND close has not recovered to entry
B = MAE <= -0.20R AND close <= -0.10R
E = MAE <= -0.20R AND no recovery AND at least 2 consecutive adverse closes

IMPORTANT:
- This is a research simulation, not a live-trading rule.
- No engine files are changed.
"""

from pathlib import Path
import time
import math
import pandas as pd
import numpy as np

try:
    import yfinance as yf
except ImportError:
    raise SystemExit(
        "yfinance missing. Install with: pip install yfinance"
    )

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "backtest_nifty500_v13_results.csv"
EXISTING_AUDIT = BASE / "v13_1_raw_candle_microstructure_audit.csv"
OUT = BASE / "v13_1_combined_guard_impact.csv"

START_DATE = pd.Timestamp("2026-07-01")
END_DATE = pd.Timestamp("2026-09-13")

WINDOW_START = "09:15"
WINDOW_END = "15:30"

GUARDS = ["A", "B", "E"]
CHECK_MINUTES = [10, 15]


def clean_num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else np.nan
    except Exception:
        return np.nan


def load_candidates():
    if not RESULTS.exists():
        raise FileNotFoundError(
            f"Missing {RESULTS.name}. Put this script in the backend folder "
            "containing the V13.1 backtest CSV."
        )

    df = pd.read_csv(RESULTS)

    for c in [
        "date", "signal_time", "direction", "true_velocity",
        "breakout_distance_atr", "rel_vol", "entry_price",
        "stop_loss", "realized_r", "outcome"
    ]:
        if c not in df.columns:
            raise ValueError(f"Required CSV column missing: {c}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["signal_time"] = pd.to_datetime(df["signal_time"], errors="coerce", utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)

    df["true_velocity"] = pd.to_numeric(df["true_velocity"], errors="coerce")
    df["breakout_distance_atr"] = pd.to_numeric(
        df["breakout_distance_atr"], errors="coerce"
    )
    df["rel_vol"] = pd.to_numeric(df["rel_vol"], errors="coerce")
    df["entry_price"] = pd.to_numeric(df["entry_price"], errors="coerce")
    df["stop_loss"] = pd.to_numeric(df["stop_loss"], errors="coerce")
    df["realized_r"] = pd.to_numeric(df["realized_r"], errors="coerce")

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

    out = df.loc[mask].copy()
    out = out.sort_values(["signal_time", "symbol"]).reset_index(drop=True)
    return out


def session_slice(data, session_date):
    if data is None or len(data) == 0:
        return pd.DataFrame()

    x = data.copy()
    if isinstance(x.index, pd.DatetimeIndex):
        idx = x.index
    else:
        return pd.DataFrame()

    if idx.tz is not None:
        idx = idx.tz_localize(None)
        x.index = idx

    day = pd.Timestamp(session_date).normalize()
    return x[(x.index >= day + pd.Timedelta(hours=9, minutes=15))
             & (x.index <= day + pd.Timedelta(hours=15, minutes=30))].copy()


def download_day(symbol, day):
    ticker = str(symbol).strip().upper()
    if not ticker.endswith(".NS"):
        ticker += ".NS"

    start = pd.Timestamp(day).normalize()
    end = start + pd.Timedelta(days=1)

    print(
        f"Downloading {ticker}: "
        f"{start.date()} -> {end.date()}"
    )

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
        # yfinance may return (field, ticker)
        if ticker in data.columns.get_level_values(-1):
            try:
                data = data.xs(ticker, axis=1, level=-1)
            except Exception:
                pass
        elif ticker in data.columns.get_level_values(0):
            try:
                data = data.xs(ticker, axis=1, level=0)
            except Exception:
                pass

    needed = ["Open", "High", "Low", "Close"]
    missing = [c for c in needed if c not in data.columns]
    if missing:
        print(f"  Missing columns: {missing}")
        return pd.DataFrame()

    data = data[needed].copy()
    data.index = pd.to_datetime(data.index, errors="coerce")
    data = data[~data.index.isna()].copy()

    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)

    return session_slice(data, day)


def get_candles(symbol, day, cache):
    key = (str(symbol).upper(), str(pd.Timestamp(day).date()))

    if key in cache:
        return cache[key]

    # Reuse the earlier audit CSV if it contains a detailed candle dump.
    # The normal audit output only contains summary metrics, so usually
    # a fresh Yahoo download is required.
    data = download_day(symbol, day)
    cache[key] = data
    time.sleep(0.15)
    return data


def candle_at_or_after(candles, target):
    if candles.empty:
        return None
    pos = candles.index.searchsorted(target)
    if pos >= len(candles):
        return None
    return candles.iloc[pos]


def metrics_until(candles, signal_time, minutes, entry, risk):
    target_time = signal_time + pd.Timedelta(minutes=minutes)
    x = candles[
        (candles.index >= signal_time)
        & (candles.index <= target_time)
    ].copy()

    if x.empty or not np.isfinite(entry) or not np.isfinite(risk) or risk <= 0:
        return None

    lows = pd.to_numeric(x["Low"], errors="coerce")
    closes = pd.to_numeric(x["Close"], errors="coerce")

    mae = float((lows.min() - entry) / risk)
    close = float(closes.iloc[-1])
    close_r = (close - entry) / risk

    # Bullish candidate: close below entry is adverse.
    no_recovery = close <= entry

    # Consecutive adverse closes at the end of the observed path.
    adverse = closes <= entry
    max_consecutive = 0
    cur = 0
    for flag in adverse.tolist():
        if bool(flag):
            cur += 1
            max_consecutive = max(max_consecutive, cur)
        else:
            cur = 0

    prev_mae = None
    if minutes >= 15:
        prev = metrics_until(
            candles, signal_time, minutes - 5, entry, risk
        )
        if prev:
            prev_mae = prev["mae_r"]

    deterioration = (
        prev_mae is not None
        and mae < (prev_mae - 0.05)
    )

    guard_a = mae <= -0.20 and no_recovery
    guard_b = mae <= -0.20 and close_r <= -0.10
    guard_e = (
        mae <= -0.20
        and no_recovery
        and max_consecutive >= 2
    )

    return {
        "minutes": minutes,
        "mae_r": mae,
        "close_r": close_r,
        "no_recovery": no_recovery,
        "max_consecutive_adverse": max_consecutive,
        "deterioration": deterioration,
        "A": bool(guard_a),
        "B": bool(guard_b),
        "E": bool(guard_e),
        "exit_close": close,
        "exit_time": x.index[-1],
    }


def simulate_confirmed_guard(row, m10, m15, guard):
    """
    Warning at +10m + confirmation at +15m.
    If both pass, simulated exit = +15m close.
    Otherwise baseline outcome is retained.
    """
    if m10 is None or m15 is None:
        return {
            "triggered": False,
            "exit_r": np.nan,
            "exit_time": None,
        }

    triggered = bool(m10[guard] and m15[guard])

    if not triggered:
        return {
            "triggered": False,
            "exit_r": float(row["realized_r"]),
            "exit_time": None,
        }

    return {
        "triggered": True,
        "exit_r": float(m15["close_r"]),
        "exit_time": m15["exit_time"],
    }


def dd_from_returns(values):
    if not values:
        return np.nan
    arr = np.asarray(values, dtype=float)
    equity = np.cumsum(arr)
    peak = np.maximum.accumulate(np.r_[0.0, equity])
    dd = peak[1:] - equity
    return float(np.max(dd)) if len(dd) else 0.0


def summarize(values, label):
    vals = pd.Series(values, dtype="float64").dropna()
    if vals.empty:
        return {
            "label": label,
            "n": 0,
            "wins": 0,
            "avg_r": np.nan,
            "total_r": np.nan,
            "max_dd": np.nan,
        }

    return {
        "label": label,
        "n": int(len(vals)),
        "wins": int((vals > 0).sum()),
        "avg_r": float(vals.mean()),
        "total_r": float(vals.sum()),
        "max_dd": dd_from_returns(vals.tolist()),
    }


def main():
    candidates = load_candidates()

    print()
    print("=" * 110)
    print("V13.1 COMBINED JULY-SEPTEMBER GUARD IMPACT TEST")
    print("=" * 110)
    print(f"Candidate trades in window : {len(candidates)}")
    print(f"Window                     : {START_DATE.date()} -> {END_DATE.date()}")
    print()
    print("Rule:")
    print("BULLISH + TV > 0 + BD 0.50-1.25 ATR + RelVol <= 1.50x")
    print("Guards A/B/E tested at +10m, +15m, and +10m warning + +15m confirmation.")
    print()

    cache = {}
    rows = []

    for i, row in candidates.iterrows():
        symbol = str(row["symbol"]).strip()
        day = pd.Timestamp(row["date"]).normalize()
        signal_time = pd.Timestamp(row["signal_time"])

        candles = get_candles(symbol, day, cache)

        if candles.empty:
            rows.append({
                "symbol": symbol,
                "date": str(day.date()),
                "signal_time": str(signal_time),
                "outcome": row["outcome"],
                "baseline_r": row["realized_r"],
                "matched": False,
            })
            continue

        entry = clean_num(row["entry_price"])
        stop = clean_num(row["stop_loss"])
        risk = abs(entry - stop)

        if not np.isfinite(entry) or not np.isfinite(risk) or risk <= 0:
            rows.append({
                "symbol": symbol,
                "date": str(day.date()),
                "signal_time": str(signal_time),
                "outcome": row["outcome"],
                "baseline_r": row["realized_r"],
                "matched": False,
            })
            continue

        m10 = metrics_until(candles, signal_time, 10, entry, risk)
        m15 = metrics_until(candles, signal_time, 15, entry, risk)

        # Need both checkpoints for the confirmation test.
        matched = m10 is not None and m15 is not None

        rec = {
            "symbol": symbol,
            "date": str(day.date()),
            "signal_time": str(signal_time),
            "outcome": row["outcome"],
            "baseline_r": float(row["realized_r"]),
            "entry": entry,
            "risk": risk,
            "matched": matched,
        }

        for minute, m in [(10, m10), (15, m15)]:
            if m is None:
                for g in GUARDS:
                    rec[f"{g}_{minute}"] = False
                rec[f"mae_r_{minute}"] = np.nan
                rec[f"close_r_{minute}"] = np.nan
            else:
                for g in GUARDS:
                    rec[f"{g}_{minute}"] = bool(m[g])
                rec[f"mae_r_{minute}"] = m["mae_r"]
                rec[f"close_r_{minute}"] = m["close_r"]

        for g in GUARDS:
            sim = simulate_confirmed_guard(row, m10, m15, g)
            rec[f"{g}_confirmed"] = sim["triggered"]
            rec[f"{g}_confirmed_r"] = sim["exit_r"]

        rows.append(rec)

    result = pd.DataFrame(rows)
    result.to_csv(OUT, index=False)

    matched = result[result["matched"] == True].copy()

    print()
    print("DATA COVERAGE")
    print("-" * 110)
    print(f"Candidate trades : {len(result)}")
    print(f"Raw 5m matched   : {len(matched)}")
    print(f"Raw 5m missing   : {len(result) - len(matched)}")

    if matched.empty:
        print()
        print("No matched 5m data. Nothing further to calculate.")
        print(f"Saved: {OUT.name}")
        return

    base_vals = matched["baseline_r"].tolist()

    base = summarize(base_vals, "BASELINE")
    print()
    print("BASELINE")
    print("-" * 110)
    print(
        f"N={base['n']} | Wins={base['wins']} | "
        f"AvgR={base['avg_r']:+.4f} | "
        f"TotalR={base['total_r']:+.2f} | "
        f"MaxDD={base['max_dd']:.2f}R"
    )

    print()
    print("EARLY HARD-GUARD SIMULATION")
    print("-" * 110)
    print(
        "Flagged = trades satisfying guard at checkpoint. "
        "SL caught = flagged SL / all SL. "
        "Target killed = flagged T1/T2 / all T1/T2."
    )

    outcome = matched["outcome"].astype(str)
    sl_mask = outcome.eq("SL_FIRST")
    target_mask = outcome.isin(["T1_FIRST", "T2_FIRST"])

    for minute in CHECK_MINUTES:
        for g in GUARDS:
            flags = matched[f"{g}_{minute}"].astype(bool)
            flagged = int(flags.sum())
            sl_total = int(sl_mask.sum())
            target_total = int(target_mask.sum())

            sl_caught = (
                int((flags & sl_mask).sum()) / sl_total * 100
                if sl_total else np.nan
            )
            target_killed = (
                int((flags & target_mask).sum()) / target_total * 100
                if target_total else np.nan
            )

            # Research simulation: if hard flag happens, exit at that checkpoint close.
            guarded = matched["baseline_r"].astype(float).copy()
            guarded.loc[flags] = matched.loc[flags, f"close_r_{minute}"]

            s = summarize(guarded.tolist(), f"{g} +{minute}m")

            print(
                f"{g} @ +{minute:02d}m | "
                f"flagged={flagged:3d} | "
                f"SL caught={sl_caught:5.1f}% | "
                f"target killed={target_killed:5.1f}% | "
                f"TotalR={s['total_r']:+7.2f} | "
                f"ΔR={s['total_r'] - base['total_r']:+7.2f} | "
                f"MaxDD={s['max_dd']:.2f}R"
            )

    print()
    print("WARNING + CONFIRMATION SIMULATION")
    print("-" * 110)
    print(
        "Warning at +10m AND same guard still true at +15m -> "
        "simulated exit at +15m close."
    )

    confirmation_rows = []

    for g in GUARDS:
        flags10 = matched[f"{g}_10"].astype(bool)
        flags15 = matched[f"{g}_15"].astype(bool)
        confirmed = flags10 & flags15

        flagged = int(confirmed.sum())
        sl_caught = (
            int((confirmed & sl_mask).sum()) / int(sl_mask.sum()) * 100
            if int(sl_mask.sum()) else np.nan
        )
        target_killed = (
            int((confirmed & target_mask).sum()) / int(target_mask.sum()) * 100
            if int(target_mask.sum()) else np.nan
        )

        guarded = matched["baseline_r"].astype(float).copy()
        guarded.loc[confirmed] = matched.loc[
            confirmed, f"{g}_confirmed_r"
        ]

        s = summarize(guarded.tolist(), f"{g} CONFIRM")
        delta = s["total_r"] - base["total_r"]

        confirmation_rows.append({
            "guard": g,
            "flagged": flagged,
            "sl_caught_pct": sl_caught,
            "target_killed_pct": target_killed,
            "guarded_total_r": s["total_r"],
            "delta_r": delta,
            "guarded_avg_r": s["avg_r"],
            "guarded_max_dd": s["max_dd"],
        })

        print(
            f"{g} +10/+15 | "
            f"confirmed={flagged:3d} | "
            f"SL caught={sl_caught:5.1f}% | "
            f"target killed={target_killed:5.1f}% | "
            f"TotalR={s['total_r']:+7.2f} | "
            f"ΔR={delta:+7.2f} | "
            f"MaxDD={s['max_dd']:.2f}R"
        )

    print()
    print("OUTCOME COUNTS IN MATCHED SAMPLE")
    print("-" * 110)
    print(matched["outcome"].value_counts().to_string())

    # Best research candidate: maximize R improvement while minimizing target kill.
    cdf = pd.DataFrame(confirmation_rows)
    if not cdf.empty:
        cdf["score"] = (
            cdf["delta_r"]
            - cdf["target_killed_pct"].fillna(0) * 0.10
        )
        best = cdf.sort_values("score", ascending=False).iloc[0]

        print()
        print("BEST CONFIRMATION CANDIDATE (RESEARCH ONLY)")
        print("-" * 110)
        print(f"Guard              : {best['guard']}")
        print(f"Timing             : +10m warning / +15m confirmation")
        print(f"Confirmed trades   : {int(best['flagged'])}")
        print(f"SL caught          : {best['sl_caught_pct']:.1f}%")
        print(f"Target killed      : {best['target_killed_pct']:.1f}%")
        print(f"Guarded Total R    : {best['guarded_total_r']:+.2f}R")
        print(f"R improvement      : {best['delta_r']:+.2f}R")
        print(f"Guarded Avg R      : {best['guarded_avg_r']:+.4f}R")
        print(f"Guarded Max DD     : {best['guarded_max_dd']:.2f}R")

    print()
    print(f"Saved: {OUT.name}")
    print()
    print("NOTE: Do NOT modify v13_engine.py from this result alone.")
    print("Small/partial Yahoo 5m coverage must be treated as a limitation.")


if __name__ == "__main__":
    main()

