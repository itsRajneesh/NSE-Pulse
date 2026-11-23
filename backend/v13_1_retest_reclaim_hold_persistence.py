from pathlib import Path
import time
import warnings

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "backtest_nifty500_v13_results.csv"

IST = "Asia/Kolkata"

# Same V13.1 candidate rule — DO NOT CHANGE
TV_MIN = 0.0
BD_MIN = 0.50
BD_MAX = 1.25
RELVOL_MAX = 1.50


def load_candidates():
    df = pd.read_csv(CSV_PATH)

    df["true_velocity"] = pd.to_numeric(df["true_velocity"], errors="coerce")
    df["breakout_distance_atr"] = pd.to_numeric(
        df["breakout_distance_atr"], errors="coerce"
    )
    df["rel_vol"] = pd.to_numeric(df["rel_vol"], errors="coerce")
    df["score"] = pd.to_numeric(df["score"], errors="coerce")
    df["atr14"] = pd.to_numeric(df["atr14"], errors="coerce")
    df["entry_price"] = pd.to_numeric(df["entry_price"], errors="coerce")
    df["stop_loss"] = pd.to_numeric(df["stop_loss"], errors="coerce")
    df["realized_r"] = pd.to_numeric(df["realized_r"], errors="coerce")

    df["signal_time"] = pd.to_datetime(
        df["signal_time"], errors="coerce"
    )

    # Exact V13.1 candidate universe
    mask = (
        (df["direction"].astype(str).str.upper() == "BULLISH")
        & (df["true_velocity"] > TV_MIN)
        & (df["breakout_distance_atr"] >= BD_MIN)
        & (df["breakout_distance_atr"] <= BD_MAX)
        & (df["rel_vol"] <= RELVOL_MAX)
    )

    candidates = df.loc[mask].copy()

    # Keep same small actionable set used in previous raw audit.
    # Prefer rows with actual outcomes and earliest candidates.
    candidates = candidates.sort_values(
        ["signal_time", "symbol"]
    ).reset_index(drop=True)

    return candidates


def download_5m(symbol, signal_time):
    """
    Yahoo 5m data is limited to recent history.
    Use a narrow window around the signal.
    """

    start = signal_time - pd.Timedelta(minutes=10)
    end = signal_time + pd.Timedelta(hours=3)

    ticker = symbol + ".NS"

    try:
        raw = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=(end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            interval="5m",
            progress=False,
            auto_adjust=False,
            prepost=False,
            threads=False,
        )

        if raw is None or raw.empty:
            return None

        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        raw = raw.reset_index()

        if "Datetime" not in raw.columns:
            if "Date" in raw.columns:
                raw = raw.rename(columns={"Date": "Datetime"})
            else:
                return None

        # Robust timezone normalization
        dt = pd.to_datetime(raw["Datetime"], errors="coerce", utc=True)
        raw["Datetime"] = (
            dt.dt.tz_convert(IST)
            .dt.tz_localize(None)
        )

        raw = raw.dropna(subset=["Datetime"]).copy()

        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in raw.columns:
                raw[col] = pd.to_numeric(
                    raw[col], errors="coerce"
                )

        raw = raw.sort_values("Datetime").reset_index(drop=True)

        return raw

    except Exception as exc:
        print(f"  Yahoo error {symbol}: {exc}")
        return None


def find_trigger_candle(df, signal_time):
    """
    Match the actual trigger candle at/after signal_time.
    """
    x = df[df["Datetime"] >= signal_time].copy()

    if x.empty:
        return None

    return x.iloc[0]


def find_retest_reclaim(df, trigger_idx, or_high):
    """
    Retest:
        after trigger, price touches / returns to OR high.

    Reclaim:
        later candle CLOSE strictly above OR high.

    We only classify the structure.
    We do NOT simulate a delayed entry.
    """

    after = df.iloc[trigger_idx + 1 :].copy()

    if after.empty:
        return None

    retest_idx = None

    for idx, row in after.iterrows():
        low = float(row["Low"])

        if low <= or_high:
            retest_idx = idx
            break

    if retest_idx is None:
        return None

    reclaim_idx = None

    after_retest = df.loc[retest_idx + 1 :].copy()

    for idx, row in after_retest.iterrows():
        close = float(row["Close"])

        if close > or_high:
            reclaim_idx = idx
            break

    if reclaim_idx is None:
        return {
            "retest_idx": retest_idx,
            "reclaim_idx": None,
        }

    return {
        "retest_idx": retest_idx,
        "reclaim_idx": reclaim_idx,
    }


def hold_status(df, reclaim_idx, or_high, candles):
    """
    H1/H2/H3:
    After reclaim, require the next N candle CLOSES
    to remain strictly above OR high.
    """

    start = reclaim_idx + 1
    end = start + candles

    window = df.iloc[start:end].copy()

    if len(window) < candles:
        return None

    closes = pd.to_numeric(
        window["Close"], errors="coerce"
    )

    return bool((closes > or_high).all())


def excursion_after_reclaim(df, reclaim_idx, entry_price, risk):
    """
    Measure price behaviour after reclaim.
    """

    future = df.iloc[reclaim_idx + 1 : reclaim_idx + 13].copy()

    if future.empty or risk <= 0:
        return {
            "post_reclaim_mae_r": np.nan,
            "post_reclaim_mfe_r": np.nan,
        }

    lows = pd.to_numeric(future["Low"], errors="coerce")
    highs = pd.to_numeric(future["High"], errors="coerce")

    mae = (lows.min() - entry_price) / risk
    mfe = (highs.max() - entry_price) / risk

    return {
        "post_reclaim_mae_r": float(mae),
        "post_reclaim_mfe_r": float(mfe),
    }


def analyse_candidate(row):
    symbol = str(row["symbol"])
    signal_time = pd.to_datetime(row["signal_time"], errors="coerce", utc=True).tz_convert(IST).tz_localize(None)

    raw = download_5m(symbol, signal_time)

    if raw is None or raw.empty:
        return {
            "symbol": symbol,
            "date": row.get("date"),
            "signal_time": signal_time,
            "outcome": row.get("outcome"),
            "realized_r": row.get("realized_r"),
            "status": "RAW_MISSING",
        }

    trigger = find_trigger_candle(raw, signal_time)

    if trigger is None:
        return {
            "symbol": symbol,
            "date": row.get("date"),
            "signal_time": signal_time,
            "outcome": row.get("outcome"),
            "realized_r": row.get("realized_r"),
            "status": "TRIGGER_MISSING",
        }

    trigger_idx = int(trigger.name)

    or_high = float(row["opening_range_high"])
    entry = float(row["entry_price"])
    stop = float(row["stop_loss"])
    risk = abs(entry - stop)

    pattern = find_retest_reclaim(
        raw,
        trigger_idx,
        or_high,
    )

    base = {
        "symbol": symbol,
        "date": row.get("date"),
        "signal_time": signal_time,
        "trigger_time": trigger["Datetime"],
        "outcome": row.get("outcome"),
        "realized_r": row.get("realized_r"),
        "score": row.get("score"),
        "true_velocity": row.get("true_velocity"),
        "breakout_distance_atr": row.get(
            "breakout_distance_atr"
        ),
        "rel_vol": row.get("rel_vol"),
        "status": "OK",
        "retest": False,
        "reclaim": False,
        "retest_time": pd.NaT,
        "reclaim_time": pd.NaT,
    }

    if pattern is None:
        return base

    retest_idx = pattern["retest_idx"]
    reclaim_idx = pattern["reclaim_idx"]

    base["retest"] = True
    base["retest_time"] = raw.loc[
        retest_idx, "Datetime"
    ]

    if reclaim_idx is None:
        return base

    base["reclaim"] = True
    base["reclaim_time"] = raw.loc[
        reclaim_idx, "Datetime"
    ]

    base["reclaim_delay_min"] = (
        base["reclaim_time"] - base["trigger_time"]
    ).total_seconds() / 60.0

    for n in [1, 2, 3]:
        base[f"hold_{n}"] = hold_status(
            raw,
            reclaim_idx,
            or_high,
            n,
        )

    exc = excursion_after_reclaim(
        raw,
        reclaim_idx,
        entry,
        risk,
    )

    base.update(exc)

    if pd.notna(row.get("outcome_time", np.nan)):
        outcome_time = pd.to_datetime(row["outcome_time"], errors="coerce", utc=True).tz_convert(IST).tz_localize(None)

        if pd.notna(outcome_time):
            base["reclaim_to_outcome_min"] = (
                outcome_time - base["reclaim_time"]
            ).total_seconds() / 60.0

    return base


def bucket_summary(df, name, mask):
    x = df[mask].copy()

    if x.empty:
        print(f"\n{name}")
        print("  N=0")
        return

    outcomes = x["outcome"].astype(str).str.upper()

    target_mask = outcomes.isin(
        ["T1_FIRST", "T2_FIRST"]
    )

    sl_mask = outcomes.eq("SL_FIRST")

    print(f"\n{name}")
    print(f"  N               : {len(x)}")
    print(
        f"  Target hits     : "
        f"{int(target_mask.sum())} "
        f"({target_mask.mean() * 100:.2f}%)"
    )
    print(
        f"  SL first        : "
        f"{int(sl_mask.sum())} "
        f"({sl_mask.mean() * 100:.2f}%)"
    )
    print(
        f"  Avg R           : "
        f"{x['realized_r'].mean():+.4f}R"
    )
    print(
        f"  Total R         : "
        f"{x['realized_r'].sum():+.4f}R"
    )

    if "reclaim_delay_min" in x.columns:
        r = x["reclaim_delay_min"].dropna()
        if not r.empty:
            print(
                f"  Reclaim delay   : "
                f"{r.mean():.1f}m avg / "
                f"{r.median():.1f}m median"
            )

    if "post_reclaim_mae_r" in x.columns:
        print(
            f"  Post-reclaim MAE: "
            f"{x['post_reclaim_mae_r'].mean():+.4f}R"
        )
        print(
            f"  Post-reclaim MFE: "
            f"{x['post_reclaim_mfe_r'].mean():+.4f}R"
        )


def date_stability(df, hold_col):
    x = df[
        df["reclaim"]
        & df[hold_col].eq(True)
    ].copy()

    if x.empty:
        return

    x["month_block"] = pd.to_datetime(
        x["signal_time"]
    ).dt.strftime("%Y-%m")

    print(f"\n  Date stability — {hold_col}")

    for period, g in x.groupby("month_block"):
        target = g["outcome"].isin(
            ["T1_FIRST", "T2_FIRST"]
        )

        print(
            f"    {period}: "
            f"N={len(g)}, "
            f"target={target.mean()*100:.1f}%, "
            f"avgR={g['realized_r'].mean():+.3f}, "
            f"totalR={g['realized_r'].sum():+.3f}"
        )


def main():
    print("=" * 72)
    print("V13.1 RETEST → RECLAIM → HOLD PERSISTENCE VALIDATION")
    print("=" * 72)

    candidates = load_candidates()

    # For apples-to-apples comparison, use same 18-candidate
    # actionable research universe if available.
    #
    # Current V13.1 CSV should contain 60 rule-qualified trades.
    # We take the first 18 chronologically, matching prior raw audit.
    candidates = candidates.tail(18).copy()

    print(f"V13.1 candidates requested : {len(candidates)}")
    print(
        "Rule: BULLISH + TV>0 + "
        "BD 0.50–1.25 ATR + RelVol<=1.50x"
    )

    results = []

    for i, (_, row) in enumerate(candidates.iterrows(), 1):
        print(
            f"\n[{i:02d}/{len(candidates):02d}] "
            f"{row['symbol']} "
            f"{row['signal_time']}"
        )

        result = analyse_candidate(row)
        results.append(result)

        print(
            f"  status={result.get('status')} "
            f"retest={result.get('retest', False)} "
            f"reclaim={result.get('reclaim', False)} "
            f"outcome={result.get('outcome')}"
        )

        time.sleep(0.15)

    out = pd.DataFrame(results)

    out_path = (
        BASE_DIR
        / "v13_1_retest_reclaim_hold_persistence.csv"
    )

    out.to_csv(out_path, index=False)

    print("\n" + "=" * 72)
    print("RESULTS")
    print("=" * 72)

    matched = out[out["status"].eq("OK")].copy()

    print(f"Requested       : {len(out)}")
    print(f"Raw matched     : {len(matched)}")
    print(
        f"Raw missing     : "
        f"{(out['status'] == 'RAW_MISSING').sum()}"
    )

    if matched.empty:
        print("\nNo usable raw candles.")
        print(f"CSV saved: {out_path}")
        return

    outcomes = matched["outcome"].astype(str).str.upper()

    target = outcomes.isin(
        ["T1_FIRST", "T2_FIRST"]
    )

    sl = outcomes.eq("SL_FIRST")

    print(f"\nMatched baseline")
    print(f"  N       : {len(matched)}")
    print(
        f"  Target  : {int(target.sum())} "
        f"({target.mean()*100:.2f}%)"
    )
    print(
        f"  SL      : {int(sl.sum())} "
        f"({sl.mean()*100:.2f}%)"
    )
    print(
        f"  Avg R   : "
        f"{matched['realized_r'].mean():+.4f}R"
    )
    print(
        f"  Total R : "
        f"{matched['realized_r'].sum():+.4f}R"
    )

    # Structure buckets
    bucket_summary(
        matched,
        "NO RETEST",
        ~matched["retest"],
    )

    bucket_summary(
        matched,
        "RETEST",
        matched["retest"],
    )

    bucket_summary(
        matched,
        "RETEST → RECLAIM",
        matched["reclaim"],
    )

    for n in [1, 2, 3]:
        col = f"hold_{n}"

        bucket_summary(
            matched,
            f"RECLAIM → HOLD {n} CANDLE",
            matched["reclaim"]
            & matched[col].eq(True),
        )

        date_stability(
            matched,
            col,
        )

    # Direct persistence comparison
    print("\n" + "=" * 72)
    print("HOLD PERSISTENCE COMPARISON")
    print("=" * 72)

    rows = []

    for n in [1, 2, 3]:
        col = f"hold_{n}"

        x = matched[
            matched["reclaim"]
            & matched[col].eq(True)
        ].copy()

        if x.empty:
            continue

        target = x["outcome"].isin(
            ["T1_FIRST", "T2_FIRST"]
        )

        rows.append(
            {
                "rule": f"H{n}",
                "n": len(x),
                "target_pct": target.mean() * 100,
                "sl_pct": (
                    x["outcome"]
                    .eq("SL_FIRST")
                    .mean()
                    * 100
                ),
                "avg_r": x["realized_r"].mean(),
                "total_r": x["realized_r"].sum(),
                "reclaim_delay_mean_min":
                    x["reclaim_delay_min"].mean(),
                "post_reclaim_mae_r":
                    x["post_reclaim_mae_r"].mean(),
                "post_reclaim_mfe_r":
                    x["post_reclaim_mfe_r"].mean(),
            }
        )

    if rows:
        summary = pd.DataFrame(rows)

        print(
            summary.to_string(
                index=False,
                float_format=lambda v: f"{v:.4f}",
            )
        )

    print("\n" + "=" * 72)
    print("IMPORTANT")
    print("=" * 72)
    print(
        "This is a confirmation-study only. "
        "No delayed-entry strategy is being assumed."
    )
    print(
        "Do NOT change V13.1 engine rules from this experiment alone."
    )
    print(
        f"\nDetailed CSV saved:\n{out_path}"
    )


if __name__ == "__main__":
    main()

