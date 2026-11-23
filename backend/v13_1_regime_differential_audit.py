from __future__ import annotations

from pathlib import Path
import importlib
import pandas as pd
import numpy as np
import yfinance as yf

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "v13_1_regime_differential_results.csv"
NIFTY_CACHE = ROOT / "_regime_differential_nifty_cache"
NIFTY_CACHE.mkdir(exist_ok=True)

IST = "Asia/Kolkata"

# Immutable cohort contracts.
EXPECTED = {
    "AUGUST": {"n": 91, "total_r": -27.428},
    "SEPTEMBER": {"n": 32, "total_r": 9.087},
}

AUG_NAMES = [
    "v13_1_bull_nifty_bearish_august_immutable.csv",
    "v13_1_august_bull_nifty_bearish_91.csv",
    "v13_1_august_91_immutable.csv",
]
SEP_NAMES = [
    "v13_1_bull_nifty_bearish_september_immutable.csv",
    "v13_1_september_bull_nifty_bearish_32.csv",
    "v13_1_september_32_immutable.csv",
]


def parse_dt(s):
    # Immutable cohort signal_time values are already IST-local naive
    # timestamps. Do NOT reinterpret them as UTC.
    return pd.to_datetime(s, errors="coerce")


def locate_exact(names, period):
    matches = []
    for name in names:
        for p in ROOT.rglob(name):
            matches.append(p)

    if len(matches) != 1:
        raise RuntimeError(
            f"{period}: exact immutable cohort artifact missing or ambiguous. "
            f"Expected exactly one of:\n" +
            "\n".join(f"  - {n}" for n in names) +
            f"\nFound: {matches}\n"
            "Refusing to reconstruct/filter a larger population."
        )
    return matches[0]


def read_exact(path, period):
    df = pd.read_csv(path)

    required = {"symbol", "signal_time"}
    if not required.issubset(df.columns):
        raise RuntimeError(
            f"{period}: source lacks required immutable key columns: {required}"
        )

    if "realized_r" in df.columns:
        pnl_col = "realized_r"
    elif "delayed_r" in df.columns:
        pnl_col = "delayed_r"
    else:
        raise RuntimeError(
            f"{period}: source lacks verified realized_r/delayed_r column."
        )

    out = df.copy()
    out["symbol"] = out["symbol"].astype(str).str.upper()
    out["signal_time"] = parse_dt(out["signal_time"])
    out["_immutable_pnl"] = pd.to_numeric(out[pnl_col], errors="coerce")

    exp = EXPECTED[period]

    if len(out) != exp["n"]:
        raise RuntimeError(
            f"{period}: immutable row count FAILED: "
            f"{len(out)} != {exp['n']}"
        )

    total = float(out["_immutable_pnl"].sum())
    if abs(total - exp["total_r"]) >= 0.02:
        raise RuntimeError(
            f"{period}: immutable TotalR FAILED: "
            f"{total:+.3f} != {exp['total_r']:+.3f}"
        )

    if out[["symbol", "signal_time"]].duplicated().any():
        raise RuntimeError(
            f"{period}: duplicate (symbol, signal_time) immutable key."
        )

    out["_immutable_key"] = (
        out["symbol"] + "|" +
        out["signal_time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    )

    return out, pnl_col


def load_immutable_cohorts():
    aug_path = locate_exact(AUG_NAMES, "AUGUST")
    sep_path = locate_exact(SEP_NAMES, "SEPTEMBER")

    aug, aug_pnl = read_exact(aug_path, "AUGUST")
    sep, sep_pnl = read_exact(sep_path, "SEPTEMBER")

    print("\n" + "=" * 70)
    print("IMMUTABLE READ-ONLY SOURCE LOCK")
    print("=" * 70)
    print(
        f"  August    : {len(aug)}/{EXPECTED['AUGUST']['n']} | "
        f"TotalR={aug['_immutable_pnl'].sum():+.3f}R | {aug_path}"
    )
    print(
        f"  September : {len(sep)}/{EXPECTED['SEPTEMBER']['n']} | "
        f"TotalR={sep['_immutable_pnl'].sum():+.3f}R | {sep_path}"
    )
    print("  No H3 rerun | No regime filter | No outcome recomputation")
    print("  SOURCE LOCK: PASS")

    return aug, sep


def fetch_nifty_day(day):
    key = str(pd.Timestamp(day).date())
    cache_path = NIFTY_CACHE / f"{key}.csv"

    if not cache_path.exists() or cache_path.stat().st_size <= 50:
        raise FileNotFoundError(
            f"Missing immutable NIFTY cache: {cache_path}. "
            "Strict audit refuses live/downloaded data."
        )

    try:
        x = pd.read_csv(cache_path)
    except Exception as e:
        raise RuntimeError(
            f"Unable to read immutable NIFTY cache: {cache_path}"
        ) from e

    if x.empty:
        raise RuntimeError(
            f"Immutable NIFTY cache is empty: {cache_path}"
        )

    date_col = "Datetime" if "Datetime" in x.columns else x.columns[0]
    x[date_col] = pd.to_datetime(x[date_col], errors="coerce")

    if x[date_col].isna().any():
        raise RuntimeError(
            f"Invalid Datetime values in immutable NIFTY cache: {cache_path}"
        )

    x = x.set_index(date_col).sort_index()

    if x.index.duplicated().any():
        raise RuntimeError(
            f"Duplicate timestamps in immutable NIFTY cache: {cache_path}"
        )

    return x


diag = importlib.import_module("v13_1_regime_atr_h3_timing_diagnostic")


def attach_context(df, period):
    rows = []

    for _, row in df.iterrows():
        sig = pd.Timestamp(row["signal_time"])

        # IMPORTANT:
        # Historical NIFTY cache is keyed by the stock-row's source date,
        # not necessarily signal_time.date(). This preserves the verified
        # cross-midnight cache mapping.
        if "date" in row.index and pd.notna(row["date"]):
            cache_key = pd.Timestamp(row["date"]).date().isoformat()
        else:
            cache_key = sig.date().isoformat()

        raw = fetch_nifty_day(cache_key)

        # Strict point-in-time cutoff: no NIFTY bar after signal_time
        # may enter any audit calculation.
        raw = raw[raw.index <= sig].copy()

        if raw.empty:
            # Cache exists, but there are no pre-signal NIFTY bars.
            # Preserve the immutable cohort row; context remains missing.
            out = row.to_dict()
            for col in [
                "nifty_atr_pct",
                "nifty_bar_range_pct",
                "nifty_range_expansion",
                "nifty_slope_5",
                "nifty_slope_12",
                "nifty_extension_atr",
            ]:
                out[col] = np.nan
            out["period"] = period
            rows.append(out)
            continue

        # Required OHLC columns.
        required_ohlc = {"Open", "High", "Low", "Close"}
        if not required_ohlc.issubset(raw.columns):
            raise RuntimeError(
                f"{period}: NIFTY cache {cache_key} lacks required OHLC columns."
            )

        raw = raw.dropna(subset=["Open", "High", "Low", "Close"]).copy()

        if raw.empty:
            raise RuntimeError(
                f"{period}: no valid OHLC NIFTY bars before signal_time={sig}"
            )

        close = pd.to_numeric(raw["Close"], errors="coerce")
        high = pd.to_numeric(raw["High"], errors="coerce")
        low = pd.to_numeric(raw["Low"], errors="coerce")
        prev_close = close.shift(1)

        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        # Historical ATR% formula independently proven on all 119
        # populated reference rows:
        # rolling 14-bar mean TR / current close * 100.
        atr14 = tr.rolling(14).mean()

        # Historical 5/12-bar slope formulas independently proven
        # on all 119 populated reference rows.
        slope5 = ((close / close.shift(5)) - 1.0) * 100.0 / 5.0
        slope12 = ((close / close.shift(12)) - 1.0) * 100.0 / 12.0

        # Historical extension formula independently proven on all
        # 119 populated reference rows:
        # (current close - EMA20) / rolling14 mean TR.
        ema20 = close.ewm(span=20, adjust=False).mean()
        extension_atr = (close - ema20) / atr14

        last_close = float(close.iloc[-1])

        out = row.to_dict()

        if len(raw) >= 14 and np.isfinite(last_close) and last_close != 0:
            out["nifty_atr_pct"] = float(
                atr14.iloc[-1] / last_close * 100.0
            )
        else:
            out["nifty_atr_pct"] = np.nan

        if len(raw) >= 5 and np.isfinite(slope5.iloc[-1]):
            out["nifty_slope_5"] = float(slope5.iloc[-1])
        else:
            out["nifty_slope_5"] = np.nan

        if len(raw) >= 12 and np.isfinite(slope12.iloc[-1]):
            out["nifty_slope_12"] = float(slope12.iloc[-1])
        else:
            out["nifty_slope_12"] = np.nan

        if (
            len(raw) >= 14
            and np.isfinite(extension_atr.iloc[-1])
        ):
            out["nifty_extension_atr"] = float(extension_atr.iloc[-1])
        else:
            out["nifty_extension_atr"] = np.nan

        # These two formulas are intentionally NOT reconstructed yet.
        # No unsupported approximation is allowed in the strict audit.
        out["nifty_bar_range_pct"] = np.nan
        out["nifty_range_expansion"] = np.nan

        out["period"] = period
        rows.append(out)

    return pd.DataFrame(rows)


def outcome_stats(df):
    r = pd.to_numeric(df["_immutable_pnl"], errors="coerce").dropna()
    wins = r[r > 0]
    losses = r[r < 0]
    gp = float(wins.sum())
    gl = float(-losses.sum())
    equity = r.cumsum()
    dd = equity.cummax() - equity
    return {
        "n": len(r),
        "win": float((r > 0).mean() * 100),
        "avg": float(r.mean()),
        "total": float(r.sum()),
        "pf": gp / gl if gl else np.inf,
        "dd": float(dd.max()) if len(dd) else 0.0,
    }


def print_cohort(df, label):
    s = outcome_stats(df)
    print(f"\n{label} COHORT SUMMARY:")
    print(f"  Trades (N)          : {s['n']}")
    print(f"  Win Rate (%)        : {s['win']:.2f}%")
    print(f"  Avg R / Trade       : {s['avg']:+.3f}R")
    print(f"  Total Realized R    : {s['total']:+.3f}R")
    print(f"  Profit Factor       : {s['pf']:.2f}")
    print(f"  Max Drawdown        : {s['dd']:.2f}R")

    print("-----------------------------------------------------------------")
    print("  POINT-IN-TIME NIFTY METRICS & COVERAGE:")
    for col, label2 in [
        ("nifty_atr_pct", "NIFTY ATR %"),
        ("nifty_bar_range_pct", "Intraday Bar Range %"),
        ("nifty_range_expansion", "Range Expansion Factor"),
        ("nifty_slope_5", "5-Bar Momentum Slope"),
        ("nifty_slope_12", "12-Bar Momentum Slope"),
        ("nifty_extension_atr", "Trend Extension (ATR)"),
    ]:
        x = pd.to_numeric(df[col], errors="coerce").dropna()
        coverage = len(x)
        total = len(df)
        if coverage:
            print(
                f"    {label2:<27} -> Mean: {x.mean():.4f} | "
                f"Median: {x.median():.4f} "
                f"[Coverage: {coverage}/{total} rows ({coverage/total*100:.1f}%)]"
            )
        else:
            print(
                f"    {label2:<27} -> unavailable "
                f"[Coverage: 0/{total} rows (0.0%)]"
            )


def main():
    print("=" * 105)
    print("V13.1 — STRICT PURE IMMUTABLE AUGUST vs SEPTEMBER DIFFERENTIAL AUDIT")
    print("Cluster: BULL NIFTY x BEARISH STOCK")
    print("H3: NOT rerun | Regime: NOT reclassified | Outcome: NOT recomputed")
    print("Population: exact verified cohort artifacts only")
    print("v13_engine.py: UNTOUCHED")
    print("=" * 105)

    aug, sep = load_immutable_cohorts()

    aug_keys = set(aug["_immutable_key"])
    sep_keys = set(sep["_immutable_key"])
    aug_pnl_before = float(aug["_immutable_pnl"].sum())
    sep_pnl_before = float(sep["_immutable_pnl"].sum())

    print("\nAttaching point-in-time NIFTY metrics via additive LEFT JOIN...")
    aug_ctx = attach_context(aug, "AUGUST")
    sep_ctx = attach_context(sep, "SEPTEMBER")

    for period, ctx, keys_before, pnl_before in [
        ("AUGUST", aug_ctx, aug_keys, aug_pnl_before),
        ("SEPTEMBER", sep_ctx, sep_keys, sep_pnl_before),
    ]:
        if len(ctx) != len(keys_before):
            raise RuntimeError(f"{period}: LEFT JOIN row-count conservation FAILED.")

        keys_after = set(ctx["_immutable_key"])
        if keys_after != keys_before:
            raise RuntimeError(f"{period}: immutable key conservation FAILED.")

        pnl_after = float(ctx["_immutable_pnl"].sum())
        if abs(pnl_after - pnl_before) >= 1e-9:
            raise RuntimeError(f"{period}: immutable P&L conservation FAILED.")

    out = pd.concat([aug_ctx, sep_ctx], ignore_index=True)

    if len(out[out["period"] == "AUGUST"]) != 91:
        raise RuntimeError("Final August count != 91.")
    if len(out[out["period"] == "SEPTEMBER"]) != 32:
        raise RuntimeError("Final September count != 32.")

    if abs(
        float(out.loc[out["period"] == "AUGUST", "_immutable_pnl"].sum())
        - (-27.428)
    ) >= 0.02:
        raise RuntimeError("Final August P&L != -27.428R.")

    if abs(
        float(out.loc[out["period"] == "SEPTEMBER", "_immutable_pnl"].sum())
        - 9.087
    ) >= 0.02:
        raise RuntimeError("Final September P&L != +9.087R.")

    out.to_csv(OUT, index=False)

    print("\n" + "=" * 105)
    print("FINAL STRICT IMMUTABLE DIFFERENTIAL MATRIX")
    print("=" * 105)

    print_cohort(aug_ctx, "AUGUST")
    print_cohort(sep_ctx, "SEPTEMBER")

    print("\n" + "-" * 105)
    print("NIFTY CONTEXT DIFFERENCE (SEPTEMBER - AUGUST)")
    print("-" * 105)

    for col, label2 in [
        ("nifty_atr_pct", "NIFTY ATR %"),
        ("nifty_bar_range_pct", "Intraday Bar Range %"),
        ("nifty_range_expansion", "Range Expansion Factor"),
        ("nifty_slope_5", "5-Bar Momentum Slope"),
        ("nifty_slope_12", "12-Bar Momentum Slope"),
        ("nifty_extension_atr", "Trend Extension (ATR)"),
    ]:
        a = pd.to_numeric(aug_ctx[col], errors="coerce").dropna()
        s = pd.to_numeric(sep_ctx[col], errors="coerce").dropna()
        if len(a) and len(s):
            print(
                f"  {label2:<27} "
                f"AUG={a.mean():.4f} | SEP={s.mean():.4f} | "
                f"DELTA={s.mean()-a.mean():+.4f}"
            )

    print("\n" + "=" * 105)
    print("IMMUTABLE CONSERVATION CHECK")
    print("=" * 105)
    print("  August    : 91/91 | TotalR=-27.428R")
    print("  September : 32/32 | TotalR=+9.087R")
    print("  LEFT JOIN : ZERO ROW DROPS")
    print("  P&L       : UNCHANGED")
    print("  FINAL AUDIT: PASS 🔒")

    print(f"\nCSV: {OUT}")


if __name__ == "__main__":
    main()