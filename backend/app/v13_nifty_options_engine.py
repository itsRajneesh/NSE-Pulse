"""
v13_nifty_options_engine.py
-------------------------------------------------------------------------------
Institutional Quantitative Intraday Options Buying Engine for NIFTY 50 (v2.3)
- Pure-Python Black-76 IV, Delta, Gamma, Theta solver (math.erf, seconds-to-expiry)
- Exact Strike-based Put-Call Parity Synthetic Forward: F_K = K + e^(rT)*(CE_mid - PE_mid)
- 4 Hard Regime Gates (Time Window, Multi-TF + Futures VWAP, ATM Straddle VWAP Decay,
  BankNifty Cross-Index Divergence + Local 5-Strike OI Wall)
- Smart Strike Selection Engine (Strictly ATM / 1-Strike ITM with |Delta| in [0.50, 0.65])
- Dual-Confirmation Entry Trigger Engine ([-5, +35] Pullback Buffer & ORB Breakout)
- Universal Capital & Risk Sizer + Full NSE F&O Statutory Charges & Slippage Engine
-------------------------------------------------------------------------------
100% Isolated Module — Zero imports or side-effects on existing V13 equity modules.
Accepts both pandas.DataFrame and pure-Python list[dict] candle sequences.
"""

from __future__ import annotations

import math
import os
import statistics
from datetime import datetime, date, time as dtime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import pandas as pd  # type: ignore
except ImportError:
    pd = None  # type: ignore

IST = timezone(timedelta(hours=5, minutes=30))
RISK_FREE_RATE = 0.068  # 6.80% RBI annualized benchmark for Black-76 discounting
SECONDS_PER_YEAR = 365.0 * 86400.0
DEFAULT_NIFTY_LOT_SIZE = 65


def round_to_nse_tick(price: float, tick: float = 0.05) -> float:
    """Round an option premium to the nearest NSE ₹0.05 tick."""
    if price <= 0 or math.isnan(price):
        return 0.05
    return round(round(price / tick) * tick, 2)


def _normalize_candles(candles: Any) -> List[Dict[str, Any]]:
    """
    Convert either a pandas.DataFrame or a list[dict] of OHLCV bars into a
    standardized list of dicts: [{'timestamp': datetime, 'open': float, 'high': float, 'low': float, 'close': float, 'volume': float}].
    """
    if candles is None:
        return []
    if isinstance(candles, list):
        return candles
    if pd is not None and isinstance(candles, pd.DataFrame):
        if candles.empty:
            return []
        out: List[Dict[str, Any]] = []
        for idx, row in candles.iterrows():
            ts = row.get("timestamp", idx)
            if hasattr(ts, "to_pydatetime"):
                ts = ts.to_pydatetime()
            out.append({
                "timestamp": ts,
                "open": float(row.get("open", row.get("Open", 0.0)) or 0.0),
                "high": float(row.get("high", row.get("High", 0.0)) or 0.0),
                "low": float(row.get("low", row.get("Low", 0.0)) or 0.0),
                "close": float(row.get("close", row.get("Close", 0.0)) or 0.0),
                "volume": float(row.get("volume", row.get("Volume", 0.0)) or 0.0),
            })
        return out
    return []


# ==============================================================================
# 1. PURE-PYTHON BLACK-76 OPTION PRICING & GREEKS ENGINE (NO SCIPY REQUIRED)
# ==============================================================================

def _norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function using math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)


def compute_seconds_to_expiry(expiry_dt: Optional[datetime], now_dt: Optional[datetime] = None) -> float:
    """
    Compute exact remaining seconds until 15:30:00 IST on expiry date.
    Clamped to a minimum of 300 seconds (5 minutes) on expiry afternoon so
    sqrt(T) never collapses to zero.
    """
    if now_dt is None:
        now_dt = datetime.now(IST)
    elif now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=IST)

    if expiry_dt is None:
        days_ahead = (3 - now_dt.weekday()) % 7
        target_date = (now_dt + timedelta(days=days_ahead)).date()
        expiry_dt = datetime.combine(target_date, dtime(15, 30), tzinfo=IST)
    elif expiry_dt.tzinfo is None:
        expiry_dt = expiry_dt.replace(tzinfo=IST)

    diff_sec = (expiry_dt - now_dt).total_seconds()
    return max(diff_sec, 300.0)


def compute_synthetic_forward_put_call_parity(
    spot_price: float,
    option_chain_rows: List[Dict[str, Any]],
    r: float = RISK_FREE_RATE,
    t_years: float = 0.01,
) -> Tuple[float, str]:
    """
    Exact Put-Call Parity Synthetic Forward calculation around Strike K:
        F_K = K + e^(r*T) * (CE_mid(K) - PE_mid(K))
    Evaluates ATM-50, ATM, and ATM+50 strikes and takes the median to eliminate
    single-strike bid-ask microstructure noise.
    """
    if spot_price <= 0:
        return 0.0, "INVALID_SPOT"

    atm_strike = int(round(spot_price / 50.0) * 50)
    target_strikes = {atm_strike - 50, atm_strike, atm_strike + 50}
    discount_inv = math.exp(r * max(t_years, 1e-6))

    synthetic_candidates: List[float] = []
    for row in option_chain_rows or []:
        strike = int(round(float(row.get("strike", 0) or 0)))
        if strike not in target_strikes:
            continue
        ce_ltp = float(row.get("ce_ltp", 0) or 0)
        pe_ltp = float(row.get("pe_ltp", 0) or 0)
        ce_bid = float(row.get("ce_bid", 0) or ce_ltp)
        ce_ask = float(row.get("ce_ask", 0) or ce_ltp)
        pe_bid = float(row.get("pe_bid", 0) or pe_ltp)
        pe_ask = float(row.get("pe_ask", 0) or pe_ltp)

        ce_mid = 0.5 * (ce_bid + ce_ask) if (ce_bid > 0 and ce_ask > 0) else ce_ltp
        pe_mid = 0.5 * (pe_bid + pe_ask) if (pe_bid > 0 and pe_ask > 0) else pe_ltp

        if ce_mid > 0.5 and pe_mid > 0.5:
            f_k = float(strike) + discount_inv * (ce_mid - pe_mid)
            if abs(f_k - spot_price) <= spot_price * 0.025:
                synthetic_candidates.append(f_k)

    if synthetic_candidates:
        return round(float(statistics.median(synthetic_candidates)), 2), "PUT_CALL_PARITY_EXACT"

    return round(float(spot_price), 2), "SPOT_FALLBACK"


def black76_price(
    forward: float,
    strike: float,
    t_years: float,
    sigma: float,
    opt_type: str,
    r: float = RISK_FREE_RATE,
) -> float:
    """Compute Black-76 theoretical option price for Call ('CE') or Put ('PE')."""
    if forward <= 0 or strike <= 0 or t_years <= 0 or sigma <= 0:
        intrinsic = max(0.0, forward - strike) if opt_type == "CE" else max(0.0, strike - forward)
        return intrinsic

    sqrt_t = math.sqrt(t_years)
    vol_sqrt_t = sigma * sqrt_t
    d1 = (math.log(forward / strike) + 0.5 * sigma * sigma * t_years) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    df = math.exp(-r * t_years)

    if opt_type.upper() == "CE":
        return df * (forward * _norm_cdf(d1) - strike * _norm_cdf(d2))
    else:
        return df * (strike * _norm_cdf(-d2) - forward * _norm_cdf(-d1))


def solve_black76_iv(
    market_price: float,
    forward: float,
    strike: float,
    t_years: float,
    opt_type: str,
    r: float = RISK_FREE_RATE,
    fallback_vix_pct: float = 14.0,
) -> float:
    """
    Hybrid Newton-Raphson + Bisection Implied Volatility solver for Black-76.
    Returns annualized volatility in decimal (e.g., 0.145 for 14.5%).
    """
    fallback_sigma = max(0.06, min(fallback_vix_pct / 100.0, 0.85))
    if market_price <= 0.05 or forward <= 0 or strike <= 0 or t_years <= 0:
        return fallback_sigma

    df = math.exp(-r * t_years)
    intrinsic = df * (max(0.0, forward - strike) if opt_type.upper() == "CE" else max(0.0, strike - forward))
    if market_price <= intrinsic + 0.10:
        return max(0.06, fallback_sigma * 0.85)

    low_vol = 0.03
    high_vol = 1.50
    sigma = fallback_sigma
    sqrt_t = math.sqrt(t_years)

    for _ in range(25):
        theo = black76_price(forward, strike, t_years, sigma, opt_type, r)
        diff = theo - market_price
        if abs(diff) < 1e-3:
            return round(max(0.04, min(sigma, 1.50)), 6)

        if diff > 0:
            high_vol = min(high_vol, sigma)
        else:
            low_vol = max(low_vol, sigma)

        vol_sqrt_t = sigma * sqrt_t
        d1 = (math.log(forward / strike) + 0.5 * sigma * sigma * t_years) / vol_sqrt_t
        vega = df * forward * sqrt_t * _norm_pdf(d1)

        if vega > 1e-4:
            next_sigma = sigma - (diff / vega)
            if low_vol < next_sigma < high_vol:
                sigma = next_sigma
            else:
                sigma = 0.5 * (low_vol + high_vol)
        else:
            sigma = 0.5 * (low_vol + high_vol)

    return round(max(0.04, min(sigma, 1.50)), 6)


def compute_black76_greeks(
    market_price: float,
    forward: float,
    strike: float,
    seconds_to_expiry: float,
    opt_type: str,
    r: float = RISK_FREE_RATE,
    fallback_vix_pct: float = 14.0,
) -> Dict[str, float]:
    """
    Compute exact Black-76 IV (%), Delta, Gamma, Vega, and informational Theta/hr.
    Because sigma * sqrt(T) is invariant under Black-76 when the same (F, T)
    is used for IV inversion and Delta evaluation, Delta is 100% distortion-free.
    """
    t_years = max(seconds_to_expiry, 300.0) / SECONDS_PER_YEAR
    sigma = solve_black76_iv(
        market_price=market_price,
        forward=forward,
        strike=strike,
        t_years=t_years,
        opt_type=opt_type,
        r=r,
        fallback_vix_pct=fallback_vix_pct,
    )

    sqrt_t = math.sqrt(t_years)
    vol_sqrt_t = max(sigma * sqrt_t, 1e-6)
    d1 = (math.log(max(forward, 1.0) / max(strike, 1.0)) + 0.5 * sigma * sigma * t_years) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    df = math.exp(-r * t_years)
    pdf_d1 = _norm_pdf(d1)

    if opt_type.upper() == "CE":
        delta = df * _norm_cdf(d1)
        theta_annual = (
            -(forward * df * pdf_d1 * sigma) / (2.0 * sqrt_t)
            + r * df * forward * _norm_cdf(d1)
            - r * df * strike * _norm_cdf(d2)
        )
    else:
        delta = -df * _norm_cdf(-d1)
        theta_annual = (
            -(forward * df * pdf_d1 * sigma) / (2.0 * sqrt_t)
            - r * df * forward * _norm_cdf(-d1)
            + r * df * strike * _norm_cdf(-d2)
        )

    gamma = (df * pdf_d1) / max(forward * vol_sqrt_t, 1e-4)
    vega_1pct = (df * forward * sqrt_t * pdf_d1) * 0.01

    theta_per_day = theta_annual / 365.0
    theta_per_hour_est = theta_per_day / 6.25

    return {
        "iv_pct": round(sigma * 100.0, 2),
        "delta": round(delta, 4),
        "abs_delta": round(abs(delta), 4),
        "gamma": round(gamma, 6),
        "vega": round(vega_1pct, 2),
        "theta_day_est": round(theta_per_day, 2),
        "theta_hr_est": round(theta_per_hour_est, 2),
    }


# ==============================================================================
# 2. PURE-PYTHON TECHNICAL INDICATORS ON 5-MIN / 15-MIN INTRADAY CANDLES
# ==============================================================================

def compute_intraday_vwap_latest(candles: Any) -> float:
    """
    Compute session-anchored Intraday VWAP for the latest trading date in `candles`.
    If volume is zero across the session (e.g., Spot Index feed), gracefully falls
    back to session cumulative TWAP (typical price mean).
    """
    bars = _normalize_candles(candles)
    if not bars:
        return 0.0

    def _bar_date(b: Dict[str, Any]) -> str:
        ts = b.get("timestamp")
        if isinstance(ts, datetime):
            return ts.strftime("%Y-%m-%d")
        if isinstance(ts, str) and len(ts) >= 10:
            return ts[:10]
        return "today"

    last_date = _bar_date(bars[-1])
    session_bars = [b for b in bars if _bar_date(b) == last_date] or bars

    pv_sum = 0.0
    v_sum = 0.0
    tp_list: List[float] = []
    for b in session_bars:
        tp = (float(b["high"]) + float(b["low"]) + float(b["close"])) / 3.0
        v = max(float(b.get("volume", 0.0) or 0.0), 0.0)
        tp_list.append(tp)
        pv_sum += tp * v
        v_sum += v

    if v_sum > 0:
        return round(pv_sum / v_sum, 2)
    return round(sum(tp_list) / max(len(tp_list), 1), 2)


def compute_ema_latest(closes: List[float], period: int = 20) -> float:
    if not closes:
        return 0.0
    alpha = 2.0 / (period + 1.0)
    ema_val = float(closes[0])
    for c in closes[1:]:
        ema_val = (float(c) - ema_val) * alpha + ema_val
    return round(ema_val, 2)


def compute_wilder_rsi_latest(closes: List[float], period: int = 14) -> float:
    if len(closes) < 3:
        return 50.0
    alpha = 1.0 / float(period)
    avg_gain = 0.0
    avg_loss = 0.0
    for i in range(1, len(closes)):
        diff = float(closes[i]) - float(closes[i - 1])
        gain = max(diff, 0.0)
        loss = max(-diff, 0.0)
        if i == 1:
            avg_gain = gain
            avg_loss = loss
        else:
            avg_gain = (gain - avg_gain) * alpha + avg_gain
            avg_loss = (loss - avg_loss) * alpha + avg_loss

    if avg_loss <= 1e-9:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def compute_wilder_atr_and_adx(candles: Any, period: int = 14) -> Dict[str, float]:
    """
    Compute Wilder's ATR(14), ADX(14), prev ADX(14), +DI(14), and -DI(14) in pure Python.
    """
    bars = _normalize_candles(candles)
    if len(bars) < period + 2:
        return {
            "atr": 18.0,
            "adx": 18.0,
            "adx_prev": 18.0,
            "plus_di": 20.0,
            "minus_di": 20.0,
        }

    alpha = 1.0 / float(period)
    atr_val = max(float(bars[0]["high"]) - float(bars[0]["low"]), 1.0)
    plus_dm_ema = 0.0
    minus_dm_ema = 0.0
    adx_val = 18.0
    adx_prev = 18.0
    plus_di = 20.0
    minus_di = 20.0

    for i in range(1, len(bars)):
        h = float(bars[i]["high"])
        l = float(bars[i]["low"])
        prev_h = float(bars[i - 1]["high"])
        prev_l = float(bars[i - 1]["low"])
        prev_c = float(bars[i - 1]["close"])

        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        up_move = h - prev_h
        down_move = prev_l - l

        pdm = up_move if (up_move > down_move and up_move > 0) else 0.0
        mdm = down_move if (down_move > up_move and down_move > 0) else 0.0

        atr_val = (tr - atr_val) * alpha + atr_val
        plus_dm_ema = (pdm - plus_dm_ema) * alpha + plus_dm_ema
        minus_dm_ema = (mdm - minus_dm_ema) * alpha + minus_dm_ema

        denom = max(atr_val, 1e-6)
        plus_di = 100.0 * (plus_dm_ema / denom)
        minus_di = 100.0 * (minus_dm_ema / denom)
        di_sum = plus_di + minus_di
        dx = (100.0 * abs(plus_di - minus_di) / di_sum) if di_sum > 1e-6 else 0.0

        adx_prev = adx_val
        adx_val = (dx - adx_val) * alpha + adx_val

    return {
        "atr": round(atr_val, 2),
        "adx": round(adx_val, 2),
        "adx_prev": round(adx_prev, 2),
        "plus_di": round(plus_di, 2),
        "minus_di": round(minus_di, 2),
    }


def resample_5m_to_15m_closes(candles_5m: Any) -> List[float]:
    """Group 5-minute bars into 15-minute buckets and return 15m closes."""
    bars = _normalize_candles(candles_5m)
    if not bars:
        return []
    closes_15m: List[float] = []
    for i in range(0, len(bars), 3):
        chunk = bars[i : i + 3]
        if chunk:
            closes_15m.append(float(chunk[-1]["close"]))
    return closes_15m


# ==============================================================================
# 3. UNIVERSAL CAPITAL, RISK SIZER & NSE STATUTORY CHARGES CALCULATOR
# ==============================================================================

MAX_NSE_EXECUTABLE_FREEZE_QTY = 1755  # Exactly 27 lots * 65 (Zerodha/NSE Official Single-Order Freeze Limit)
MAX_FREEZE_LOTS = 27                  # 1755 // 65
DEFAULT_MAX_SYSTEM_LOTS_CAP = 150     # System safety ceiling default (~9,750 qty)


def get_max_system_lots_cap() -> int:
    """
    Dynamically resolves the system lot ceiling from NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP.
    Guarantees safe fallback to 150 lots if unset, empty, non-numeric, or <= 0.
    Tolerates float-string representations (e.g. '150.0') via int(float(...)).
    """
    try:
        raw_val = os.getenv("NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP", str(DEFAULT_MAX_SYSTEM_LOTS_CAP))
        if raw_val is None:
            return DEFAULT_MAX_SYSTEM_LOTS_CAP
        clean_str = str(raw_val).strip()
        if not clean_str:
            return DEFAULT_MAX_SYSTEM_LOTS_CAP
        parsed = int(float(clean_str))
        return parsed if parsed > 0 else DEFAULT_MAX_SYSTEM_LOTS_CAP
    except (ValueError, TypeError, Exception):
        return DEFAULT_MAX_SYSTEM_LOTS_CAP


MAX_SYSTEM_LOTS_CAP = get_max_system_lots_cap()


def compute_iceberg_slices(total_lots: int, max_slice_lots: int = MAX_FREEZE_LOTS) -> List[int]:
    """Splits total lots into legal executable order slices strictly <= max_slice_lots (27 lots = 1,755 qty)."""
    eff_total = max(int(total_lots or 0), 0)
    eff_max = max(int(max_slice_lots or MAX_FREEZE_LOTS), 1)
    slices: List[int] = []
    remaining = eff_total
    while remaining > 0:
        chunk = min(remaining, eff_max)
        slices.append(chunk)
        remaining -= chunk
    return slices


def compute_weighted_slice_entry(base_ltp: float, slices: List[int]) -> float:
    """
    Simulates real-world order book depth sweep across iceberg slices:
    - Leg 1: Fills at base_ltp (top of book)
    - Leg 2+: Sweeps next depth rows (+0.15 pts / 3 NSE ticks per subsequent leg)
    """
    if not slices or len(slices) <= 1:
        return round_to_nse_tick(base_ltp)
    slice_fills = [round_to_nse_tick(base_ltp + (i * 0.15)) for i in range(len(slices))]
    weighted_entry = sum(s * p for s, p in zip(slices, slice_fills)) / max(sum(slices), 1)
    return round_to_nse_tick(weighted_entry)


def compute_nse_option_statutory_charges(
    entry_premium: float,
    exit_premium: float,
    lots: int,
    lot_size: int = DEFAULT_NIFTY_LOT_SIZE,
    brokerage_per_order: float = 20.0,
    total_executed_legs: Optional[int] = None,
) -> Dict[str, float]:
    """
    Calculate exact Indian NSE Equity Options Intraday Statutory Charges:
    - Brokerage: ₹20 per executed order leg (default 2 legs = ₹40 per simple trade pair, or dynamic multi-leg iceberg)
    - STT (Securities Transaction Tax): 0.10% on Sell Turnover
    - NSE Exchange Transaction Charge: 0.03503% on Total Turnover (Buy + Sell)
    - SEBI Turnover Fees: 0.0001% (₹10 per Crore) on Total Turnover
    - Stamp Duty: 0.003% on Buy Turnover
    - GST: 18% on (Brokerage + Exchange Txn + SEBI Fees)
    """
    eff_lots = max(int(lots), 1)
    qty = eff_lots * max(int(lot_size), 1)
    buy_turnover = max(entry_premium, 0.0) * qty
    sell_turnover = max(exit_premium, 0.0) * qty
    total_turnover = buy_turnover + sell_turnover

    legs_count = max(int(total_executed_legs), 2) if total_executed_legs is not None else 2
    brokerage = float(legs_count) * brokerage_per_order
    stt = sell_turnover * 0.0010
    exch_txn = total_turnover * 0.0003503
    sebi_fee = total_turnover * 0.000001
    stamp_duty = buy_turnover * 0.00003
    gst = 0.18 * (brokerage + exch_txn + sebi_fee)

    total_charges = brokerage + stt + exch_txn + sebi_fee + stamp_duty + gst
    return {
        "qty": qty,
        "buy_turnover": round(buy_turnover, 2),
        "sell_turnover": round(sell_turnover, 2),
        "brokerage": round(brokerage, 2),
        "stt": round(stt, 2),
        "exchange_txn": round(exch_txn, 2),
        "gst": round(gst, 2),
        "stamp_and_sebi": round(stamp_duty + sebi_fee, 2),
        "total_charges": round(total_charges, 2),
        "charges_per_lot": round(total_charges / eff_lots, 2),
        "breakeven_pts": round(total_charges / max(qty, 1), 2),
        "executed_legs": legs_count,
    }


def compute_universal_position_sizing(
    capital_inr: float,
    risk_mode: str,
    risk_value: float,
    entry_premium: float,
    sl_premium: float,
    t1_premium: float,
    t2_premium: float,
    lot_size: int = DEFAULT_NIFTY_LOT_SIZE,
    spread_pts: float = 0.35,
    max_outlay_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Universal Capital & Risk Sizer that works dynamically for ANY capital (₹10k to ₹1Cr+)
    and ANY risk preference (% of Capital or Fixed ₹ per trade).
    Enforces Guard 3 (20.0-pt Sizing Denominator Floor to prevent 5-lot inflation on tight candles)
    and Zerodha-Style Auto-Slice Iceberg Execution (1,755 Qty / 27 Lots per slice).
    """
    capital = max(float(capital_inr or 0.0), 1000.0)
    lot_sz = max(int(lot_size or DEFAULT_NIFTY_LOT_SIZE), 1)
    mode = str(risk_mode or "PERCENT").upper()

    if mode == "FIXED_INR":
        risk_budget_inr = max(float(risk_value or 500.0), 100.0)
        effective_risk_pct = round((risk_budget_inr / capital) * 100.0, 2)
    else:
        effective_risk_pct = max(float(risk_value or 2.0), 0.1)
        risk_budget_inr = round(capital * (effective_risk_pct / 100.0), 2)

    sl_pts = max(round(entry_premium - sl_premium, 2), 1.0)
    t1_pts = max(round(t1_premium - entry_premium, 2), 1.0)
    t2_pts = max(round(t2_premium - entry_premium, 2), 1.0)

    # Guard 3 (Refinement #1): Keep chart sl_pts unchanged for fast T1/+2.0R targets,
    # but floor the sizing denominator at 20.0 pts so tight 12-14pt candles never inflate 3 lots into 5 lots!
    sizing_sl_pts = max(sl_pts, 20.0)

    slippage_pts_est = round(max(float(spread_pts or 0.30), 0.40), 2)
    slippage_per_lot_inr = round(slippage_pts_est * lot_sz, 2)
    raw_sl_loss_per_lot = round(sl_pts * lot_sz, 2)
    sizing_sl_loss_per_lot = round(sizing_sl_pts * lot_sz, 2)
    capital_per_lot = round(entry_premium * lot_sz, 2)

    # 1. Statutory Breakdown: Separate Order-Flat Brokerage from Variable Per-Lot Taxes
    one_lot_charges_sl = compute_nse_option_statutory_charges(
        entry_premium=entry_premium,
        exit_premium=sl_premium,
        lots=1,
        lot_size=lot_sz,
    )
    flat_order_brokerage_gst = round(
        one_lot_charges_sl["brokerage"] + (0.18 * one_lot_charges_sl["brokerage"]), 2
    )  # ₹40 + 18% GST = ₹47.20
    variable_charges_per_lot = round(
        one_lot_charges_sl["total_charges"] - flat_order_brokerage_gst, 2
    )  # STT + Exch Txn + SEBI + Stamp + Txn GST
    variable_risk_per_lot = round(
        sizing_sl_loss_per_lot + variable_charges_per_lot + slippage_per_lot_inr, 2
    )

    # 2. Pure Algebraic Sizing: Deduct Fixed Order Brokerage First
    net_risk_budget_for_lots = max(0.0, risk_budget_inr - flat_order_brokerage_gst)
    lots_by_risk = int(math.floor(net_risk_budget_for_lots / max(variable_risk_per_lot, 1.0)))

    # 3. Institutional Auto-Slice Iceberg Engine: Exact 1,755 Qty (27 Lots) Executable Freeze Limit
    max_freeze_lots = max(1, MAX_NSE_EXECUTABLE_FREEZE_QTY // lot_sz)  # 27 lots at 65 lot size

    # Dynamic Capital Outlay Protection (% of capital) from argument or .env (e.g. 30, 50, 100)
    if max_outlay_pct is not None:
        raw_outlay = float(max_outlay_pct)
    else:
        try:
            import os
            raw_outlay = float(str(os.getenv("NIFTY_OPTIONS_MAX_OUTLAY_PCT", "30")).strip())
        except Exception:
            raw_outlay = 30.0

    parsed_outlay_pct = (raw_outlay / 100.0) if raw_outlay > 1.0 else raw_outlay
    MAX_OPTION_OUTLAY_PCT = max(0.05, min(parsed_outlay_pct, 1.0))
    outlay_pct_label = f"{int(round(MAX_OPTION_OUTLAY_PCT * 100))}%"

    max_outlay_capital = capital * MAX_OPTION_OUTLAY_PCT
    lots_by_capital = int(math.floor(max_outlay_capital / max(capital_per_lot, 1.0)))

    # Dynamically resolve system safety ceiling per calculation (supports runtime os.environ overrides)
    system_lots_cap = get_max_system_lots_cap()
    allowed_lots = max(0, min(lots_by_risk, lots_by_capital, system_lots_cap))
    display_lots = max(allowed_lots, 1)
    display_qty = display_lots * lot_sz

    # Auto-Slice Iceberg decomposition for orders > 27 lots (1,755 qty)
    entry_slices = compute_iceberg_slices(display_lots, max_freeze_lots)
    entry_legs = max(len(entry_slices), 1)
    is_iceberg = entry_legs > 1
    weighted_entry_prem = compute_weighted_slice_entry(entry_premium, entry_slices)
    iceberg_sweep_pts = round(max(weighted_entry_prem - entry_premium, 0.0), 2)

    t1_lots = 0 if display_lots == 1 else math.ceil(display_lots / 2)
    runner_lots = display_lots - t1_lots
    t1_slices = compute_iceberg_slices(t1_lots, max_freeze_lots) if t1_lots > 0 else []
    runner_slices = compute_iceberg_slices(runner_lots, max_freeze_lots) if runner_lots > 0 else []
    pre_t1_total_legs = entry_legs * 2
    post_t1_total_legs = entry_legs + len(t1_slices) + len(runner_slices)

    # 4. Compute True Multi-Lot Execution Financials (with per-leg brokerage & book-sweep awareness)
    charges_sl = compute_nse_option_statutory_charges(
        weighted_entry_prem, sl_premium, display_lots, lot_sz, total_executed_legs=pre_t1_total_legs
    )
    charges_t1 = compute_nse_option_statutory_charges(
        weighted_entry_prem, t1_premium, display_lots, lot_sz, total_executed_legs=post_t1_total_legs
    )
    charges_t2 = compute_nse_option_statutory_charges(
        weighted_entry_prem, t2_premium, display_lots, lot_sz, total_executed_legs=post_t1_total_legs
    )

    total_slippage_inr = round((slippage_pts_est + iceberg_sweep_pts) * display_qty, 2)
    net_max_loss_inr = round((sl_pts * display_qty) + charges_sl["total_charges"] + total_slippage_inr, 2)
    net_t1_profit_inr = round((t1_pts * display_qty) - charges_t1["total_charges"] - total_slippage_inr, 2)
    net_t2_profit_inr = round((t2_pts * display_qty) - charges_t2["total_charges"] - total_slippage_inr, 2)

    net_rr_t1 = round(net_t1_profit_inr / max(net_max_loss_inr, 1.0), 2)
    net_rr_t2 = round(net_t2_profit_inr / max(net_max_loss_inr, 1.0), 2)

    # 5. Effective Risk Per Lot (Exact Paisa Match between Top Bar and Trade Card)
    effective_risk_per_lot_inr = round(net_max_loss_inr / display_lots, 2)

    min_capital_for_1_lot_by_risk = (
        round((variable_risk_per_lot + flat_order_brokerage_gst) / (effective_risk_pct / 100.0), 0)
        if effective_risk_pct > 0
        else capital_per_lot
    )
    min_capital_recommended = max(min_capital_for_1_lot_by_risk, round(capital_per_lot / MAX_OPTION_OUTLAY_PCT, 0))

    if allowed_lots <= 0:
        if lots_by_capital <= 0:
            sizing_status = "INSUFFICIENT_BUYING_POWER"
            sizing_note = (
                f"1 Lot ({lot_sz} qty) requires ₹{capital_per_lot:,.0f} outlay, which exceeds available {outlay_pct_label} capital "
                f"outlay budget (₹{max_outlay_capital:,.0f}). Minimum total capital required: ₹{(capital_per_lot / MAX_OPTION_OUTLAY_PCT):,.0f}."
            )
        else:
            sizing_status = "INSUFFICIENT_RISK_BUDGET"
            sizing_note = (
                f"1 Lot all-in SL risk is ₹{(variable_risk_per_lot + flat_order_brokerage_gst):,.0f}, which exceeds "
                f"your ₹{risk_budget_inr:,.0f} risk budget. Minimum capital at {effective_risk_pct:.1f}% risk for 1 lot: ₹{min_capital_recommended:,.0f}."
            )
    elif is_iceberg:
        sizing_status = "AUTO_SLICED_ICEBERG"
        slices_str = "+".join(f"{s}L" for s in entry_slices)
        sizing_note = (
            f"Auto-Sliced Iceberg: {allowed_lots} Lots ({allowed_lots * lot_sz} qty) split into "
            f"{entry_legs} Legs [{slices_str}] within 1,755 Qty ({max_freeze_lots}L) NSE Freeze Limit."
        )
    elif lots_by_capital < lots_by_risk:
        sizing_status = "CAPPED_BY_OUTLAY_LIMIT"
        sizing_note = (
            f"Sized to {allowed_lots} Lot(s) ({allowed_lots * lot_sz} qty) — capped by {outlay_pct_label} Max Outlay "
            f"Protection (₹{max_outlay_capital:,.0f})."
        )
    else:
        sizing_status = "OPTIMAL"
        sizing_note = (
            f"Optimal {allowed_lots} Lot(s) ({allowed_lots * lot_sz} qty) within ₹{risk_budget_inr:,.0f} "
            f"risk budget ({effective_risk_pct:.2f}% of ₹{capital:,.0f})."
        )

    return {
        "capital_inr": round(capital, 2),
        "risk_mode": mode,
        "risk_value": round(float(risk_value), 2),
        "effective_risk_pct": effective_risk_pct,
        "risk_budget_inr": risk_budget_inr,
        "lot_size": lot_sz,
        "allowed_lots": allowed_lots,
        "allowed_qty": allowed_lots * lot_sz,
        "study_lots": display_lots,
        "study_qty": display_qty,
        "is_iceberg": is_iceberg,
        "entry_slices": entry_slices,
        "entry_legs": entry_legs,
        "t1_lots": t1_lots,
        "runner_lots": runner_lots,
        "t1_slices": t1_slices,
        "runner_slices": runner_slices,
        "max_freeze_qty": MAX_NSE_EXECUTABLE_FREEZE_QTY,
        "max_freeze_lots": max_freeze_lots,
        "max_system_lots_cap": system_lots_cap,
        "weighted_entry_premium": weighted_entry_prem,
        "sizing_sl_pts_floor": sizing_sl_pts,
        "max_outlay_pct": int(round(MAX_OPTION_OUTLAY_PCT * 100)),
        "max_outlay_capital_inr": round(max_outlay_capital, 2),
        "capital_per_lot_inr": capital_per_lot,
        "capital_required_inr": round(capital_per_lot * display_lots, 2),
        "capital_utilization_pct": round(((capital_per_lot * display_lots) / capital) * 100.0, 2),
        "raw_sl_loss_per_lot_inr": raw_sl_loss_per_lot,
        "all_in_risk_per_lot_inr": effective_risk_per_lot_inr,
        "estimated_charges_inr": charges_sl["total_charges"],
        "estimated_slippage_inr": total_slippage_inr,
        "breakeven_points": round(charges_sl["breakeven_pts"] + slippage_pts_est + iceberg_sweep_pts, 2),
        "net_max_loss_inr": net_max_loss_inr,
        "net_max_loss_pct_capital": round((net_max_loss_inr / capital) * 100.0, 2),
        "net_t1_profit_inr": net_t1_profit_inr,
        "net_t2_profit_inr": net_t2_profit_inr,
        "net_rr_t1": net_rr_t1,
        "net_rr_t2": net_rr_t2,
        "min_risk_for_1_lot_inr": round(variable_risk_per_lot + flat_order_brokerage_gst, 2),
        "min_capital_for_1_lot_inr": min_capital_recommended,
        "sizing_status": sizing_status,
        "sizing_note": sizing_note,
        "charges_breakdown": charges_sl,
    }


# ==============================================================================
# 4. NIFTY-PULSE QUANT v2.3 MASTER EVALUATION PIPELINE (GATES -> STRIKE -> SIGNAL)
# ==============================================================================

def evaluate_nifty_options_quant_pipeline(
    market_bundle: Dict[str, Any],
    capital_inr: float = 100000.0,
    risk_mode: str = "PERCENT",
    risk_value: float = 2.0,
    lot_size: int = DEFAULT_NIFTY_LOT_SIZE,
    max_outlay_pct: Optional[float] = None,
    now_dt: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    End-to-End Quantitative Pipeline for NIFTY 50 Intraday Options Buying:
    - Evaluates Module 1 (4 Hard Regime Gates + Straddle VWAP + BankNifty + Local OI Wall)
    - Evaluates Module 2 (Smart Strike Selection Engine: ATM vs 1-Strike ITM with Black-76 Greeks)
    - Evaluates Module 3 (Dual-Confirmation Entry Trigger Engine: Pullback [-5,+35] & ORB Breakout)
    - Evaluates Module 4 (Dynamic Delta-Floor SL, T1/T2, 20-Min Time-Stop & Universal Capital Sizing)
    """
    if now_dt is None:
        now_dt = datetime.now(IST)
    elif now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=IST)

    feed_mode: str = market_bundle.get("feed_mode", "DEGRADED")
    is_full_fyers: bool = feed_mode == "FULL"

    spot_ltp = float(market_bundle.get("spot_ltp", 0.0) or 0.0)
    india_vix = float(market_bundle.get("india_vix", 14.0) or 14.0)
    futures_ltp = float(market_bundle.get("futures_ltp", 0.0) or 0.0)
    banknifty_ltp = float(market_bundle.get("banknifty_ltp", 0.0) or 0.0)

    spot_5m_bars = _normalize_candles(market_bundle.get("spot_5m"))
    futures_5m_bars = _normalize_candles(market_bundle.get("futures_5m"))
    banknifty_5m_bars = _normalize_candles(market_bundle.get("banknifty_5m"))
    option_chain: List[Dict[str, Any]] = market_bundle.get("option_chain", [])
    expiry_dt: Optional[datetime] = market_bundle.get("expiry_dt")
    expiry_str: str = market_bundle.get("expiry_str", "Nearest Weekly")
    option_candles_5m: Dict[str, Any] = market_bundle.get("option_candles_5m") or {}

    seconds_to_expiry = compute_seconds_to_expiry(expiry_dt, now_dt)
    t_years = seconds_to_expiry / SECONDS_PER_YEAR
    dte_days = max(0, (expiry_dt.date() - now_dt.date()).days) if expiry_dt else 2

    # 1. Determine Implied / Futures Forward Price F
    if futures_ltp > 0:
        forward_price = round(futures_ltp, 2)
        forward_source = "FYERS_FUTURES_LTP"
    else:
        forward_price, forward_source = compute_synthetic_forward_put_call_parity(
            spot_price=spot_ltp,
            option_chain_rows=option_chain,
            r=RISK_FREE_RATE,
            t_years=t_years,
        )

    # 2. Compute 5m and 15m technical series on NIFTY Spot & Futures
    if spot_5m_bars:
        closes_5m = [float(b["close"]) for b in spot_5m_bars]
        if spot_ltp <= 0:
            spot_ltp = closes_5m[-1]
        spot_vwap = compute_intraday_vwap_latest(spot_5m_bars)
        spot_ema20_5m = compute_ema_latest(closes_5m, 20)
        spot_rsi_5m = compute_wilder_rsi_latest(closes_5m, 14)
        adx_bundle = compute_wilder_atr_and_adx(spot_5m_bars, 14)

        closes_15m = resample_5m_to_15m_closes(spot_5m_bars)
        spot_ema20_15m = compute_ema_latest(closes_15m, 20) if closes_15m else spot_ema20_5m
        day_open = float(spot_5m_bars[0].get("open", spot_ltp)) if spot_5m_bars else spot_ltp
        spot_change = round(spot_ltp - day_open, 2)
        spot_change_pct = round((spot_change / day_open) * 100, 2) if day_open > 0 else 0.0
    else:
        spot_vwap = spot_ltp
        spot_ema20_5m = spot_ltp
        spot_ema20_15m = spot_ltp
        spot_rsi_5m = 50.0
        adx_bundle = {"atr": 20.0, "adx": 18.0, "adx_prev": 18.0, "plus_di": 20.0, "minus_di": 20.0}
        spot_change = 0.0
        spot_change_pct = 0.0

    if futures_5m_bars:
        futures_vwap = compute_intraday_vwap_latest(futures_5m_bars)
        if futures_ltp <= 0:
            futures_ltp = round(float(futures_5m_bars[-1]["close"]), 2)
        anchor_price = futures_ltp
        anchor_vwap = futures_vwap
        vwap_source = "NIFTY_FUTURES_REAL_VOLUME_VWAP"
    else:
        futures_vwap = spot_vwap
        anchor_price = spot_ltp
        anchor_vwap = spot_vwap
        vwap_source = "SPOT_TWAP_ANCHOR_DEGRADED"

    # 3. Enrich Option Chain with Exact Black-76 IV & Greeks
    atm_strike = int(round(spot_ltp / 50.0) * 50) if spot_ltp > 0 else 25000
    enriched_chain: List[Dict[str, Any]] = []
    local_strikes_set = {atm_strike - 100, atm_strike - 50, atm_strike, atm_strike + 50, atm_strike + 100}

    local_ce_oi_sum = 0
    local_pe_oi_sum = 0
    local_ce_doi_sum = 0
    local_pe_doi_sum = 0
    atm_row_enriched: Optional[Dict[str, Any]] = None

    for row in option_chain:
        k = int(round(float(row.get("strike", 0) or 0)))
        if k <= 0:
            continue
        ce_ltp = float(row.get("ce_ltp", 0.0) or 0.0)
        pe_ltp = float(row.get("pe_ltp", 0.0) or 0.0)

        ce_greeks = compute_black76_greeks(
            market_price=ce_ltp,
            forward=forward_price,
            strike=k,
            seconds_to_expiry=seconds_to_expiry,
            opt_type="CE",
            fallback_vix_pct=india_vix,
        )
        pe_greeks = compute_black76_greeks(
            market_price=pe_ltp,
            forward=forward_price,
            strike=k,
            seconds_to_expiry=seconds_to_expiry,
            opt_type="PE",
            fallback_vix_pct=india_vix,
        )

        ce_oi = int(row.get("ce_oi", 0) or 0)
        pe_oi = int(row.get("pe_oi", 0) or 0)
        ce_doi = int(row.get("ce_chg_oi", 0) or 0)
        pe_doi = int(row.get("pe_chg_oi", 0) or 0)

        if k in local_strikes_set:
            local_ce_oi_sum += ce_oi
            local_pe_oi_sum += pe_oi
            local_ce_doi_sum += ce_doi
            local_pe_doi_sum += pe_doi

        ce_bid = float(row.get("ce_bid", 0.0) or ce_ltp)
        ce_ask = float(row.get("ce_ask", 0.0) or ce_ltp)
        pe_bid = float(row.get("pe_bid", 0.0) or pe_ltp)
        pe_ask = float(row.get("pe_ask", 0.0) or pe_ltp)

        ce_spread_pct = round(((ce_ask - ce_bid) / max(ce_ltp, 1.0)) * 100.0, 2) if ce_ask > ce_bid else 0.15
        pe_spread_pct = round(((pe_ask - pe_bid) / max(pe_ltp, 1.0)) * 100.0, 2) if pe_ask > pe_bid else 0.15

        item = {
            **row,
            "strike": k,
            "is_atm": k == atm_strike,
            "ce_iv": ce_greeks["iv_pct"],
            "ce_delta": ce_greeks["delta"],
            "ce_gamma": ce_greeks["gamma"],
            "ce_theta_hr": ce_greeks["theta_hr_est"],
            "ce_spread_pct": ce_spread_pct,
            "pe_iv": pe_greeks["iv_pct"],
            "pe_delta": pe_greeks["delta"],
            "pe_gamma": pe_greeks["gamma"],
            "pe_theta_hr": pe_greeks["theta_hr_est"],
            "pe_spread_pct": pe_spread_pct,
        }
        if k == atm_strike:
            atm_row_enriched = item
        enriched_chain.append(item)

    local_pcr = round(local_pe_oi_sum / max(local_ce_oi_sum, 1), 2) if local_ce_oi_sum > 0 else 1.0

    # ==========================================================================
    # MODULE 1: 4 HARD REGIME GATES EVALUATION
    # ==========================================================================
    t_now = now_dt.time()
    is_weekday = now_dt.weekday() < 5
    in_entry_window = is_weekday and (dtime(9, 25) <= t_now <= dtime(14, 15))
    in_market_hours = is_weekday and (dtime(9, 15) <= t_now <= dtime(15, 30))

    gate_a_pass = in_entry_window
    if not is_weekday or not in_market_hours:
        gate_a_reason = f"Market Closed ({now_dt.strftime('%H:%M IST')}) — Displaying EOD/Last Session Quant State"
    elif t_now < dtime(9, 25):
        gate_a_reason = "09:15–09:25 IST Opening Whip Filter Active (Wait for 09:25 bar)"
    elif t_now > dtime(14, 15):
        gate_a_reason = "Post-14:15 IST Late-Session Gamma/Theta Block Active (No Fresh Entries)"
    else:
        gate_a_reason = f"Active Intraday Entry Window ({now_dt.strftime('%H:%M IST')})"

    bull_trend = (
        spot_ltp > spot_ema20_5m
        and spot_ltp >= spot_ema20_15m * 0.9995
        and anchor_price >= anchor_vwap
        and adx_bundle["plus_di"] >= adx_bundle["minus_di"]
    )
    bear_trend = (
        spot_ltp < spot_ema20_5m
        and spot_ltp <= spot_ema20_15m * 1.0005
        and anchor_price <= anchor_vwap
        and adx_bundle["minus_di"] > adx_bundle["plus_di"]
    )
    if bull_trend:
        directional_bias = "BULLISH_CE"
        gate_b_pass = True
        gate_b_reason = (
            f"Bullish Alignment: Spot ({spot_ltp:.1f}) > 5m/15m EMA20 ({spot_ema20_5m:.1f}/{spot_ema20_15m:.1f}) "
            f"& Anchor > VWAP ({anchor_vwap:.1f})"
        )
    elif bear_trend:
        directional_bias = "BEARISH_PE"
        gate_b_pass = True
        gate_b_reason = (
            f"Bearish Alignment: Spot ({spot_ltp:.1f}) < 5m/15m EMA20 ({spot_ema20_5m:.1f}/{spot_ema20_15m:.1f}) "
            f"& Anchor < VWAP ({anchor_vwap:.1f})"
        )
    else:
        gate_b_pass = False
        # Institutional Hierarchical Consensus:
        # Strict point-based buffer (+-3.0 pts on Nifty Spot), NOT percentage multiplier!
        if anchor_price >= anchor_vwap and spot_ltp >= (spot_ema20_15m - 3.0):
            directional_bias = "BULLISH_CE"
            gate_b_reason = (
                f"Bullish Pullback (Gate B Blocked): Spot ({spot_ltp:.1f}) holding above VWAP ({anchor_vwap:.1f}) "
                f"& 15m EMA ({spot_ema20_15m:.1f}), testing 5m EMA ({spot_ema20_5m:.1f})"
            )
        elif anchor_price <= anchor_vwap and spot_ltp <= (spot_ema20_15m + 3.0):
            directional_bias = "BEARISH_PE"
            gate_b_reason = (
                f"Bearish Pullback (Gate B Blocked): Spot ({spot_ltp:.1f}) holding below VWAP ({anchor_vwap:.1f}) "
                f"& 15m EMA ({spot_ema20_15m:.1f}), testing 5m EMA ({spot_ema20_5m:.1f})"
            )
        else:
            # Fallback strictly anchored to institutional VWAP
            directional_bias = "BULLISH_CE" if anchor_price >= anchor_vwap else "BEARISH_PE"
            gate_b_reason = (
                f"Mixed/Chop Regime: Spot {spot_ltp:.1f} vs VWAP {anchor_vwap:.1f}, "
                f"5m EMA {spot_ema20_5m:.1f}, 15m EMA {spot_ema20_15m:.1f}"
            )

    atm_ce_ltp = float(atm_row_enriched.get("ce_ltp", 120.0)) if atm_row_enriched else 120.0
    atm_pe_ltp = float(atm_row_enriched.get("pe_ltp", 120.0)) if atm_row_enriched else 120.0
    atm_straddle_ltp = round(atm_ce_ltp + atm_pe_ltp, 2)

    atm_ce_bars = _normalize_candles(option_candles_5m.get(f"{atm_strike}_CE"))
    atm_pe_bars = _normalize_candles(option_candles_5m.get(f"{atm_strike}_PE"))
    if atm_ce_bars and atm_pe_bars:
        ce_vwap = compute_intraday_vwap_latest(atm_ce_bars)
        pe_vwap = compute_intraday_vwap_latest(atm_pe_bars)
        atm_straddle_vwap = round(ce_vwap + pe_vwap, 2)
        straddle_source = "LIVE_OPTION_5M_VWAP"
    else:
        atm_straddle_vwap = float(market_bundle.get("straddle_session_vwap", atm_straddle_ltp) or atm_straddle_ltp)
        straddle_source = "SESSION_TRACKED_STRADDLE_VWAP"

    adx_val = adx_bundle["adx"]
    adx_prev = adx_bundle["adx_prev"]
    straddle_melting = (atm_straddle_ltp < atm_straddle_vwap * 0.985) and (adx_val < 20.0)
    vix_ok = 10.5 <= india_vix <= 26.0
    adx_ok = adx_val >= 18.5 and (adx_val >= adx_prev - 1.0)

    gate_c_pass = (not straddle_melting) and vix_ok and adx_ok
    if straddle_melting:
        gate_c_reason = (
            f"THETA TRAP DETECTED: ATM Straddle (₹{atm_straddle_ltp:.1f}) melting below Straddle VWAP "
            f"(₹{atm_straddle_vwap:.1f}) with weak ADX ({adx_val:.1f})"
        )
    elif not adx_ok:
        if adx_val < 18.5:
            gate_c_reason = f"Low Momentum: 5m ADX(14) is {adx_val:.1f} (prev {adx_prev:.1f}, requires >= 18.5)"
        else:
            gate_c_reason = (
                f"ADX Momentum Cooling: 5m ADX(14) dipped from {adx_prev:.1f} to {adx_val:.1f} "
                f"({adx_val - adx_prev:+.1f} > -1.0 max slope drop)"
            )
    elif not vix_ok:
        gate_c_reason = f"VIX Regime Alert: India VIX at {india_vix:.2f} (outside 10.5–26.0 normal band)"
    else:
        gate_c_reason = (
            f"Momentum & Vol Healthy: ADX {adx_val:.1f} | VIX {india_vix:.2f} | "
            f"ATM Straddle ₹{atm_straddle_ltp:.1f} vs VWAP ₹{atm_straddle_vwap:.1f}"
        )

    bn_diverging = False
    bn_status_text = "BYPASSED_DEGRADED"
    if len(banknifty_5m_bars) >= 4:
        bn_vwap = compute_intraday_vwap_latest(banknifty_5m_bars)
        bn_close = float(banknifty_5m_bars[-1]["close"])
        bn_ret_15m = ((bn_close - float(banknifty_5m_bars[-4]["close"])) / max(bn_close, 1.0)) * 100.0
        if directional_bias == "BULLISH_CE" and bn_close < bn_vwap and bn_ret_15m < -0.25:
            bn_diverging = True
            bn_status_text = f"BEARISH_DIVERGENCE ({bn_ret_15m:+.2f}% < VWAP)"
        elif directional_bias == "BEARISH_PE" and bn_close > bn_vwap and bn_ret_15m > 0.25:
            bn_diverging = True
            bn_status_text = f"BULLISH_DIVERGENCE ({bn_ret_15m:+.2f}% > VWAP)"
        else:
            bn_status_text = f"ALIGNED ({bn_ret_15m:+.2f}%)"

    oi_wall_blocked = False
    if directional_bias == "BULLISH_CE":
        if local_pcr < 0.65 and local_ce_doi_sum > max(local_pe_doi_sum * 1.8, 100000):
            oi_wall_blocked = True
    else:
        if local_pcr > 1.45 and local_pe_doi_sum > max(local_ce_doi_sum * 1.8, 100000):
            oi_wall_blocked = True

    gate_d_pass = (not bn_diverging) and (not oi_wall_blocked)
    if bn_diverging:
        gate_d_reason = f"BankNifty Cross-Index Divergence: {bn_status_text}"
    elif oi_wall_blocked:
        gate_d_reason = f"Institutional OI Wall Blocking Trend (Local 5-Strike PCR: {local_pcr:.2f})"
    else:
        gate_d_reason = f"Internals Aligned: Local 5-Strike PCR {local_pcr:.2f} | BankNifty: {bn_status_text}"

    gates = [
        {
            "id": "GATE_A_TIME",
            "name": "Gate A: Intraday Timing Window (09:25–14:15 IST)",
            "passed": gate_a_pass,
            "status": "PASS" if gate_a_pass else ("AFTER_HOURS" if not in_market_hours else "BLOCKED"),
            "detail": gate_a_reason,
        },
        {
            "id": "GATE_B_MTF_VWAP",
            "name": "Gate B: 5m/15m EMA20 + Futures VWAP Consensus",
            "passed": gate_b_pass,
            "status": "PASS" if gate_b_pass else "BLOCKED",
            "detail": gate_b_reason,
        },
        {
            "id": "GATE_C_STRADDLE_DECAY",
            "name": "Gate C: ATM Straddle VWAP Anti-Decay & ADX(14)",
            "passed": gate_c_pass,
            "status": "PASS" if gate_c_pass else "BLOCKED",
            "detail": gate_c_reason,
        },
        {
            "id": "GATE_D_INTERNALS",
            "name": "Gate D: BankNifty Confirmation & Local 5-Strike OI",
            "passed": gate_d_pass,
            "status": "PASS" if gate_d_pass else "BLOCKED",
            "detail": gate_d_reason,
        },
    ]

    # ==========================================================================
    # MODULE 2: SMART STRIKE SELECTION ENGINE (ATM vs 1-STRIKE ITM, |Delta| 0.50-0.65)
    # ==========================================================================
    opt_side = "CE" if directional_bias == "BULLISH_CE" else "PE"
    itm_strike = (atm_strike - 50) if opt_side == "CE" else (atm_strike + 50)
    chain_by_strike = {r["strike"]: r for r in enriched_chain}
    selected_contract: Optional[Dict[str, Any]] = None

    target_delta = 0.60 if dte_days <= 1 else 0.55
    scored_candidates: List[Dict[str, Any]] = []

    for k in [itm_strike, atm_strike]:
        row = chain_by_strike.get(k)
        if not row:
            continue
        ltp = float(row.get("ce_ltp" if opt_side == "CE" else "pe_ltp", 0.0) or 0.0)
        delta_val = abs(float(row.get("ce_delta" if opt_side == "CE" else "pe_delta", 0.52) or 0.52))
        gamma_val = float(row.get("ce_gamma" if opt_side == "CE" else "pe_gamma", 0.0012) or 0.0012)
        iv_val = float(row.get("ce_iv" if opt_side == "CE" else "pe_iv", india_vix) or india_vix)
        theta_hr = float(row.get("ce_theta_hr" if opt_side == "CE" else "pe_theta_hr", -2.5) or -2.5)
        spread_pct = float(row.get("ce_spread_pct" if opt_side == "CE" else "pe_spread_pct", 0.20) or 0.20)
        bid_val = float(row.get("ce_bid" if opt_side == "CE" else "pe_bid", ltp) or ltp)
        ask_val = float(row.get("ce_ask" if opt_side == "CE" else "pe_ask", ltp) or ltp)
        oi_val = int(row.get("ce_oi" if opt_side == "CE" else "pe_oi", 0) or 0)
        doi_val = int(row.get("ce_chg_oi" if opt_side == "CE" else "pe_chg_oi", 0) or 0)
        vol_val = int(row.get("ce_volume" if opt_side == "CE" else "pe_volume", 0) or 0)
        symbol_str = str(
            row.get("ce_symbol" if opt_side == "CE" else "pe_symbol")
            or f"NIFTY {expiry_str} {k} {opt_side}"
        )

        if ltp > 5.0 and 0.45 <= delta_val <= 0.72 and spread_pct <= 0.85:
            in_sweet_spot = (0.50 <= delta_val <= 0.65)
            sweet_spot_score = 3.0 if in_sweet_spot else 1.0
            itm_shield_score = 1.0 if (dte_days <= 1 and k == itm_strike) else 0.0
            delta_distance_penalty = abs(delta_val - target_delta) * 5.0
            spread_penalty = spread_pct * 0.5
            total_score = sweet_spot_score + itm_shield_score - delta_distance_penalty - spread_penalty

            delta_status_str = "in [0.50, 0.65]" if in_sweet_spot else f"(Near-ATM {delta_val:.2f})"

            scored_candidates.append({
                "score": total_score,
                "contract": {
                    "strike": k,
                    "opt_type": opt_side,
                    "moneyness": "ATM" if k == atm_strike else "1-STRIKE ITM",
                    "symbol": symbol_str,
                    "expiry": expiry_str,
                    "dte_days": dte_days,
                    "ltp": round_to_nse_tick(ltp),
                    "bid": round_to_nse_tick(bid_val),
                    "ask": round_to_nse_tick(ask_val),
                    "spread_pts": round(max(ask_val - bid_val, 0.25), 2),
                    "spread_pct": spread_pct,
                    "iv_pct": iv_val,
                    "delta": round(delta_val if opt_side == "CE" else -delta_val, 4),
                    "abs_delta": round(delta_val, 4),
                    "gamma": gamma_val,
                    "theta_hr_est": theta_hr,
                    "oi": oi_val,
                    "chg_oi": doi_val,
                    "volume": vol_val,
                    "selection_reason": (
                        f"Selected {k} {opt_side} ({'1-Strike ITM (Gamma Shield)' if (dte_days <= 1 and k != atm_strike) else ('1-Strike ITM (Delta Sweet Spot)' if k != atm_strike else 'ATM High-Liquidity')}): "
                        f"|Delta|={delta_val:.2f} {delta_status_str}, Spread={spread_pct:.2f}%, IV={iv_val:.1f}%"
                    ),
                }
            })

    if scored_candidates:
        scored_candidates.sort(key=lambda x: x["score"], reverse=True)
        selected_contract = scored_candidates[0]["contract"]

    if selected_contract is None:
        fallback_k = itm_strike if dte_days <= 1 else atm_strike
        est_ltp = round_to_nse_tick(max(atm_straddle_ltp * 0.54, 95.0))
        g_fb = compute_black76_greeks(est_ltp, forward_price, fallback_k, seconds_to_expiry, opt_side, fallback_vix_pct=india_vix)
        selected_contract = {
            "strike": fallback_k,
            "opt_type": opt_side,
            "moneyness": "ATM" if fallback_k == atm_strike else "1-STRIKE ITM",
            "symbol": f"NIFTY {expiry_str} {fallback_k} {opt_side}",
            "expiry": expiry_str,
            "dte_days": dte_days,
            "ltp": est_ltp,
            "bid": round_to_nse_tick(est_ltp - 0.20),
            "ask": round_to_nse_tick(est_ltp + 0.20),
            "spread_pts": 0.40,
            "spread_pct": round((0.40 / max(est_ltp, 1.0)) * 100.0, 2),
            "iv_pct": g_fb["iv_pct"],
            "delta": g_fb["delta"],
            "abs_delta": g_fb["abs_delta"],
            "gamma": g_fb["gamma"],
            "theta_hr_est": g_fb["theta_hr_est"],
            "oi": 0,
            "chg_oi": 0,
            "volume": 0,
            "selection_reason": f"Fallback {fallback_k} {opt_side} (|Delta|={g_fb['abs_delta']:.2f})",
        }

    # ==========================================================================
    # MODULE 3: DUAL-CONFIRMATION ENTRY TRIGGER ENGINE (PULLBACK [-5,+35] & ORB)
    # ==========================================================================
    trigger_fired = False
    trigger_type = "WAITING_FOR_SETUP"
    trigger_reason = "Monitoring 5m candles for Institutional VWAP/EMA20 Pullback or Opening Range Breakout."
    spot_swing_stop = spot_ema20_5m - (28.0 if opt_side == "CE" else -28.0)

    if len(spot_5m_bars) >= 5:
        last_bar = spot_5m_bars[-1]
        prev_bars = spot_5m_bars[-4:-1]
        c_open = float(last_bar["open"])
        c_high = float(last_bar["high"])
        c_low = float(last_bar["low"])
        c_close = float(last_bar["close"])
        c_range = max(c_high - c_low, 0.5)
        c_body = abs(c_close - c_open)
        body_ratio = c_body / c_range

        if opt_side == "CE":
            # Guard 4: True 5m EMA20 Pullback Zone [-3.0, +15.0] pts + Active VWAP Alignment (No +35pt mid-air buys!)
            dyn_support = spot_ema20_5m
            pullback_dist = c_low - dyn_support
            pullback_touched = -3.0 <= pullback_dist <= 15.0
            bullish_close = (
                (c_close > c_open)
                and (c_close > dyn_support)
                and (c_close >= spot_vwap)
                and (anchor_price >= anchor_vwap)
                and (body_ratio >= 0.45)
            )
            rsi_ok = 50.0 <= spot_rsi_5m <= 74.0
            box_high = max(float(b["high"]) for b in prev_bars)
            box_low = min(float(b["low"]) for b in prev_bars)
            box_width = round(box_high - box_low, 2)
            max_box_width = round(max(38.0, spot_ltp * 0.0016), 2)
            orb_breakout = (
                (c_close > box_high)
                and (box_width <= max_box_width)
                and (c_close >= spot_vwap)
                and (anchor_price >= anchor_vwap)
                and (c_close > spot_ema20_5m)
                and (body_ratio >= 0.45)
                and (spot_rsi_5m >= 54.0)
            )

            spot_swing_stop = round(min(c_low, min(float(b["low"]) for b in prev_bars)) - 3.0, 2)

            if pullback_touched and bullish_close and rsi_ok:
                trigger_fired = True
                trigger_type = "VWAP_EMA20_PULLBACK_RESUMPTION"
                trigger_reason = (
                    f"5m Bullish Pullback Resumption off Dynamic Zone ({dyn_support:.1f}, "
                    f"low offset {pullback_dist:+.1f} pts in [-3,+15] buffer, Body {body_ratio*100:.0f}%, RSI {spot_rsi_5m:.1f})"
                )
            elif orb_breakout:
                trigger_fired = True
                trigger_type = "MOMENTUM_BOX_BREAKOUT"
                trigger_reason = (
                    f"5m Bullish Breakout above 3-Bar Box ({box_high:.1f}, width {box_width:.1f} pts <= {max_box_width:.1f}) "
                    f"with Body {body_ratio*100:.0f}%, RSI {spot_rsi_5m:.1f} & ADX {adx_val:.1f}"
                )
        else:
            # Guard 4: True 5m EMA20 Pullback Zone [-3.0, +15.0] pts + Active VWAP Alignment (No +35pt mid-air buys!)
            dyn_resistance = spot_ema20_5m
            pullback_dist = dyn_resistance - c_high
            pullback_touched = -3.0 <= pullback_dist <= 15.0
            bearish_close = (
                (c_close < c_open)
                and (c_close < dyn_resistance)
                and (c_close <= spot_vwap)
                and (anchor_price <= anchor_vwap)
                and (body_ratio >= 0.45)
            )
            rsi_ok = 26.0 <= spot_rsi_5m <= 50.0
            box_high = max(float(b["high"]) for b in prev_bars)
            box_low = min(float(b["low"]) for b in prev_bars)
            box_width = round(box_high - box_low, 2)
            max_box_width = round(max(38.0, spot_ltp * 0.0016), 2)
            orb_breakdown = (
                (c_close < box_low)
                and (box_width <= max_box_width)
                and (c_close <= spot_vwap)
                and (anchor_price <= anchor_vwap)
                and (c_close < spot_ema20_5m)
                and (body_ratio >= 0.45)
                and (spot_rsi_5m <= 46.0)
            )

            spot_swing_stop = round(max(c_high, max(float(b["high"]) for b in prev_bars)) + 3.0, 2)

            if pullback_touched and bearish_close and rsi_ok:
                trigger_fired = True
                trigger_type = "VWAP_EMA20_PULLBACK_RESUMPTION"
                trigger_reason = (
                    f"5m Bearish Pullback Rejection off Dynamic Zone ({dyn_resistance:.1f}, "
                    f"high offset {pullback_dist:+.1f} pts in [-3,+15] buffer, Body {body_ratio*100:.0f}%, RSI {spot_rsi_5m:.1f})"
                )
            elif orb_breakdown:
                trigger_fired = True
                trigger_type = "MOMENTUM_BOX_BREAKDOWN"
                trigger_reason = (
                    f"5m Bearish Breakdown below 3-Bar Box ({box_low:.1f}, width {box_width:.1f} pts <= {max_box_width:.1f}) "
                    f"with Body {body_ratio*100:.0f}%, RSI {spot_rsi_5m:.1f} & ADX {adx_val:.1f}"
                )

    # ==========================================================================
    # MODULE 4: OPTION SL (DELTA-FLOOR + CANDLE LOW), TARGETS & UNIVERSAL SIZING
    # ==========================================================================
    entry_prem = float(selected_contract["ltp"])
    abs_delta = max(float(selected_contract["abs_delta"]), 0.45)
    gamma_val = float(selected_contract["gamma"])

    raw_spot_sl_pts = abs(spot_ltp - spot_swing_stop)
    sl_spot_pts = round(max(22.0, min(raw_spot_sl_pts, 52.0)), 2)

    delta_gamma_sl_pts = (abs_delta * sl_spot_pts) + (0.5 * gamma_val * (sl_spot_pts ** 2))

    opt_key = f"{selected_contract['strike']}_{opt_side}"
    opt_bars = _normalize_candles(option_candles_5m.get(opt_key))
    opt_candle_sl_pts = 0.0
    if opt_bars:
        opt_last_low = float(opt_bars[-1]["low"])
        if 0 < opt_last_low < entry_prem:
            opt_candle_sl_pts = (entry_prem - opt_last_low) + 1.50

    raw_opt_sl_pts = max(delta_gamma_sl_pts, opt_candle_sl_pts)
    opt_sl_pts = round(max(10.0, min(raw_opt_sl_pts, max(entry_prem * 0.24, 14.0))), 2)

    sl_premium = round_to_nse_tick(max(entry_prem - opt_sl_pts, 2.0))
    actual_sl_pts = round(entry_prem - sl_premium, 2)

    t1_premium = round_to_nse_tick(entry_prem + (1.5 * actual_sl_pts))
    t2_premium = round_to_nse_tick(entry_prem + (2.5 * actual_sl_pts))
    trail_cost_sl = round_to_nse_tick(entry_prem + 2.0)

    sizing_report = compute_universal_position_sizing(
        capital_inr=capital_inr,
        risk_mode=risk_mode,
        risk_value=risk_value,
        entry_premium=entry_prem,
        sl_premium=sl_premium,
        t1_premium=t1_premium,
        t2_premium=t2_premium,
        lot_size=lot_size,
        spread_pts=float(selected_contract.get("spread_pts", 0.35)),
        max_outlay_pct=max_outlay_pct,
    )

    core_gates_pass = gate_b_pass and gate_c_pass and gate_d_pass
    all_gates_pass = gate_a_pass and core_gates_pass

    if all_gates_pass and trigger_fired:
        signal_state = "EXECUTE_BUY"
        signal_headline = f"BUY {selected_contract['symbol']} @ ₹{entry_prem:.2f}"
    elif core_gates_pass and not gate_a_pass and trigger_fired:
        signal_state = "READY_AFTER_HOURS_STUDY"
        signal_headline = f"SETUP ALIGNED (Outside 09:25–14:15 Window): {selected_contract['symbol']}"
    elif core_gates_pass:
        signal_state = "ARMED_WAITING_TRIGGER"
        signal_headline = f"REGIME GREEN — Waiting for 5m Pullback/Breakout on {selected_contract['symbol']}"
    else:
        signal_state = "NO_TRADE_REGIME_BLOCKED"
        blocked_names = [g["id"].replace("GATE_", "Gate ") for g in gates if not g["passed"]]
        signal_headline = f"NO-TRADE ZONE — Blocked by {', '.join(blocked_names)}"

    return {
        "generated_at": now_dt.isoformat(),
        "ist_time_str": now_dt.strftime("%d %b %Y, %I:%M:%S %p IST"),
        "feed_mode": feed_mode,
        "feed_badge": (
            "🟢 FULL MODE (Fyers v3 Live 5m Candles + Option Chain)"
            if is_full_fyers
            else "🟡 DEGRADED MODE (Free NSE/Yahoo Fallback — Connect Fyers for Live Option 5m & Futures VWAP)"
        ),
        "degraded_bypassed_checks": (
            []
            if is_full_fyers
            else [
                "NIFTY Futures Real-Volume VWAP (Using Spot Intraday TWAP + Put-Call Parity Forward)",
                "Individual Option 5m Trigger Candle Swing Low & Option Volume SMA",
                "BankNifty Futures 5m VWAP Cross-Index Filter (Using Spot Index Fallback)",
            ]
        ),
        "market_snapshot": {
            "spot_ltp": round(spot_ltp, 2),
            "spot_change": spot_change,
            "spot_change_pct": spot_change_pct,
            "futures_ltp": round(forward_price, 2),
            "forward_source": forward_source,
            "spot_vwap": spot_vwap,
            "futures_vwap": futures_vwap,
            "vwap_source": vwap_source,
            "spot_ema20_5m": spot_ema20_5m,
            "spot_ema20_15m": spot_ema20_15m,
            "spot_rsi_5m": spot_rsi_5m,
            "adx_5m": adx_bundle["adx"],
            "adx_prev_5m": adx_bundle["adx_prev"],
            "plus_di_5m": adx_bundle["plus_di"],
            "minus_di_5m": adx_bundle["minus_di"],
            "atr_5m": adx_bundle["atr"],
            "india_vix": round(india_vix, 2),
            "atm_strike": atm_strike,
            "atm_straddle_ltp": atm_straddle_ltp,
            "atm_straddle_vwap": atm_straddle_vwap,
            "straddle_source": straddle_source,
            "local_5strike_pcr": local_pcr,
            "local_ce_oi": local_ce_oi_sum,
            "local_pe_oi": local_pe_oi_sum,
            "local_ce_chg_oi": local_ce_doi_sum,
            "local_pe_chg_oi": local_pe_doi_sum,
            "banknifty_ltp": round(banknifty_ltp, 2),
            "banknifty_status": bn_status_text,
            "expiry_str": expiry_str,
            "dte_days": dte_days,
            "seconds_to_expiry": int(seconds_to_expiry),
        },
        "regime_gates": {
            "all_passed": all_gates_pass,
            "core_passed": core_gates_pass,
            "directional_bias": directional_bias,
            "gates": gates,
        },
        "selected_contract": selected_contract,
        "entry_trigger": {
            "trigger_fired": trigger_fired,
            "trigger_type": trigger_type,
            "trigger_reason": trigger_reason,
            "spot_swing_stop": round(spot_swing_stop, 2),
            "sl_spot_pts": sl_spot_pts,
        },
        "trade_plan": {
            "signal_state": signal_state,
            "signal_headline": signal_headline,
            "trigger_type": trigger_type,
            "symbol": selected_contract["symbol"],
            "strike": selected_contract["strike"],
            "opt_type": selected_contract["opt_type"],
            "moneyness": selected_contract["moneyness"],
            "entry_premium": entry_prem,
            "sl_premium": sl_premium,
            "sl_points": actual_sl_pts,
            "t1_premium": t1_premium,
            "t1_points": round(t1_premium - entry_prem, 2),
            "t2_premium": t2_premium,
            "t2_points": round(t2_premium - entry_prem, 2),
            "trail_sl_at_t1": trail_cost_sl,
            "time_stop_minutes": 20,
            "time_stop_rule": "Exit at market if held >= 20 wall-clock minutes and unrealized profit < +0.5R",
            "hard_eod_squareoff": "15:15 IST",
        },
        "position_sizing": sizing_report,
        "option_chain_window": sorted(
            [r for r in enriched_chain if abs(r["strike"] - atm_strike) <= 250],
            key=lambda x: x["strike"],
        ),
    }
