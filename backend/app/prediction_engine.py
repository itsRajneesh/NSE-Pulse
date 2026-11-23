from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .indicators import calculate_ema, calculate_rsi, calculate_relative_volume
from .models import PredictionSetup, SignalType
from .market_context import (
    MarketContext,
    apply_context_scores,
)

OPENING_RANGE_START = "09:15"
OPENING_RANGE_END = "09:30"

MIN_CONFIDENCE_CONFIRMED = 70.0
MIN_CONFIDENCE_DEVELOPING = 65.0


def _normalize_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Make sure the dataframe has a timezone-aware/naive datetime index
    that can be safely used for session calculations.
    """
    out = df.copy()

    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)

    # Convert timezone-aware timestamps to IST.
    if out.index.tz is not None:
        out.index = out.index.tz_convert("Asia/Kolkata")

    return out.sort_index()


def _get_trading_sessions(df: pd.DataFrame) -> list[pd.Timestamp]:
    """
    Return unique trading dates available in the dataframe.
    """
    dates = pd.DatetimeIndex(df.index).normalize().unique()
    return sorted(dates)


def _get_latest_session(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return only the latest available trading session.

    This is important when the code is tested after market hours:
    it uses the latest completed market session automatically.
    """
    sessions = _get_trading_sessions(df)

    if not sessions:
        return df.iloc[0:0].copy()

    latest_date = sessions[-1]

    return df[pd.DatetimeIndex(df.index).normalize() == latest_date].copy()


def _get_previous_session(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return the trading session immediately before the latest session.
    """
    sessions = _get_trading_sessions(df)

    if len(sessions) < 2:
        return df.iloc[0:0].copy()

    previous_date = sessions[-2]

    return df[pd.DatetimeIndex(df.index).normalize() == previous_date].copy()


def calculate_session_vwap(session_df: pd.DataFrame) -> pd.Series:
    """
    Calculate VWAP from the beginning of the current trading session.

    VWAP resets at the start of every trading day.
    """
    if session_df.empty:
        return pd.Series(dtype=float)

    typical_price = (session_df["High"] + session_df["Low"] + session_df["Close"]) / 3.0

    volume = session_df["Volume"].replace(0, np.nan)

    cumulative_pv = (typical_price * volume).cumsum()
    cumulative_volume = volume.cumsum()

    return cumulative_pv / cumulative_volume


def calculate_atr(
    df: pd.DataFrame,
    period: int = 14,
) -> pd.Series:
    """
    Wilder-style ATR.
    """
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    previous_close = close.shift(1)

    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = true_range.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    return atr


def get_opening_range(
    session_df: pd.DataFrame,
) -> tuple[Optional[float], Optional[float]]:
    """
    Calculate the Opening Range using ONLY the latest trading session's
    09:15 <= time < 09:30 candles.
    """
    if session_df.empty:
        return None, None

    times = pd.DatetimeIndex(session_df.index).time

    start = pd.Timestamp(OPENING_RANGE_START).time()
    end = pd.Timestamp(OPENING_RANGE_END).time()

    mask = (times >= start) & (times < end)

    opening_df = session_df.loc[mask]

    if opening_df.empty:
        return None, None

    return (
        float(opening_df["High"].max()),
        float(opening_df["Low"].min()),
    )


def get_previous_day_levels(
    df: pd.DataFrame,
) -> tuple[Optional[float], Optional[float]]:
    """
    Get High/Low from the trading session immediately before
    the latest available trading session.
    """
    previous_session = _get_previous_session(df)

    if previous_session.empty:
        return None, None

    return (
        float(previous_session["High"].max()),
        float(previous_session["Low"].min()),
    )


def _is_strong_bullish_candle(row: pd.Series) -> bool:
    candle_range = float(row["High"] - row["Low"])

    if candle_range <= 0:
        return False

    body = abs(float(row["Close"] - row["Open"]))

    return row["Close"] > row["Open"] and body / candle_range >= 0.60


def _is_strong_bearish_candle(row: pd.Series) -> bool:
    candle_range = float(row["High"] - row["Low"])

    if candle_range <= 0:
        return False

    body = abs(float(row["Close"] - row["Open"]))

    return row["Close"] < row["Open"] and body / candle_range >= 0.60


def evaluate_prediction_setup(
    symbol: str,
    name: str,
    sector: str,
    df: pd.DataFrame,
    context: Optional[MarketContext] = None,
) -> Optional[PredictionSetup]:
    """
    Evaluate one stock for a high-quality intraday prediction setup.

    The engine automatically uses the latest available trading session,
    whether the market is currently open or closed.
    """

    if df is None or df.empty:
        return None

    required_columns = {
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
    }

    if not required_columns.issubset(df.columns):
        return None

    df = _normalize_datetime_index(df)

    if len(df) < 30:
        return None

    # ---------------------------------------------------------
    # Latest trading session
    # ---------------------------------------------------------

    session_df = _get_latest_session(df)

    if session_df.empty or len(session_df) < 2:
        return None

    # ---------------------------------------------------------
    # Previous trading session
    # ---------------------------------------------------------

    previous_session = _get_previous_session(df)

    if previous_session.empty:
        return None

    # ---------------------------------------------------------
    # Indicators
    #
    # EMA / RSI / ATR need historical warm-up candles.
    # Therefore calculate them on ALL data available up to
    # the decision time, then take the latest value from the
    # current trading session.
    #
    # VWAP remains session-specific.
    # ---------------------------------------------------------

    session_df = session_df.copy()

    # EMA20 on historical data available up to the decision point.
    df = df.copy()

    df["EMA20"] = calculate_ema(
        df["Close"],
        period=20,
    )

    # RSI14 on historical data available up to the decision point.
    df["RSI14"] = calculate_rsi(
        df["Close"],
        period=14,
    )

    # ATR14 on historical data available up to the decision point.
    df["ATR14"] = calculate_atr(
        df,
        period=14,
    )

    # Copy the historical indicator values into the current
    # trading session.
    session_df["EMA20"] = df["EMA20"].reindex(
        session_df.index
    )

    session_df["RSI14"] = df["RSI14"].reindex(
        session_df.index
    )

    session_df["ATR14"] = df["ATR14"].reindex(
        session_df.index
    )

    # ---------------------------------------------------------
    # Relative Volume
    #
    # Historical data is already limited to the decision
    # timestamp during backtesting, so no future candles
    # are included.
    # ---------------------------------------------------------

    rel_vol_result = calculate_relative_volume(
        df,
        lookback_candles=10 * 25,
    )

    if isinstance(rel_vol_result, tuple):
        rel_vol_result = rel_vol_result[0]

    if isinstance(rel_vol_result, pd.Series):
        session_df["RelVol"] = rel_vol_result.reindex(
            session_df.index
        )
    else:
        session_df["RelVol"] = float(rel_vol_result)

    # VWAP must remain current-session only.
    session_df["VWAP"] = calculate_session_vwap(
        session_df
    )

    latest = session_df.iloc[-1]

    ltp = float(latest["Close"])

    ema20 = float(latest["EMA20"]) if pd.notna(latest["EMA20"]) else np.nan
    rsi14 = float(latest["RSI14"]) if pd.notna(latest["RSI14"]) else np.nan
    rel_vol = float(latest["RelVol"]) if pd.notna(latest["RelVol"]) else np.nan
    vwap = float(latest["VWAP"]) if pd.notna(latest["VWAP"]) else np.nan
    atr14 = float(latest["ATR14"]) if pd.notna(latest["ATR14"]) else np.nan

    if not all(
        np.isfinite(value) for value in [ltp, ema20, rsi14, rel_vol, vwap, atr14]
    ):
        return None

    # ---------------------------------------------------------
    # Opening Range
    # ---------------------------------------------------------

    opening_high, opening_low = get_opening_range(session_df)

    if opening_high is None or opening_low is None:
        return None

    # ---------------------------------------------------------
    # Previous day High / Low
    # ---------------------------------------------------------

    previous_day_high = float(previous_session["High"].max())
    previous_day_low = float(previous_session["Low"].min())

    # ---------------------------------------------------------
    # Candle quality
    # ---------------------------------------------------------

    bullish_candle = _is_strong_bullish_candle(latest)
    bearish_candle = _is_strong_bearish_candle(latest)

    # ---------------------------------------------------------
    # Breakout / Breakdown state
    # ---------------------------------------------------------

    confirmed_breakout = ltp > opening_high
    confirmed_breakdown = ltp < opening_low

    # Price distance from Opening Range boundary.
    # This allows an early/developing setup before the actual break.
    bullish_distance = max(opening_high - ltp, 0.0)
    bearish_distance = max(ltp - opening_low, 0.0)

    near_bullish_breakout = not confirmed_breakout and bullish_distance <= atr14

    near_bearish_breakdown = not confirmed_breakdown and bearish_distance <= atr14

    # ---------------------------------------------------------
    # Directional conditions
    # ---------------------------------------------------------

    bullish_ema = ltp > ema20
    bearish_ema = ltp < ema20

    bullish_vwap = ltp > vwap
    bearish_vwap = ltp < vwap

    bullish_rsi = rsi14 > 50
    bearish_rsi = rsi14 < 50

    strong_volume = rel_vol >= 2.0
    valid_volume = rel_vol >= 1.5

    above_previous_high = ltp > previous_day_high
    below_previous_low = ltp < previous_day_low

    # ---------------------------------------------------------
    # V5 SCORE
    #
    # Stock setup quality       = 60 points
    # NIFTY alignment            = 20 points
    # Sector alignment           = 10 points
    # Entry quality              = 10 points
    #
    # Maximum total              = 100
    # This is a setup-quality score, NOT a probability.
    # ---------------------------------------------------------

    bullish_stock_score = 0.0
    bearish_stock_score = 0.0

    bullish_reasons: list[str] = []
    bearish_reasons: list[str] = []

    # ---------------------------------------------------------
    # Stock setup quality — maximum 60 points
    # ---------------------------------------------------------

    # Opening Range — 18 points
    if confirmed_breakout:
        bullish_stock_score += 18
        bullish_reasons.append("Confirmed opening range breakout")
    elif near_bullish_breakout:
        bullish_stock_score += 9
        bullish_reasons.append("Price approaching opening range high")

    if confirmed_breakdown:
        bearish_stock_score += 18
        bearish_reasons.append("Confirmed opening range breakdown")
    elif near_bearish_breakdown:
        bearish_stock_score += 9
        bearish_reasons.append("Price approaching opening range low")

    # EMA trend — 10 points
    if bullish_ema:
        bullish_stock_score += 10
        bullish_reasons.append("Price above 20 EMA")

    if bearish_ema:
        bearish_stock_score += 10
        bearish_reasons.append("Price below 20 EMA")

    # VWAP — 10 points
    if bullish_vwap:
        bullish_stock_score += 10
        bullish_reasons.append("Price above VWAP")

    if bearish_vwap:
        bearish_stock_score += 10
        bearish_reasons.append("Price below VWAP")

    # RSI quality — 7 points
    if bullish_rsi:
        if 55 <= rsi14 <= 65:
            bullish_stock_score += 7
            bullish_reasons.append(f"Healthy bullish RSI zone ({rsi14:.1f})")
        elif 65 < rsi14 <= 75:
            bullish_stock_score += 3
            bullish_reasons.append(f"Strong bullish momentum ({rsi14:.1f})")
        elif rsi14 > 75:
            bullish_reasons.append(
                f"RSI extended at {rsi14:.1f} - chase risk"
            )

    if bearish_rsi:
        if 35 <= rsi14 <= 45:
            bearish_stock_score += 7
            bearish_reasons.append(f"Healthy bearish RSI zone ({rsi14:.1f})")
        elif 25 <= rsi14 < 35:
            bearish_stock_score += 3
            bearish_reasons.append(f"Strong bearish momentum ({rsi14:.1f})")
        elif rsi14 < 25:
            bearish_reasons.append(
                f"RSI oversold at {rsi14:.1f} - bounce risk"
            )

    # Volume — 10 points
    if valid_volume:
        bullish_stock_score += 7
        bearish_stock_score += 7

        bullish_reasons.append(f"Relative volume {rel_vol:.2f}x")
        bearish_reasons.append(f"Relative volume {rel_vol:.2f}x")

    if strong_volume:
        bullish_stock_score += 3
        bearish_stock_score += 3

    # Previous day level — 3 points
    if above_previous_high:
        bullish_stock_score += 3
        bullish_reasons.append("Price above previous day high")

    if below_previous_low:
        bearish_stock_score += 3
        bearish_reasons.append("Price below previous day low")

    # Candle quality — 2 points
    if bullish_candle:
        bullish_stock_score += 2
        bullish_reasons.append("Strong bullish candle")

    if bearish_candle:
        bearish_stock_score += 2
        bearish_reasons.append("Strong bearish candle")

    # ---------------------------------------------------------
    # VWAP over-extension penalty
    # ---------------------------------------------------------

    distance_from_vwap = abs(ltp - vwap)

    if atr14 > 0:
        vwap_distance_atr = distance_from_vwap / atr14

        if vwap_distance_atr > 2.5:

            if bullish_stock_score > 0:
                bullish_stock_score -= 5
                bullish_reasons.append(
                    "Price extended >2.5 ATR from VWAP"
                )

            if bearish_stock_score > 0:
                bearish_stock_score -= 5
                bearish_reasons.append(
                    "Price extended >2.5 ATR from VWAP"
                )

    bullish_stock_score = min(60.0, max(0.0, bullish_stock_score))
    bearish_stock_score = min(60.0, max(0.0, bearish_stock_score))

    # ---------------------------------------------------------
    # Select stock direction BEFORE market/sector context
    # ---------------------------------------------------------

    if bullish_stock_score >= bearish_stock_score:
        direction = SignalType.BULLISH
        stock_score = bullish_stock_score
        reasons = bullish_reasons
        confirmed = confirmed_breakout
        developing = near_bullish_breakout
    else:
        direction = SignalType.BEARISH
        stock_score = bearish_stock_score
        reasons = bearish_reasons
        confirmed = confirmed_breakdown
        developing = near_bearish_breakdown

    # ---------------------------------------------------------
    # Trade levels
    #
    # Entry is the actual Opening Range breakout/breakdown
    # trigger. The latest candle confirms the move but does
    # not redefine the trigger price.
    # ---------------------------------------------------------

    if direction == SignalType.BULLISH:

        # Bullish breakout trigger
        entry_price = opening_high

        # Protective stop below the opening range / VWAP
        stop_loss = min(
            opening_low,
            vwap,
        )

        # Safety fallback
        if stop_loss >= entry_price:
            stop_loss = entry_price - atr14

        risk_amount = entry_price - stop_loss

        if risk_amount <= 0:
            return None

        target_1 = entry_price + (risk_amount * 1.5)
        target_2 = entry_price + (risk_amount * 2.5)

    else:

        # Bearish breakdown trigger
        entry_price = opening_low

        # Protective stop above the opening range / VWAP
        stop_loss = max(
            opening_high,
            vwap,
        )

        # Safety fallback
        if stop_loss <= entry_price:
            stop_loss = entry_price + atr14

        risk_amount = stop_loss - entry_price

        if risk_amount <= 0:
            return None

        target_1 = entry_price - (risk_amount * 1.5)
        target_2 = entry_price - (risk_amount * 2.5)

    # ---------------------------------------------------------
    # V5 Market + Sector Context
    # ---------------------------------------------------------

    if context is None:
        return None

    context = apply_context_scores(
        context,
        direction.value,
    )

    market_score = context.market_score
    sector_score = context.sector_score

    if market_score > 0:
        reasons.append(
            f"NIFTY aligned {context.nifty_direction} "
            f"({context.nifty_change_pct:+.2f}%)"
        )
    elif market_score < 0:
        reasons.append(
            f"NIFTY against setup "
            f"({context.nifty_change_pct:+.2f}%)"
        )
    else:
        reasons.append(
            f"NIFTY neutral ({context.nifty_change_pct:+.2f}%)"
        )

    if sector_score > 0:
        reasons.append(
            f"Sector aligned {context.sector_direction} "
            f"({context.sector_change_pct:+.2f}%)"
        )
    elif sector_score < 0:
        reasons.append(
            f"Sector against setup "
            f"({context.sector_change_pct:+.2f}%)"
        )
    else:
        if context.sector_direction == "NEUTRAL":
            reasons.append("Sector context neutral")
        else:
            reasons.append("Sector benchmark unavailable")

    # ---------------------------------------------------------
    # Entry quality — maximum 10 points
    #
    # Measure how close the current price is to a meaningful
    # breakout/breakdown trigger.
    #
    # For confirmed setups, the trigger is already crossed.
    # We therefore judge how far price has moved beyond the
    # breakout/breakdown level and penalize excessive extension.
    # ---------------------------------------------------------

    entry_quality_score = 0.0

    if atr14 > 0:

        if direction == SignalType.BULLISH:

            if confirmed_breakout:
                extension = max(ltp - opening_high, 0.0)
            else:
                extension = max(opening_high - ltp, 0.0)

        else:

            if confirmed_breakdown:
                extension = max(opening_low - ltp, 0.0)
            else:
                extension = max(ltp - opening_low, 0.0)

        extension_atr = extension / atr14

        if extension_atr <= 0.25:
            entry_quality_score = 10.0
            reasons.append("Entry zone close to breakout trigger")

        elif extension_atr <= 0.50:
            entry_quality_score = 7.0
            reasons.append("Entry zone reasonably close to trigger")

        elif extension_atr <= 1.00:
            entry_quality_score = 4.0
            reasons.append("Entry zone somewhat extended")

        else:
            entry_quality_score = 0.0
            reasons.append("Price extended from trigger - avoid chasing")

    else:
        entry_quality_score = 0.0

    # ---------------------------------------------------------
    # Final V5 score
    # ---------------------------------------------------------

    score = (
        stock_score
        + market_score
        + sector_score
        + entry_quality_score
    )

    score = min(100.0, max(0.0, score))

    # ---------------------------------------------------------
    # V5 Volume Confirmation Gate
    #
    # A confirmed breakout/breakdown must have meaningful
    # volume confirmation. Otherwise do not classify it as
    # a high-confidence confirmed setup.
    # ---------------------------------------------------------

    if confirmed and rel_vol < 1.5:
        return None

    # ---------------------------------------------------------
    # Setup qualification
    # ---------------------------------------------------------

    if confirmed:
        if score < MIN_CONFIDENCE_CONFIRMED:
            return None

        setup_type = (
            "CONFIRMED_BREAKOUT_LONG"
            if direction == SignalType.BULLISH
            else "CONFIRMED_BREAKDOWN_SHORT"
        )

    elif developing:
        if score < MIN_CONFIDENCE_DEVELOPING:
            return None

        setup_type = (
            "DEVELOPING_BREAKOUT_LONG"
            if direction == SignalType.BULLISH
            else "DEVELOPING_BREAKDOWN_SHORT"
        )

    else:
        return None

    # ---------------------------------------------------------
    # Final sanity checks
    # ---------------------------------------------------------

    if direction == SignalType.BULLISH:
        if not (stop_loss < entry_price < target_1 < target_2):
            return None

    else:
        if not (target_2 < target_1 < entry_price < stop_loss):
            return None

    latest_timestamp = session_df.index[-1]

    if latest_timestamp.tzinfo is not None:
        latest_timestamp = latest_timestamp.tz_convert("Asia/Kolkata")

    return PredictionSetup(
        symbol=symbol,
        name=name,
        sector=sector,
        signal_type=direction,
        setup_type=setup_type,
        ltp=round(ltp, 2),
        entry_price=round(entry_price, 2),
        stop_loss=round(stop_loss, 2),
        target_1=round(target_1, 2),
        target_2=round(target_2, 2),
        risk_amount=round(risk_amount, 2),
        risk_reward_ratio_t1="1:1.5",
        risk_reward_ratio_t2="1:2.5",
        confidence_score=round(score, 2),
        ema20=round(ema20, 2),
        rsi14=round(rsi14, 2),
        rel_vol=round(rel_vol, 2),
        vwap=round(vwap, 2),
        atr14=round(atr14, 2),
        opening_range_high=round(opening_high, 2),
        opening_range_low=round(opening_low, 2),
        previous_day_high=round(previous_day_high, 2),
        previous_day_low=round(previous_day_low, 2),
        reasons=reasons,
        last_updated=latest_timestamp.strftime("%d %b %Y, %I:%M %p"),
    )