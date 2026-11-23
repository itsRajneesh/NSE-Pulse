"""
V13.1 Recovery-Aware Trajectory Experiment
------------------------------------------
RESEARCH ONLY. Does NOT modify v13_engine.py.

Goal:
Test whether a +10m adverse move should become an exit only when
the trade also shows persistent failure / lack of recovery by +15m.

Candidate rule:
BULLISH + True Velocity > 0 + breakout distance 0.50-1.25 ATR
+ RelVol <= 1.50x

Important:
- No hard +10m exit.
- +10m is ONLY a warning checkpoint.
- Exit is simulated only at +15m when the trajectory remains weak.
- Yahoo 5m data may be unavailable for older dates (>~60 days).
"""

from pathlib import Path
import time
import math
import pandas as pd
import numpy as np
import yfinance as yf

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "backtest_nifty500_v13_results.csv"
OUT = BASE / "v13_1_recovery_trajectory_experiment.csv"

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
        "entry_price", "stop_loss", "realized_r", "outcome"
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
        "entry_price", "stop_loss", "realized_r"
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
        print("  Required OHLC columns missing.")
        return pd.DataFrame()

    data = data[needed].copy()
    data.index = pd.to_datetime(data.index, errors="coerce")
    data = data[~data.index.isna()].copy()

    # Normalize all timestamps to India local time, then make them naive.
    if data.index.tz is not None:
        data.index = data.index.tz_convert("Asia/Kolkata").tz_localize(None)

    day = pd.Timestamp(day).normalize()
    data = data[
        (data.index >= day + pd.Timedelta(hours=9, minutes=15))
        & (data.index <= day + pd.Timedelta(hours=15, minutes=30))
    ].copy()

    return data


def checkpoint(candles, signal_time, minutes, entry, risk):
    end = signal_time + pd.Timedelta(minutes=minutes)

    x = candles[
        (candles.index >= signal_time)
        & (candles.index <= end)
    ].copy()

    if x.empty or not np.isfinite(entry) or not np.isfinite(risk) or risk <= 0:
        return None

    low = pd.to_numeric(x["Low"], errors="coerce")
    close = pd.to_numeric(x["Close"], errors="coerce")

    mae_r = float((low.min() - entry) / risk)
    close_r = float((close.iloc[-1] - entry) / risk)

    return {
        "time": x.index[-1],
        "mae_r": mae_r,
        "close_r": close_r,
        "close": float(close.iloc[-1]),
    }


def drawdown(values):
    arr = np.asarray(values, dtype=float)
    equity = np.cumsum(arr)
    peaks = np.maximum.accumulate(np.r_[0.0, equity])[1:]
    return float(np.max(peaks - equity)) if len(arr) else 0.0


def apply_guard(df, flag_col, exit_r_col):
    out = df["baseline_r"].astype(float).copy()
    flags = df[flag_col].fillna(False).astype(bool)
    out.loc[flags] = df.loc[flags, exit_r_col]
    return out


def summary(vals):
    vals = pd.Series(vals, dtype=float).dropna()
    return {
        "n": len(vals),
        "wins": int((vals > 0).sum()),
        "avg": float(vals.mean()) if len(vals) else np.nan,
        "total": float(vals.sum()) if len(vals) else np.nan,
        "dd": drawdown(vals.tolist()) if len(vals) else np.nan,
    }


def main():
    candidates = load_candidates()

    print()
    print("=" * 112)
    print("V13.1 RECOVERY-AWARE TRAJECTORY EXPERIMENT")
    print("=" * 112)
    print(f"Candidate trades : {len(candidates)}")
    print(f"Window           : {START_DATE.date()} -> {END_DATE.date()}")
    print()
    print("No +10m hard exit. +10m is warning only.")
    print("Exit can occur only at +15m after persistent failure.")
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
            "baseline_r": num(row["realized_r"]),
            "matched": False,
        }

        if candles.empty:
            rows.append(rec)
            continue

        entry = num(row["entry_price"])
        stop = num(row["stop_loss"])
        risk = abs(entry - stop)

        m10 = checkpoint(candles, signal_time, 10, entry, risk)
        m15 = checkpoint(candles, signal_time, 15, entry, risk)

        if m10 is None or m15 is None:
            rows.append(rec)
            continue

        rec["matched"] = True
        rec["entry"] = entry
        rec["risk"] = risk

        rec["mae10_r"] = m10["mae_r"]
        rec["close10_r"] = m10["close_r"]
        rec["mae15_r"] = m15["mae_r"]
        rec["close15_r"] = m15["close_r"]

        # Recovery trajectory:
        # positive means the +15m close improved versus +10m close.
        rec["recovery_10_to_15_r"] = m15["close_r"] - m10["close_r"]

        # A negative value means the adverse excursion got deeper.
        rec["mae_change_10_to_15_r"] = m15["mae_r"] - m10["mae_r"]

        # Base adverse warning at +10m.
        rec["adverse10"] = m10["mae_r"] <= -0.20

        # Persistent failure at +15m:
        # still meaningfully adverse AND still below entry.
        rec["persistent"] = (
            m10["mae_r"] <= -0.20
            and m10["close_r"] <= 0.0
            and m15["mae_r"] <= -0.20
            and m15["close_r"] <= 0.0
        )

        # Persistent + no recovery from +10m to +15m.
        rec["persistent_no_recovery"] = (
            rec["persistent"]
            and m15["close_r"] <= m10["close_r"]
        )

        # Persistent + weak close at +15m.
        rec["persistent_weak_close"] = (
            rec["persistent"]
            and m15["close_r"] <= -0.10
        )

        # Persistent + actual deterioration in adverse excursion.
        rec["persistent_deterioration"] = (
            rec["persistent"]
            and m15["mae_r"] < (m10["mae_r"] - 0.05)
        )

        # Recovery-aware candidates:
        # R1 = persistence alone
        # R2 = persistence + no recovery
        # R3 = persistence + weak close
        # R4 = persistence + deterioration
        rec["R1_persistent"] = rec["persistent"]
        rec["R2_no_recovery"] = rec["persistent_no_recovery"]
        rec["R3_weak_close"] = rec["persistent_weak_close"]
        rec["R4_deterioration"] = rec["persistent_deterioration"]

        # All exits are simulated at the +15m close.
        for name in ["R1_persistent", "R2_no_recovery",
                     "R3_weak_close", "R4_deterioration"]:
            rec[name + "_exit_r"] = (
                m15["close_r"] if rec[name] else rec["baseline_r"]
            )

        rows.append(rec)

    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)

    matched = df[df["matched"] == True].copy()

    print()
    print("DATA COVERAGE")
    print("-" * 112)
    print(f"Candidate trades : {len(df)}")
    print(f"5m matched       : {len(matched)}")
    print(f"5m missing       : {len(df) - len(matched)}")

    if matched.empty:
        print("No matched trades.")
        print(f"Saved: {OUT.name}")
        return

    base = summary(matched["baseline_r"])
    print()
    print("BASELINE")
    print("-" * 112)
    print(
        f"N={base['n']} | Wins={base['wins']} | "
        f"AvgR={base['avg']:+.4f} | TotalR={base['total']:+.2f} | "
        f"MaxDD={base['dd']:.2f}R"
    )

    sl = matched["outcome"].eq("SL_FIRST")
    target = matched["outcome"].isin(["T1_FIRST", "T2_FIRST"])
    sl_n = int(sl.sum())
    target_n = int(target.sum())

    print()
    print("RECOVERY-AWARE CANDIDATES")
    print("-" * 112)
    print(
        "Every guard below uses +10m ONLY as warning; "
        "simulated exit occurs at +15m close."
    )

    names = [
        ("R1", "R1_persistent"),
        ("R2", "R2_no_recovery"),
        ("R3", "R3_weak_close"),
        ("R4", "R4_deterioration"),
    ]

    result_rows = []

    for label, col in names:
        flags = matched[col].fillna(False).astype(bool)
        flagged = int(flags.sum())

        sl_caught = (
            int((flags & sl).sum()) / sl_n * 100
            if sl_n else np.nan
        )
        target_killed = (
            int((flags & target).sum()) / target_n * 100
            if target_n else np.nan
        )

        guarded = matched[col + "_exit_r"].astype(float)
        s = summary(guarded)

        delta = s["total"] - base["total"]

        result_rows.append({
            "guard": label,
            "flagged": flagged,
            "sl_caught_pct": sl_caught,
            "target_killed_pct": target_killed,
            "total_r": s["total"],
            "delta_r": delta,
            "avg_r": s["avg"],
            "max_dd": s["dd"],
        })

        print(
            f"{label} | flagged={flagged:2d} | "
            f"SL caught={sl_caught:5.1f}% | "
            f"target killed={target_killed:5.1f}% | "
            f"TotalR={s['total']:+6.2f} | "
            f"ΔR={delta:+6.2f} | "
            f"MaxDD={s['dd']:.2f}R"
        )

    print()
    print("TRAJECTORY DIAGNOSTICS")
    print("-" * 112)
    print(
        "Columns: +10m MAE, +10m close, +15m MAE, +15m close, "
        "and recovery from +10m to +15m."
    )

    cols = [
        "symbol", "date", "outcome",
        "mae10_r", "close10_r",
        "mae15_r", "close15_r",
        "recovery_10_to_15_r",
        "mae_change_10_to_15_r",
        "R1_persistent", "R2_no_recovery",
        "R3_weak_close", "R4_deterioration",
    ]
    print(matched[cols].to_string(index=False))

    print()
    print("OUTCOME COUNTS")
    print("-" * 112)
    print(matched["outcome"].value_counts().to_string())

    print()
    print("INTERPRETATION GUIDE")
    print("-" * 112)
    print("R1 = adverse at +10m and still adverse at +15m.")
    print("R2 = R1 + +15m close failed to recover versus +10m.")
    print("R3 = R1 + +15m close <= -0.10R.")
    print("R4 = R1 + adverse excursion deteriorated by >0.05R.")
    print()
    print("No rule should be added to v13_engine.py from this experiment alone.")
    print(f"Saved: {OUT.name}")


if __name__ == "__main__":
    main()
