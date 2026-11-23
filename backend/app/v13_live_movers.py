"""
V13 NSE Live Top Movers: Isolated Quantitative Pipeline for Top 20 Gainers & Losers.
Zero-interference standalone engine with 4-Tier Quant Filtration, 20-EMA High-Tight Flag
execution planning, and Session Candidate Registry (anti-flicker).
"""
import os
import time
import math
from datetime import datetime
import json
from typing import Any, Optional
import pandas as pd
import pytz

from .v13_engine import normalize_nse_tick

IST_TZ = pytz.timezone('Asia/Kolkata')

# Load official NSE index constituents
_NSE_INDEX_CACHE: dict[str, set[str]] = {}
_SHORTABLE_UNIVERSE_CACHE: Optional[set[str]] = None

def _load_nse_constituents() -> dict[str, set[str]]:
    global _NSE_INDEX_CACHE
    if _NSE_INDEX_CACHE:
        return _NSE_INDEX_CACHE
    try:
        data_path = os.path.join(os.path.dirname(__file__), "data", "nse_index_constituents.json")
        if os.path.exists(data_path):
            with open(data_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
                _NSE_INDEX_CACHE = {k: set(v) for k, v in raw.items()}
    except Exception as e:
        print(f"Notice loading NSE constituents: {e}")
    return _NSE_INDEX_CACHE

def _load_fno_and_liquid_symbols() -> set[str]:
    """
    Load the short-eligible institutional universe (F&O + Nifty 50 + Nifty Next 50 + Nifty Midcap 50).
    Cached in memory for O(1) lookup across the entire 60-second evaluation cycle.
    """
    global _SHORTABLE_UNIVERSE_CACHE
    if _SHORTABLE_UNIVERSE_CACHE is not None:
        return _SHORTABLE_UNIVERSE_CACHE

    constituents = _load_nse_constituents()
    shortable: set[str] = set()
    for key in ("FNO", "NIFTY_50", "NIFTY_NEXT_50", "NIFTY_MIDCAP_50"):
        shortable.update(s.strip().upper() for s in constituents.get(key, set()))
    _SHORTABLE_UNIVERSE_CACHE = shortable
    return _SHORTABLE_UNIVERSE_CACHE

class SessionMoverRegistry:
    """
    Session-level registry for tracking Top Movers without card flickering.
    Once a mover enters Top 20 and is qualified as a RUNNER or SHORT_RUNNER, it is preserved
    in the session registry (within a 45-minute active TTL) so traders don't lose sight of active runners.
    """
    def __init__(self):
        self.registered_movers: dict[str, dict[str, Any]] = {}
        self.last_updated_date: Optional[str] = None
        self.last_eval_time: float = 0.0

    def _reset_if_new_session(self):
        try:
            from .v13_ledger import get_effective_trading_date
            today = get_effective_trading_date() or datetime.now(IST_TZ).strftime("%Y-%m-%d")
        except Exception:
            today = datetime.now(IST_TZ).strftime("%Y-%m-%d")
        if self.last_updated_date != today:
            self.registered_movers.clear()
            self.last_updated_date = today

    def get_registered(self, max_age_seconds: float = 2700.0) -> list[dict[str, Any]]:
        self._reset_if_new_session()
        now_ts = time.time()
        active: list[dict[str, Any]] = []
        for sym, item in list(self.registered_movers.items()):
            last_seen = float(item.get("_last_seen_ts") or now_ts)
            if now_ts - last_seen <= max_age_seconds:
                active.append(item)
            else:
                self.registered_movers.pop(sym, None)
        return active

    def update_candidate(self, symbol: str, mover_data: dict[str, Any]):
        self._reset_if_new_session()
        now_ts = time.time()
        stored = dict(mover_data)
        if isinstance(stored.get("trade_plan"), dict):
            stored["trade_plan"] = dict(stored["trade_plan"])
        stored["_last_seen_ts"] = now_ts
        self.registered_movers[symbol] = stored

GLOBAL_MOVER_REGISTRY = SessionMoverRegistry()


class NSELiveVariationsFetcher:
    """
    Fetches real-time Top 20 Gainers & Losers from the official NSE API
    using a persistent HTTP session with automatic Akamai cookie acquisition,
    a 25-second in-memory cache, and explicit staleness telemetry (> 5 minutes).
    """
    _cached_gainers: Optional[dict] = None
    _cached_losers: Optional[dict] = None
    _last_fetch: float = 0.0
    _last_fetch_iso: str = ""
    _session: Optional[Any] = None
    _cookies_initialized_at: float = 0.0

    @classmethod
    def _init_session(cls, force_new: bool = False) -> Any:
        """Initialize or refresh the persistent NSE HTTP session and Akamai cookies."""
        import requests
        now = time.time()
        if cls._session is None or force_new or (now - cls._cookies_initialized_at > 240.0):
            s = requests.Session()
            s.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.nseindia.com/market-data/top-gainers-losers",
                "X-Requested-With": "XMLHttpRequest",
                "Connection": "keep-alive",
            })
            try:
                # Warm up the session on the base NSE URL to acquire valid session cookies
                s.get("https://www.nseindia.com", timeout=5)
                cls._cookies_initialized_at = now
            except Exception:
                pass
            cls._session = s
        return cls._session

    @classmethod
    def get_variations(cls, force: bool = False) -> tuple[Optional[dict], Optional[dict], str, bool]:
        """
        Fetch live NSE Top 20 Gainers & Losers.
        Returns a 4-tuple: (gainers_dict, losers_dict, last_fetch_iso, is_stale).
        """
        now = time.time()
        if not force and cls._cached_gainers and cls._cached_losers and (now - cls._last_fetch < 25.0):
            return cls._cached_gainers, cls._cached_losers, cls._last_fetch_iso, False

        for attempt in range(2):
            try:
                session = cls._init_session(force_new=(attempt > 0))
                resp_g = session.get(
                    "https://www.nseindia.com/api/live-analysis-variations?index=gainers",
                    timeout=5,
                )
                resp_l = session.get(
                    "https://www.nseindia.com/api/live-analysis-variations?index=loosers",
                    timeout=5,
                )

                if resp_g.status_code in (401, 403) or resp_l.status_code in (401, 403):
                    continue

                if resp_g.status_code == 200 and resp_l.status_code == 200:
                    data_g = resp_g.json()
                    data_l = resp_l.json()
                    if data_g and data_l:
                        cls._cached_gainers = data_g
                        cls._cached_losers = data_l
                        cls._last_fetch = now
                        cls._last_fetch_iso = datetime.now(IST_TZ).isoformat()
                        return cls._cached_gainers, cls._cached_losers, cls._last_fetch_iso, False
            except Exception:
                continue

        # Fallback to last valid cache; flag as stale if older than 300 seconds (5 minutes)
        is_stale = (now - cls._last_fetch) > 300.0 if cls._last_fetch > 0 else True
        if cls._cached_gainers and cls._cached_losers:
            return cls._cached_gainers, cls._cached_losers, cls._last_fetch_iso, is_stale

        return None, None, cls._last_fetch_iso or datetime.now(IST_TZ).isoformat(), True


def _calculate_tod_rel_vol(
    session_vol: float,
    snap_vol: float,
    snap_rel_vol: float,
    snap_bar_end_iso: Optional[str] = None,
) -> float:
    """
    Time-of-Day adjusted Relative Volume with Stamped Timestamp Normalization.
    Clamps effective_now to 15:30 IST of the snapshot date to prevent off-market/weekend dilation.
    Uniform 50.0x cap applied.
    """
    if session_vol <= 0:
        return round(max(0.0, min(snap_rel_vol, 50.0)), 2)

    if snap_rel_vol > 0:
        if snap_vol > 0 and session_vol > snap_vol:
            raw_scaling = session_vol / snap_vol

            # Intra-bar elapsed time normalization with off-market clamping
            if snap_bar_end_iso:
                try:
                    now_ist = datetime.now(IST_TZ)
                    snap_end = datetime.fromisoformat(snap_bar_end_iso)
                    if snap_end.tzinfo is None:
                        snap_end = snap_end.replace(tzinfo=IST_TZ)

                    # 1. Anchor market close strictly to the snapshot date's 15:30:00 IST
                    mkt_close = snap_end.replace(hour=15, minute=30, second=0, microsecond=0)
                    effective_now = min(now_ist, mkt_close)

                    # 2. Elapsed seconds since snapshot candle close
                    delta_seconds = max(0.0, (effective_now - snap_end).total_seconds())

                    # 3. Derive total bars elapsed up to the snapshot from open (09:15 IST)
                    session_start = snap_end.replace(hour=9, minute=15, second=0, microsecond=0)
                    minutes_from_open = max(15.0, (snap_end - session_start).total_seconds() / 60.0)
                    total_bars_elapsed = max(1, int(round(minutes_from_open / 15.0)))

                    # 4. Fraction of 15m candle (clamped to 2.0 to absorb scanner delays)
                    fraction_of_bar = min(2.0, max(0.0, delta_seconds / 900.0))
                    expected_growth = 1.0 + (fraction_of_bar / total_bars_elapsed)
                    normalized_scaling = raw_scaling / expected_growth
                except Exception:
                    normalized_scaling = raw_scaling
            else:
                normalized_scaling = raw_scaling

            scaling = min(3.0, max(1.0, normalized_scaling))
            return round(min(snap_rel_vol * scaling, 50.0), 2)

        return round(min(snap_rel_vol, 50.0), 2)

    return 0.0



def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        f = float(val)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


def evaluate_mover_stock(
    stock_record: dict[str, Any],
    df_cache: Optional[dict[str, pd.DataFrame]] = None,
    rank: int = 1,
    is_gainer: bool = True,
    v13_score: Optional[float] = None,
    min_v13_score: float = 65.0,
    shortable_symbols: Optional[set[str]] = None,
) -> dict[str, Any]:
    """
    Apply 4-Tier V14 Quant Filtration Pipeline to a candidate Top Mover:
    Tier 1: Microstructure & Liquidity (Turnover >= 25 Cr, Price >= 20, EQ series)
    Tier 2: Circuit Freeze Guard (Reject locked ceiling/floor)
    Tier 3: Blow-off & Intraday Range Exhaustion Guard (Bar 1 <= 2.5x ATR14, Session < 8.0x 15m ATR14 & < 9.0%)
    Tier 4: 20-EMA High-Tight Flag Structure with Gate #0 Short Restriction & Directional NSE Tick Rounding
    """
    symbol = str(stock_record.get("symbol", "")).strip()
    name = str(stock_record.get("name", symbol))
    sector = str(stock_record.get("sector", "General"))
    snap = stock_record.get("snapshot", {})

    # Detect F&O and Shortable Liquid Universe membership
    constituents = _load_nse_constituents()
    fno_symbols = constituents.get("FNO", set())
    is_fno = symbol in fno_symbols or bool(stock_record.get("is_fno"))
    liquid_short_set = shortable_symbols if shortable_symbols is not None else _load_fno_and_liquid_symbols()
    is_shortable_liquid = is_fno or (symbol.upper() in liquid_short_set)

    price = _safe_float(snap.get("price"))
    change_pct = _safe_float(snap.get("latest_session_change_pct"))
    rel_vol = _safe_float(snap.get("rel_vol"), 0.0)
    ema20 = _safe_float(snap.get("ema20"))
    vwap = _safe_float(snap.get("vwap"), price)
    atr14 = _safe_float(snap.get("atr14"))
    rsi14 = _safe_float(snap.get("rsi14"), 50.0)
    bar_range = None

    # Estimate cumulative session volume from cached DF or proxy
    session_vol = 0.0
    snap_or_h = _safe_float(snap.get("opening_range_high"), 0.0)
    snap_or_l = _safe_float(snap.get("opening_range_low"), 0.0)
    or_high = snap_or_h if snap_or_h > 0 else None
    or_low = snap_or_l if snap_or_l > 0 else None
    or_atr14 = atr14
    daily_atr = atr14 * 4.0
    day_high = _safe_float(snap.get("high") or snap.get("high_price") or snap.get("day_high"))
    day_low = _safe_float(snap.get("low") or snap.get("low_price") or snap.get("day_low"))

    df = (df_cache.get(symbol) or df_cache.get(f"{symbol}.NS")) if df_cache else None
    if df is None:
        try:
            from .v13_scanner import get_v13_cached_df
            df = get_v13_cached_df(f"{symbol}.NS")
        except Exception:
            df = None

    if df is not None and not df.empty:
        try:
            from .v13_engine import (
                _latest_session,
                _opening_range,
                _atr,
                _daily_atr14,
                _ema,
                _session_vwap,
                _rsi,
                _relative_volume,
            )
            session = _latest_session(df)
            if not session.empty:
                session_vol = _safe_float(session["Volume"].sum())
                or_h, or_l = _opening_range(session)
                if or_h and or_h > 0:
                    or_high = _safe_float(or_h)
                if or_l and or_l > 0:
                    or_low = _safe_float(or_l)
                if not day_high and "High" in session.columns:
                    day_high = _safe_float(session["High"].max())
                if not day_low and "Low" in session.columns:
                    day_low = _safe_float(session["Low"].min())
                atr_series = _atr(df, 14)
                if atr14 <= 0 and not atr_series.empty:
                    atr14 = _safe_float(atr_series.iloc[-1])
                if not atr_series.empty:
                    or_bar_idx = max(0, len(atr_series) - len(session))
                    or_atr14 = _safe_float(atr_series.iloc[or_bar_idx], atr14)
                daily_atr = _safe_float(_daily_atr14(df, 14), atr14 * 4.0)
                if rel_vol <= 0:
                    rel_vol = _safe_float(_relative_volume(df, session), 0.0)
                live_ema = _safe_float(_ema(df["Close"], 20).iloc[-1])
                if live_ema > 0:
                    ema20 = live_ema
                vwap_series = _session_vwap(session)
                if not vwap_series.empty:
                    live_vwap = _safe_float(vwap_series.dropna().iloc[-1])
                    if live_vwap > 0:
                        vwap = live_vwap
            rsi_s = _rsi(df["Close"], 14).dropna()
            if not rsi_s.empty:
                live_rsi = _safe_float(rsi_s.iloc[-1])
                if live_rsi > 0:
                    rsi14 = live_rsi
            if "High" in df.columns and "Low" in df.columns and len(df) > 0:
                bar_range = round(_safe_float(df["High"].iloc[-1] - df["Low"].iloc[-1]), 2)
        except Exception:
            pass

    if bar_range is None and atr14 > 0:
        bar_range = round(atr14 * 0.75, 2)

    # Priority 1: Live actual turnover & volume from snapshot/NSE feed if present
    live_turnover = _safe_float(snap.get("turnover_cr") or snap.get("turnover"))
    live_vol = _safe_float(snap.get("volume") or snap.get("trade_quantity"))
    if live_vol > 0:
        session_vol = live_vol

    if live_turnover > 0:
        turnover_cr = round(live_turnover, 2)
    else:
        if session_vol <= 0 and snap.get("rel_vol"):
            # Conservative volume estimate if direct volume sum unavailable
            session_vol = max(100_000.0, rel_vol * 200_000.0)
        turnover_cr = round((session_vol * price) / 10_000_000.0, 2)

    # -------------------------------------------------------------
    # 4-TIER QUANT FILTRATION PIPELINE
    # -------------------------------------------------------------
    reasons: list[str] = []
    archetype = "OBSERVATION"
    status = "CONSOLIDATION"
    warning = None
    trade_plan = None

    # Check if stock has verified V13 badge (exempt from turnover floor)
    has_v13_badge = bool(v13_score is not None and v13_score > 0)
    if has_v13_badge and turnover_cr < 25.0:
        reasons.append(f"V13 Badge (₹{turnover_cr:.1f}Cr Turnover Exemption)")

    effective_daily_atr = daily_atr if daily_atr > 0 else (atr14 * 4.0)
    ref_or_atr = max(atr14, or_atr14, effective_daily_atr * 0.25) if atr14 > 0 else 0.0
    is_confirmed_vol_breakout = (
        rel_vol >= 1.50
        and (
            (is_gainer and or_high and price > or_high and price >= vwap)
            or (not is_gainer and or_low and price < or_low and price <= vwap)
        )
    )
    max_or_mult = 4.0 if is_confirmed_vol_breakout else 3.0

    # TIER 1: Microstructure & Base Price Floor (>= Rs 20.0, or >= Rs 50 Cr Turnover Exemption)
    is_sub_20_exempt = (price < 20.0 and turnover_cr >= 50.0)
    if is_sub_20_exempt:
        reasons.append(f"High-Turnover Penny Exemption (₹{turnover_cr:.1f}Cr ≥ ₹50Cr)")

    if price < 20.0 and not is_sub_20_exempt:
        archetype = "OBSERVATION"
        status = "SUB_20_PENNY"
        warning = f"Penny Price Guard: Price (₹{price:.2f}) below ₹20.00 floor & turnover (₹{turnover_cr:.1f}Cr) < ₹50Cr."
        reasons.append("Penny Price Guard (< ₹20 & < ₹50Cr)")
    # TIER 1B: Turnover Floor (Minimum ₹25 Crore) - bypassed for scrips carrying V13 badge
    elif turnover_cr < 25.0 and not has_v13_badge:
        archetype = "OBSERVATION"
        status = "LOW_LIQUIDITY"
        warning = f"Session Turnover ₹{turnover_cr:.1f} Cr below ₹25 Cr institutional liquidity threshold"
        reasons.append(f"Turnover ₹{turnover_cr:.1f} Cr < ₹25 Cr requirement")
    # TIER 2: True Circuit Freeze Guard (Reject genuinely locked ceiling/floor)
    # F&O stocks have dynamic operating bands and do NOT have 2%, 5%, or 10% fixed circuits.
    elif not is_fno and is_gainer and (change_pct >= 19.8 or (change_pct >= 9.9 and day_high > 0 and price >= day_high * 0.999 and bar_range == 0)):
        archetype = "EXHAUSTION_WARNING"
        status = "CIRCUIT_LOCK"
        warning = f"Stock locked at Upper Circuit Limit ({change_pct:+.1f}%). Zero sell-side depth exit risk."
        reasons.append("Upper Circuit Ceiling Shield")
    elif not is_fno and not is_gainer and (change_pct <= -19.8 or (change_pct <= -9.9 and day_low > 0 and price <= day_low * 1.001 and bar_range == 0)):
        archetype = "EXHAUSTION_WARNING"
        status = "CIRCUIT_LOCK"
        warning = f"Stock locked at Lower Circuit Limit ({change_pct:+.1f}%). Zero buyer depth exit risk."
        reasons.append("Lower Circuit Floor Shield")
    elif is_fno and (change_pct >= 19.8 or change_pct <= -19.8):
        archetype = "EXHAUSTION_WARNING"
        status = "EXTREME_VOLATILITY"
        warning = f"Extreme F&O Move ({change_pct:+.1f}%). Excessive volatility expansion risk."
        reasons.append("Extreme Volatility Shield (≥20%)")
    # TIER 3A: Opening Range Blow-off Exhaustion Guard (Stationary ref_or_atr + 4.0x Confirmed Volume Breakout Allowance)
    elif or_high and or_low and ref_or_atr > 0 and ((or_high - or_low) > (max_or_mult * ref_or_atr)):
        or_width = or_high - or_low
        atr_mult = or_width / ref_or_atr
        archetype = "EXHAUSTION_WARNING"
        status = "EXHAUSTION_ALERT"
        warning = f"Blow-off Exhaustion: Bar 1 Range ({or_width:.2f}) is {atr_mult:.1f}x Ref-ATR. Move exhausted at open."
        reasons.append(f"Opening Range Exhaustion ({atr_mult:.1f}x Ref-ATR)")
    # TIER 3B: Intraday Range Exhaustion Guard (Session Range >= 8.0x 15m ATR14 or Move >= 9.0%)
    elif (day_high > 0 and day_low > 0 and atr14 > 0 and ((day_high - day_low) >= (8.0 * atr14))) or abs(change_pct) >= 9.0:
        day_range = max(0.0, day_high - day_low)
        atr_mult = (day_range / atr14) if atr14 > 0 else 0.0
        archetype = "EXHAUSTION_WARNING"
        status = "DAILY_ATR_EXHAUSTED"
        warning = (
            f"Intraday Range Exhausted: Session Range (₹{day_range:.2f}) is {atr_mult:.1f}x 15m-ATR "
            f"({change_pct:+.1f}%). Mean-reversion trap risk."
        )
        reasons.append(f"Intraday Range Exhausted ({atr_mult:.1f}x 15m ATR / {change_pct:+.1f}%)")
    # TIER 4: 20-EMA High-Tight Flag Structure (Tradeable Runners: Bull & Bear)
    else:
        if is_gainer:
            # Bullish Criteria:
            # 1. Price strictly above or equal to session VWAP (Institutional Floor)
            # 2. Price strictly above or equal to 20-EMA (Trend Support)
            # 3. RelVol >= 1.50x
            # 4. Price within 1.5 ATR of 20-EMA (healthy high-tight flag, not sky-high extended)
            is_above_vwap = price >= vwap
            is_above_ema20 = price >= ema20
            dist_to_ema20 = (price - ema20) / atr14 if atr14 > 0 else 0.5
            is_flag_structure = is_above_vwap and is_above_ema20 and (0.0 <= dist_to_ema20 <= 1.5)

            if is_flag_structure and rel_vol >= 1.50:
                archetype = "RUNNER"
                status = "QUALIFIED_RUNNER"
                reasons.append(f"20-EMA High-Tight Flag Confirmed (RelVol {rel_vol:.1f}x)")

                # Generate 20-EMA Flag Execution Plan with V14 Structural Stop-Loss & NSE Tick Normalization
                entry = normalize_nse_tick(price, direction="BULLISH", is_sl=False)
                min_sl_dist = max(0.40 * atr14, entry * 0.005) if atr14 > 0 else (entry * 0.008)

                raw_candidates = [
                    (ema20 - (0.50 * atr14)) if (ema20 > 0 and atr14 > 0) else (entry * 0.985),
                    (entry - (1.50 * atr14)) if atr14 > 0 else (entry * 0.985),
                ]
                valid_stops = [s for s in raw_candidates if s < entry]
                raw_stop = max(valid_stops) if valid_stops else (entry - min_sl_dist)
                clamped_stop = min(raw_stop, entry - min_sl_dist)

                stop_loss = normalize_nse_tick(clamped_stop, direction="BULLISH", is_sl=True)
                risk = round(max(entry - stop_loss, 0.05), 2)
                t1 = normalize_nse_tick(entry + (1.5 * risk), direction="BULLISH", is_sl=False)
                t2 = normalize_nse_tick(entry + (2.5 * risk), direction="BULLISH", is_sl=False)

                trade_plan = {
                    "entry": entry,
                    "stop_loss": stop_loss,
                    "target_1": t1,
                    "target_2": t2,
                    "risk_amount": risk,
                    "risk_reward_t1": "1:1.5",
                    "risk_reward_t2": "1:2.5",
                    "plan_type": "20_EMA_HIGH_TIGHT_FLAG",
                    "live_risk": round(abs(price - stop_loss), 2),
                }
            else:
                archetype = "OBSERVATION"
                status = "CONSOLIDATION"
                reasons.append(f"Consolidating inside 15m structure • RelVol: {rel_vol:.1f}x")

                # Generate 20-EMA Consolidation Trade Plan (Structural Reclaim Trigger)
                # If price is below VWAP or 20-EMA, anchor entry just above the immediate reclaim hurdle.
                immediate_hurdles = [price]
                if vwap > 0:
                    immediate_hurdles.append(vwap)
                if ema20 > 0:
                    immediate_hurdles.append(ema20)

                hurdle_max = max(immediate_hurdles)
                if hurdle_max > price:
                    buffer = 0.10 if hurdle_max >= 100 else 0.05
                    raw_entry = hurdle_max + buffer
                else:
                    raw_entry = price

                entry = normalize_nse_tick(raw_entry, direction="BULLISH", is_sl=False)
                min_sl_dist = max(0.40 * atr14, entry * 0.005) if atr14 > 0 else (entry * 0.008)

                support_floor = ema20 if (0 < ema20 < entry) else (entry * 0.990)
                raw_candidates = [
                    (support_floor - (0.50 * atr14)) if atr14 > 0 else (entry * 0.985),
                    (entry - (1.50 * atr14)) if atr14 > 0 else (entry * 0.985),
                ]
                valid_stops = [s for s in raw_candidates if s < entry]
                raw_stop = max(valid_stops) if valid_stops else (entry - min_sl_dist)
                clamped_stop = min(raw_stop, entry - min_sl_dist)

                stop_loss = normalize_nse_tick(clamped_stop, direction="BULLISH", is_sl=True)
                risk = round(max(entry - stop_loss, 0.05), 2)
                t1 = normalize_nse_tick(entry + (1.5 * risk), direction="BULLISH", is_sl=False)
                t2 = normalize_nse_tick(entry + (2.5 * risk), direction="BULLISH", is_sl=False)

                trade_plan = {
                    "entry": entry,
                    "stop_loss": stop_loss,
                    "target_1": t1,
                    "target_2": t2,
                    "risk_amount": risk,
                    "risk_reward_t1": "1:1.5",
                    "risk_reward_t2": "1:2.5",
                    "plan_type": "20_EMA_CONSOLIDATION_PLAN",
                    "live_risk": round(abs(price - stop_loss), 2),
                }
        else:
            # Gate #0: Institutional Short-Selling Eligibility Guard
            if not is_shortable_liquid:
                archetype = "OBSERVATION"
                status = "CASH_SHORT_RESTRICTED"
                warning = "Non-F&O / Non-Liquid Cash Stock: Intraday short-selling restricted (High short-squeeze & MIS inventory risk)."
                reasons.append("Gate #0: Cash Short Restricted (Non-F&O)")
                trade_plan = None
            else:
                # Bearish / Loser Criteria:
                # 1. Price strictly below or equal to session VWAP (Institutional Ceiling)
                # 2. Price strictly below 20-EMA (Trend Breakdown Resistance)
                # 3. RelVol >= 1.50x
                # 4. Price within 1.5 ATR below 20-EMA (-1.5 <= dist <= 0.0, healthy bear flag, not oversold crash)
                is_below_vwap = price <= vwap
                is_below_ema20 = price < ema20
                dist_to_ema20 = (price - ema20) / atr14 if atr14 > 0 else -0.5
                is_bear_flag = is_below_vwap and is_below_ema20 and (-1.5 <= dist_to_ema20 <= 0.0)

                if is_bear_flag and rel_vol >= 1.50:
                    archetype = "SHORT_RUNNER"
                    status = "QUALIFIED_SHORT"
                    reasons.append(f"20-EMA Bear Flag Breakdown Confirmed (RelVol {rel_vol:.1f}x)")

                    # Generate 20-EMA Bear Flag Execution Plan with V14 Structural Stop-Loss & NSE Tick Normalization
                    entry = normalize_nse_tick(price, direction="BEARISH", is_sl=False)
                    min_sl_dist = max(0.40 * atr14, entry * 0.005) if atr14 > 0 else (entry * 0.008)

                    raw_candidates = [
                        (ema20 + (0.50 * atr14)) if (ema20 > 0 and atr14 > 0) else (entry * 1.015),
                        (entry + (1.50 * atr14)) if atr14 > 0 else (entry * 1.015),
                    ]
                    valid_stops = [s for s in raw_candidates if s > entry]
                    raw_stop = min(valid_stops) if valid_stops else (entry + min_sl_dist)
                    clamped_stop = max(raw_stop, entry + min_sl_dist)

                    stop_loss = normalize_nse_tick(clamped_stop, direction="BEARISH", is_sl=True)
                    risk = round(max(stop_loss - entry, 0.05), 2)
                    t1 = normalize_nse_tick(entry - (1.5 * risk), direction="BEARISH", is_sl=False)
                    t2 = normalize_nse_tick(entry - (2.5 * risk), direction="BEARISH", is_sl=False)

                    trade_plan = {
                        "entry": entry,
                        "stop_loss": stop_loss,
                        "target_1": t1,
                        "target_2": t2,
                        "risk_amount": risk,
                        "risk_reward_t1": "1:1.5",
                        "risk_reward_t2": "1:2.5",
                        "plan_type": "20_EMA_BEAR_FLAG_BREAKDOWN",
                        "live_risk": round(abs(stop_loss - price), 2),
                    }
                else:
                    archetype = "OBSERVATION"
                    status = "BEARISH_MOVER"
                    reasons.append(f"Active Selling Pressure ({change_pct:+.1f}%) • RelVol: {rel_vol:.1f}x")

                    # Generate 20-EMA Bear Consolidation Trade Plan (Structural Breakdown Trigger)
                    immediate_floors = [price]
                    if vwap > 0:
                        immediate_floors.append(vwap)
                    if ema20 > 0:
                        immediate_floors.append(ema20)

                    floor_min = min(immediate_floors)
                    if floor_min < price:
                        buffer = 0.10 if floor_min >= 100 else 0.05
                        raw_entry = floor_min - buffer
                    else:
                        raw_entry = price

                    entry = normalize_nse_tick(raw_entry, direction="BEARISH", is_sl=False)
                    min_sl_dist = max(0.40 * atr14, entry * 0.005) if atr14 > 0 else (entry * 0.008)

                    res_ceiling = ema20 if ema20 > entry else (entry * 1.010)
                    raw_candidates = [
                        (res_ceiling + (0.50 * atr14)) if atr14 > 0 else (entry * 1.015),
                        (entry + (1.50 * atr14)) if atr14 > 0 else (entry * 1.015),
                    ]
                    valid_stops = [s for s in raw_candidates if s > entry]
                    raw_stop = min(valid_stops) if valid_stops else (entry + min_sl_dist)
                    clamped_stop = max(raw_stop, entry + min_sl_dist)

                    stop_loss = normalize_nse_tick(clamped_stop, direction="BEARISH", is_sl=True)
                    risk = round(max(stop_loss - entry, 0.05), 2)
                    t1 = normalize_nse_tick(entry - (1.5 * risk), direction="BEARISH", is_sl=False)
                    t2 = normalize_nse_tick(entry - (2.5 * risk), direction="BEARISH", is_sl=False)

                    trade_plan = {
                        "entry": entry,
                        "stop_loss": stop_loss,
                        "target_1": t1,
                        "target_2": t2,
                        "risk_amount": risk,
                        "risk_reward_t1": "1:1.5",
                        "risk_reward_t2": "1:2.5",
                        "plan_type": "20_EMA_BEAR_CONSOLIDATION_PLAN",
                        "live_risk": round(abs(stop_loss - price), 2),
                    }

    return {
        "symbol": symbol,
        "name": name,
        "sector": sector,
        "rank": rank,
        "price": price,
        "change_pct": round(change_pct, 2),
        "volume": session_vol,
        "turnover_cr": turnover_cr,
        "rel_vol": round(rel_vol, 2),
        "ema20": round(ema20, 2) if ema20 > 0 else None,
        "vwap": round(vwap, 2) if vwap > 0 else None,
        "atr14": round(atr14, 2) if atr14 > 0 else None,
        "rsi14": round(rsi14, 1) if rsi14 is not None else 50.0,
        "bar_range": bar_range,
        "dist_to_ema20": round(abs(price - ema20) / atr14, 2) if (atr14 > 0 and ema20 > 0) else 0.0,
        "archetype": archetype,
        "status": status,
        "reasons": reasons,
        "warning": warning,
        "trade_plan": trade_plan,
        "is_nifty500": bool(stock_record.get("is_nifty500", True)),
        "is_fno": is_fno,
        "is_shortable_liquid": is_shortable_liquid,
        "v13_score": round(v13_score, 1) if v13_score is not None else None,
        "is_v13_active": bool(v13_score is not None and v13_score >= min_v13_score),
        "updated_at": datetime.now(IST_TZ).isoformat(),
    }


def compute_live_top_movers(
    universe: list[dict[str, Any]], 
    df_cache: Optional[dict] = None,
    category: str = "ALL",
    force: bool = False,
    v13_candidates: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """
    Pure NSE Top 20 Intersection Pipeline:
    1. Fetches official NSE Top 20 Gainers & Losers for the requested category.
    2. Filters ONLY stocks that exist in our verified Institutional Universe (1,468 Stocks / Mcap >= 1000Cr).
    3. Rejects all penny, microcap, or unlisted scrips without adding any outside stocks.
    4. Preserves exact official NSE rank (nse_rank) on every card for 100% transparency.
    5. Calculates 20-EMA High-Tight Flag, VWAP, and Trade Execution Plans.
    6. Identifies dual-confirmed V13 Active Runners (Score >= threshold ∩ 20-EMA).
    """
    cat = (category or "ALL").upper().strip()

    if not universe:
        return {
            "category": cat,
            "gainers": [],
            "losers": [],
            "runners": [],
            "short_runners": [],
            "exhaustion": [],
            "total_tracked": 0,
            "is_stale": False,
            "updated_at": datetime.now(IST_TZ).isoformat(),
        }

    # Map universe symbols to records for instant O(1) enrichment
    universe_map: dict[str, dict[str, Any]] = {
        s.get("symbol"): s for s in universe if s.get("symbol")
    }

    # Load short-eligible liquid universe once per evaluation cycle
    shortable_symbols = _load_fno_and_liquid_symbols()

    # Confluence category configuration
    is_confluence_cat = cat in ["V13_ACTIVE", "V13_CONFLUENCE", "V13_RUNNERS"]
    min_v13_score = 65.0
    try:
        from dotenv import dotenv_values
        env_backend = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        if os.path.exists(env_backend):
            live_env = dotenv_values(env_backend)
            if live_env and live_env.get("V13_ACTIVE_RUNNER_MIN_SCORE"):
                min_v13_score = float(live_env["V13_ACTIVE_RUNNER_MIN_SCORE"])
            else:
                min_v13_score = float(os.getenv("V13_ACTIVE_RUNNER_MIN_SCORE", "65"))
        else:
            min_v13_score = float(os.getenv("V13_ACTIVE_RUNNER_MIN_SCORE", "65"))
    except Exception:
        min_v13_score = 65.0

    # Build authoritative V13 Screener candidate score lookup map
    v13_score_map: dict[str, float] = {}
    if v13_candidates:
        for c in v13_candidates:
            if isinstance(c, dict):
                c_sym = str(c.get("symbol", "")).strip().upper()
                c_score = _safe_float(c.get("score"), 0.0)
                if c_sym and c_score > 0:
                    v13_score_map[c_sym] = max(v13_score_map.get(c_sym, 0.0), c_score)
            else:
                c_sym = str(getattr(c, "symbol", "")).strip().upper()
                c_score = _safe_float(getattr(c, "score", 0.0), 0.0)
                if c_sym and c_score > 0:
                    v13_score_map[c_sym] = max(v13_score_map.get(c_sym, 0.0), c_score)

    # In addition, check universe stock records if any have signals with score
    for s in universe:
        if isinstance(s, dict):
            s_sym = str(s.get("symbol", "")).strip().upper()
            if s_sym and s_sym not in v13_score_map:
                for sig in s.get("signals", []):
                    if isinstance(sig, dict):
                        sig_score = _safe_float(sig.get("score"), 0.0)
                        if sig_score > 0:
                            v13_score_map[s_sym] = max(v13_score_map.get(s_sym, 0.0), sig_score)

    # Map category to NSE API key
    nse_key_map = {
        "ALL": "allSec",
        "NIFTY_50": "NIFTY",
        "BANK_NIFTY": "BANKNIFTY",
        "NIFTY_NEXT_50": "NIFTYNEXT50",
        "FNO": "FOSec",
        "ABOVE_20": "SecGtr20",
        "BELOW_20": "SecLwr20",
    }

    # Fetch live official NSE Top 20 variations (4-tuple unpacking)
    raw_g_dict, raw_l_dict, fetch_iso, is_stale = NSELiveVariationsFetcher.get_variations(force=force)

    evaluated_gainers: list[dict[str, Any]] = []
    evaluated_losers: list[dict[str, Any]] = []
    runners: list[dict[str, Any]] = []
    short_runners: list[dict[str, Any]] = []
    exhaustion: list[dict[str, Any]] = []

    if raw_g_dict and raw_l_dict:
        if cat in ["COMBINED", "MASTER"] or is_confluence_cat:
            # =========================================================
            # MASTER / COMBINED / CONFLUENCE CATEGORY: ALL-INDICES FUSION PIPELINE
            # =========================================================
            # Extract and deduplicate items across all available indices
            indices_to_merge = [
                ("allSec", "ALL"),
                ("NIFTY", "NIFTY 50"),
                ("BANKNIFTY", "BANK NIFTY"),
                ("NIFTYNEXT50", "NEXT 50"),
                ("FOSec", "F&O"),
            ]

            # 1. Deduplicate Gainers
            combined_gainers_map: dict[str, dict[str, Any]] = {}
            for idx_key, idx_tag in indices_to_merge:
                items = raw_g_dict.get(idx_key, {}).get("data", [])
                for rank_idx, item in enumerate(items, 1):
                    sym = str(item.get("symbol", "")).strip()
                    if sym in universe_map:
                        if sym not in combined_gainers_map:
                            combined_gainers_map[sym] = {
                                "raw_item": item,
                                "best_nse_rank": rank_idx,
                                "index_tags": [idx_tag],
                            }
                        else:
                            # Keep best rank and accumulate index tags
                            existing = combined_gainers_map[sym]
                            if idx_tag not in existing["index_tags"]:
                                existing["index_tags"].append(idx_tag)
                            if rank_idx < existing["best_nse_rank"]:
                                existing["best_nse_rank"] = rank_idx

            # 2. Deduplicate Losers
            combined_losers_map: dict[str, dict[str, Any]] = {}
            for idx_key, idx_tag in indices_to_merge:
                items = raw_l_dict.get(idx_key, {}).get("data", [])
                for rank_idx, item in enumerate(items, 1):
                    sym = str(item.get("symbol", "")).strip()
                    if sym in universe_map:
                        if sym not in combined_losers_map:
                            combined_losers_map[sym] = {
                                "raw_item": item,
                                "best_nse_rank": rank_idx,
                                "index_tags": [idx_tag],
                            }
                        else:
                            existing = combined_losers_map[sym]
                            if idx_tag not in existing["index_tags"]:
                                existing["index_tags"].append(idx_tag)
                            if rank_idx < existing["best_nse_rank"]:
                                existing["best_nse_rank"] = rank_idx

            # Evaluate combined gainers sorted by % change descending
            sorted_combined_g = sorted(
                combined_gainers_map.items(),
                key=lambda x: _safe_float(x[1]["raw_item"].get("perChange")),
                reverse=True
            )
            for master_rank, (sym, c_data) in enumerate(sorted_combined_g, 1):
                item = c_data["raw_item"]
                stock_record = universe_map[sym]
                snap = dict(stock_record.get("snapshot", {}))
                snap["price"] = _safe_float(item.get("ltp"), snap.get("price"))
                snap["latest_session_change_pct"] = _safe_float(item.get("perChange"), snap.get("latest_session_change_pct"))
                if item.get("high_price"):
                    snap["high_price"] = _safe_float(item.get("high_price"))
                if item.get("low_price"):
                    snap["low_price"] = _safe_float(item.get("low_price"))
                if item.get("turnover"):
                    snap["turnover_cr"] = round(_safe_float(item.get("turnover")) / 100.0, 2)
                if item.get("trade_quantity"):
                    live_q = _safe_float(item.get("trade_quantity"))
                    snap["rel_vol"] = _calculate_tod_rel_vol(live_q, _safe_float(snap.get("volume")), _safe_float(snap.get("rel_vol"), 0.0), snap_bar_end_iso=snap.get("bar_end_time"))
                    snap["volume"] = live_q
                enriched = dict(stock_record)
                enriched["snapshot"] = snap

                c_score = v13_score_map.get(sym.upper())
                eval_item = evaluate_mover_stock(
                    enriched, 
                    df_cache=df_cache, 
                    rank=master_rank, 
                    is_gainer=True,
                    v13_score=c_score,
                    min_v13_score=min_v13_score,
                    shortable_symbols=shortable_symbols,
                )
                eval_item["rank"] = master_rank
                eval_item["nse_rank"] = c_data["best_nse_rank"]
                eval_item["index_tags"] = c_data["index_tags"]
                eval_item["turnover_cr"] = round(_safe_float(item.get("turnover", 0.0)) / 100.0, 2) if item.get("turnover") else eval_item["turnover_cr"]
                eval_item["volume"] = _safe_float(item.get("trade_quantity"), eval_item["volume"])

                # Authoritative V13 Screener Score and active status tagging
                eval_item["v13_score"] = round(c_score, 1) if c_score is not None else None
                eval_item["is_v13_active"] = bool(c_score is not None and c_score >= min_v13_score)

                if is_confluence_cat:
                    # In V13 Active Runners: Only stocks that possess a V13 score enter Top Gainers
                    if eval_item.get("v13_score") is not None and eval_item["v13_score"] > 0:
                        evaluated_gainers.append(eval_item)
                    # And only stocks that pass BOTH (V13 Active + 20-EMA High-Tight Flag) enter runners
                    if eval_item["is_v13_active"] and eval_item["archetype"] == "RUNNER":
                        runners.append(eval_item)
                    elif eval_item["archetype"] == "EXHAUSTION_WARNING":
                        exhaustion.append(eval_item)
                else:
                    evaluated_gainers.append(eval_item)
                    if eval_item["archetype"] == "RUNNER":
                        runners.append(eval_item)
                    elif eval_item["archetype"] == "EXHAUSTION_WARNING":
                        exhaustion.append(eval_item)

            # Evaluate combined losers sorted by % change ascending
            sorted_combined_l = sorted(
                combined_losers_map.items(),
                key=lambda x: _safe_float(x[1]["raw_item"].get("perChange"))
            )
            for master_rank, (sym, c_data) in enumerate(sorted_combined_l, 1):
                item = c_data["raw_item"]
                stock_record = universe_map[sym]
                snap = dict(stock_record.get("snapshot", {}))
                snap["price"] = _safe_float(item.get("ltp"), snap.get("price"))
                snap["latest_session_change_pct"] = _safe_float(item.get("perChange"), snap.get("latest_session_change_pct"))
                if item.get("high_price"):
                    snap["high_price"] = _safe_float(item.get("high_price"))
                if item.get("low_price"):
                    snap["low_price"] = _safe_float(item.get("low_price"))
                if item.get("turnover"):
                    snap["turnover_cr"] = round(_safe_float(item.get("turnover")) / 100.0, 2)
                if item.get("trade_quantity"):
                    live_q = _safe_float(item.get("trade_quantity"))
                    snap["rel_vol"] = _calculate_tod_rel_vol(live_q, _safe_float(snap.get("volume")), _safe_float(snap.get("rel_vol"), 0.0), snap_bar_end_iso=snap.get("bar_end_time"))
                    snap["volume"] = live_q
                enriched = dict(stock_record)
                enriched["snapshot"] = snap

                c_score = v13_score_map.get(sym.upper())
                eval_item = evaluate_mover_stock(
                    enriched, 
                    df_cache=df_cache, 
                    rank=master_rank, 
                    is_gainer=False,
                    v13_score=c_score,
                    min_v13_score=min_v13_score,
                    shortable_symbols=shortable_symbols,
                )
                eval_item["rank"] = master_rank
                eval_item["nse_rank"] = c_data["best_nse_rank"]
                eval_item["index_tags"] = c_data["index_tags"]
                eval_item["turnover_cr"] = round(_safe_float(item.get("turnover", 0.0)) / 100.0, 2) if item.get("turnover") else eval_item["turnover_cr"]
                eval_item["volume"] = _safe_float(item.get("trade_quantity"), eval_item["volume"])

                # Authoritative V13 Screener Score and active status tagging
                eval_item["v13_score"] = round(c_score, 1) if c_score is not None else None
                eval_item["is_v13_active"] = bool(c_score is not None and c_score >= min_v13_score)

                if is_confluence_cat:
                    # In V13 Active Runners: Only stocks that possess a V13 score enter Top Losers
                    if eval_item.get("v13_score") is not None and eval_item["v13_score"] > 0:
                        evaluated_losers.append(eval_item)
                    # And only stocks that pass BOTH (V13 Active + 20-EMA Bear Breakdown) enter short_runners
                    if eval_item["is_v13_active"] and eval_item["archetype"] == "SHORT_RUNNER":
                        short_runners.append(eval_item)
                    elif eval_item["archetype"] == "EXHAUSTION_WARNING":
                        exhaustion.append(eval_item)
                else:
                    evaluated_losers.append(eval_item)
                    if eval_item["archetype"] == "SHORT_RUNNER":
                        short_runners.append(eval_item)
                    elif eval_item["archetype"] == "EXHAUSTION_WARNING":
                        exhaustion.append(eval_item)

            if is_confluence_cat:
                for idx, g in enumerate(evaluated_gainers, 1):
                    g["rank"] = idx
                for idx, l in enumerate(evaluated_losers, 1):
                    l["rank"] = idx

        else:
            # Single category specific handling
            index_key = nse_key_map.get(cat, "allSec")
            nse_g_items = raw_g_dict.get(index_key, {}).get("data", [])
            nse_l_items = raw_l_dict.get(index_key, {}).get("data", [])

            # Process Gainers: ONLY keep items from official NSE Top 20 that exist in our 1000Cr universe
            for nse_rank, item in enumerate(nse_g_items, 1):
                sym = str(item.get("symbol", "")).strip()
                stock_record = universe_map.get(sym)
                if stock_record:
                    # Merge fresh NSE live prices into snapshot
                    snap = dict(stock_record.get("snapshot", {}))
                    snap["price"] = _safe_float(item.get("ltp"), snap.get("price"))
                    snap["latest_session_change_pct"] = _safe_float(item.get("perChange"), snap.get("latest_session_change_pct"))
                    if item.get("high_price"):
                        snap["high_price"] = _safe_float(item.get("high_price"))
                    if item.get("low_price"):
                        snap["low_price"] = _safe_float(item.get("low_price"))
                    if item.get("turnover"):
                        snap["turnover_cr"] = round(_safe_float(item.get("turnover")) / 100.0, 2)
                    if item.get("trade_quantity"):
                        live_q = _safe_float(item.get("trade_quantity"))
                        snap["rel_vol"] = _calculate_tod_rel_vol(live_q, _safe_float(snap.get("volume")), _safe_float(snap.get("rel_vol"), 0.0), snap_bar_end_iso=snap.get("bar_end_time"))
                        snap["volume"] = live_q
                    enriched_record = dict(stock_record)
                    enriched_record["snapshot"] = snap

                    c_score = v13_score_map.get(sym.upper())
                    eval_item = evaluate_mover_stock(
                        enriched_record, 
                        df_cache=df_cache, 
                        rank=nse_rank, 
                        is_gainer=True,
                        v13_score=c_score,
                        min_v13_score=min_v13_score,
                        shortable_symbols=shortable_symbols,
                    )
                    eval_item["nse_rank"] = nse_rank
                    eval_item["rank"] = nse_rank
                    eval_item["turnover_cr"] = round(_safe_float(item.get("turnover", 0.0)) / 100.0, 2) if item.get("turnover") else eval_item["turnover_cr"]
                    eval_item["volume"] = _safe_float(item.get("trade_quantity"), eval_item["volume"])
                    eval_item["index_tags"] = [cat.replace("_", " ")]

                    # Authoritative V13 Screener Score and active status tagging
                    eval_item["v13_score"] = round(c_score, 1) if c_score is not None else None
                    eval_item["is_v13_active"] = bool(c_score is not None and c_score >= min_v13_score)

                    evaluated_gainers.append(eval_item)
                    if eval_item["archetype"] == "RUNNER":
                        runners.append(eval_item)
                    elif eval_item["archetype"] == "EXHAUSTION_WARNING":
                        exhaustion.append(eval_item)

            # Process Losers: ONLY keep items from official NSE Top 20 that exist in our 1000Cr universe
            for nse_rank, item in enumerate(nse_l_items, 1):
                sym = str(item.get("symbol", "")).strip()
                stock_record = universe_map.get(sym)
                if stock_record:
                    snap = dict(stock_record.get("snapshot", {}))
                    snap["price"] = _safe_float(item.get("ltp"), snap.get("price"))
                    snap["latest_session_change_pct"] = _safe_float(item.get("perChange"), snap.get("latest_session_change_pct"))
                    if item.get("high_price"):
                        snap["high_price"] = _safe_float(item.get("high_price"))
                    if item.get("low_price"):
                        snap["low_price"] = _safe_float(item.get("low_price"))
                    if item.get("turnover"):
                        snap["turnover_cr"] = round(_safe_float(item.get("turnover")) / 100.0, 2)
                    if item.get("trade_quantity"):
                        live_q = _safe_float(item.get("trade_quantity"))
                        snap["rel_vol"] = _calculate_tod_rel_vol(live_q, _safe_float(snap.get("volume")), _safe_float(snap.get("rel_vol"), 0.0), snap_bar_end_iso=snap.get("bar_end_time"))
                        snap["volume"] = live_q
                    enriched_record = dict(stock_record)
                    enriched_record["snapshot"] = snap

                    c_score = v13_score_map.get(sym.upper())
                    eval_item = evaluate_mover_stock(
                        enriched_record, 
                        df_cache=df_cache, 
                        rank=nse_rank, 
                        is_gainer=False,
                        v13_score=c_score,
                        min_v13_score=min_v13_score,
                        shortable_symbols=shortable_symbols,
                    )
                    eval_item["nse_rank"] = nse_rank
                    eval_item["rank"] = nse_rank
                    eval_item["turnover_cr"] = round(_safe_float(item.get("turnover", 0.0)) / 100.0, 2) if item.get("turnover") else eval_item["turnover_cr"]
                    eval_item["volume"] = _safe_float(item.get("trade_quantity"), eval_item["volume"])
                    eval_item["index_tags"] = [cat.replace("_", " ")]

                    # Authoritative V13 Screener Score and active status tagging
                    eval_item["v13_score"] = round(c_score, 1) if c_score is not None else None
                    eval_item["is_v13_active"] = bool(c_score is not None and c_score >= min_v13_score)

                    evaluated_losers.append(eval_item)
                    if eval_item["archetype"] == "SHORT_RUNNER":
                        short_runners.append(eval_item)
                    elif eval_item["archetype"] == "EXHAUSTION_WARNING":
                        exhaustion.append(eval_item)

    else:
        # Fallback only if NSE API is down: evaluate from universe
        valid = [s for s in universe if _safe_float(s.get("snapshot", {}).get("price")) > 0]
        constituents = _load_nse_constituents()
        if cat == "NIFTY_50":
            valid = [s for s in valid if s.get("symbol") in constituents.get("NIFTY_50", set())]
        elif cat == "BANK_NIFTY":
            valid = [s for s in valid if s.get("symbol") in constituents.get("BANK_NIFTY", set())]
        elif cat == "NIFTY_NEXT_50":
            valid = [s for s in valid if s.get("symbol") in constituents.get("NIFTY_NEXT_50", set())]
        elif cat == "FNO":
            valid = [s for s in valid if s.get("symbol") in constituents.get("FNO", set())]

        sorted_g = sorted(valid, key=lambda x: _safe_float(x.get("snapshot", {}).get("latest_session_change_pct")), reverse=True)[:20]
        sorted_l = sorted(valid, key=lambda x: _safe_float(x.get("snapshot", {}).get("latest_session_change_pct")))[:20]

        for rank, s in enumerate(sorted_g, 1):
            sym = str(s.get("symbol", "")).strip().upper()
            c_score = v13_score_map.get(sym)
            eval_item = evaluate_mover_stock(
                s, 
                df_cache=df_cache, 
                rank=rank, 
                is_gainer=True,
                v13_score=c_score,
                min_v13_score=min_v13_score,
                shortable_symbols=shortable_symbols,
            )
            eval_item["nse_rank"] = rank
            eval_item["v13_score"] = round(c_score, 1) if c_score is not None else None
            eval_item["is_v13_active"] = bool(c_score is not None and c_score >= min_v13_score)

            if is_confluence_cat:
                # In V13 Active Runners: Only stocks that possess a V13 score enter Top Gainers
                if eval_item.get("v13_score") is not None and eval_item["v13_score"] > 0:
                    evaluated_gainers.append(eval_item)
                if eval_item["is_v13_active"] and eval_item["archetype"] == "RUNNER":
                    runners.append(eval_item)
                elif eval_item["archetype"] == "EXHAUSTION_WARNING":
                    exhaustion.append(eval_item)
            else:
                evaluated_gainers.append(eval_item)
                if eval_item["archetype"] == "RUNNER":
                    runners.append(eval_item)
                elif eval_item["archetype"] == "EXHAUSTION_WARNING":
                    exhaustion.append(eval_item)

        for rank, s in enumerate(sorted_l, 1):
            sym = str(s.get("symbol", "")).strip().upper()
            c_score = v13_score_map.get(sym)
            eval_item = evaluate_mover_stock(
                s, 
                df_cache=df_cache, 
                rank=rank, 
                is_gainer=False,
                v13_score=c_score,
                min_v13_score=min_v13_score,
                shortable_symbols=shortable_symbols,
            )
            eval_item["nse_rank"] = rank
            eval_item["v13_score"] = round(c_score, 1) if c_score is not None else None
            eval_item["is_v13_active"] = bool(c_score is not None and c_score >= min_v13_score)

            if is_confluence_cat:
                # In V13 Active Runners: Only stocks that possess a V13 score enter Top Losers
                if eval_item.get("v13_score") is not None and eval_item["v13_score"] > 0:
                    evaluated_losers.append(eval_item)
                if eval_item["is_v13_active"] and eval_item["archetype"] == "SHORT_RUNNER":
                    short_runners.append(eval_item)
                elif eval_item["archetype"] == "EXHAUSTION_WARNING":
                    exhaustion.append(eval_item)
            else:
                evaluated_losers.append(eval_item)
                if eval_item["archetype"] == "SHORT_RUNNER":
                    short_runners.append(eval_item)
                elif eval_item["archetype"] == "EXHAUSTION_WARNING":
                    exhaustion.append(eval_item)

        if is_confluence_cat:
            for idx, g in enumerate(evaluated_gainers, 1):
                g["rank"] = idx
            for idx, l in enumerate(evaluated_losers, 1):
                l["rank"] = idx

    # Register qualified runners into GLOBAL_MOVER_REGISTRY (45m TTL sticky tracking)
    if cat in ["COMBINED", "MASTER"] or is_confluence_cat:
        seen_runner_syms = set()
        for r_item in runners:
            r_sym = r_item.get("symbol")
            if r_sym:
                seen_runner_syms.add(r_sym)
                GLOBAL_MOVER_REGISTRY.update_candidate(r_sym, r_item)
        for sr_item in short_runners:
            sr_sym = sr_item.get("symbol")
            if sr_sym:
                seen_runner_syms.add(sr_sym)
                GLOBAL_MOVER_REGISTRY.update_candidate(sr_sym, sr_item)

        current_top_mover_syms = {
            item.get("symbol")
            for item in (evaluated_gainers + evaluated_losers + exhaustion)
            if item.get("symbol")
        }

        # Retain active sticky runners within 45m TTL ONLY if they genuinely dipped out of NSE Top 20
        # AND still pass live 20-EMA / VWAP flag structure with freshly recalculated LTP & trade_plan
        for reg_item in GLOBAL_MOVER_REGISTRY.get_registered(max_age_seconds=2700.0):
            reg_sym = reg_item.get("symbol")
            if not reg_sym or reg_sym in seen_runner_syms:
                continue

            # If stock is still in current NSE Top 20 (gainers/losers/exhaustion) but no longer a runner,
            # evict its stale runner record so it never shadows the fresh Top 20 card!
            if reg_sym in current_top_mover_syms:
                GLOBAL_MOVER_REGISTRY.registered_movers.pop(reg_sym, None)
                continue

            stock_record = universe_map.get(reg_sym)
            if not stock_record:
                GLOBAL_MOVER_REGISTRY.registered_movers.pop(reg_sym, None)
                continue

            was_gainer = reg_item.get("archetype") == "RUNNER"
            c_score = v13_score_map.get(reg_sym.upper())
            fresh_reg = evaluate_mover_stock(
                stock_record,
                df_cache=df_cache,
                rank=reg_item.get("rank", 21),
                is_gainer=was_gainer,
                v13_score=c_score,
                min_v13_score=min_v13_score,
                shortable_symbols=shortable_symbols,
            )
            fresh_reg["nse_rank"] = reg_item.get("nse_rank", fresh_reg.get("rank", 21))
            fresh_reg["index_tags"] = reg_item.get("index_tags", ["STICKY"])
            fresh_reg["v13_score"] = round(c_score, 1) if c_score is not None else None
            fresh_reg["is_v13_active"] = bool(c_score is not None and c_score >= min_v13_score)
            fresh_reg["_last_seen_ts"] = reg_item.get("_last_seen_ts", time.time())

            if is_confluence_cat and not fresh_reg.get("is_v13_active"):
                continue

            if fresh_reg.get("archetype") == "RUNNER":
                GLOBAL_MOVER_REGISTRY.registered_movers[reg_sym] = fresh_reg
                runners.append(fresh_reg)
                seen_runner_syms.add(reg_sym)
            elif fresh_reg.get("archetype") == "SHORT_RUNNER":
                GLOBAL_MOVER_REGISTRY.registered_movers[reg_sym] = fresh_reg
                short_runners.append(fresh_reg)
                seen_runner_syms.add(reg_sym)
            else:
                GLOBAL_MOVER_REGISTRY.registered_movers.pop(reg_sym, None)

    return {
        "category": cat,
        "min_v13_score": round(min_v13_score, 1) if min_v13_score is not None else 65.0,
        "gainers": evaluated_gainers,
        "losers": evaluated_losers,
        "runners": runners,
        "short_runners": short_runners,
        "exhaustion": exhaustion,
        "total_tracked": len(evaluated_gainers) + len(evaluated_losers),
        "is_stale": bool(is_stale),
        "updated_at": fetch_iso if (raw_g_dict and raw_l_dict) else datetime.now(IST_TZ).isoformat(),
    }
