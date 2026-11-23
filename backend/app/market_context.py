from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from .config import SECTOR_BENCHMARKS


import pandas as pd

import yfinance as yf


@dataclass
class MarketContext:
    """
    Market and sector context used by Prediction V5.

    Scores are directional context, not probability.
    """

    nifty_direction: str = "NEUTRAL"
    nifty_change_pct: float = 0.0

    sector_direction: str = "NEUTRAL"
    sector_change_pct: float = 0.0

    market_score: float = 0.0
    sector_score: float = 0.0


def calculate_direction(
    change_pct: float,
    bullish_threshold: float = 0.20,
    bearish_threshold: float = -0.20,
) -> str:
    """
    Convert percentage movement into a simple market direction.
    """

    if change_pct >= bullish_threshold:
        return "BULLISH"

    if change_pct <= bearish_threshold:
        return "BEARISH"

    return "NEUTRAL"


def calculate_alignment_score(
    stock_direction: str,
    context_direction: str,
    max_score: float,
) -> float:
    """
    Reward alignment and penalize strong disagreement.

    Returns a score between -max_score and +max_score.
    """

    if stock_direction == "NEUTRAL":
        return 0.0

    if context_direction == "NEUTRAL":
        return 0.0

    if stock_direction == context_direction:
        return max_score

    return -max_score


def build_market_context(
    nifty_change_pct: float,
    sector_change_pct: float,
) -> MarketContext:
    """
    Build directional context from NIFTY and sector movement.
    """

    nifty_direction = calculate_direction(nifty_change_pct)

    sector_direction = calculate_direction(sector_change_pct)

    return MarketContext(
        nifty_direction=nifty_direction,
        nifty_change_pct=round(float(nifty_change_pct), 2),
        sector_direction=sector_direction,
        sector_change_pct=round(float(sector_change_pct), 2),
    )


def apply_context_scores(
    context: MarketContext,
    stock_direction: str,
) -> MarketContext:
    """
    Calculate market and sector alignment scores
    for the selected stock direction.
    """

    context.market_score = calculate_alignment_score(
        stock_direction=stock_direction,
        context_direction=context.nifty_direction,
        max_score=20.0,
    )

    context.sector_score = calculate_alignment_score(
        stock_direction=stock_direction,
        context_direction=context.sector_direction,
        max_score=10.0,
    )

    return context


def get_nifty_change_pct() -> float:
    """
    Get latest available NIFTY 50 session percentage change.
    """

    try:
        df = yf.Ticker("^NSEI").history(period="5d", interval="1d")

        if df is None or df.empty or len(df) < 2:
            return 0.0

        latest_close = float(df["Close"].iloc[-1])
        previous_close = float(df["Close"].iloc[-2])

        if previous_close <= 0:
            return 0.0

        return ((latest_close - previous_close) / previous_close) * 100.0

    except Exception as e:
        print(f"NIFTY context fetch failed: {e}")
        return 0.0


def get_sector_change_pct(
    sector_ticker: str,
) -> float:
    """
    Get latest available percentage change for a sector benchmark.

    The ticker is supplied by the caller so we can later map
    NSE sectors to suitable Yahoo Finance benchmarks.
    """

    if not sector_ticker:
        return 0.0

    try:
        df = yf.Ticker(sector_ticker).history(period="5d", interval="1d")

        if df is None or df.empty or len(df) < 2:
            return 0.0

        latest_close = float(df["Close"].iloc[-1])
        previous_close = float(df["Close"].iloc[-2])

        if previous_close <= 0:
            return 0.0

        return ((latest_close - previous_close) / previous_close) * 100.0

    except Exception as e:
        print(f"Sector context fetch failed " f"for {sector_ticker}: {e}")
        return 0.0


def get_sector_benchmark_ticker(sector: str) -> str:
    return SECTOR_BENCHMARKS.get(sector, "")

def get_live_context_for_sector(sector: str) -> MarketContext:
    """
    Get market + sector context for one sector.

    This function is kept for compatibility.
    For scanning many stocks, use build_live_context_cache()
    so Yahoo data is fetched only once per benchmark.
    """

    nifty_change_pct = get_nifty_change_pct()

    sector_ticker = get_sector_benchmark_ticker(sector)

    if sector_ticker:
        sector_change_pct = get_sector_change_pct(sector_ticker)
    else:
        sector_change_pct = 0.0

    return build_market_context(
        nifty_change_pct=nifty_change_pct,
        sector_change_pct=sector_change_pct,
    )


def build_live_context_cache(sectors: list[str]) -> dict[str, MarketContext]:
    """
    Fetch NIFTY once and each unique sector benchmark once.

    This prevents hundreds of duplicate Yahoo requests during
    a 500-stock prediction scan.
    """

    nifty_change_pct = get_nifty_change_pct()

    sector_changes: dict[str, float] = {}

    for sector in sectors:
        sector_ticker = get_sector_benchmark_ticker(sector)

        if sector_ticker and sector_ticker not in sector_changes:
            sector_changes[sector_ticker] = get_sector_change_pct(
                sector_ticker
            )

    context_cache: dict[str, MarketContext] = {}

    for sector in sectors:
        sector_ticker = get_sector_benchmark_ticker(sector)

        if sector_ticker:
            sector_change_pct = sector_changes.get(
                sector_ticker,
                0.0,
            )
        else:
            sector_change_pct = 0.0

        context_cache[sector] = build_market_context(
            nifty_change_pct=nifty_change_pct,
            sector_change_pct=sector_change_pct,
        )

    return context_cache