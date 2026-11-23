from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "v13_1_regime_differential_results.csv"
CACHE = ROOT / "_regime_differential_nifty_cache"
OUT = ROOT / "v13_1_nifty_metric_forensic_results.csv"

# Research-only: never modify engine or source datasets.
df = pd.read_csv(RESULTS)
df["signal_time"] = pd.to_datetime(df["signal_time"], errors="coerce")

# Only rows for which the historical forensic dataset was known to contain
# the six NIFTY metrics: August 91 + September 28 = 119 observations.
targets = df[
    (
        (df["period"].eq("AUGUST")) &
        (df["direction"].eq("BEARISH"))
    ) |
    (
        (df["period"].eq("SEPTEMBER")) &
        (df["direction"].eq("BEARISH"))
    )
].copy()

print("RESULT_ROWS:", len(df))
print("TARGET_ROWS_DISCOVERED:", len(targets))
print("NOTE: This script does NOT claim these are the original 119 until exact immutable cohort membership is verified.")

rows = []

for _, r in targets.iterrows():
    sig = r["signal_time"]
    if pd.isna(sig):
        continue

    f = CACHE / f"{sig.strftime('%Y-%m-%d')}.csv"
    if not f.exists():
        continue

    n = pd.read_csv(f)
    if "Datetime" not in n.columns:
        continue

    n["Datetime"] = pd.to_datetime(n["Datetime"], errors="coerce")
    n = n[n["Datetime"] <= sig].sort_values("Datetime").copy()

    if len(n) < 61:
        continue

    for c in ["Open", "High", "Low", "Close"]:
        n[c] = pd.to_numeric(n[c], errors="coerce")

    n = n.dropna(subset=["Open", "High", "Low", "Close"]).copy()

    if len(n) < 61:
        continue

    cur = n.iloc[-1]
    prior60 = n.iloc[-61:-1]

    cur_range = float(cur["High"] - cur["Low"])

    prev_close = n["Close"].shift(1)
    tr = pd.concat(
        [
            n["High"] - n["Low"],
            (n["High"] - prev_close).abs(),
            (n["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    prior_tr60 = tr.iloc[-61:-1]

    rows.append({
        "symbol": r["symbol"],
        "signal_time": sig,
        "period": r["period"],
        "direction": r["direction"],
        "pit_bars": len(n),

        "current_open": float(cur["Open"]),
        "current_high": float(cur["High"]),
        "current_low": float(cur["Low"]),
        "current_close": float(cur["Close"]),
        "current_hl": cur_range,

        "prior60_hl_mean": float(prior60.sub(prior60["Low"], axis=0).mean()) if False else float((prior60["High"] - prior60["Low"]).mean()),
        "prior60_hl_median": float((prior60["High"] - prior60["Low"]).median()),
        "prior60_tr_mean": float(prior_tr60.mean()),
        "prior60_tr_median": float(prior_tr60.median()),

        # Candidate bar-range percentages
        "range_over_open_pct": cur_range / float(cur["Open"]) * 100,
        "range_over_high_pct": cur_range / float(cur["High"]) * 100,
        "range_over_low_pct": cur_range / float(cur["Low"]) * 100,
        "range_over_close_pct": cur_range / float(cur["Close"]) * 100,

        # Candidate expansion denominators
        "exp_prior60_hl_mean": cur_range / float((prior60["High"] - prior60["Low"]).mean()),
        "exp_prior60_hl_median": cur_range / float((prior60["High"] - prior60["Low"]).median()),
        "exp_prior60_tr_mean": cur_range / float(prior_tr60.mean()),
        "exp_prior60_tr_median": cur_range / float(prior_tr60.median()),
    })

out = pd.DataFrame(rows)
out.to_csv(OUT, index=False)

print("FORENSIC_ROWS_WRITTEN:", len(out))
print("OUTPUT:", OUT)
print("PRODUCTION_FILES_MODIFIED: 0")
