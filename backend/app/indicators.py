"""
Quantitative Indicator Calculations: EMA (20), RSI (14), and Relative Volume (RelVol).
"""
import numpy as np
import pandas as pd
from typing import Tuple, List, Dict, Any


def calculate_ema(series: pd.Series, period: int = 20) -> pd.Series:
    """
    Calculates Exponential Moving Average (EMA).
    Formula: EMA_t = (Close_t * k) + (EMA_{t-1} * (1 - k)) where k = 2 / (period + 1)
    """
    if series.empty or len(series) == 0:
        return pd.Series(dtype=float)
    return series.ewm(span=period, adjust=False).mean()


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculates Wilder's Relative Strength Index (RSI).
    """
    if len(series) < period + 1:
        # Fallback if not enough data
        return pd.Series([50.0] * len(series), index=series.index)

    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    # Wilder's smoothing uses alpha = 1 / period
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # Replace NaN when avg_loss is 0 (RSI = 100 if gain > 0 else 50)
    rsi = rsi.fillna(100.0)
    # If both gain and loss are 0, RSI is 50
    rsi = rsi.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)
    return rsi


def calculate_relative_volume(df_15m: pd.DataFrame, lookback_candles: int = 10 * 25) -> Tuple[float, int, int]:
    """
    Calculates Relative Volume (RelVol).
    Current volume vs the rolling average volume over the lookback window.
    Standard NSE session has 25 candles of 15m (09:15 to 15:30).
    10 trading days = ~250 candles.
    Returns: (rel_vol, current_vol, avg_vol)
    """
    if df_15m.empty or 'Volume' not in df_15m.columns:
        return 1.0, 0, 0

    volumes = df_15m['Volume'].dropna()
    if len(volumes) == 0:
        return 1.0, 0, 0

    current_vol = int(volumes.iloc[-1])
    
    if len(volumes) > 1:
        # Average volume of preceding candles (up to lookback window)
        historical_vols = volumes.iloc[-min(len(volumes), lookback_candles):-1]
        avg_vol = int(historical_vols.mean()) if len(historical_vols) > 0 else current_vol
    else:
        avg_vol = current_vol

    if avg_vol <= 0:
        rel_vol = 1.0
    else:
        rel_vol = round(current_vol / avg_vol, 2)

    return rel_vol, current_vol, avg_vol
