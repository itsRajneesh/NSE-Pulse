"""
V13.1 — Relative Weakness Stability + Exact H3 Timing Diagnostic

DO NOT MODIFY v13_engine.py.

Tests:
1) Exact Signal -> H3 confirmation duration using signal_to_h3_min
   already calculated by the clean H3 simulation.
2) H3 timing buckets:
      EARLY  <= 30 min
      MID    31-60 min
      LATE   61-90 min
      VERY_LATE > 90 min
3) September chronological sub-period stability:
      Sep 1-3
      Sep 4-7
      Sep 8-9
      Sep 10-11
4) Main hypothesis:
      BULL NIFTY x BEARISH STOCK
5) Secondary:
      NIFTY regime x direction x ATR
"""

from pathlib import Path
import warnings
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent
H3_FILE = BASE / "v13_1_delayed_entry_h3_results.csv"
OUTPUT = BASE / "v13_1_relative_weakness_stability_results.csv"
IST = "Asia/Kolkata"

NIFTY_CACHE = {}


def load_clean_h3():
    if not H3_FILE.exists():
        raise FileNotFoundError(
            f"Missing: {H3_FILE}"
        )

    df = pd.read_csv(H3_FILE)

    df["signal_time"] = (
        pd.to_datetime(df["signal_time"], errors="coerce", utc=True)
        .dt.tz_convert(IST)
        .dt.tz_localize(None)
    )

    df["h3_end_time"] = (
        pd.to_datetime(df["h3_end_time"], errors="coerce", utc=True)
        .dt.tz_convert(IST)
        .dt.tz_localize(None)
    )

    df["delayed_entry_time"] = (
        pd.to_datetime(df["delayed_entry_time"], errors="coerce", utc=True)
        .dt.tz_convert(IST)
        .dt.tz_localize(None)
    )

    df["symbol"] = df["symbol"].astype(str).str.upper()
    df["direction"] = df["direction"].astype(str).str.upper()

    df = df[
        (df["signal_time"] >= pd.Timestamp("2026-09-01"))
        & (df["signal_time"] < pd.Timestamp("2026-10-01"))
    ].copy()

    if "accounting_status" in df.columns:
        df = df[df["accounting_status"] == "TRADEABLE_H3"].copy()
    else:
        df = df[df["h3_confirmed"] == True].copy()

    df = df.drop_duplicates(["symbol", "signal_time"]).reset_index(drop=True)

    required = [
        "symbol", "signal_time", "h3_end_time",
        "delayed_entry_time", "delayed_r", "outcome",
        "direction", "score", "ltp", "atr14",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(f"Missing required columns: {missing}")

    # Use the exact H3 timestamp difference from the clean simulation.
    df["signal_to_h3_min_exact"] = (
        df["h3_end_time"] - df["signal_time"]
    ).dt.total_seconds() / 60.0

    # Sanity check against the existing simulation field if available.
    if "signal_to_h3_min" in df.columns:
        stored = pd.to_numeric(df["signal_to_h3_min"], errors="coerce")
        mismatch = (
            stored.notna()
            & df["signal_to_h3_min_exact"].notna()
            & ((stored - df["signal_to_h3_min_exact"]).abs() > 0.01)
        ).sum()
        if mismatch:
            raise RuntimeError(
                f"H3 timing mismatch found in {mismatch} rows. "
                "Do not proceed until accounting is consistent."
            )

    print(f"Clean September tradeable H3 rows: {len(df)}")

    if len(df) != 98:
        raise RuntimeError(
            f"Expected exactly 98 clean tradeable H3 rows, got {len(df)}"
        )

    return df


def fetch_nifty_day(date):
    key = str(pd.Timestamp(date).date())

    if key in NIFTY_CACHE:
        return NIFTY_CACHE[key].copy()

    start = pd.Timestamp(date).normalize()
    end = start + pd.Timedelta(days=1)

    x = yf.download(
        "^NSEI",
        start=start.strftime("%Y-%m-%d"),
        end=(end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        interval="5m",
        auto_adjust=False,
        progress=False,
        prepost=False,
    )

    if x.empty:
        NIFTY_CACHE[key] = pd.DataFrame()
        return pd.DataFrame()

    if isinstance(x.columns, pd.MultiIndex):
        x.columns = x.columns.get_level_values(0)

    x.index = pd.to_datetime(x.index)

    if getattr(x.index, "tz", None) is not None:
        x.index = x.index.tz_convert(IST).tz_localize(None)

    NIFTY_CACHE[key] = x.copy()
    return x


def get_nifty_regime(raw, signal_time):
    """
    Point-in-time only:
    NIFTY candles after signal_time are never used.
    """
    if raw.empty:
        return None

    x = raw[raw.index <= signal_time].copy()

    if len(x) < 20:
        return None

    close = pd.to_numeric(x["Close"], errors="coerce")
    high = pd.to_numeric(x["High"], errors="coerce")
    low = pd.to_numeric(x["Low"], errors="coerce")

    valid = close.notna() & high.notna() & low.notna()
    close = close[valid]
    high = high[valid]
    low = low[valid]

    if len(close) < 20:
        return None

    prev_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14,
    ).mean()

    if pd.isna(atr.iloc[-1]) or atr.iloc[-1] <= 0:
        return None

    ema20 = close.ewm(
        span=20,
        adjust=False,
        min_periods=20,
    ).mean().iloc[-1]

    # Session VWAP, point-in-time.
    volume = pd.to_numeric(x["Volume"], errors="coerce").fillna(0)
    typical = (high + low + close) / 3.0
    cum_volume = volume.cumsum()
    vwap_series = (
        (typical * volume).cumsum()
        / cum_volume.replace(0, np.nan)
    )
    vwap = vwap_series.iloc[-1]

    last = float(close.iloc[-1])
    atr_now = float(atr.iloc[-1])

    tail = close.tail(6)
    move_30m = (
        float(tail.iloc[-1] - tail.iloc[0])
        if len(tail) >= 2
        else 0.0
    )
    move_30m_atr = move_30m / atr_now

    bull_votes = (
        int(last > float(ema20))
        + int(last > float(vwap))
        + int(move_30m_atr > 0)
    )

    bear_votes = (
        int(last < float(ema20))
        + int(last < float(vwap))
        + int(move_30m_atr < 0)
    )

    if bull_votes >= 2:
        regime = "BULL"
    elif bear_votes >= 2:
        regime = "BEAR"
    else:
        regime = "NEUTRAL"

    return {
        "nifty_regime": regime,
        "nifty_atr14": atr_now,
        "nifty_30m_move_atr": move_30m_atr,
    }


def atr_bucket(atr_pct):
    if not np.isfinite(atr_pct):
        return "UNKNOWN"
    if atr_pct < 0.50:
        return "LOW"
    if atr_pct < 1.00:
        return "NORMAL"
    return "HIGH"


def timing_bucket(minutes):
    if not np.isfinite(minutes):
        return "UNKNOWN"
    if minutes <= 30:
        return "EARLY"
    if minutes <= 60:
        return "MID"
    if minutes <= 90:
        return "LATE"
    return "VERY_LATE"


def add_context(df):
    rows = []

    for _, r in df.iterrows():
        sig = r["signal_time"]

        raw = fetch_nifty_day(sig.date())
        ctx = get_nifty_regime(raw, sig)

        if ctx is None:
            continue

        ltp = float(r["ltp"])
        atr = float(r["atr14"])

        atr_pct = (
            atr / ltp * 100.0
            if ltp > 0 and atr > 0
            else np.nan
        )

        nifty_regime = ctx["nifty_regime"]
        direction = r["direction"]

        if (
            (direction == "BULLISH" and nifty_regime == "BULL")
            or
            (direction == "BEARISH" and nifty_regime == "BEAR")
        ):
            alignment = "ALIGNED"
        elif (
            (direction == "BULLISH" and nifty_regime == "BEAR")
            or
            (direction == "BEARISH" and nifty_regime == "BULL")
        ):
            alignment = "OPPOSED"
        else:
            alignment = "NEUTRAL"

        h3_minutes = float(r["signal_to_h3_min_exact"])

        rows.append(
            {
                "symbol": r["symbol"],
                "signal_time": sig,
                "direction": direction,
                "score": float(r["score"]),
                "delayed_r": float(r["delayed_r"]),
                "outcome": r["outcome"],
                "atr_pct": atr_pct,
                "atr_regime": atr_bucket(atr_pct),
                "nifty_regime": nifty_regime,
                "market_alignment": alignment,
                "nifty_atr14": ctx["nifty_atr14"],
                "nifty_30m_move_atr": ctx["nifty_30m_move_atr"],
                "signal_to_h3_min": h3_minutes,
                "h3_timing": timing_bucket(h3_minutes),
            }
        )

    return pd.DataFrame(rows)


def calc_stats(g):
    if g.empty:
        return None

    r = pd.to_numeric(g["delayed_r"], errors="coerce").dropna()

    if r.empty:
        return None

    wins = int((r > 0).sum())
    target = int(
        g["outcome"].astype(str).str.contains(
            "T1|T2", regex=True
        ).sum()
    )
    sl = int(
        g["outcome"].astype(str).str.contains(
            "SL", regex=True
        ).sum()
    )
    eod = int(
        g["outcome"].astype(str).str.contains(
            "EOD", regex=True
        ).sum()
    )

    gross_win = float(r[r > 0].sum())
    gross_loss = float(-r[r < 0].sum())
    pf = gross_win / gross_loss if gross_loss > 0 else np.inf

    equity = r.cumsum()
    dd = equity.cummax() - equity
    max_dd = float(dd.max()) if len(dd) else 0.0

    return {
        "N": len(r),
        "Win%": wins / len(r) * 100,
        "Target%": target / len(r) * 100,
        "SL%": sl / len(r) * 100,
        "EOD%": eod / len(r) * 100,
        "AvgR": float(r.mean()),
        "TotalR": float(r.sum()),
        "PF": pf,
        "MaxDD": max_dd,
    }


def print_group(g, label):
    s = calc_stats(g)

    if s is None:
        print(f"{label:45s} N=0")
        return

    pf = "inf" if np.isinf(s["PF"]) else f"{s['PF']:.2f}"

    print(
        f"{label:45s} "
        f"N={s['N']:3d} "
        f"Win={s['Win%']:6.2f}% "
        f"Tgt={s['Target%']:6.2f}% "
        f"SL={s['SL%']:6.2f}% "
        f"AvgR={s['AvgR']:7.3f} "
        f"TotalR={s['TotalR']:8.3f} "
        f"PF={pf:>5s} "
        f"DD={s['MaxDD']:6.2f}"
    )


def chronological_period(ts):
    d = ts.date()

    if pd.Timestamp("2026-09-01").date() <= d <= pd.Timestamp("2026-09-03").date():
        return "P1 Sep1-3"

    if pd.Timestamp("2026-09-04").date() <= d <= pd.Timestamp("2026-09-07").date():
        return "P2 Sep4-7"

    if pd.Timestamp("2026-09-08").date() <= d <= pd.Timestamp("2026-09-09").date():
        return "P3 Sep8-9"

    if pd.Timestamp("2026-09-10").date() <= d <= pd.Timestamp("2026-09-11").date():
        return "P4 Sep10-11"

    return "OUT"


def main():
    df = load_clean_h3()

    print("\nFetching point-in-time NIFTY regime...")
    result = add_context(df)

    if result.empty:
        raise RuntimeError("No rows received NIFTY context.")

    result["period"] = result["signal_time"].apply(chronological_period)

    if len(result) != 98:
        raise RuntimeError(
            f"Expected 98 diagnostic rows, got {len(result)}"
        )

    result.to_csv(OUTPUT, index=False)

    print("\n" + "=" * 110)
    print("V13.1 — RELATIVE WEAKNESS STABILITY + EXACT H3 TIMING")
    print("=" * 110)

    print("\nOVERALL CLEAN H3 BASELINE")
    print_group(result, "All 98 clean H3")

    print("\n" + "-" * 110)
    print("A) EXACT SIGNAL -> H3 CONFIRMATION TIMING")
    print("-" * 110)

    print(
        f"Mean Signal -> H3 : "
        f"{result['signal_to_h3_min'].mean():.1f} min"
    )
    print(
        f"Median Signal -> H3 : "
        f"{result['signal_to_h3_min'].median():.1f} min"
    )
    print(
        f"Min / Max : "
        f"{result['signal_to_h3_min'].min():.1f} / "
        f"{result['signal_to_h3_min'].max():.1f} min"
    )

    for k in ["EARLY", "MID", "LATE", "VERY_LATE"]:
        print_group(
            result[result["h3_timing"] == k],
            k,
        )

    print("\n" + "-" * 110)
    print("B) MAIN HYPOTHESIS — BULL NIFTY x BEARISH STOCK")
    print("-" * 110)

    rw = result[
        (result["nifty_regime"] == "BULL")
        & (result["direction"] == "BEARISH")
    ].copy()

    print_group(rw, "ALL — BULL NIFTY x BEARISH STOCK")

    print("\nChronological stability:")
    for p in [
        "P1 Sep1-3",
        "P2 Sep4-7",
        "P3 Sep8-9",
        "P4 Sep10-11",
    ]:
        print_group(
            rw[rw["period"] == p],
            p,
        )

    print("\n" + "-" * 110)
    print("C) SAME HYPOTHESIS — EACH PERIOD x H3 TIMING")
    print("-" * 110)

    for p in [
        "P1 Sep1-3",
        "P2 Sep4-7",
        "P3 Sep8-9",
        "P4 Sep10-11",
    ]:
        for t in ["EARLY", "MID", "LATE", "VERY_LATE"]:
            g = rw[
                (rw["period"] == p)
                & (rw["h3_timing"] == t)
            ]
            if not g.empty:
                print_group(g, f"{p} x {t}")

    print("\n" + "-" * 110)
    print("D) NIFTY REGIME x STOCK DIRECTION")
    print("-" * 110)

    for key, g in result.groupby(
        ["nifty_regime", "direction"],
        dropna=False,
    ):
        print_group(g, f"{key[0]} x {key[1]}")

    print("\n" + "-" * 110)
    print("E) REGIME x DIRECTION x ATR")
    print("-" * 110)

    for key, g in result.groupby(
        ["nifty_regime", "direction", "atr_regime"],
        dropna=False,
    ):
        print_group(
            g,
            f"{key[0]} x {key[1]} x ATR-{key[2]}",
        )

    print("\n" + "-" * 110)
    print("F) MAIN HYPOTHESIS x ATR")
    print("-" * 110)

    for atr in ["LOW", "NORMAL", "HIGH"]:
        print_group(
            rw[rw["atr_regime"] == atr],
            f"BULL NIFTY x BEARISH STOCK x ATR-{atr}",
        )

    print("\n" + "=" * 110)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 110)
    print(f"Rows analyzed : {len(result)}")
    print(f"Output CSV    : {OUTPUT}")
    print("v13_engine.py : UNTOUCHED")


if __name__ == "__main__":
    main()