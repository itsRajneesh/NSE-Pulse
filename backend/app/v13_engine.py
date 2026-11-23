from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
import math

import numpy as np
import pandas as pd

IST_TZ = timezone(timedelta(hours=5, minutes=30))


# ============================================================
# V13 ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â INDEPENDENT DISCOVERY ENGINE
#
# IMPORTANT:
# - V13 does NOT depend on V5/V12 qualification gates.
# - Bullish and Bearish are evaluated independently.
# - Score is a QUALITY SCORE, never a probability.
# - This module only discovers/ranks setups. Backtesting is
#   intentionally kept outside this file.
# ============================================================

OPENING_RANGE_START = "09:15"
OPENING_RANGE_END = "09:30"

MIN_BARS_FOR_DISCOVERY = 20

# Classification thresholds are deliberately kept separate
# from the actual score calculation so they can be backtested.
HIGH_CONFIDENCE_SCORE = 85.0
STRONG_SETUP_SCORE = 80.0
WATCH_SCORE = 72.0


@dataclass
class V13Candidate:
    symbol: str
    name: str
    sector: str

    signal_type: str
    setup_type: str
    action: str
    grade: str

    score: float
    ltp: float

    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    risk_amount: float

    risk_reward_t1: str
    risk_reward_t2: str

    ema20: float
    rsi14: float
    rel_vol: float
    vwap: float
    atr14: float
    true_velocity: float

    opening_range_high: float
    opening_range_low: float
    previous_day_high: float
    previous_day_low: float

    breakout_distance_atr: float
    breakout_candle_range: float
    reasons: list[str]
    penalties: list[str]
    score_breakdown: dict[str, float]

    t1_progress_pct: float = 0.0
    execution_status: str = "FRESH_ENTRY"
    signal_time: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _DirectionEvaluation:
    direction: str
    score: float
    setup_type: str
    entry: float
    stop: float
    target_1: float
    target_2: float
    risk: float
    rr1: float
    rr2: float
    reasons: list[str]
    penalties: list[str]
    breakout_distance_atr: float
    breakout_candle_range: float
    true_velocity: float
    ema20: float
    rsi14: float
    rel_vol: float
    vwap: float
    atr14: float
    score_breakdown: dict[str, float]
    t1_progress_pct: float = 0.0
    execution_status: str = "FRESH_ENTRY"


# ============================================================
# BASIC HELPERS
# ============================================================

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        value = float(value)
        if not math.isfinite(value):
            return default
        return value
    except (TypeError, ValueError):
        return default


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def normalize_nse_tick(price: float, direction: str = "BULLISH", is_sl: bool = False) -> float:
    """
    Normalizes price strictly to NSE 5-paisa (Rs 0.05) tick size.
    Uses integer paise arithmetic to guarantee zero IEEE-754 floating point drift
    (guarantees exact 1420.30 instead of 1420.3000000000002).

    Rounding Policy:
    - Bullish: Floored to 5 paise (conservative wider SL buffer, realistic target clearance)
    - Bearish: Ceiled to 5 paise (conservative wider SL buffer, realistic target clearance)
    """
    if price <= 0.0:
        return 0.0

    paise = int(round(price * 100.0))
    direction_upper = str(direction).upper()

    if direction_upper == "BULLISH":
        norm_paise = (paise // 5) * 5
    else:
        norm_paise = ((paise + 4) // 5) * 5

    return round(norm_paise / 100.0, 2)


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    rename_map = {}
    for column in out.columns:
        text = str(column).strip().lower()
        if text == "open":
            rename_map[column] = "Open"
        elif text == "high":
            rename_map[column] = "High"
        elif text == "low":
            rename_map[column] = "Low"
        elif text == "close":
            rename_map[column] = "Close"
        elif text == "volume":
            rename_map[column] = "Volume"

    out = out.rename(columns=rename_map)

    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(out.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns: {sorted(missing)}")

    out = out.copy()
    for column in required:
        out[column] = pd.to_numeric(out[column], errors="coerce")

    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    out = out.sort_index()

    return out


def _session_dates(df: pd.DataFrame) -> list[pd.Timestamp]:
    index = pd.DatetimeIndex(df.index)

    if index.tz is not None:
        dates = index.tz_localize(None).normalize()
    else:
        dates = index.normalize()

    return list(pd.Index(dates).unique())


def _latest_session(df: pd.DataFrame) -> pd.DataFrame:
    dates = _session_dates(df)
    if not dates:
        return df.iloc[0:0].copy()

    latest = dates[-1]

    index = pd.DatetimeIndex(df.index)
    if index.tz is not None:
        normalised = index.tz_localize(None).normalize()
    else:
        normalised = index.normalize()

    return df.loc[normalised == latest].copy()


def _previous_session(df: pd.DataFrame) -> pd.DataFrame:
    dates = _session_dates(df)
    if len(dates) < 2:
        return df.iloc[0:0].copy()

    previous = dates[-2]

    index = pd.DatetimeIndex(df.index)
    if index.tz is not None:
        normalised = index.tz_localize(None).normalize()
    else:
        normalised = index.normalize()

    return df.loc[normalised == previous].copy()


def _opening_range(session: pd.DataFrame) -> tuple[Optional[float], Optional[float]]:
    if session.empty:
        return None, None

    times = pd.DatetimeIndex(session.index).time
    start = pd.Timestamp(OPENING_RANGE_START).time()
    end = pd.Timestamp(OPENING_RANGE_END).time()

    opening = session.loc[(times >= start) & (times < end)]

    if opening.empty:
        return None, None

    return (
        _safe_float(opening["High"].max()),
        _safe_float(opening["Low"].min()),
    )


def _previous_day_levels(df: pd.DataFrame) -> tuple[Optional[float], Optional[float], Optional[float]]:
    previous = _previous_session(df)

    if previous.empty:
        return None, None, None

    return (
        _safe_float(previous["High"].max()),
        _safe_float(previous["Low"].min()),
        _safe_float(previous["Close"].iloc[-1]),
    )


# ============================================================
# INDICATORS
# ============================================================

def _ema(series: pd.Series, period: int = 20) -> pd.Series:
    return series.ewm(
        span=period,
        adjust=False,
        min_periods=period,
    ).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()

    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100.0 - (100.0 / (1.0 + rs))

    # A completely one-sided move can produce NaN because avg_loss
    # is zero. Treat that as extreme momentum rather than failure.
    result = result.where(~result.isna(), np.where(avg_gain > 0, 100.0, 50.0))

    return result


def _calculate_wilder_atr_series(true_range: pd.Series, period: int = 14) -> pd.Series:
    """
    Exact implementation of J. Welles Wilder's original ATR specification (1978).
    Seeds the recursive filter with the 14-period SMA to achieve immediate convergence.
    """
    n = len(true_range)
    if n < period:
        return true_range.rolling(window=max(1, n), min_periods=1).mean()

    atr = pd.Series(index=true_range.index, dtype=float)
    # 1. Initial seed is the arithmetic mean of the first 14 True Ranges
    initial_sma = float(true_range.iloc[:period].mean())
    atr.iloc[period - 1] = initial_sma

    # 2. Subsequent values use Wilder's recursive smoothing
    prev_atr = initial_sma
    for i in range(period, n):
        current_tr = float(true_range.iloc[i])
        curr_atr = ((prev_atr * (period - 1)) + current_tr) / period
        atr.iloc[i] = curr_atr
        prev_atr = curr_atr

    # Backfill warm-up period for non-null output
    atr.iloc[:period - 1] = true_range.iloc[:period - 1].expanding().mean()
    return atr


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    previous_close = df["Close"].shift(1)

    true_range = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - previous_close).abs(),
            (df["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return _calculate_wilder_atr_series(true_range, period=period)


def _daily_atr14(df: pd.DataFrame, period: int = 14) -> float:
    """
    Calculate 14-period Average True Range (ATR) from completed daily sessions.
    Reconstructed from historical 15m bars to avoid extra network requests.
    Uses Wilder's textbook SMA-14 initial seed for immediate convergence.
    """
    try:
        dates = _session_dates(df)
        if len(dates) < 3:
            return 0.0

        daily_rows: list[dict[str, float]] = []
        index = pd.DatetimeIndex(df.index)
        normalised = index.tz_localize(None).normalize() if index.tz is not None else index.normalize()

        # Include completed sessions (exclude latest if forming)
        completed_dates = dates[:-1] if len(dates) > 1 else dates
        for date in completed_dates:
            session = df.loc[normalised == date].sort_index()
            if session.empty:
                continue
            try:
                daily_rows.append(
                    {
                        "High": float(session["High"].max()),
                        "Low": float(session["Low"].min()),
                        "Close": float(session["Close"].iloc[-1]),
                    }
                )
            except (TypeError, ValueError, IndexError):
                continue

        if len(daily_rows) < 2:
            return 0.0

        daily = pd.DataFrame(daily_rows)
        previous_close = daily["Close"].shift(1)
        true_range = pd.concat(
            [
                daily["High"] - daily["Low"],
                (daily["High"] - previous_close).abs(),
                (daily["Low"] - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        daily_atr = _calculate_wilder_atr_series(true_range, period=period)
        return _safe_float(daily_atr.iloc[-1])
    except Exception:
        return 0.0

def _true_velocity(
    df: pd.DataFrame,
) -> Optional[float]:
    """
    Calculate 5-session directional velocity from completed sessions only.

    Velocity = 5-session price change % / 5-session ATR %.

    The current/incomplete session is excluded deliberately so an intraday
    signal never gets to use today's unfinished daily close. Daily OHLC is
    reconstructed from the available 15m bars, which keeps this helper
    independent of a second Yahoo request.
    """
    dates = _session_dates(df)
    if len(dates) < 7:
        return None

    daily_rows: list[dict[str, float]] = []

    index = pd.DatetimeIndex(df.index)
    if index.tz is not None:
        normalised = index.tz_localize(None).normalize()
    else:
        normalised = index.normalize()

    # Exclude the latest session because it may still be forming.
    completed_dates = dates[:-1]

    for date in completed_dates:
        session = df.loc[normalised == date].sort_index()
        if session.empty:
            continue

        try:
            daily_rows.append(
                {
                    "Open": float(session["Open"].iloc[0]),
                    "High": float(session["High"].max()),
                    "Low": float(session["Low"].min()),
                    "Close": float(session["Close"].iloc[-1]),
                }
            )
        except (TypeError, ValueError, IndexError):
            continue

    if len(daily_rows) < 6:
        return None

    daily = pd.DataFrame(daily_rows)
    previous_close = daily["Close"].shift(1)

    true_range = pd.concat(
        [
            daily["High"] - daily["Low"],
            (daily["High"] - previous_close).abs(),
            (daily["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # Five-session Wilder-style ATR.
    atr5 = true_range.ewm(
        alpha=1 / 5,
        adjust=False,
        min_periods=5,
    ).mean()

    current_close = _safe_float(daily["Close"].iloc[-1])
    anchor_close = _safe_float(daily["Close"].iloc[-6])
    current_atr5 = _safe_float(atr5.iloc[-1])

    if current_close <= 0 or anchor_close <= 0 or current_atr5 <= 0:
        return None

    price_change_pct = (current_close / anchor_close - 1.0) * 100.0
    atr_pct = (current_atr5 / current_close) * 100.0

    if atr_pct <= 0:
        return None

    return price_change_pct / atr_pct


def _session_vwap(session: pd.DataFrame) -> pd.Series:
    if session.empty:
        return pd.Series(dtype=float)

    typical_price = (
        session["High"] + session["Low"] + session["Close"]
    ) / 3.0

    volume = session["Volume"].replace(0, np.nan)

    cumulative_pv = (typical_price * volume).cumsum()
    cumulative_volume = volume.cumsum()

    return cumulative_pv / cumulative_volume


def _relative_volume(
    df: pd.DataFrame,
    session: pd.DataFrame,
    lookback_sessions: int = 20,
) -> float:
    """
    Time-of-Day aware Relative Volume.
    Slices historical bars strictly by wall-clock time (<= cutoff_time).
    Retains zero-volume mornings to prevent survivorship bias and applies
    Participation-Weighted Median if >50% of historical mornings were zero.
    Uniform 50.0x hard ceiling applied.
    """

    if session.empty or "Volume" not in df.columns:
        return 0.0

    dates = _session_dates(df)
    if len(dates) < 2:
        return 0.0

    current_date = dates[-1]

    index = pd.DatetimeIndex(df.index)
    if index.tz is not None:
        normalised = index.tz_localize(None).normalize()
    else:
        normalised = index.normalize()

    historical_dates = [
        date for date in dates[:-1]
        if date < current_date
    ][-lookback_sessions:]

    if not historical_dates:
        return 0.0

    current_cumulative = float(
        session["Volume"].fillna(0).cumsum().iloc[-1]
    )
    if current_cumulative <= 0:
        return 0.0

    cutoff_time = session.index[-1].time()
    historical_values: list[float] = []

    for date in historical_dates:
        historical = df.loc[normalised == date]
        if historical.empty:
            continue

        historical = historical.sort_index()
        usable = historical.loc[historical.index.time <= cutoff_time]

        # Retain zero-trade mornings as 0.0 (prevents survivorship bias)
        if usable.empty:
            historical_values.append(0.0)
        else:
            historical_values.append(float(usable["Volume"].fillna(0).sum()))

    if not historical_values:
        return 0.0

    raw_median = float(np.median(historical_values))

    if raw_median > 0:
        baseline = raw_median
    else:
        # Participation-Weighted Median Fallback (resolves survivorship bias without freak spike skew)
        non_zero = [v for v in historical_values if v > 0]
        if non_zero:
            participation_ratio = len(non_zero) / len(historical_values)
            baseline = float(np.median(non_zero)) * participation_ratio
        else:
            # 100% dormant historical mornings: use nominal floor
            baseline = 100.0

    baseline = max(baseline, 1.0)
    raw_rel_vol = current_cumulative / baseline
    return round(min(raw_rel_vol, 50.0), 2)

# ============================================================
# MARKET / SECTOR CONTEXT
# ============================================================

def _context_direction(context: Optional[Any], field: str) -> str:
    if context is None:
        return "NEUTRAL"

    if isinstance(context, dict):
        val = context.get(field, "NEUTRAL")
    else:
        val = getattr(context, field, "NEUTRAL")
    return str(val if val is not None else "NEUTRAL").upper()


def _context_alignment(
    direction: str,
    context: Optional[Any],
    current_score: float = 0.0,
) -> tuple[float, float, list[str], list[str]]:
    """
    Returns (nifty_score, sector_score, reasons, penalties).

    Institutional Gating Architecture:
    - NIFTY Alignment: +5.0 (Aligned), -2.5 (Opposing), 0.0 (Neutral)
    - Sector Alignment:
      * Self-Sufficiency Gate: Sector +5.0 tailwind bonus is strictly unlocked ONLY if
        the stock's independent score is already >= 72.0 (Watchlist threshold).
        If current_score < 72.0, sector bonus is locked to 0.0 to prevent weak
        stocks (e.g. score 68) from piggybacking into the watchlist.
      * Asymmetric Headwind Friction: If the sector is opposing the trade direction,
        a -2.5 friction penalty is applied (not -5.0) to filter noisy marginal setups
        without killing genuine standalone winners.
    """
    reasons: list[str] = []
    penalties: list[str] = []

    if context is None:
        return 0.0, 0.0, reasons, penalties

    nifty = _context_direction(context, "nifty_direction")
    sector = _context_direction(context, "sector_direction")

    nifty_score = 0.0
    sector_score = 0.0

    if direction == "BULLISH":
        if nifty == "BULLISH":
            nifty_score = 5.0
            reasons.append("NIFTY aligned bullish")
        elif nifty == "BEARISH":
            nifty_score = -2.5
            penalties.append("NIFTY against bullish setup")

        if sector == "BULLISH":
            if current_score >= 60.0:
                sector_score = 5.0
                reasons.append("Sector aligned bullish")
            else:
                sector_score = 0.0
        elif sector == "BEARISH":
            sector_score = -2.5
            penalties.append("Sector against bullish setup")

    else:
        if nifty == "BEARISH":
            nifty_score = 5.0
            reasons.append("NIFTY aligned bearish")
        elif nifty == "BULLISH":
            nifty_score = -2.5
            penalties.append("NIFTY against bearish setup")

        if sector == "BEARISH":
            if current_score >= 60.0:
                sector_score = 5.0
                reasons.append("Sector aligned bearish")
            else:
                sector_score = 0.0
        elif sector == "BULLISH":
            sector_score = -2.5
            penalties.append("Sector against bearish setup")

    return nifty_score, sector_score, reasons, penalties


# ============================================================
# CANDLE / STRUCTURE QUALITY
# ============================================================

def _candle_quality(row: pd.Series, direction: str, atr14: float = 0.0) -> tuple[float, bool]:
    candle_range = _safe_float(row["High"] - row["Low"])

    if candle_range <= 0:
        return 0.0, False

    body = abs(_safe_float(row["Close"] - row["Open"]))
    body_ratio = body / candle_range

    if direction == "BULLISH":
        valid = row["Close"] > row["Open"]
    else:
        valid = row["Close"] < row["Open"]

    if not valid:
        return 0.0, False

    # HYBRID CANDLE QUALITY: If candle range expansion >= 1.0 * ATR14 and closes in trade direction,
    # award full 5.0 points regardless of wicks/body-ratio.
    if atr14 > 0 and candle_range >= 1.0 * atr14:
        return 5.0, True

    if body_ratio >= 0.65:
        return 5.0, True

    if body_ratio >= 0.50:
        return 3.0, True

    return 1.0, True


def _trend_structure(
    df: pd.DataFrame,
    direction: str,
    rel_vol: float = 1.0,
    opening_high: Optional[float] = None,
    opening_low: Optional[float] = None,
    vwap: Optional[float] = None,
    close: Optional[float] = None,
) -> tuple[float, list[str], list[str]]:
    """
    Evaluate 15-minute intraday structural progression (Max: 12.0 points).
    Restores the full 100-point engine scale across both early and regular sessions,
    verifies authentic progressive Higher-Lows / Lower-Highs, and rewards sustained
    3-bar VWAP trend-holding during high-tight flag consolidations.
    """
    score = 0.0
    reasons: list[str] = []
    penalties: list[str] = []

    if len(df) < 6:
        # Phase 1: Early Morning Session Structure (Bars 2-5, 09:30 - 10:15 IST)
        # In early session, multi-bar HH/HL cannot form yet.
        # Award institutional momentum structure ONLY if volume and level expansion confirm it.
        c = close if close is not None else float(df["Close"].iloc[-1])
        v = vwap if vwap is not None else c

        if direction == "BULLISH":
            is_orb_break = opening_high is not None and c > opening_high
            is_above_vwap = c >= v
            if is_orb_break and is_above_vwap:
                if rel_vol >= 2.5:
                    score += 12.0
                    reasons.append("Explosive opening breakout structure (RelVol >= 2.5x)")
                elif rel_vol >= 2.0:
                    score += 10.0
                    reasons.append("Opening session breakout structure (RelVol >= 2.0x)")
                elif rel_vol >= 1.5:
                    score += 6.0
                    reasons.append("Early session breakout expansion (RelVol >= 1.5x)")
        else:
            is_orb_break = opening_low is not None and c < opening_low
            is_below_vwap = c <= v
            if is_orb_break and is_below_vwap:
                if rel_vol >= 2.5:
                    score += 12.0
                    reasons.append("Explosive opening breakdown structure (RelVol >= 2.5x)")
                elif rel_vol >= 2.0:
                    score += 10.0
                    reasons.append("Opening session breakdown structure (RelVol >= 2.0x)")
                elif rel_vol >= 1.5:
                    score += 6.0
                    reasons.append("Early session breakdown expansion (RelVol >= 1.5x)")

        return score, reasons, penalties

    recent = df.tail(6)

    highs = recent["High"].to_numpy(dtype=float)
    lows = recent["Low"].to_numpy(dtype=float)
    closes = recent["Close"].to_numpy(dtype=float)

    if direction == "BULLISH":
        # Pillar 1 (+4.0 pts): Multi-bar Higher-High expansion
        higher_highs = highs[-1] >= np.max(highs[-4:-1])
        # Pillar 2 (+4.0 pts): Authentic progressive Higher-Low
        higher_lows = (lows[-1] >= lows[-2]) and (lows[-2] >= np.min(lows[-4:-1]))
        # Pillar 3 (+4.0 pts): Multi-bar closing expansion OR sustained 3-bar VWAP hold
        higher_closes = (closes[-1] >= np.max(closes[-4:-1])) or (
            vwap is not None and np.min(closes[-3:]) >= vwap and closes[-1] >= closes[-2]
        )

        if higher_highs:
            score += 4.0
            reasons.append("Higher-high structure")
        if higher_lows:
            score += 4.0
            reasons.append("Higher-low structure")
        if higher_closes:
            score += 4.0
            reasons.append("Sustained bullish closing structure")

        if not higher_highs and not higher_lows:
            penalties.append("Bullish structure not expanding")

    else:
        # Pillar 1 (+4.0 pts): Multi-bar Lower-Low expansion
        lower_lows = lows[-1] <= np.min(lows[-4:-1])
        # Pillar 2 (+4.0 pts): Authentic progressive Lower-High
        lower_highs = (highs[-1] <= highs[-2]) and (highs[-2] <= np.max(highs[-4:-1]))
        # Pillar 3 (+4.0 pts): Multi-bar closing breakdown OR sustained 3-bar VWAP ceiling hold
        lower_closes = (closes[-1] <= np.min(closes[-4:-1])) or (
            vwap is not None and np.max(closes[-3:]) <= vwap and closes[-1] <= closes[-2]
        )

        if lower_lows:
            score += 4.0
            reasons.append("Lower-low structure")
        if lower_highs:
            score += 4.0
            reasons.append("Lower-high structure")
        if lower_closes:
            score += 4.0
            reasons.append("Sustained bearish closing structure")

        if not lower_lows and not lower_highs:
            penalties.append("Bearish structure not expanding")

    return score, reasons, penalties


# ============================================================
# DIRECTION-SPECIFIC DISCOVERY
# ============================================================

def _evaluate_direction(
    df: pd.DataFrame,
    direction: str,
    context: Optional[Any] = None,
    allow_below_threshold: bool = False,
    symbol: Optional[str] = None,
) -> Optional[_DirectionEvaluation]:
    session = _latest_session(df)

    if len(session) < 1:
        return None

    # LIVE TRADING HOURS SAFEGUARDS (09:15 to 15:30 IST, Monday-Friday):
    # 1. Reject stale previous-session data if Yahoo Finance has not delivered today's candles yet.
    # 2. Reject discovery during Opening Range formation (09:15 to 09:30 AM IST).
    now_ist = datetime.now(IST_TZ)
    if now_ist.weekday() <= 4 and pd.Timestamp("09:15").time() <= now_ist.time() <= pd.Timestamp("15:30").time():
        session_dates = _session_dates(df)
        if session_dates:
            latest_sess_date = session_dates[-1]
            latest_date_obj = latest_sess_date.date() if hasattr(latest_sess_date, "date") else pd.Timestamp(latest_sess_date).date()
            if latest_date_obj != now_ist.date():
                return None
        if now_ist.time() < pd.Timestamp(OPENING_RANGE_END).time():
            return None

    opening_high, opening_low = _opening_range(session)

    if opening_high is None or opening_low is None:
        return None

    previous_high, previous_low, previous_close = _previous_day_levels(df)

    if previous_high is None or previous_low is None or previous_close is None or previous_close <= 0:
        return None

    # We only discover after the opening range is complete (09:30 AM).
    latest_time = pd.DatetimeIndex(session.index)[-1].time()
    if latest_time < pd.Timestamp(OPENING_RANGE_END).time():
        return None

    # RULE: Market Close Cutoff (15:30 IST)
    # The screener continues observing through the regular trading session (until 15:30 IST close).
    # Live trade notification cutoff at 15:00 IST is enforced at the Telegram alert boundary.
    if latest_time >= pd.Timestamp("15:30").time():
        return None

    close = _safe_float(session["Close"].iloc[-1])
    latest = session.iloc[-1]

    # RULE 1: Minimum Base Price Guard (>= Rs 20.0, or >= Rs 50 Crore Session Turnover Exemption)
    # Reject micro-penny stocks below Rs 20 unless session turnover >= Rs 50 Crore (500,000,000)
    session_vol = _safe_float(session["Volume"].sum())
    session_turnover = session_vol * close
    is_sub_20_exempt = (close < 20.0 and session_turnover >= 500_000_000.0)
    if close < 20.0 and not is_sub_20_exempt:
        return None

    # RULE 1B: Sub-₹30 Liquidity & Turnover Hard Shield (Rs 20.0 to Rs 30.0)
    # Protects against 5-paisa tick spread slippage (0.25% per tick) and operator-driven low depth:
    # 1. Require cumulative session volume >= 2,000,000 shares OR session turnover >= Rs 10 Crore (100,000,000)
    if 20.0 <= close < 30.0:
        if session_vol < 2_000_000 and session_turnover < 100_000_000:
            return None

    # CIRCUIT LOCK PROTECTION GUARD: Block frozen stocks locked in Upper/Lower Circuit limits (zero candle range)
    latest_range = _safe_float(latest["High"] - latest["Low"])
    if latest_range <= 0.0:
        return None

    ema_series = _ema(df["Close"], 20)
    rsi_series = _rsi(df["Close"], 14)
    atr_series = _atr(df, 14)
    vwap_series = _session_vwap(session)

    ema20 = _safe_float(ema_series.iloc[-1])
    rsi14 = _safe_float(rsi_series.iloc[-1], 50.0)
    atr14 = _safe_float(atr_series.iloc[-1])
    vwap = _safe_float(vwap_series.iloc[-1], close)

    rel_vol = _relative_volume(df, session)
    true_velocity = _true_velocity(df)

    if atr14 <= 0:
        return None

    # Sub-₹30 Institutional Multiplier: require strong institutional volume (>= 1.50x)
    if close < 30.0 and rel_vol < 1.50:
        return None

    # Hoisted Daily ATR calculation: required as a stationary anchor for both
    # the Opening Range width guard and the Intraday Momentum expansion gate.
    daily_atr = _daily_atr14(df, 14)
    effective_daily_atr = daily_atr if daily_atr > 0 else (atr14 * 4.0)

    # Point-in-time Opening Bar ATR + 25% Daily ATR floor:
    # 1. Prevents midday 15m ATR contraction from retroactively killing valid morning breakouts (e.g., LT).
    # 2. Prevents dull prior-afternoon 15m ATR from making a normal 1% opening candle look like > 3.0x ATR.
    or_bar_idx = max(0, len(atr_series) - len(session))
    or_atr14 = _safe_float(atr_series.iloc[or_bar_idx], atr14)
    ref_or_atr = max(atr14, or_atr14, effective_daily_atr * 0.25)

    # RULE: Wide Opening Range Exhaustion Hard Guard (Blow-off exhaustion filter)
    # Unconfirmed setups are rejected if OR width > 3.0 * ref_or_atr.
    # Confirmed volume breakouts (RelVol >= 1.50x holding VWAP, including 0.15*ATR retest cushion) are permitted up to 4.0 * ref_or_atr.
    or_width = opening_high - opening_low
    session_high = _safe_float(session["High"].max(), close) if not session.empty else close
    session_low = _safe_float(session["Low"].min(), close) if not session.empty else close
    retest_tol = 0.15 * atr14

    is_confirmed_vol_breakout = (
        (
            direction == "BULLISH"
            and (close > opening_high or (session_high > opening_high and close >= opening_high - retest_tol))
            and close >= vwap
            and rel_vol >= 1.50
        )
        or (
            direction == "BEARISH"
            and (close < opening_low or (session_low < opening_low and close <= opening_low + retest_tol))
            and close <= vwap
            and rel_vol >= 1.50
        )
    )
    max_or_atr_mult = 4.0 if is_confirmed_vol_breakout else 3.0
    if or_width > max_or_atr_mult * ref_or_atr:
        return None

    # Session price change percentage for circuit boundary guards
    day_change_pct = ((close - previous_close) / previous_close) * 100.0

    # RULE: Volatility-Normalized Dynamic Intraday Momentum Gate
    # Replaces primitive flat +/-0.80% static percentage filter with asset-agnostic Daily ATR expansion.
    # Adaptive Threshold coupled with Institutional Relative Volume:
    # 1. RelVol >= 1.50x (Blowout Volume) -> 0.25 * Daily ATR (Early entry on heavy institutional accumulation)
    # 2. 1.20x <= RelVol < 1.50x -> 0.30 * Daily ATR (Higher expansion requirement for moderate volume safety)
    # 3. RelVol < 1.20x -> Handled by institutional volume hard gate (rejected)
    req_atr_ratio = 0.25 if rel_vol >= 1.50 else 0.30
    min_required_move = req_atr_ratio * effective_daily_atr

    if direction == "BULLISH":
        if close <= previous_close:
            return None
        if close > opening_high:
            price_expansion = max(close - opening_low, close - previous_close)
        else:
            anchor = max(previous_close, opening_low)
            price_expansion = close - anchor
        if price_expansion < min_required_move:
            return None
    else:
        if close >= previous_close:
            return None
        if close < opening_low:
            price_expansion = max(opening_high - close, previous_close - close)
        else:
            anchor = min(previous_close, opening_high)
            price_expansion = anchor - close
        if price_expansion < min_required_move:
            return None

    # RULE: Circuit Proximity & Ceiling Freeze Guard
    # Block stocks locked at standard exchange circuit limits (2%, 5%, 10%, 20%) with zero sellers / frozen top
    is_at_circuit_ceiling = (
        (1.85 <= day_change_pct <= 2.05) or
        (4.80 <= day_change_pct <= 5.05) or
        (9.80 <= day_change_pct <= 10.10) or
        (day_change_pct >= 19.60)
    )
    if direction == "BULLISH" and is_at_circuit_ceiling:
        if close >= (latest["High"] - (0.05 * atr14)):
            return None

    is_at_circuit_floor = (
        (-2.05 <= day_change_pct <= -1.85) or
        (-5.05 <= day_change_pct <= -4.80) or
        (-10.10 <= day_change_pct <= -9.80) or
        (day_change_pct <= -19.60)
    )
    if direction == "BEARISH" and is_at_circuit_floor:
        if close <= (latest["Low"] + (0.05 * atr14)):
            return None

    # RULE 3: All-Day Institutional Volume Hard Gate (Min 1.20x RelVol across all sessions)
    # A breakout without institutional volume is statistically a fakeout/retail trap.
    if rel_vol < 1.20:
        return None

    # Opening whipsaw window (09:30 - 10:00 AM) requires strong 1.50x RelVol
    if latest_time < pd.Timestamp("10:00").time() and rel_vol < 1.50:
        return None

    # RULE: Bar 2 (09:30 - 09:45 AM) Early Micro-Confirmation Guard
    # When Bar 2 is evaluated mid-bar, require institutional blowout volume (>= 2.0x) AND
    # solid price breakout buffer (>= 0.20 ATR past OR level) to avoid wick traps (e.g. LTF/SWANDEF).
    is_bar_2 = (len(session) == 2 and latest_time == pd.Timestamp("09:30").time())
    if is_bar_2:
        if rel_vol < 2.00:
            return None
        if direction == "BULLISH" and (close - opening_high) < (0.20 * atr14):
            return None
        elif direction == "BEARISH" and (opening_low - close) < (0.20 * atr14):
            return None

    score = 0.0
    score_breakdown: dict[str, float] = {}
    reasons: list[str] = []
    penalties: list[str] = []

    # --------------------------------------------------------
    # 1. Trend structure ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â 12
    # --------------------------------------------------------

    structure_score, structure_reasons, structure_penalties = _trend_structure(
        session,
        direction,
        rel_vol=rel_vol,
        opening_high=opening_high,
        opening_low=opening_low,
        vwap=vwap,
        close=close,
    )
    score_before = score
    score += structure_score
    score_breakdown["trend_structure"] = float(score - score_before)
    reasons.extend(structure_reasons)
    penalties.extend(structure_penalties)

    # --------------------------------------------------------
    # 2. EMA alignment ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â 10
    # --------------------------------------------------------

    score_before = score

    if direction == "BULLISH":
        if close > ema20:
            score += 10.0
            reasons.append("Price above 20 EMA")
        elif close >= ema20 - (0.25 * atr14):
            score += 4.0
            reasons.append("Price near 20 EMA")
        else:
            penalties.append("Price below 20 EMA")

    else:
        if close < ema20:
            score += 10.0
            reasons.append("Price below 20 EMA")
        elif close <= ema20 + (0.25 * atr14):
            score += 4.0
            reasons.append("Price near 20 EMA")
        else:
            penalties.append("Price above 20 EMA")

    score_breakdown["ema_alignment"] = float(score - score_before)

    # --------------------------------------------------------
    # 3. VWAP alignment ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â 10
    # --------------------------------------------------------

    score_before = score

    if direction == "BULLISH":
        if close > vwap:
            score += 10.0
            reasons.append("Price above VWAP")
        elif close >= vwap - (0.20 * atr14):
            score += 4.0
            reasons.append("Price near VWAP")
        else:
            penalties.append("Price below VWAP")
    else:
        if close < vwap:
            score += 10.0
            reasons.append("Price below VWAP")
        elif close <= vwap + (0.20 * atr14):
            score += 4.0
            reasons.append("Price near VWAP")
        else:
            penalties.append("Price above VWAP")

    score_breakdown["vwap_alignment"] = float(score - score_before)

    # --------------------------------------------------------
    # 4. RSI momentum ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â 8
    # --------------------------------------------------------

    score_before = score

    if direction == "BULLISH":
        if 55 <= rsi14 <= 68:
            score += 8.0
            reasons.append(f"Healthy bullish RSI ({rsi14:.1f})")
        elif 68 < rsi14 <= 75:
            score += 5.0
            reasons.append(f"Strong bullish momentum ({rsi14:.1f})")
        elif 50 <= rsi14 < 55:
            score += 3.0
            reasons.append(f"Developing bullish RSI ({rsi14:.1f})")
        elif rsi14 > 75:
            if rel_vol >= 1.5:
                score += 6.0
                reasons.append(f"Extreme breakout momentum RSI ({rsi14:.1f})")
            else:
                penalties.append(f"RSI overextended ({rsi14:.1f})")
        else:
            penalties.append(f"RSI not bullish ({rsi14:.1f})")

    else:
        if 32 <= rsi14 <= 45:
            score += 8.0
            reasons.append(f"Healthy bearish RSI ({rsi14:.1f})")
        elif 25 <= rsi14 < 32:
            score += 5.0
            reasons.append(f"Strong bearish momentum ({rsi14:.1f})")
        elif 45 < rsi14 <= 50:
            score += 3.0
            reasons.append(f"Developing bearish RSI ({rsi14:.1f})")
        elif rsi14 < 25:
            if rel_vol >= 1.5:
                score += 6.0
                reasons.append(f"Extreme breakdown momentum RSI ({rsi14:.1f})")
            else:
                penalties.append(f"RSI oversold ({rsi14:.1f})")
        else:
            penalties.append(f"RSI not bearish ({rsi14:.1f})")

    score_breakdown["rsi_momentum"] = float(score - score_before)

    # --------------------------------------------------------
    # 5. Volume ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â 12
    # --------------------------------------------------------

    score_before = score

    if rel_vol >= 3.0:
        score += 12.0
        reasons.append(f"Very strong relative volume ({rel_vol:.2f}x)")
    elif rel_vol >= 2.0:
        score += 10.0
        reasons.append(f"Strong relative volume ({rel_vol:.2f}x)")
    elif rel_vol >= 1.5:
        score += 8.0
        reasons.append(f"Confirmed relative volume ({rel_vol:.2f}x)")
    elif rel_vol >= 1.2:
        score += 4.0
        reasons.append(f"Moderate relative volume ({rel_vol:.2f}x)")
    else:
        penalties.append(f"Weak relative volume ({rel_vol:.2f}x)")

    score_breakdown["volume"] = float(score - score_before)

    # --------------------------------------------------------
    # 6. Opening-range breakout / breakdown ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â 18
    # --------------------------------------------------------

    score_before = score

    if direction == "BULLISH":
        distance = (close - opening_high) / atr14

        if close > opening_high:
            score += 18.0
            setup_type = "CONFIRMED_BREAKOUT_LONG"
            reasons.append("Confirmed opening range breakout")
        elif distance >= -0.20:
            score += 10.0
            setup_type = "DEVELOPING_BREAKOUT_LONG"
            reasons.append("Price near opening range breakout")
        elif distance >= -0.50:
            score += 5.0
            setup_type = "DEVELOPING_BREAKOUT_LONG"
            reasons.append("Price approaching opening range breakout")
        else:
            setup_type = "DEVELOPING_BREAKOUT_LONG"
            penalties.append("Price too far below opening range high")

    else:
        distance = (opening_low - close) / atr14

        if close < opening_low:
            score += 18.0
            setup_type = "CONFIRMED_BREAKDOWN_SHORT"
            reasons.append("Confirmed opening range breakdown")
        elif distance >= -0.20:
            score += 10.0
            setup_type = "DEVELOPING_BREAKDOWN_SHORT"
            reasons.append("Price near opening range breakdown")
        elif distance >= -0.50:
            score += 5.0
            setup_type = "DEVELOPING_BREAKDOWN_SHORT"
            reasons.append("Price approaching opening range breakdown")
        else:
            setup_type = "DEVELOPING_BREAKDOWN_SHORT"
            penalties.append("Price too far above opening range low")

    score_breakdown["opening_range"] = float(score - score_before)

    # --------------------------------------------------------
    # 7. Previous-day level ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â 7
    # --------------------------------------------------------

    score_before = score

    if direction == "BULLISH":
        if close > previous_high:
            score += 7.0
            reasons.append("Price above previous day high")
        elif close >= previous_high - (0.25 * atr14):
            score += 3.0
            reasons.append("Price near previous day high")
    else:
        if close < previous_low:
            score += 7.0
            reasons.append("Price below previous day low")
        elif close <= previous_low + (0.25 * atr14):
            score += 3.0
            reasons.append("Price near previous day low")

    score_breakdown["previous_day_level"] = float(score - score_before)

    # --------------------------------------------------------
    # 8. Candle quality  5
    # --------------------------------------------------------

    candle_score, valid_candle = _candle_quality(latest, direction, atr14)
    score_before = score
    score += candle_score

    if candle_score >= 5:
        reasons.append(
            "Strong bullish candle" if direction == "BULLISH"
            else "Strong bearish candle"
        )
    elif valid_candle:
        reasons.append(
            "Supportive bullish candle" if direction == "BULLISH"
            else "Supportive bearish candle"
        )

    score_breakdown["candle_quality"] = float(score - score_before)

    # --------------------------------------------------------
    # 9. True Velocity — 8
    #
    # Evaluated before Market + Sector Context so all 90 stock-specific
    # technical points are accumulated before checking current_score >= 60.0.
    # --------------------------------------------------------

    score_before = score

    # True Velocity Squeeze Exemption:
    # If today's breakout has RelVol >= 1.5 or is near/crossing ORB (distance >= -0.20),
    # exempt from consolidation penalty and award base velocity points (+4.0).
    is_active_breakout = rel_vol >= 1.5 or distance >= -0.20

    if true_velocity is not None:
        aligned_velocity = (
            true_velocity if direction == "BULLISH" else -true_velocity
        )

        if aligned_velocity >= 5.0:
            score += 8.0
            reasons.append(f"Explosive true velocity ({true_velocity:.2f})")
        elif aligned_velocity >= 3.0:
            score += 6.0
            reasons.append(f"Strong true velocity ({true_velocity:.2f})")
        elif aligned_velocity >= 2.0:
            score += 4.0
            reasons.append(f"Good true velocity ({true_velocity:.2f})")
        elif aligned_velocity >= 1.0:
            score += 2.0
            reasons.append(f"Positive true velocity ({true_velocity:.2f})")
        elif is_active_breakout:
            score += 4.0
            reasons.append("Squeeze breakout: Past velocity exempted by volume/ORB surge")
        else:
            penalties.append(f"Weak/opposite true velocity ({true_velocity:.2f})")
    else:
        if is_active_breakout:
            score += 4.0
            reasons.append("Squeeze breakout: Past velocity exempted by volume/ORB surge")
        else:
            penalties.append("True velocity unavailable")

    score_breakdown["true_velocity"] = float(score - score_before)

    # --------------------------------------------------------
    # 10. Market + sector alignment — 10
    # --------------------------------------------------------

    nifty_score, sector_score, context_reasons, context_penalties = _context_alignment(
        direction,
        context,
        current_score=score,
    )
    score_before = score
    score += (nifty_score + sector_score)
    reasons.extend(context_reasons)
    penalties.extend(context_penalties)

    score_breakdown["nifty_alignment"] = float(nifty_score)
    score_breakdown["sector_alignment"] = float(sector_score)
    score_breakdown["market_sector_alignment"] = float(score - score_before)

    # --------------------------------------------------------
    # 11. Extension / chase penalty
    # --------------------------------------------------------

    score_before = score

    vwap_distance_atr = abs(close - vwap) / atr14
    is_early_breakout = len(session) <= 3

    # PARABOLIC CLIMAX FILTER: Hard block buying vertical blow-off tops extended > 4.0 ATR from VWAP
    if vwap_distance_atr > 4.0 and not is_early_breakout:
        return None

    if vwap_distance_atr > 2.5:
        score -= 2.0 if is_early_breakout else 8.0
        penalties.append("Price extended >2.5 ATR from VWAP")
    elif vwap_distance_atr > 2.0:
        score -= 1.0 if is_early_breakout else 4.0
        penalties.append("Price extended >2 ATR from VWAP")

    score_breakdown["extension_chase"] = float(score - score_before)

    # --------------------------------------------------------
    # 11. Trade construction
    #
    # Entry remains anchored to the OR level. Stop is anchored
    # to the closest valid structural support/resistance (VWAP,
    # OR boundary, or 1.5 ATR) to ensure realistic risk-reward targets.
    # --------------------------------------------------------

    if direction == "BULLISH":
        entry = normalize_nse_tick(opening_high, direction="BULLISH", is_sl=False)
        min_sl_dist = max(0.40 * atr14, 0.005 * entry) if entry > 0 else 0.40 * atr14

        candidates = [
            opening_low - (0.35 * atr14),
            vwap - (0.50 * atr14),
            entry - (1.50 * atr14),
        ]

        # Pre-filter: Only consider structural levels that are strictly below (entry - min_sl_dist)
        valid_stops = [s for s in candidates if s <= (entry - min_sl_dist)]
        raw_stop = max(valid_stops) if valid_stops else (entry - min_sl_dist)
        stop = normalize_nse_tick(raw_stop, direction="BULLISH", is_sl=True)

        risk = round(entry - stop, 2)
        target_1 = normalize_nse_tick(entry + (1.5 * risk), direction="BULLISH", is_sl=False)
        target_2 = normalize_nse_tick(entry + (2.5 * risk), direction="BULLISH", is_sl=False)

    else:
        entry = normalize_nse_tick(opening_low, direction="BEARISH", is_sl=False)
        min_sl_dist = max(0.40 * atr14, 0.005 * entry) if entry > 0 else 0.40 * atr14

        candidates = [
            opening_high + (0.35 * atr14),
            vwap + (0.50 * atr14),
            entry + (1.50 * atr14),
        ]

        # Pre-filter: Only consider structural levels that are strictly above (entry + min_sl_dist)
        valid_stops = [s for s in candidates if s >= (entry + min_sl_dist)]
        raw_stop = min(valid_stops) if valid_stops else (entry + min_sl_dist)
        stop = normalize_nse_tick(raw_stop, direction="BEARISH", is_sl=True)

        risk = round(stop - entry, 2)
        target_1 = normalize_nse_tick(entry - (1.5 * risk), direction="BEARISH", is_sl=False)
        target_2 = normalize_nse_tick(entry - (2.5 * risk), direction="BEARISH", is_sl=False)

    if risk <= 0:
        return None

    # RULE 1: Minimum Entry Price Guard (>= Rs 20.0, or >= Rs 50 Crore Session Turnover Exemption)
    # Reject penny / micro-priced stocks below Rs 20 unless session turnover >= Rs 50 Crore (500,000,000)
    session_vol = _safe_float(session["Volume"].sum())
    session_turnover = session_vol * close
    if entry < 20.0 and session_turnover < 500_000_000.0:
        return None

    # RULE: Daily ATR Budget Guard (Exhaustion Filter)
    # Anchor traveled distance to the breakout entry price (entry - day_low) rather than live close
    # so winning breakouts are never retroactively deleted as live price rallies toward Target 1.
    day_low = _safe_float(session["Low"].min(), close)
    day_high = _safe_float(session["High"].max(), close)
    entry_traveled = max(0.0, entry - day_low) if direction == "BULLISH" else max(0.0, day_high - entry)
    remaining_daily_room = max(0.0, effective_daily_atr - entry_traveled)
    t1_distance = abs(target_1 - entry)

    if t1_distance > (1.20 * remaining_daily_room):
        return None

    rr1 = abs(target_1 - entry) / risk
    rr2 = abs(target_2 - entry) / risk

    # RULE: Wide Opening Range Exhaustion Penalty
    # Evaluated against stationary ref_or_atr; partially offset (-4.0 vs -8.0) when confirmed by volume breakout.
    score_before = score
    or_width = opening_high - opening_low
    if or_width > 2.0 * ref_or_atr:
        if is_confirmed_vol_breakout:
            score -= 4.0
            penalties.append(f"Wide opening range ({or_width:.2f} > 2.0 ATR), partially offset by volume breakout")
        else:
            score -= 8.0
            penalties.append(f"Opening range excessively wide ({or_width:.2f} > 2.0 ATR), high exhaustion risk")

    # RULE 2: Tight Stop Loss Penalty (Protection against market noise)
    # If risk percentage is < 0.50% or stop distance < 0.35 ATR, penalize heavily (-4.0 / -3.0 pts)
    risk_pct = (risk / entry) * 100.0 if entry > 0 else 0.0
    if risk_pct < 0.50:
        score -= 4.0
        penalties.append(f"Ultra-tight stop risk ({risk_pct:.2f}% < 0.50%) vulnerable to noise")
    elif risk < 0.35 * atr14:
        score -= 3.0
        penalties.append("Stop distance too tight for ATR")

    score_breakdown["trade_risk_penalties"] = float(score - score_before)

    final_score = _clamp(score)

    # Calculate Target 1 progress percentage and execution status
    t1_dist = abs(target_1 - entry)
    if t1_dist > 0:
        if direction == "BULLISH":
            move = close - entry
        else:
            move = entry - close
        t1_progress_pct = round(max(0.0, (move / t1_dist) * 100.0), 2)
    else:
        t1_progress_pct = 0.0

    is_triggered = (close > entry) if direction == "BULLISH" else (close < entry)
    entry_dist_atr = abs(close - entry) / atr14
    if t1_progress_pct >= 100.0:
        execution_status = "TARGET_HIT"
    elif t1_progress_pct >= 75.0:
        execution_status = "TARGET_NEAR"
    elif not is_triggered:
        execution_status = "PRE_BREAKOUT_WATCH"
    elif t1_progress_pct <= 25.0 and entry_dist_atr <= 0.40:
        execution_status = "EARLY_TRIGGER"
    else:
        execution_status = "ACTIONABLE_IN_PLAY"

    # Minimum structural quality:
    # V13 can discover developing setups, but it should not call
    # every stock a candidate merely because indicators exist.
    if not allow_below_threshold and final_score < WATCH_SCORE:
        return None

    return _DirectionEvaluation(
        direction=direction,
        score=round(final_score, 2),
        setup_type=setup_type,
        entry=round(entry, 2),
        stop=round(stop, 2),
        target_1=round(target_1, 2),
        target_2=round(target_2, 2),
        risk=round(risk, 2),
        rr1=round(rr1, 2),
        rr2=round(rr2, 2),
        reasons=reasons,
        penalties=penalties,
        breakout_distance_atr=round(distance, 2),
        breakout_candle_range=round(_safe_float(latest["High"] - latest["Low"]), 2),
        true_velocity=round(true_velocity, 2) if true_velocity is not None else 0.0,
        score_breakdown={k: round(float(v), 2) for k, v in score_breakdown.items()},
        ema20=round(ema20, 2),
        rsi14=round(rsi14, 2),
        rel_vol=round(rel_vol, 2),
        vwap=round(vwap, 2),
        atr14=round(atr14, 2),
        t1_progress_pct=t1_progress_pct,
        execution_status=execution_status,
    )


# ============================================================
# PUBLIC API
# ============================================================

def _classification(score: float) -> tuple[str, str]:
    if score >= HIGH_CONFIDENCE_SCORE:
        return "A", "HIGH_CONFIDENCE"

    if score >= STRONG_SETUP_SCORE:
        return "B+", "STRONG_SETUP"

    if score >= WATCH_SCORE:
        return "B", "WATCH"

    return "D", "BELOW_THRESHOLD"


def evaluate_v13_bullish(
    symbol: str,
    name: str,
    sector: str,
    df: pd.DataFrame,
    context: Optional[Any] = None,
) -> Optional[V13Candidate]:
    """
    Independently evaluate the bullish side.

    This function never asks whether the bearish setup is stronger.
    """

    try:
        clean = _normalise_columns(df)

        if len(clean) < MIN_BARS_FOR_DISCOVERY:
            return None

        evaluation = _evaluate_direction(
            clean,
            "BULLISH",
            context=context,
            symbol=symbol,
        )

        if evaluation is None:
            return None

        grade, action = _classification(evaluation.score)

        latest_session = _latest_session(clean)
        latest_timestamp = pd.DatetimeIndex(latest_session.index)[-1]

        return V13Candidate(
            symbol=symbol,
            name=name,
            sector=sector,
            signal_type="BULLISH",
            setup_type=evaluation.setup_type,
            action=action,
            grade=grade,
            score=evaluation.score,
            ltp=round(_safe_float(clean["Close"].iloc[-1]), 2),
            entry_price=evaluation.entry,
            stop_loss=evaluation.stop,
            target_1=evaluation.target_1,
            target_2=evaluation.target_2,
            risk_amount=evaluation.risk,
            risk_reward_t1="1:1.5",
            risk_reward_t2="1:2.5",
            ema20=round(evaluation.ema20, 2),
            rsi14=round(evaluation.rsi14, 2),
            rel_vol=round(evaluation.rel_vol, 2),
            vwap=round(evaluation.vwap, 2),
            atr14=round(evaluation.atr14, 2),
            true_velocity=evaluation.true_velocity,
            opening_range_high=round(_safe_float(_opening_range(latest_session)[0]), 2),
            opening_range_low=round(_safe_float(_opening_range(latest_session)[1]), 2),
            previous_day_high=round(_safe_float(_previous_day_levels(clean)[0]), 2),
            previous_day_low=round(_safe_float(_previous_day_levels(clean)[1]), 2),
            breakout_distance_atr=evaluation.breakout_distance_atr,
            breakout_candle_range=evaluation.breakout_candle_range,
            reasons=evaluation.reasons,
            penalties=evaluation.penalties,
            score_breakdown=evaluation.score_breakdown,
            t1_progress_pct=evaluation.t1_progress_pct,
            execution_status=evaluation.execution_status,
            signal_time=latest_timestamp.isoformat(),
        )

    except Exception:
        return None


def evaluate_v13_bearish(
    symbol: str,
    name: str,
    sector: str,
    df: pd.DataFrame,
    context: Optional[Any] = None,
) -> Optional[V13Candidate]:
    """
    Independently evaluate the bearish side.

    This function never asks whether the bullish setup is stronger.
    """

    try:
        clean = _normalise_columns(df)

        if len(clean) < MIN_BARS_FOR_DISCOVERY:
            return None

        evaluation = _evaluate_direction(
            clean,
            "BEARISH",
            context=context,
            symbol=symbol,
        )

        if evaluation is None:
            return None

        grade, action = _classification(evaluation.score)

        latest_session = _latest_session(clean)
        latest_timestamp = pd.DatetimeIndex(latest_session.index)[-1]

        return V13Candidate(
            symbol=symbol,
            name=name,
            sector=sector,
            signal_type="BEARISH",
            setup_type=evaluation.setup_type,
            action=action,
            grade=grade,
            score=evaluation.score,
            ltp=round(_safe_float(clean["Close"].iloc[-1]), 2),
            entry_price=evaluation.entry,
            stop_loss=evaluation.stop,
            target_1=evaluation.target_1,
            target_2=evaluation.target_2,
            risk_amount=evaluation.risk,
            risk_reward_t1="1:1.5",
            risk_reward_t2="1:2.5",
            ema20=round(evaluation.ema20, 2),
            rsi14=round(evaluation.rsi14, 2),
            rel_vol=round(evaluation.rel_vol, 2),
            vwap=round(evaluation.vwap, 2),
            atr14=round(evaluation.atr14, 2),
            true_velocity=evaluation.true_velocity,
            opening_range_high=round(_safe_float(_opening_range(latest_session)[0]), 2),
            opening_range_low=round(_safe_float(_opening_range(latest_session)[1]), 2),
            previous_day_high=round(_safe_float(_previous_day_levels(clean)[0]), 2),
            previous_day_low=round(_safe_float(_previous_day_levels(clean)[1]), 2),
            breakout_distance_atr=evaluation.breakout_distance_atr,
            breakout_candle_range=evaluation.breakout_candle_range,
            reasons=evaluation.reasons,
            penalties=evaluation.penalties,
            score_breakdown=evaluation.score_breakdown,
            t1_progress_pct=evaluation.t1_progress_pct,
            execution_status=evaluation.execution_status,
            signal_time=latest_timestamp.isoformat(),
        )

    except Exception:
        return None


def discover_v13_setups(
    symbol: str,
    name: str,
    sector: str,
    df: pd.DataFrame,
    context: Optional[Any] = None,
) -> dict[str, Optional[V13Candidate]]:
    """
    Run BOTH direction engines independently.

    Returns:
        {
            "bullish": candidate_or_none,
            "bearish": candidate_or_none,
        }
    """

    return {
        "bullish": evaluate_v13_bullish(
            symbol=symbol,
            name=name,
            sector=sector,
            df=df,
            context=context,
        ),
        "bearish": evaluate_v13_bearish(
            symbol=symbol,
            name=name,
            sector=sector,
            df=df,
            context=context,
        ),
    }


def rank_v13_bullish(
    candidates: list[Optional[V13Candidate]],
) -> list[V13Candidate]:
    """
    Rank ONLY bullish candidates.
    """

    valid = [
        candidate
        for candidate in candidates
        if candidate is not None
        and candidate.signal_type == "BULLISH"
        and candidate.action != "NO_SETUP"
    ]

    return sorted(
        valid,
        key=lambda candidate: candidate.score,
        reverse=True,
    )

# This def is intentionally placed after rank_v13_bullish to maintain alphabetical order in the public API list below. And also to keep the code organized and readable, as both functions serve similar purposes but for different signal types.
def rank_v13_bearish(
    candidates: list[Optional[V13Candidate]],
) -> list[V13Candidate]:
    """
    Rank ONLY bearish candidates.
    """

    valid = [
        candidate
        for candidate in candidates
        if candidate is not None
        and candidate.signal_type == "BEARISH"
        and candidate.action != "NO_SETUP"
    ]

    return sorted(
        valid,
        key=lambda candidate: candidate.score,
        reverse=True,
    )


def rank_v13_setups(
    candidates: list[Optional[V13Candidate]],
) -> dict[str, list[V13Candidate]]:
    """
    Convenience wrapper.

    IMPORTANT:
    Bullish and Bearish remain separate lists.
    """

    bullish = rank_v13_bullish(candidates)
    bearish = rank_v13_bearish(candidates)

    return {
        "bullish": bullish,
        "bearish": bearish,
    }


def evaluate_v13_diagnostic(
    symbol: str,
    name: str,
    sector: str,
    df: pd.DataFrame,
    context: Optional[Any] = None,
) -> list[V13Candidate]:
    """
    Evaluate setups regardless of threshold gate, returning candidates with score < 72.
    """
    results = []
    try:
        clean = _normalise_columns(df)
        if len(clean) < MIN_BARS_FOR_DISCOVERY:
            return results

        latest_session = _latest_session(clean)
        if latest_session.empty:
            return results
        latest_timestamp = pd.DatetimeIndex(latest_session.index)[-1]

        for direction in ("BULLISH", "BEARISH"):
            evaluation = _evaluate_direction(
                clean,
                direction,
                context=context,
                allow_below_threshold=True,
                symbol=symbol,
            )
            if evaluation is not None and evaluation.score < WATCH_SCORE:
                grade, action = _classification(evaluation.score)
                cand = V13Candidate(
                    symbol=symbol,
                    name=name,
                    sector=sector,
                    signal_type=direction,
                    setup_type=evaluation.setup_type,
                    action=action,
                    grade=grade,
                    score=evaluation.score,
                    ltp=round(_safe_float(clean["Close"].iloc[-1]), 2),
                    entry_price=evaluation.entry,
                    stop_loss=evaluation.stop,
                    target_1=evaluation.target_1,
                    target_2=evaluation.target_2,
                    risk_amount=evaluation.risk,
                    risk_reward_t1="1:1.5",
                    risk_reward_t2="1:2.5",
                    ema20=round(evaluation.ema20, 2),
                    rsi14=round(evaluation.rsi14, 2),
                    rel_vol=round(evaluation.rel_vol, 2),
                    vwap=round(evaluation.vwap, 2),
                    atr14=round(evaluation.atr14, 2),
                    true_velocity=evaluation.true_velocity,
                    opening_range_high=round(_safe_float(_opening_range(latest_session)[0]), 2),
                    opening_range_low=round(_safe_float(_opening_range(latest_session)[1]), 2),
                    previous_day_high=round(_safe_float(_previous_day_levels(clean)[0]), 2),
                    previous_day_low=round(_safe_float(_previous_day_levels(clean)[1]), 2),
                    breakout_distance_atr=evaluation.breakout_distance_atr,
                    breakout_candle_range=evaluation.breakout_candle_range,
                    reasons=evaluation.reasons,
                    penalties=evaluation.penalties,
                    score_breakdown=evaluation.score_breakdown,
                    t1_progress_pct=evaluation.t1_progress_pct,
                    execution_status=evaluation.execution_status,
                    signal_time=latest_timestamp.isoformat(),
                )
                results.append(cand)
    except Exception:
        pass

    return results


__all__ = [
    "V13Candidate",
    "evaluate_v13_bullish",
    "evaluate_v13_bearish",
    "evaluate_v13_diagnostic",
    "discover_v13_setups",
    "rank_v13_bullish",
    "rank_v13_bearish",
    "rank_v13_setups",
]