"""
Pydantic data models for stock data, indicators, signals, and screener responses.
"""
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class SignalType(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class Candle(BaseModel):
    timestamp: str = Field(..., description="ISO timestamp or YYYY-MM-DD HH:MM")
    open: float
    high: float
    low: float
    close: float
    volume: int


class TechnicalIndicators(BaseModel):
    ema20: float
    rsi14: float
    rel_vol: float
    current_vol: int
    avg_vol_10d: int
    price_change_pct: float
    day_high: float
    day_low: float
    last_candle_high: float
    last_candle_low: float


class TradeParameters(BaseModel):
    entry_price: float
    stop_loss: float
    risk_amount: float
    target_1: float
    target_2: float
    risk_reward_ratio_t1: str = "1:1.5"
    risk_reward_ratio_t2: str = "1:2.0"


class StockSignal(BaseModel):
    symbol: str
    name: str
    sector: str
    ltp: float
    price_change_pct: float
    signal_type: SignalType
    signal_reason: List[str] = []
    is_active_signal: bool
    rel_vol: float
    trade_params: Optional[TradeParameters] = None
    indicators: TechnicalIndicators
    last_updated: str


class MarketStatus(BaseModel):
    is_open: bool
    session_message: str
    market_time_ist: str
    mode: str = "live"  # 'live' or 'simulation'
    is_holiday: bool = False
    holiday_name: Optional[str] = None
    next_holiday_notice: Optional[str] = None
    next_trading_session: Optional[str] = None


class ScreenerResponse(BaseModel):
    total_scanned: int
    active_signals_count: int
    bullish_count: int
    bearish_count: int
    neutral_count: int
    bullish_ratio: float
    market_sentiment: str
    market_status: MarketStatus
    last_refreshed: str
    stocks: List[StockSignal]


class StockHistoryResponse(BaseModel):
    symbol: str
    name: str
    sector: str
    timeframe: str = "15m"
    candles: List[Candle]
    ema20_series: List[Dict[str, Any]]
    rsi_series: List[Dict[str, Any]]
    trade_params: Optional[TradeParameters] = None
    signal_type: SignalType = SignalType.NEUTRAL

class PredictionSetup(BaseModel):
    symbol: str
    name: str
    sector: str

    signal_type: SignalType
    setup_type: str

    ltp: float
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float

    risk_amount: float
    risk_reward_ratio_t1: str
    risk_reward_ratio_t2: str

    confidence_score: float

    ema20: float
    rsi14: float
    rel_vol: float
    vwap: float
    atr14: float

    opening_range_high: float
    opening_range_low: float
    previous_day_high: float
    previous_day_low: float

    reasons: List[str]
    last_updated: str


class PredictionResponse(BaseModel):
    market_status: MarketStatus
    scan_time: str

    total_scanned: int
    setups_found: int

    top_setups: List[PredictionSetup]