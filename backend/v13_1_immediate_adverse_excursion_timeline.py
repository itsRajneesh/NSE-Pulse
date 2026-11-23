from __future__ import annotations

from pathlib import Path
import time
import numpy as np
import pandas as pd
import yfinance as yf

CSV = Path("backtest_nifty500_v13_results.csv")
OUT = Path("v13_1_raw_candle_microstructure_audit.csv")

def norm_cols(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).strip().title() for c in df.columns]
    return df

def candle_features(row):
    o, h, l, c = [float(row[x]) for x in ["Open","High","Low","Close"]]
    rng = h - l
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    return {
        "body_pct_range": body / rng * 100 if rng > 0 else np.nan,
        "upper_wick_pct_range": upper / rng * 100 if rng > 0 else np.nan,
        "lower_wick_pct_range": lower / rng * 100 if rng > 0 else np.nan,
        "close_location": (c - l) / rng if rng > 0 else np.nan,
        "candle_return_pct": (c - o) / o * 100 if o else np.nan,
        "range_pct_price": rng / o * 100 if o else np.nan,
    }

base = pd.read_csv(CSV)
for c in ["true_velocity","breakout_distance_atr","rel_vol","realized_r"]:
    base[c] = pd.to_numeric(base[c], errors="coerce")
base["signal_dt"] = pd.to_datetime(base["signal_time"], errors="coerce")
base["trigger_dt"] = pd.to_datetime(base["trigger_time"], errors="coerce")
base["outcome_dt"] = pd.to_datetime(base["outcome_time"], errors="coerce")

v = base[
    (base["direction"].str.upper() == "BULLISH") &
    (base["true_velocity"] > 0) &
    (base["breakout_distance_atr"] >= 0.50) &
    (base["breakout_distance_atr"] <= 1.25) &
    (base["rel_vol"] <= 1.50) &
    (base["outcome"].isin(["SL_FIRST","T1_FIRST","T2_FIRST"]))
].copy()

# Use trigger_time as the actual execution candle when available.
# If absent, use signal_time. We inspect the trigger candle and subsequent candles.
rows = []

for symbol, g in v.groupby("symbol"):
    ticker = symbol if str(symbol).endswith(".NS") else f"{symbol}.NS"
    start = (g["signal_dt"].min() - pd.Timedelta(minutes=30)).date()
    end = (g["outcome_dt"].max() + pd.Timedelta(days=1)).date()

    print(f"Downloading {ticker}: {start} -> {end}")
    try:
        raw = yf.download(
            ticker,
            start=str(start),
            end=str(end),
            interval="5m",
            auto_adjust=False,
            progress=False,
            prepost=False,
            threads=False,
        )
        raw = norm_cols(raw)
    except Exception as e:
        print(f"  ERROR: {e}")
        continue

    if raw.empty:
        print("  NO DATA")
        continue

    raw.index = pd.to_datetime(raw.index)
    if raw.index.tz is None:
        raw.index = raw.index.tz_localize("Asia/Kolkata")
    else:
        raw.index = raw.index.tz_convert("Asia/Kolkata")

    # Restrict regular NSE session.
    raw = raw.between_time("09:15", "15:30").copy()
    raw = raw[~raw.index.duplicated(keep="last")]

    for _, trade in g.iterrows():
        signal_dt = trade["signal_dt"]
        trigger_dt = trade["trigger_dt"]
        if pd.isna(trigger_dt):
            trigger_dt = signal_dt

        # Find the first raw candle at/after trigger timestamp.
        candidates = raw[raw.index >= trigger_dt]
        if candidates.empty:
            rows.append({
                **trade.to_dict(),
                "raw_status": "NO_TRIGGER_CANDLE"
            })
            continue

        trig_idx = candidates.index[0]
        pos = raw.index.get_loc(trig_idx)
        window = raw.iloc[pos:pos+7].copy()

        if len(window) < 3:
            rows.append({
                **trade.to_dict(),
                "raw_status": "INSUFFICIENT_FUTURE_CANDLES"
            })
            continue

        f = candle_features(window.iloc[0])

        entry = float(trade["entry_price"])
        sl = float(trade["stop_loss"])
        t1 = float(trade["target_1"])
        t2 = float(trade["target_2"])

        # Immediate next 1/2 candle close returns from entry.
        close1 = float(window.iloc[1]["Close"])
        close2 = float(window.iloc[2]["Close"])
        next1_ret_pct = (close1 - entry) / entry * 100
        next2_ret_pct = (close2 - entry) / entry * 100

        # Immediate adverse-excursion timeline from actual entry.
        # For a bullish trade, adverse excursion is entry -> Low.
        # We intentionally keep this descriptive first; no guard is imposed yet.
        risk = abs(entry - sl)

        timeline = {}
        for mins, n_candles in [(5, 1), (10, 2), (15, 3), (20, 4), (30, 6)]:
            w = window.iloc[1:1+n_candles]
            if w.empty:
                timeline[f"mae_r_{mins}m"] = np.nan
                timeline[f"mfe_r_{mins}m"] = np.nan
                timeline[f"close_return_pct_{mins}m"] = np.nan
                continue

            timeline[f"mae_r_{mins}m"] = (
                (float(w["Low"].min()) - entry) / risk if risk > 0 else np.nan
            )
            timeline[f"mfe_r_{mins}m"] = (
                (float(w["High"].max()) - entry) / risk if risk > 0 else np.nan
            )
            last_close = float(w.iloc[-1]["Close"])
            timeline[f"close_return_pct_{mins}m"] = (
                (last_close - entry) / entry * 100
            )

        # Time to worst MAE/MFE within the first 30 minutes.
        future30 = window.iloc[1:7].copy()
        if not future30.empty:
            lows = pd.to_numeric(future30["Low"], errors="coerce")
            highs = pd.to_numeric(future30["High"], errors="coerce")

            mae_idx = lows.idxmin()
            mfe_idx = highs.idxmax()

            mae_time = int(round(
                (mae_idx - trig_idx).total_seconds() / 60.0
            ))
            mfe_time = int(round(
                (mfe_idx - trig_idx).total_seconds() / 60.0
            ))

            mae30_r = (float(lows.min()) - entry) / risk if risk > 0 else np.nan
            mfe30_r = (float(highs.max()) - entry) / risk if risk > 0 else np.nan
        else:
            mae_time = np.nan
            mfe_time = np.nan
            mae30_r = np.nan
            mfe30_r = np.nan

        # First close strictly above entry after trigger.
        # This is intentionally close-based, not intrabar, to avoid optimistic labeling.
        first_positive_close_min = np.nan
        for idx2, rr in future30.iterrows():
            cc = float(rr["Close"])
            if cc > entry:
                first_positive_close_min = int(round(
                    (idx2 - trig_idx).total_seconds() / 60.0
                ))
                break

        # Trigger candle itself.
        trigger_low = float(window.iloc[0]["Low"])
        trigger_high = float(window.iloc[0]["High"])
        trigger_mae_r = (trigger_low - entry) / risk if risk > 0 else np.nan
        trigger_mfe_r = (trigger_high - entry) / risk if risk > 0 else np.nan

        rows.append({
            **trade.to_dict(),
            **f,
            "raw_status": "OK",
            "trigger_candle_time": trig_idx,
            "next1_close_return_pct": next1_ret_pct,
            "next2_close_return_pct": next2_ret_pct,
            "mae_r_5m": timeline["mae_r_5m"],
            "mae_r_10m": timeline["mae_r_10m"],
            "mae_r_15m": timeline["mae_r_15m"],
            "mae_r_20m": timeline["mae_r_20m"],
            "mae_r_30m": timeline["mae_r_30m"],
            "mfe_r_5m": timeline["mfe_r_5m"],
            "mfe_r_10m": timeline["mfe_r_10m"],
            "mfe_r_15m": timeline["mfe_r_15m"],
            "mfe_r_20m": timeline["mfe_r_20m"],
            "mfe_r_30m": timeline["mfe_r_30m"],
            "close_return_pct_5m": timeline["close_return_pct_5m"],
            "close_return_pct_10m": timeline["close_return_pct_10m"],
            "close_return_pct_15m": timeline["close_return_pct_15m"],
            "close_return_pct_20m": timeline["close_return_pct_20m"],
            "close_return_pct_30m": timeline["close_return_pct_30m"],
            "time_to_mae_min": mae_time,
            "time_to_mfe_min": mfe_time,
            "mae30_r": mae30_r,
            "mfe30_r": mfe30_r,
            "time_to_first_positive_close_min": first_positive_close_min,
            "trigger_candle_mae_r": trigger_mae_r,
            "trigger_candle_mfe_r": trigger_mfe_r,
            "trigger_open": float(window.iloc[0]["Open"]),
            "trigger_high": trigger_high,
            "trigger_low": trigger_low,
            "trigger_close": float(window.iloc[0]["Close"]),
            "next1_open": float(window.iloc[1]["Open"]),
            "next1_high": float(window.iloc[1]["High"]),
            "next1_low": float(window.iloc[1]["Low"]),
            "next1_close": float(window.iloc[1]["Close"]),
            "next2_open": float(window.iloc[2]["Open"]),
            "next2_high": float(window.iloc[2]["High"]),
            "next2_low": float(window.iloc[2]["Low"]),
            "next2_close": float(window.iloc[2]["Close"]),
        })

    time.sleep(0.5)

out = pd.DataFrame(rows)
out.to_csv(OUT, index=False)

ok = out[out["raw_status"] == "OK"].copy()
print("\nRAW CANDLE AUDIT COMPLETE")
print("="*100)
print(f"Actionable trades requested : {len(v)}")
print(f"Raw candles matched         : {len(ok)}")

for outcome in ["SL_FIRST","T1_FIRST","T2_FIRST"]:
    x = ok[ok["outcome"] == outcome]
    if x.empty:
        continue
    print(f"\n{outcome} n={len(x)}")
    for c in [
        "mae_r_5m","mae_r_10m","mae_r_15m","mae_r_20m","mae_r_30m",
        "mfe_r_5m","mfe_r_10m","mfe_r_15m","mfe_r_20m","mfe_r_30m",
        "time_to_mae_min","time_to_mfe_min",
        "time_to_first_positive_close_min",
    ]:
        print(f"  {c:<34} mean={x[c].mean():+.4f} median={x[c].median():+.4f}")

print("\nEARLY FAILURE RATE — MAE THRESHOLDS")
print("-"*100)
for mins in [5, 10, 15, 20, 30]:
    col = f"mae_r_{mins}m"
    for threshold in [-0.10, -0.20, -0.25, -0.30]:
        z = ok[ok[col].notna()]
        if z.empty:
            continue
        fail = (z[col] <= threshold).mean() * 100
        sl_fail = (z[z["outcome"] == "SL_FIRST"][col] <= threshold).mean() * 100
        win = z[z["outcome"].isin(["T1_FIRST","T2_FIRST"])]
        win_fail = (win[col] <= threshold).mean() * 100 if not win.empty else np.nan
        print(
            f"  {mins:>2}m  MAE <= {threshold:+.2f}R | "
            f"all={fail:5.1f}% | SL={sl_fail:5.1f}% | "
            f"TARGET={win_fail:5.1f}%"
        )

print(f"\nSaved: {OUT}")
