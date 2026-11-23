from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class V13Risk(BaseModel):
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    risk_amount: Optional[float] = None
    risk_reward_t1: Optional[str] = None
    risk_reward_t2: Optional[str] = None


class V13Indicators(BaseModel):
    ema20: Optional[float] = None
    rsi14: Optional[float] = None
    rel_vol: Optional[float] = None
    vwap: Optional[float] = None
    atr14: Optional[float] = None
    true_velocity: Optional[float] = None
    breakout_distance_atr: Optional[float] = None


class V13Confirmation(BaseModel):
    opening_range_high: Optional[float] = None
    opening_range_low: Optional[float] = None
    previous_day_high: Optional[float] = None
    previous_day_low: Optional[float] = None
    reasons: list[str] = []
    penalties: list[str] = []


class V13Signal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    name: str
    sector: str
    direction: str
    setup: str
    stage: str
    score: float
    signal_time: str

    market: dict[str, Any] = {}
    price: Optional[float] = None
    risk: V13Risk
    indicators: V13Indicators
    confirmation: V13Confirmation
