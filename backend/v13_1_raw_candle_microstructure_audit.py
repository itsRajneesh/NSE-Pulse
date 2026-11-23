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

        # MAE/MFE over next six 5-min candles, measured from actual entry.
        future = window.iloc[1:7]
        mae = (future["Low"].min() - entry) / entry * 100
        mfe = (future["High"].max() - entry) / entry * 100

        # Express adverse/favourable excursion in R using the actual stop distance.
        risk = abs(entry - sl)
        mae_r = ((future["Low"].min() - entry) / risk) if risk > 0 else np.nan
        mfe_r = ((future["High"].max() - entry) / risk) if risk > 0 else np.nan

        # Did the trigger candle itself show immediate adverse excursion?
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
            "mae_pct_next6": mae,
            "mfe_pct_next6": mfe,
            "mae_r_next6": mae_r,
            "mfe_r_next6": mfe_r,
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
        "body_pct_range","upper_wick_pct_range","lower_wick_pct_range",
        "close_location","next1_close_return_pct","next2_close_return_pct",
        "mae_r_next6","mfe_r_next6","trigger_candle_mae_r","trigger_candle_mfe_r"
    ]:
        print(f"  {c:<28} mean={x[c].mean():+.4f} median={x[c].median():+.4f}")

print(f"\nSaved: {OUT}")
