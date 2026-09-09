"""
Core Screener and Dynamic Trade Parameter Generation Engine.
Evaluates 15-minute candle data against Feature A & Feature B requirements.
"""
import pandas as pd
from typing import Optional, Tuple, List
from .models import SignalType, TradeParameters, TechnicalIndicators, StockSignal
from .indicators import calculate_ema, calculate_rsi, calculate_relative_volume


def evaluate_stock_signal(
    symbol: str,
    name: str,
    sector: str,
    df_15m: pd.DataFrame,
    price_change_threshold: float = 1.5,
    rel_vol_threshold: float = 1.5,
    rsi_threshold: float = 50.0,
    ema_period: int = 20
) -> StockSignal:
    """
    Scans a stock on the 15-minute timeframe according to:
    1. Volatility & Momentum: Price Change % >= +1.5% (Bullish) or <= -1.5% (Bearish)
    2. Volume Filter: Relative Volume (RelVol) >= 1.5
    3. Trend Confirmation:
       - Bullish: Price > 20 EMA and RSI(14) > 50
       - Bearish: Price < 20 EMA and RSI(14) < 50
    And calculates Dynamic Entry, SL, Target 1 (1:1.5 RR) and Target 2 (1:2.0 RR).
    """
    if df_15m.empty or len(df_15m) < 2:
        indicators = TechnicalIndicators(
            ema20=0.0,
            rsi14=50.0,
            rel_vol=1.0,
            current_vol=0,
            avg_vol_10d=0,
            price_change_pct=0.0,
            day_high=0.0,
            day_low=0.0,
            last_candle_high=0.0,
            last_candle_low=0.0
        )
        return StockSignal(
            symbol=symbol,
            name=name,
            sector=sector,
            ltp=0.0,
            price_change_pct=0.0,
            signal_type=SignalType.NEUTRAL,
            signal_reason=["Insufficient candle data"],
            is_active_signal=False,
            rel_vol=1.0,
            trade_params=None,
            indicators=indicators,
            last_updated=""
        )

    df_15m = df_15m.copy()
    close_series = df_15m['Close']
    high_series = df_15m['High']
    low_series = df_15m['Low']
    open_series = df_15m['Open']

    ema_series = calculate_ema(close_series, period=ema_period)
    rsi_series = calculate_rsi(close_series, period=14)
    rel_vol, current_vol, avg_vol = calculate_relative_volume(df_15m)

    ltp = round(float(close_series.iloc[-1]), 2)
    ema20 = round(float(ema_series.iloc[-1]), 2)
    rsi14 = round(float(rsi_series.iloc[-1]), 2)

    # Breakout candle (last completed 15m candle)
    breakout_candle = df_15m.iloc[-1]
    last_candle_high = round(float(breakout_candle['High']), 2)
    last_candle_low = round(float(breakout_candle['Low']), 2)

    # Day Open / Reference Price for % Change (matches TradingView daily change)
    # Check if we have multiple trading days in the index
    if hasattr(df_15m.index, 'normalize'):
        unique_days = df_15m.index.normalize().unique()
        if len(unique_days) >= 2:
            prev_day = unique_days[-2]
            prev_day_close = float(df_15m[df_15m.index.normalize() == prev_day]['Close'].iloc[-1])
            ref_price = prev_day_close
            # Day high/low of current session
            current_day_data = df_15m[df_15m.index.normalize() == unique_days[-1]]
            day_high = round(float(current_day_data['High'].max()), 2)
            day_low = round(float(current_day_data['Low'].min()), 2)
        else:
            ref_price = float(open_series.iloc[0])
            day_high = round(float(high_series.max()), 2)
            day_low = round(float(low_series.min()), 2)
    else:
        ref_price = float(open_series.iloc[0])
        day_high = round(float(high_series.max()), 2)
        day_low = round(float(low_series.min()), 2)

    price_change_pct = round(((ltp - ref_price) / ref_price) * 100.0, 2)

    indicators = TechnicalIndicators(
        ema20=ema20,
        rsi14=rsi14,
        rel_vol=rel_vol,
        current_vol=current_vol,
        avg_vol_10d=avg_vol,
        price_change_pct=price_change_pct,
        day_high=day_high,
        day_low=day_low,
        last_candle_high=last_candle_high,
        last_candle_low=last_candle_low
    )

    # Check Criteria
    bullish_reasons = []
    bearish_reasons = []

    # Criteria 1: Volatility & Momentum
    is_bullish_momentum = price_change_pct >= price_change_threshold
    is_bearish_momentum = price_change_pct <= -price_change_threshold

    if is_bullish_momentum:
        bullish_reasons.append(f"Price Change +{price_change_pct}% >= +{price_change_threshold}%")
    if is_bearish_momentum:
        bearish_reasons.append(f"Price Change {price_change_pct}% <= -{price_change_threshold}%")

    # Criteria 2: Volume Filter
    has_rel_vol = rel_vol >= rel_vol_threshold
    if has_rel_vol:
        vol_text = f"RelVol {rel_vol}x >= {rel_vol_threshold}x"
        bullish_reasons.append(vol_text)
        bearish_reasons.append(vol_text)

    # Criteria 3: Trend Confirmation
    is_bullish_trend = (ltp > ema20) and (rsi14 > rsi_threshold)
    if is_bullish_trend:
        bullish_reasons.append(f"Price ({ltp}) > 20 EMA ({ema20}) & RSI ({rsi14}) > {rsi_threshold}")

    is_bearish_trend = (ltp < ema20) and (rsi14 < rsi_threshold)
    if is_bearish_trend:
        bearish_reasons.append(f"Price ({ltp}) < 20 EMA ({ema20}) & RSI ({rsi14}) < {rsi_threshold}")

    # Determine Signal
    is_active_bullish = is_bullish_momentum and has_rel_vol and is_bullish_trend
    is_active_bearish = is_bearish_momentum and has_rel_vol and is_bearish_trend

    signal_type = SignalType.NEUTRAL
    signal_reason: List[str] = []
    trade_params: Optional[TradeParameters] = None

    if is_active_bullish:
        signal_type = SignalType.BULLISH
        signal_reason = bullish_reasons
        entry_price = last_candle_high
        stop_loss = last_candle_low
        risk_amount = round(entry_price - stop_loss, 2)
        if risk_amount <= 0.05:
            risk_amount = round(entry_price * 0.005, 2)
            stop_loss = round(entry_price - risk_amount, 2)

        target_1 = round(entry_price + (risk_amount * 1.5), 2)
        target_2 = round(entry_price + (risk_amount * 2.0), 2)

        trade_params = TradeParameters(
            entry_price=entry_price,
            stop_loss=stop_loss,
            risk_amount=risk_amount,
            target_1=target_1,
            target_2=target_2,
            risk_reward_ratio_t1="1:1.5",
            risk_reward_ratio_t2="1:2.0"
        )

    elif is_active_bearish:
        signal_type = SignalType.BEARISH
        signal_reason = bearish_reasons
        entry_price = last_candle_low
        stop_loss = last_candle_high
        risk_amount = round(stop_loss - entry_price, 2)
        if risk_amount <= 0.05:
            risk_amount = round(entry_price * 0.005, 2)
            stop_loss = round(entry_price + risk_amount, 2)

        target_1 = round(entry_price - (risk_amount * 1.5), 2)
        target_2 = round(entry_price - (risk_amount * 2.0), 2)

        trade_params = TradeParameters(
            entry_price=entry_price,
            stop_loss=stop_loss,
            risk_amount=risk_amount,
            target_1=target_1,
            target_2=target_2,
            risk_reward_ratio_t1="1:1.5",
            risk_reward_ratio_t2="1:2.0"
        )

    else:
        entry_price = last_candle_high
        stop_loss = last_candle_low
        risk_amount = max(round(entry_price - stop_loss, 2), round(ltp * 0.005, 2))
        target_1 = round(entry_price + (risk_amount * 1.5), 2)
        target_2 = round(entry_price + (risk_amount * 2.0), 2)
        trade_params = TradeParameters(
            entry_price=entry_price,
            stop_loss=stop_loss,
            risk_amount=risk_amount,
            target_1=target_1,
            target_2=target_2,
            risk_reward_ratio_t1="1:1.5",
            risk_reward_ratio_t2="1:2.0"
        )
        signal_reason = ["Consolidating / Neutral - Awaiting Breakout Conditions"]

    last_dt = df_15m.index[-1]
    timestamp_str = last_dt.strftime("%d %b %Y, %I:%M %p") if hasattr(last_dt, 'strftime') else str(last_dt)

    return StockSignal(
        symbol=symbol,
        name=name,
        sector=sector,
        ltp=ltp,
        price_change_pct=price_change_pct,
        signal_type=signal_type,
        signal_reason=signal_reason,
        is_active_signal=(signal_type != SignalType.NEUTRAL),
        rel_vol=rel_vol,
        trade_params=trade_params,
        indicators=indicators,
        last_updated=timestamp_str
    )
