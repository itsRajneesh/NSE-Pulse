
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

CSV = Path("backtest_nifty500_v13_results.csv")
OUT = Path("v13_1_aug_sep_candidate_guard_matrix.csv")

START = "2026-08-01"
END = "2026-09-13"

# V13.1 predeclared setup universe from the existing backtest.
df = pd.read_csv(CSV)
df["date"] = pd.to_datetime(df["date"], errors="coerce")
df["signal_time"] = pd.to_datetime(df["signal_time"], errors="coerce")
df["trigger_time"] = pd.to_datetime(df["trigger_time"], errors="coerce")
df["outcome_time"] = pd.to_datetime(df["outcome_time"], errors="coerce")

df = df[
    (df["direction"].astype(str).str.upper() == "BULLISH")
    & (pd.to_numeric(df["true_velocity"], errors="coerce") > 0)
    & (pd.to_numeric(df["breakout_distance_atr"], errors="coerce").between(0.50, 1.25))
    & (pd.to_numeric(df["rel_vol"], errors="coerce") <= 1.50)
    & (df["outcome"].isin(["SL_FIRST", "T1_FIRST", "T2_FIRST"]))
    & (df["date"] >= START)
    & (df["date"] < END)
].copy()

# Keep one row per actionable trade.
df = df.sort_values(["symbol", "trigger_time"]).reset_index(drop=True)

def session_candles(symbol, day):
    ticker = symbol if str(symbol).endswith(".NS") else f"{symbol}.NS"
    print(f"Downloading {ticker}: {day.date()} -> {(day + pd.Timedelta(days=1)).date()}")
    try:
        x = yf.download(
            ticker,
            start=day.strftime("%Y-%m-%d"),
            end=(day + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            interval="5m",
            auto_adjust=False,
            prepost=False,
            progress=False,
            threads=False,
        )
    except Exception as e:
        print("  ERROR:", e)
        return None
    if x is None or x.empty:
        print("  NO DATA")
        return None

    if isinstance(x.columns, pd.MultiIndex):
        x.columns = [c[0] for c in x.columns]
    x.index = pd.to_datetime(x.index)
    if x.index.tz is None:
        x.index = x.index.tz_localize("Asia/Kolkata")
    else:
        x.index = x.index.tz_convert("Asia/Kolkata")
    return x

rows = []
cache = {}

for _, t in df.iterrows():
    day = pd.Timestamp(t["date"]).normalize()
    key = (str(t["symbol"]), str(day.date()))
    if key not in cache:
        cache[key] = session_candles(str(t["symbol"]), day)
        time.sleep(0.25)

    raw = cache[key]
    if raw is None or raw.empty:
        continue

    trig = pd.Timestamp(t["trigger_time"])
    if trig.tzinfo is None:
        trig = trig.tz_localize("Asia/Kolkata")
    else:
        trig = trig.tz_convert("Asia/Kolkata")

    session = raw.between_time("09:15", "15:30")
    after = session[session.index >= trig]
    if len(after) < 7:
        continue

    entry = float(t["entry_price"])
    sl = float(t["stop_loss"])
    risk = abs(entry - sl)
    if risk <= 0:
        continue

    # Candle 0 = trigger candle. Future candles 1..6 represent +5..+30m.
    future = after.iloc[1:7].copy()

    closes = pd.to_numeric(future["Close"], errors="coerce")
    lows = pd.to_numeric(future["Low"], errors="coerce")

    close_r = (closes - entry) / risk
    mae_r = (lows - entry) / risk

    # Cumulative MAE at each checkpoint.
    mae5 = float(mae_r.iloc[:1].min())
    mae10 = float(mae_r.iloc[:2].min())
    mae15 = float(mae_r.iloc[:3].min())
    mae20 = float(mae_r.iloc[:4].min())
    mae30 = float(mae_r.iloc[:6].min())

    # "Recovery" = close excursion versus cumulative worst MAE.
    # We use +10/+15m as guard decision windows.
    close5 = float(close_r.iloc[0])
    close10 = float(close_r.iloc[1])
    close15 = float(close_r.iloc[2])

    rec10 = close10 - mae10
    rec15 = close15 - mae15

    # Consecutive adverse closes after trigger.
    adverse = (closes <= entry).astype(int)
    max_consecutive = 0
    run = 0
    for v in adverse:
        if v:
            run += 1
            max_consecutive = max(max_consecutive, run)
        else:
            run = 0

    # Persistence / deterioration:
    # At +10m/+15m, compare cumulative MAE to the prior checkpoint.
    deterioration10 = mae10 < mae5 - 0.05
    deterioration15 = mae15 < mae10 - 0.05

    # Candidate A-E. These are intentionally descriptive tests, not engine rules.
    # A: MAE + no recovery
    A10 = (mae10 <= -0.20) and (close10 <= 0.0)
    A15 = (mae15 <= -0.20) and (close15 <= 0.0)

    # B: MAE + weak close
    B10 = (mae10 <= -0.20) and (close10 <= -0.10)
    B15 = (mae15 <= -0.20) and (close15 <= -0.10)

    # C: MAE + deterioration
    C10 = (mae10 <= -0.20) and deterioration10
    C15 = (mae15 <= -0.20) and deterioration15

    # D: MAE + no recovery + deterioration
    D10 = (mae10 <= -0.20) and (close10 <= 0.0) and deterioration10
    D15 = (mae15 <= -0.20) and (close15 <= 0.0) and deterioration15

    # E: MAE + no recovery + 2 adverse closes
    E10 = (mae10 <= -0.20) and (close10 <= 0.0) and (max_consecutive >= 2)
    E15 = (mae15 <= -0.20) and (close15 <= 0.0) and (max_consecutive >= 2)

    rows.append({
        **t.to_dict(),
        "mae5_r": mae5,
        "mae10_r": mae10,
        "mae15_r": mae15,
        "mae20_r": mae20,
        "mae30_r": mae30,
        "close5_r": close5,
        "close10_r": close10,
        "close15_r": close15,
        "recovery10_r": rec10,
        "recovery15_r": rec15,
        "max_consecutive_adverse_closes": max_consecutive,
        "deterioration10": deterioration10,
        "deterioration15": deterioration15,
        "A_10m": A10, "A_15m": A15,
        "B_10m": B10, "B_15m": B15,
        "C_10m": C10, "C_15m": C15,
        "D_10m": D10, "D_15m": D15,
        "E_10m": E10, "E_15m": E15,
    })

out = pd.DataFrame(rows)
out.to_csv(OUT, index=False)

print("\nAUGUST/SEPTEMBER GUARD MATRIX")
print("=" * 110)
print(f"V13.1 candidate trades in window : {len(df)}")
print(f"Raw 5m matched                    : {len(out)}")

for candidate in ["A","B","C","D","E"]:
    for mins in [10, 15]:
        col = f"{candidate}_{mins}m"
        if col not in out:
            continue
        flag = out[col].fillna(False).astype(bool)
        caught = out[flag]
        sl = out[out["outcome"].eq("SL_FIRST")]
        target = out[out["outcome"].isin(["T1_FIRST","T2_FIRST"])]

        sl_caught = (sl[col].fillna(False).astype(bool).mean() * 100) if len(sl) else np.nan
        target_killed = (target[col].fillna(False).astype(bool).mean() * 100) if len(target) else np.nan

        print(
            f"{candidate} @ +{mins:02d}m | flagged={len(caught):3d} | "
            f"SL caught={sl_caught:5.1f}% | target killed={target_killed:5.1f}%"
        )

print("\nOUTCOME COUNTS IN MATCHED SAMPLE")
print(out["outcome"].value_counts().to_string())
print(f"\nSaved: {OUT}")
