from __future__ import annotations

from typing import Any
import pandas as pd
import numpy as np


def _clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()

    if isinstance(out.columns, pd.MultiIndex):
        if out.columns.nlevels == 2:
            out.columns = out.columns.get_level_values(-1)

    out.columns = [str(c).strip().title() for c in out.columns]

    required = ["Open", "High", "Low", "Close", "Volume"]
    if not set(required).issubset(out.columns):
        return pd.DataFrame()

    out = out.dropna(subset=["Open", "High", "Low", "Close"]).copy()

    index = pd.DatetimeIndex(out.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    out.index = index

    return out.sort_index()


def build_nifty_context(
    raw: pd.DataFrame,
    signal_time: Any,
) -> dict[str, Any]:
    """Build point-in-time NIFTY context without using post-signal bars."""

    x = _clean_ohlcv(raw)
    if x.empty:
        return {}

    ts = pd.Timestamp(signal_time)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)

    x = x[x.index <= ts].copy()

    if len(x) < 20:
        return {}

    close = x["Close"].astype(float)
    high = x["High"].astype(float)
    low = x["Low"].astype(float)
    open_ = x["Open"].astype(float)

    last_close = float(close.iloc[-1])

    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr14 = tr.rolling(14).mean()
    atr_value = float(atr14.iloc[-1]) if pd.notna(atr14.iloc[-1]) else np.nan

    atr_pct = (
        atr_value / last_close * 100.0
        if np.isfinite(atr_value) and last_close != 0
        else np.nan
    )

    slope5 = (
        ((last_close / float(close.iloc[-6])) - 1.0) * 100.0 / 5.0
        if len(close) >= 6 and float(close.iloc[-6]) != 0
        else np.nan
    )

    slope12 = (
        ((last_close / float(close.iloc[-13])) - 1.0) * 100.0 / 12.0
        if len(close) >= 13 and float(close.iloc[-13]) != 0
        else np.nan
    )

    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])

    # Intraday Session VWAP (with Typical Price Session Mean fallback when ^NSEI spot Volume == 0)
    norm_dates = x.index.normalize()
    latest_date = norm_dates[-1]
    latest_sess = x[norm_dates == latest_date]
    tp_series = (
        latest_sess["High"].astype(float)
        + latest_sess["Low"].astype(float)
        + latest_sess["Close"].astype(float)
    ) / 3.0
    if "Volume" in latest_sess.columns:
        vol_series = latest_sess["Volume"].astype(float).fillna(0.0)
        tot_vol = float(vol_series.sum())
    else:
        vol_series = pd.Series(0.0, index=latest_sess.index)
        tot_vol = 0.0

    if tot_vol > 0:
        nifty_vwap = float((tp_series * vol_series).sum() / tot_vol)
    else:
        nifty_vwap = float(tp_series.mean()) if not tp_series.empty else last_close

    prev_dates = [d for d in norm_dates.unique() if d < latest_date]
    if prev_dates:
        prev_sess = x[norm_dates == prev_dates[-1]]
        prev_close = float(prev_sess["Close"].iloc[-1]) if not prev_sess.empty else float(latest_sess["Open"].iloc[0])
    else:
        prev_close = float(latest_sess["Open"].iloc[0]) if not latest_sess.empty else last_close

    extension_atr = (
        (last_close - float(ema20)) / atr_value
        if np.isfinite(atr_value) and atr_value != 0
        else np.nan
    )

    current_bar_range_pct = (
        (float(high.iloc[-1]) - float(low.iloc[-1]))
        / float(open_.iloc[-1])
        * 100.0
        if float(open_.iloc[-1]) != 0
        else np.nan
    )

    # Quantitative Deadband Buffer + Structural Alignment (EMA20 & Session VWAP/TWAP):
    # Prevents 3:15 PM MIS short-covering dead-cat bounces below 20-EMA/VWAP from flipping regime to BULLISH.
    SLOPE_DEADBAND = 0.035  # % per 15m bar
    above_structure = (last_close >= ema20) and (last_close >= nifty_vwap)
    below_structure = (last_close <= ema20) and (last_close <= nifty_vwap)

    if slope5 > SLOPE_DEADBAND:
        if above_structure:
            direction = "BULLISH"
        elif below_structure and last_close < prev_close and np.isfinite(extension_atr) and extension_atr <= -0.50:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"
    elif slope5 < -SLOPE_DEADBAND:
        if below_structure:
            direction = "BEARISH"
        elif above_structure and last_close > prev_close and np.isfinite(extension_atr) and extension_atr >= 0.50:
            direction = "BULLISH"
        else:
            direction = "NEUTRAL"
    else:
        if pd.notna(slope12) and slope12 < -SLOPE_DEADBAND and below_structure and last_close < prev_close:
            direction = "BEARISH"
        elif pd.notna(slope12) and slope12 > SLOPE_DEADBAND and above_structure and last_close > prev_close:
            direction = "BULLISH"
        else:
            direction = "NEUTRAL"

    return {
        "nifty_direction": direction,
        "nifty_close": last_close,
        "nifty_vwap": round(nifty_vwap, 2),
        "nifty_ema20": round(ema20, 2),
        "nifty_atr_pct": atr_pct,
        "nifty_bar_range_pct": current_bar_range_pct,
        "nifty_range_expansion": None,
        "nifty_slope5": slope5,
        "nifty_slope12": slope12,
        "nifty_extension_atr": extension_atr,
        "signal_time": x.index[-1].isoformat(),
        "bars_used": int(len(x)),
    }
