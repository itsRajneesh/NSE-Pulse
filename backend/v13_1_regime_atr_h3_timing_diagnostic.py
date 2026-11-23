"""
V13.1 — September Holdout Diagnostic
Tests:
1) NIFTY market-regime alignment
2) Stock ATR volatility context
3) Early / Mid / Late H3 confirmation timing

IMPORTANT:
- Diagnostic only.
- v13_engine.py is NOT modified.
- Uses existing clean September H3 result CSV.
- All calculations are point-in-time.
"""

from pathlib import Path
import warnings
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

BASE = Path(__file__).resolve().parent
H3_FILE = BASE / "v13_1_delayed_entry_h3_results.csv"
OUTPUT = BASE / "v13_1_regime_atr_h3_timing_results.csv"
IST = "Asia/Kolkata"


def load_clean_h3():
    """
    Load ONLY the final clean September H3 accounting CSV.

    This intentionally does not depend on
    backtest_nifty500_v13_results(2).csv because that file may be empty
    in the local V13 backend even though it exists in the conversation
    artifacts.
    """
    if not H3_FILE.exists():
        raise FileNotFoundError(
            f"{H3_FILE.name} not found in: {BASE}"
        )

    h3 = pd.read_csv(H3_FILE)

    h3["signal_time"] = (
        pd.to_datetime(h3["signal_time"], errors="coerce", utc=True)
        .dt.tz_convert(IST).dt.tz_localize(None)
    )
    h3["symbol"] = h3["symbol"].astype(str).str.upper()

    # Exact September holdout.
    h3 = h3[
        (h3["signal_time"] >= pd.Timestamp("2026-09-01"))
        & (h3["signal_time"] < pd.Timestamp("2026-10-01"))
    ].copy()

    # Final accounting patch marks only actual tradeable H3 rows this way.
    if "accounting_status" in h3.columns:
        h3 = h3[h3["accounting_status"] == "TRADEABLE_H3"].copy()
    elif "h3_confirmed" in h3.columns:
        h3 = h3[h3["h3_confirmed"] == True].copy()
    else:
        raise RuntimeError(
            "H3 CSV has neither accounting_status nor h3_confirmed."
        )

    h3 = h3.drop_duplicates(["symbol", "signal_time"])

    required = [
        "symbol", "signal_time", "delayed_entry_time",
        "delayed_r", "outcome", "direction", "score",
        "ltp", "atr14"
    ]
    missing = [c for c in required if c not in h3.columns]
    if missing:
        raise RuntimeError(
            f"H3 CSV missing required columns: {missing}"
        )

    print(f"Clean September H3 rows: {len(h3)}")

    if len(h3) != 98:
        raise RuntimeError(
            f"Expected exactly 98 clean tradeable H3 rows, got {len(h3)}"
        )

    return h3.reset_index(drop=True)


NIFTY_CACHE = {}


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


def nifty_context(raw, signal_time):
    """
    Point-in-time NIFTY context.
    No candle after signal_time is used.
    """
    if raw.empty:
        return None

    x = raw[raw.index <= signal_time].copy()

    if len(x) < 20:
        return None

    close = pd.to_numeric(x["Close"], errors="coerce")
    high = pd.to_numeric(x["High"], errors="coerce")
    low = pd.to_numeric(x["Low"], errors="coerce")
    volume = pd.to_numeric(x["Volume"], errors="coerce").fillna(0)

    valid = close.notna() & high.notna() & low.notna()
    close = close[valid]
    high = high[valid]
    low = low[valid]
    volume = volume[valid]

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

    atr14 = tr.ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14,
    ).mean()

    if pd.isna(atr14.iloc[-1]) or atr14.iloc[-1] <= 0:
        return None

    ema20 = close.ewm(
        span=20,
        adjust=False,
        min_periods=20,
    ).mean().iloc[-1]

    typical = (high + low + close) / 3
    vol_sum = volume.cumsum()
    vwap = (typical * volume).cumsum() / vol_sum.replace(0, np.nan)
    vwap = vwap.iloc[-1]

    natr = float(atr14.iloc[-1])
    last = float(close.iloc[-1])

    # Last ~30 minutes = six 5-minute candles.
    tail = close.tail(6)
    move_30m = float(tail.iloc[-1] - tail.iloc[0]) if len(tail) >= 2 else 0.0
    move_30m_atr = move_30m / natr

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
        "nifty_ema20": float(ema20),
        "nifty_vwap": float(vwap),
        "nifty_atr14": natr,
        "nifty_30m_move_atr": move_30m_atr,
    }


def classify_atr(atr_pct):
    # Stock ATR as % of price, calculated from the existing point-in-time
    # V13 candidate snapshot.
    if not np.isfinite(atr_pct):
        return "UNKNOWN"
    if atr_pct < 0.50:
        return "LOW"
    if atr_pct < 1.00:
        return "NORMAL"
    return "HIGH"


def classify_timing(delay_min):
    if not np.isfinite(delay_min):
        return "UNKNOWN"
    if delay_min <= 30:
        return "EARLY"
    if delay_min <= 60:
        return "MID"
    return "LATE"


def add_context(df):
    rows = []

    for _, r in df.iterrows():
        signal_time = r["signal_time"]
        symbol = r["symbol"]
        direction = str(r["direction"]).upper()

        nifty = fetch_nifty_day(signal_time.date())
        ctx = nifty_context(nifty, signal_time)

        if ctx is None:
            continue

        ltp = float(r["ltp"])
        stock_atr = float(r["atr14"])

        atr_pct = (
            stock_atr / ltp * 100.0
            if ltp > 0 and stock_atr > 0
            else np.nan
        )

        atr_regime = classify_atr(atr_pct)

        nifty_regime = ctx["nifty_regime"]

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

        entry_time = pd.to_datetime(
            r["delayed_entry_time"],
            errors="coerce",
        )

        delay = (
            (entry_time - signal_time).total_seconds() / 60.0
            if pd.notna(entry_time)
            else np.nan
        )

        rows.append(
            {
                "symbol": symbol,
                "signal_time": signal_time,
                "direction": direction,
                "score": float(r["score"]),
                "delayed_r": float(r["delayed_r"]),
                "outcome": r["outcome"],
                "stock_atr": stock_atr,
                "atr_pct": atr_pct,
                "atr_regime": atr_regime,
                "nifty_regime": nifty_regime,
                "market_alignment": alignment,
                "nifty_atr14": ctx["nifty_atr14"],
                "nifty_30m_move_atr": ctx["nifty_30m_move_atr"],
                "h3_delay_min": delay,
                "h3_timing": classify_timing(delay),
            }
        )

    return pd.DataFrame(rows)


def stats(x):
    if len(x) == 0:
        return None

    r = pd.to_numeric(x["delayed_r"], errors="coerce").dropna()

    if len(r) == 0:
        return None

    wins = int((r > 0).sum())
    losses = int((r < 0).sum())

    gross_win = float(r[r > 0].sum())
    gross_loss = float(-r[r < 0].sum())

    pf = gross_win / gross_loss if gross_loss > 0 else np.inf

    equity = r.cumsum()
    dd = equity.cummax() - equity
    max_dd = float(dd.max()) if len(dd) else 0.0

    target = int(x["outcome"].astype(str).str.contains("T1|T2", regex=True).sum())
    sl = int(x["outcome"].astype(str).str.contains("SL", regex=True).sum())
    eod = int(x["outcome"].astype(str).str.contains("EOD", regex=True).sum())

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


def print_grouped(df, cols, title):
    print("\n" + "-" * 100)
    print(title)
    print("-" * 100)

    grouped = df.groupby(cols, dropna=False)

    for key, g in grouped:
        if not isinstance(key, tuple):
            key = (key,)

        label = " x ".join(str(v) for v in key)
        s = stats(g)

        if s is None:
            continue

        print(
            f"{label:38s} "
            f"N={s['N']:3d} "
            f"Win={s['Win%']:6.2f}% "
            f"Tgt={s['Target%']:6.2f}% "
            f"SL={s['SL%']:6.2f}% "
            f"AvgR={s['AvgR']:7.3f} "
            f"TotalR={s['TotalR']:8.3f} "
            f"PF={s['PF']:5.2f} "
            f"DD={s['MaxDD']:6.2f}"
        )


def main():
    base = load_clean_h3()

    print("\nFetching point-in-time NIFTY context...")
    result = add_context(base)

    if result.empty:
        raise RuntimeError("No rows received NIFTY context.")

    result.to_csv(OUTPUT, index=False)

    print("\n" + "=" * 100)
    print("V13.1 — NIFTY REGIME + ATR + H3 TIMING DIAGNOSTIC")
    print("=" * 100)
    print(f"Input clean H3 rows : {len(base)}")
    print(f"Diagnostic rows     : {len(result)}")
    print(f"Output              : {OUTPUT.name}")

    if len(result) != 98:
        print(
            f"\nWARNING: NIFTY context available for {len(result)}/98 rows. "
            "Rows without sufficient point-in-time NIFTY data were excluded."
        )

    print_grouped(result, ["market_alignment"], "1) NIFTY MARKET ALIGNMENT")
    print_grouped(result, ["nifty_regime", "direction"], "2) NIFTY REGIME x STOCK DIRECTION")
    print_grouped(result, ["atr_regime"], "3) STOCK ATR VOLATILITY CONTEXT")
    print_grouped(result, ["h3_timing"], "4) H3 CONFIRMATION TIMING")
    print_grouped(result, ["market_alignment", "h3_timing"], "5) MARKET ALIGNMENT x H3 TIMING")
    print_grouped(result, ["atr_regime", "h3_timing"], "6) ATR REGIME x H3 TIMING")
    print_grouped(result, ["nifty_regime", "atr_regime"], "7) NIFTY REGIME x ATR")
    print_grouped(
        result,
        ["market_alignment", "atr_regime", "h3_timing"],
        "8) FINAL 3-WAY MATRIX — ALIGNMENT x ATR x H3 TIMING",
    )

    print("\n" + "=" * 100)
    print("OVERALL DIAGNOSTIC")
    print("=" * 100)

    s = stats(result)
    print(
        f"N={s['N']} | Win={s['Win%']:.2f}% | "
        f"Target={s['Target%']:.2f}% | SL={s['SL%']:.2f}% | "
        f"AvgR={s['AvgR']:.3f} | TotalR={s['TotalR']:.3f} | "
        f"PF={s['PF']:.2f} | MaxDD={s['MaxDD']:.2f}R"
    )

    print("\nDONE.")
    print("Engine untouched: v13_engine.py")
    print("Diagnostic CSV:", OUTPUT)


if __name__ == "__main__":
    main()
