"""
V13.1 TRUE OOS — AUGUST 2026
Exact same H3 hypothesis, no parameter tuning.

Important:
- v13_engine.py is NOT imported or modified.
- Reuses the already-approved delayed-entry H3 simulation functions.
- Uses August 2026 only as unseen holdout relative to the September-derived hypothesis.
- Same-session H3, next 5m open, same SL/T1/T2 logic.
- Then evaluates BULL NIFTY x BEARISH STOCK using point-in-time NIFTY context.
"""

from pathlib import Path
import importlib
import sys
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
SIM_NAME = "v13_1_delayed_entry_h3_simulation"
REGIME_NAME = "v13_1_regime_atr_h3_timing_diagnostic"

CSV = BASE / "backtest_nifty500_v13_results.csv"
OUT_DIR = BASE / "_oos_august_output"
OUT_DIR.mkdir(exist_ok=True)
OUTPUT = OUT_DIR / "v13_1_true_oos_august_h3_results.csv"

START = pd.Timestamp("2026-08-01")
END = pd.Timestamp("2026-09-01")
IST = "Asia/Kolkata"


def load_august_candidates():
    df = pd.read_csv(CSV)

    df["signal_time"] = (
        pd.to_datetime(df["signal_time"], errors="coerce", utc=True)
        .dt.tz_convert(IST)
        .dt.tz_localize(None)
    )

    df["symbol"] = df["symbol"].astype(str).str.upper()

    df = df[
        (df["signal_time"] >= START)
        & (df["signal_time"] < END)
    ].copy()

    df = df.sort_values(
        ["signal_time", "symbol"]
    ).reset_index(drop=True)

    if df.empty:
        raise RuntimeError("No August candidates found.")

    print(f"August candidates from V13 baseline: {len(df)}")

    print("\nAugust direction split:")
    print(df["direction"].value_counts().to_string())

    print("\nAugust date split:")
    print(
        df.groupby(df["signal_time"].dt.date)
        .size()
        .to_string()
    )

    return df


def run_exact_h3():
    sim = importlib.import_module(SIM_NAME)

    # Preserve the September simulator; only override the candidate source.
    sim.load_candidates = load_august_candidates

    # Prevent overwriting the clean September result.
    sim.BASE = OUT_DIR

    # Keep input CSV pointing at the real backend baseline CSV.
    sim.CSV = CSV

    print("\n" + "=" * 90)
    print("V13.1 TRUE OOS — AUGUST 2026 H3 TEST")
    print("=" * 90)
    print("Hypothesis : exact same Retest -> Reclaim -> H3")
    print("Entry      : next 5m candle OPEN")
    print("Session    : same trading session only")
    print("Tuning     : NONE")
    print("Engine     : v13_engine.py UNTOUCHED")
    print("=" * 90)

    # main() is the already-approved clean simulation logic.
    sim.main()

    produced = OUT_DIR / "v13_1_delayed_entry_h3_results.csv"

    if not produced.exists():
        raise RuntimeError(
            f"Expected H3 output not found: {produced}"
        )

    h3 = pd.read_csv(produced)

    h3["signal_time"] = (
        pd.to_datetime(h3["signal_time"], errors="coerce", utc=True)
        .dt.tz_convert(IST)
        .dt.tz_localize(None)
    )

    if "h3_end_time" in h3.columns:
        h3["h3_end_time"] = (
            pd.to_datetime(h3["h3_end_time"], errors="coerce", utc=True)
            .dt.tz_convert(IST)
            .dt.tz_localize(None)
        )

    if "delayed_entry_time" in h3.columns:
        h3["delayed_entry_time"] = (
            pd.to_datetime(
                h3["delayed_entry_time"],
                errors="coerce",
                utc=True,
            )
            .dt.tz_convert(IST)
            .dt.tz_localize(None)
        )

    # Only tradeable same-session H3 rows are P&L rows.
    if "accounting_status" in h3.columns:
        tradeable = h3[
            h3["accounting_status"] == "TRADEABLE_H3"
        ].copy()
    else:
        tradeable = h3[
            h3.get("h3_confirmed", False) == True
        ].copy()

    tradeable = tradeable[
        (tradeable["signal_time"] >= START)
        & (tradeable["signal_time"] < END)
    ].copy()

    tradeable.to_csv(OUTPUT, index=False)

    print("\nClean August H3 tradeable rows:", len(tradeable))

    return tradeable


def max_dd(r):
    r = pd.to_numeric(r, errors="coerce").dropna()
    if r.empty:
        return 0.0
    equity = r.cumsum()
    return float((equity.cummax() - equity).max())


def stats(df):
    if df.empty:
        return {
            "N": 0, "Win%": 0.0, "Target%": 0.0,
            "SL%": 0.0, "AvgR": 0.0,
            "TotalR": 0.0, "PF": 0.0, "DD": 0.0
        }

    r = pd.to_numeric(df["delayed_r"], errors="coerce").dropna()

    wins = int((r > 0).sum())
    target = int(
        df["outcome"].astype(str)
        .str.contains("T1|T2", regex=True)
        .sum()
    )
    sl = int(
        df["outcome"].astype(str)
        .str.contains("SL", regex=True)
        .sum()
    )

    gp = float(r[r > 0].sum())
    gl = float(-r[r < 0].sum())
    pf = gp / gl if gl > 0 else np.inf

    return {
        "N": len(r),
        "Win%": wins / len(r) * 100,
        "Target%": target / len(r) * 100,
        "SL%": sl / len(r) * 100,
        "AvgR": float(r.mean()),
        "TotalR": float(r.sum()),
        "PF": pf,
        "DD": max_dd(r),
    }


def print_stats(label, df):
    s = stats(df)
    pf = "inf" if np.isinf(s["PF"]) else f"{s['PF']:.2f}"

    print(
        f"{label:52s}"
        f"N={s['N']:3d} "
        f"Win={s['Win%']:6.2f}% "
        f"Tgt={s['Target%']:6.2f}% "
        f"SL={s['SL%']:6.2f}% "
        f"AvgR={s['AvgR']:7.3f} "
        f"TotalR={s['TotalR']:8.3f} "
        f"PF={pf:>5s} "
        f"DD={s['DD']:6.2f}"
    )


def add_point_in_time_regime(df):
    diag = importlib.import_module(REGIME_NAME)

    rows = []

    for _, row in df.iterrows():
        sig = row["signal_time"]

        raw = diag.fetch_nifty_day(sig.date())
        ctx = diag.nifty_context(raw, sig)

        if ctx is None:
            regime = "UNKNOWN"
        else:
            regime = ctx["nifty_regime"]

        direction = str(row["direction"]).upper()

        if regime == "BULL" and direction == "BEARISH":
            cluster = "BULL_NIFTY_x_BEARISH_STOCK"
        elif regime == "BULL" and direction == "BULLISH":
            cluster = "BULL_NIFTY_x_BULLISH_STOCK"
        elif regime == "BEAR" and direction == "BEARISH":
            cluster = "BEAR_NIFTY_x_BEARISH_STOCK"
        elif regime == "BEAR" and direction == "BULLISH":
            cluster = "BEAR_NIFTY_x_BULLISH_STOCK"
        elif regime == "NEUTRAL":
            cluster = "NEUTRAL"
        else:
            cluster = "UNKNOWN"

        x = row.to_dict()
        x["nifty_regime"] = regime
        x["regime_direction_cluster"] = cluster

        rows.append(x)

    return pd.DataFrame(rows)


def main():
    tradeable = run_exact_h3()

    if tradeable.empty:
        print("\nNO TRADEABLE H3 ROWS IN AUGUST.")
        return

    result = add_point_in_time_regime(tradeable)

    print("\n" + "=" * 90)
    print("TRUE OOS RESULTS — AUGUST 2026")
    print("=" * 90)

    print_stats("ALL AUGUST TRADEABLE H3", result)

    print("\nNIFTY REGIME x STOCK DIRECTION")
    print("-" * 90)

    for key, g in result.groupby(
        ["nifty_regime", "direction"],
        dropna=False
    ):
        print_stats(
            f"{key[0]} x {key[1]}",
            g,
        )

    print("\nMAIN HYPOTHESIS — BULL NIFTY x BEARISH STOCK")
    print("-" * 90)

    rw = result[
        result["regime_direction_cluster"]
        == "BULL_NIFTY_x_BEARISH_STOCK"
    ].copy()

    print_stats(
        "AUGUST — BULL NIFTY x BEARISH STOCK",
        rw,
    )

    if not rw.empty:
        rw["date"] = rw["signal_time"].dt.date

        print("\nDaily stability of main hypothesis:")
        for d, g in rw.groupby("date"):
            print_stats(str(d), g)

    print("\nH3 confirmation timing — diagnostic only")
    if "h3_end_time" in result.columns:
        result["signal_to_h3_min"] = (
            result["h3_end_time"] - result["signal_time"]
        ).dt.total_seconds() / 60.0

        print(
            f"Mean   : {result['signal_to_h3_min'].mean():.1f} min"
        )
        print(
            f"Median : {result['signal_to_h3_min'].median():.1f} min"
        )

    result.to_csv(OUTPUT, index=False)

    print("\n" + "=" * 90)
    print("TRUE OOS COMPLETE")
    print("=" * 90)
    print(f"Diagnostic CSV : {OUTPUT}")
    print("v13_engine.py  : UNTOUCHED")
    print("September data : NOT used as test candidates")
    print("Parameter tune : NONE")


if __name__ == "__main__":
    main()


