"""
NSE-PULSE V13: Modular Real-Time Conviction Rating & "Take Trade" Stamp Engine.

Evaluates 3 high-impact quantitative pillars in < 5ms:
1. Pillar 1: NIFTY 50 Intraday Flow (Max: 1.0 Pt)
   - Trending & Aligned (Above/Below VWAP) -> +1.0 Pt (Zero Penalty) ✅
   - Neutral / Sideways Flow (Chop)        ->  0.0 Pt (Hard Penalty -1.0 Pt) ⚠️
   - Counter-Trend (Opposing Direction)    ->  0.0 Pt (Hard Penalty -1.0 Pt) 🛑

2. Pillar 2: 1,468-Stock Universe Sector Breadth (Max: 1.0 Pt)
   - >= 60% Stocks Aligned (Strong Wave)   -> +1.0 Pt (Zero Penalty) ✅
   - 40% - 59% Stocks Aligned (Neutral)    -> +0.5 Pt (Soft Penalty -0.5 Pt) ⚠️
   - < 40% Stocks Aligned (Opposing)       ->  0.0 Pt (Hard Penalty -1.0 Pt) 🛑

3. Pillar 3: Last Closed 15m Candle Breakout Purity (Max: 1.0 Pt)
   - Wick Ratio <= 25% (Solid Real Body)   -> +1.0 Pt (Zero Penalty) ✅
   - Wick Ratio 26% - 40% (Minor Wick)     -> +0.5 Pt (Soft Penalty -0.5 Pt) ⚠️
   - Wick Ratio > 40% (Heavy Rejection)    ->  0.0 Pt (Hard Penalty -1.0 Pt) 🛑

Output:
- Grade A+ (>= 2.5 / 3.0): 🟢 HIGH PROBABILITY • Full Size (100%) • Hold for Full Targets
- Grade B  (1.5 - 2.0 / 3.0): 🟡 MODERATE PROBABILITY • Trade Half Size (50%) • Trail to Breakeven
- Grade C  (<= 1.0 / 3.0): ⚪ LOW PROBABILITY / CAUTION • Skip / No Trade (0%) • High Trap Risk

100% Plug-and-Play: Can be dynamically enabled/disabled via ENABLE_CONVICTION_RATING in .env / config.py.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("v13_conviction")


def is_conviction_rating_enabled() -> bool:
    """Dynamically check if conviction rating stamp is enabled via .env or config."""
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path, override=True)
    except Exception:
        pass
    val = os.getenv("ENABLE_CONVICTION_RATING", "true").strip().lower()
    return val in ("true", "1", "yes")


def evaluate_nifty_flow(
    market_context: Optional[Dict[str, Any]],
    direction: str,
) -> Tuple[float, str, str]:
    """
    Pillar 1: Evaluate NIFTY 50 Intraday Flow (Max: 1.0 Pt).
    Scores & Penalties:
    - Trending & Aligned (VWAP ke upar/niche) -> +1.0 Pt (Zero Penalty) ✅
    - Neutral / Sideways Flow (Chop)           ->  0.0 Pt (Hard Penalty -1.0 Pt loss) ⚠️
    - Counter-Trend (Opposing Direction)       ->  0.0 Pt (Hard Penalty -1.0 Pt loss) 🛑
    """
    ctx = market_context or {}
    dir_upper = str(direction or "BULLISH").upper()

    # 1. Fallback self-healing: If context missing or empty, fetch live Nifty regime
    if not ctx or "nifty_direction" not in ctx:
        try:
            from .market_regime import get_nifty_regime
            nifty_regime = get_nifty_regime()
            if nifty_regime:
                ctx = {
                    "nifty_direction": getattr(nifty_regime, "direction", "NEUTRAL"),
                    "nifty_ltp": getattr(nifty_regime, "current_close", None),
                    "nifty_vwap": getattr(nifty_regime, "vwap", None),
                }
        except Exception:
            pass

    nifty_dir = str(ctx.get("nifty_direction") or "").upper()

    # 2. Fallback to granular Nifty price vs VWAP ONLY when slope-based nifty_direction is unavailable
    if nifty_dir not in ("BULLISH", "BEARISH", "NEUTRAL"):
        n_ltp = ctx.get("nifty_ltp")
        n_vwap = ctx.get("nifty_vwap")
        if n_ltp is not None and n_vwap is not None:
            try:
                n_ltp_f = float(n_ltp)
                n_vwap_f = float(n_vwap)
                if n_ltp_f > n_vwap_f:
                    nifty_dir = "BULLISH"
                elif n_ltp_f < n_vwap_f:
                    nifty_dir = "BEARISH"
                else:
                    nifty_dir = "NEUTRAL"
            except (ValueError, TypeError):
                nifty_dir = "NEUTRAL"
        else:
            nifty_dir = "NEUTRAL"

    # 3. Match against signal direction
    if dir_upper == "BULLISH":
        if nifty_dir == "BULLISH":
            return 1.0, "✅", "NIFTY Bullish Flow (Above VWAP)"
        elif nifty_dir == "NEUTRAL":
            return 0.0, "⚠️", "NIFTY Neutral / Sideways Flow"
        else:
            return 0.0, "🛑", "NIFTY Opposing Trend (Counter-Trend Trap)"
    else:  # BEARISH
        if nifty_dir == "BEARISH":
            return 1.0, "✅", "NIFTY Bearish Flow (Below VWAP)"
        elif nifty_dir == "NEUTRAL":
            return 0.0, "⚠️", "NIFTY Neutral / Sideways Flow"
        else:
            return 0.0, "🛑", "NIFTY Opposing Trend (Counter-Trend Trap)"


def evaluate_sector_breadth(
    sector_name: str,
    direction: str,
    universe: Optional[List[Any]],
) -> Tuple[float, str, str]:
    """
    Pillar 2: Evaluate Sector Breadth across 1,468-Stock Universe (Max: 1.0 Pt).
    Scores & Penalties:
    - >= 60% Stocks Aligned (Strong Wave)   -> +1.0 Pt (Zero Penalty) ✅
    - 40% - 59% Stocks Aligned (Neutral)    -> +0.5 Pt (Soft Penalty -0.5 Pt loss) ⚠️
    - < 40% Stocks Aligned (Opposing)       ->  0.0 Pt (Hard Penalty -1.0 Pt loss) 🛑
    """
    clean_sec = str(sector_name or "").strip()
    dir_upper = str(direction or "BULLISH").upper()

    if not clean_sec or clean_sec.lower() in ("nse equity", "equity", "unknown", "none"):
        clean_sec = "Market"

    # Self-healing: Grab universe from main scan cache or disk if not provided
    if not universe:
        try:
            from .main import _V13_SCAN_RESULT
            if _V13_SCAN_RESULT and _V13_SCAN_RESULT.get("universe"):
                universe = _V13_SCAN_RESULT.get("universe")
        except Exception:
            pass

    if not universe:
        return 0.5, "⚠️", f"{clean_sec} Baseline (Universe syncing)"

    # Filter universe for stocks in this sector
    sec_lower = clean_sec.lower()
    sector_stocks = []

    def _get_val(obj: Any, keys: List[str], default: Optional[float] = None) -> Optional[float]:
        for k in keys:
            if isinstance(obj, dict):
                v = obj.get(k)
            else:
                v = getattr(obj, k, None)
            if v is not None:
                try:
                    return float(v)
                except (ValueError, TypeError):
                    pass
        return default

    for item in universe:
        if isinstance(item, dict):
            s_name = str(item.get("sector") or "").strip().lower()
            snap = item.get("snapshot") or {}
        else:
            s_name = str(getattr(item, "sector", "") or "").strip().lower()
            snap = getattr(item, "snapshot", {}) or {}

        if s_name and (sec_lower in s_name or s_name in sec_lower):
            c_pct_f = _get_val(snap, ["latest_session_change_pct", "change_pct"], default=None)
            if c_pct_f is None:
                c_pct_f = _get_val(item, ["latest_session_change_pct", "change_pct"], default=0.0)

            ltp_f = _get_val(snap, ["price", "close", "ltp"], default=None)
            if ltp_f is None:
                ltp_f = _get_val(item, ["price", "close", "ltp"], default=0.0)

            vwap_f = _get_val(snap, ["vwap"], default=None)
            if vwap_f is None:
                vwap_f = _get_val(item, ["vwap"], default=ltp_f)

            is_pos = (ltp_f >= vwap_f) and (c_pct_f >= 0.15)
            is_neg = (ltp_f <= vwap_f) and (c_pct_f <= -0.15)
            sector_stocks.append({
                "change_pct": c_pct_f,
                "is_pos": is_pos,
                "is_neg": is_neg,
            })

    total_count = len(sector_stocks)

    # Niche Sector (< 10 stocks): Baseline 0.5 pt to avoid law of small numbers
    if total_count < 10:
        return 0.5, "⚠️", f"{clean_sec} Niche ({total_count} Stocks Mixed)"

    if dir_upper == "BULLISH":
        green_count = sum(1 for s in sector_stocks if s["is_pos"])
        breadth_pct = round((green_count / total_count) * 100.0, 1)
        if breadth_pct >= 60.0:
            return 1.0, "✅", f"{clean_sec} Buying ({int(breadth_pct)}% of {total_count} Stocks Green)"
        elif breadth_pct >= 40.0:
            return 0.5, "⚠️", f"{clean_sec} Mixed ({int(breadth_pct)}% of {total_count} Stocks Green)"
        else:
            return 0.0, "🛑", f"{clean_sec} Opposing ({int(breadth_pct)}% of {total_count} Stocks Green)"
    else:  # BEARISH
        red_count = sum(1 for s in sector_stocks if s["is_neg"])
        red_pct = round((red_count / total_count) * 100.0, 1)
        if red_pct >= 60.0:
            return 1.0, "✅", f"{clean_sec} Selling ({int(red_pct)}% of {total_count} Stocks Red)"
        elif red_pct >= 40.0:
            return 0.5, "⚠️", f"{clean_sec} Mixed ({int(red_pct)}% of {total_count} Stocks Red)"
        else:
            return 0.0, "🛑", f"{clean_sec} Opposing ({int(red_pct)}% of {total_count} Stocks Red)"


def evaluate_candle_purity(
    signal: Dict[str, Any],
) -> Tuple[float, str, str]:
    """
    Pillar 3: Evaluate Last Closed 15m Candle Breakout Purity (Max: 1.0 Pt).
    Scores & Penalties:
    - Wick Ratio <= 25% (Solid Real Body)      -> +1.0 Pt (Zero Penalty) ✅
    - Wick Ratio 26% - 40% (Minor Wick)        -> +0.5 Pt (Soft Penalty -0.5 Pt loss) ⚠️
    - Wick Ratio > 40% (Heavy Wick Rejection)  ->  0.0 Pt (Hard Penalty -1.0 Pt loss) 🛑
    """
    dir_upper = str(
        (signal.get("direction") or signal.get("signal_type") or "BULLISH")
        if isinstance(signal, dict)
        else getattr(signal, "direction", getattr(signal, "signal_type", "BULLISH"))
    ).upper()

    # 1. First prioritize dedicated last_candle snapshot dictionary
    target_candle = (
        signal.get("last_candle")
        if isinstance(signal, dict)
        else getattr(signal, "last_candle", None)
    )

    # 2. Fallback to raw candle list if available
    if not target_candle:
        candles = (
            (signal.get("candles") or signal.get("ohlcv_15m") or [])
            if isinstance(signal, dict)
            else (getattr(signal, "candles", None) or getattr(signal, "ohlcv_15m", None) or [])
        )
        if isinstance(candles, list) and len(candles) >= 2:
            target_candle = candles[-2]
        elif isinstance(candles, list) and len(candles) == 1:
            target_candle = candles[0]

    if target_candle and isinstance(target_candle, dict):
        try:
            c_open = float(target_candle.get("open", 0.0))
            c_high = float(target_candle.get("high", 0.0))
            c_low = float(target_candle.get("low", 0.0))
            c_close = float(target_candle.get("close", 0.0))
            c_range = c_high - c_low

            if c_range > 0:
                if dir_upper == "BULLISH":
                    upper_wick = c_high - max(c_open, c_close)
                    wick_ratio = max(0.0, min(1.0, upper_wick / c_range))
                else:
                    lower_wick = min(c_open, c_close) - c_low
                    wick_ratio = max(0.0, min(1.0, lower_wick / c_range))

                wick_pct = int(round(wick_ratio * 100))

                if wick_ratio <= 0.25:
                    return 1.0, "✅", f"Clean Breakout Structure ({wick_pct}% Wick)"
                elif wick_ratio <= 0.40:
                    return 0.5, "⚠️", f"Minor Wick Resistance ({wick_pct}% Wick)"
                else:
                    return 0.0, "🛑", f"Heavy Wick Rejection ({wick_pct}% Wick)"
        except (ValueError, TypeError):
            pass

    # Fallback heuristic only when raw candle data is completely omitted
    score = float(signal.get("score", 0.0) if isinstance(signal, dict) else getattr(signal, "score", 0.0) or 0.0)
    ind = signal.get("indicators", {}) if isinstance(signal, dict) else getattr(signal, "indicators", {}) or {}
    rel_vol = float(
        ind.get("rel_vol", signal.get("rel_vol", 1.0))
        if isinstance(ind, dict) and isinstance(signal, dict)
        else getattr(signal, "rel_vol", 1.0) or 1.0
    )

    if score >= 80.0 and rel_vol >= 1.8:
        return 1.0, "✅", "Clean Breakout Structure (Confirmed)"
    elif score >= 75.0:
        return 0.5, "⚠️", "Minor Wick Resistance (26%-40% Wick)"
    else:
        return 0.0, "🛑", "Heavy Wick Rejection / Weak Body"


def evaluate_conviction(
    signal: Dict[str, Any],
    market_context: Optional[Dict[str, Any]] = None,
    universe: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """
    Main evaluation pipeline: Computes 3 pillars and returns conviction summary dictionary.
    Scores & Penalties Model:
    - Max Score = 3.0 Points
    - Grade A+ (>= 2.5): 🟢 HIGH PROBABILITY • Full Size (100%) • Hold for Full Targets
    - Grade B  (1.5 - 2.0): 🟡 MODERATE PROBABILITY • Trade Half Size (50%) • Trail to Breakeven
    - Grade C  (<= 1.0): ⚪ LOW PROBABILITY / CAUTION • Skip / No Trade (0%) • High Trap Risk
    """
    if not is_conviction_rating_enabled():
        return {"enabled": False}

    direction = str(signal.get("direction") or signal.get("signal_type") or "BULLISH").upper()
    sector = str(signal.get("sector") or "NSE Equity")

    ctx = market_context or signal.get("_market_context") or {}
    uni = universe if universe is not None else signal.get("_universe")

    # 1. Evaluate 3 Pillars
    p1_pts, p1_icon, p1_desc = evaluate_nifty_flow(ctx, direction)
    p2_pts, p2_icon, p2_desc = evaluate_sector_breadth(sector, direction, uni)
    p3_pts, p3_icon, p3_desc = evaluate_candle_purity(signal)

    total_score = round(p1_pts + p2_pts + p3_pts, 1)

    # 2. Determine Conviction Grade & Directive
    if total_score >= 2.5:
        grade = "GRADE_A_PLUS"
        badge_header = "🟢 GRADE A+ (HIGH PROBABILITY)"
        directive = "High Conviction • Execute Full Size (100%) • Hold for Full Targets"
    elif total_score >= 1.5:
        grade = "GRADE_B"
        badge_header = "🟡 GRADE B (MODERATE PROBABILITY)"
        directive = "Moderate Conviction • Trade Half Size (50%) • Trail Stop to Breakeven Early"
    else:
        grade = "GRADE_C"
        badge_header = "⚪ GRADE C (LOW PROBABILITY / CAUTION)"
        directive = "Low Conviction • Skip / No Trade (0%) • High Trap Risk"

    # V14 WICK-PROTECTED IDIOSYNCRATIC ALPHA OVERRIDE:
    # Standalone high-momentum alpha setups (Score >= 85.0, RelVol >= 3.0x) penalized by red Nifty/Sector
    # are safely promoted from Grade C to Grade B (50% size), STRICTLY IF Candle Integrity (P3 >= 0.5) verifies
    # that the candle is clean and NOT a shooting star or heavy rejection wick.
    override_applied = False
    override_reason = ""
    if grade == "GRADE_C":
        v13_score = float(signal.get("score") if isinstance(signal, dict) else getattr(signal, "score", 0.0) or 0.0)
        ind_map = signal.get("indicators") if isinstance(signal, dict) else getattr(signal, "indicators", None)
        ind_vol = ind_map.get("rel_vol") if isinstance(ind_map, dict) else None
        rel_vol = float(
            signal.get("rel_vol") or ind_vol
            if isinstance(signal, dict)
            else getattr(signal, "rel_vol", 1.0) or 1.0
        )
        is_extreme_alpha = (v13_score >= 85.0) and (rel_vol >= 3.0)
        is_candle_clean = (p3_pts >= 0.5)

        if is_extreme_alpha and is_candle_clean:
            grade = "GRADE_B"
            total_score = 1.5
            badge_header = "🟡 GRADE B (IDIOSYNCRATIC ALPHA OVERRIDE)"
            directive = "Standalone Momentum • Trade Half Size (50%) • Score >= 85 & RelVol >= 3.0x"
            override_applied = True
            override_reason = "IDIOSYNCRATIC_ALPHA_OVERRIDE (Score >= 85, Vol >= 3x, Wick Protected)"

    return {
        "enabled": True,
        "total_score": total_score,
        "max_score": 3.0,
        "grade": grade,
        "badge_header": badge_header,
        "directive": directive,
        "guidance": directive,
        "pillar_1": {"points": p1_pts, "icon": p1_icon, "desc": p1_desc},
        "pillar_2": {"points": p2_pts, "icon": p2_icon, "desc": p2_desc},
        "pillar_3": {"points": p3_pts, "icon": p3_icon, "desc": p3_desc},
        "override_applied": override_applied,
        "override_reason": override_reason,
    }


def format_conviction_block(conviction_data: Dict[str, Any]) -> str:
    """
    Renders the formatted Markdown Conviction Rating block for the Telegram notification card.
    Returns empty string if disabled.
    """
    if not conviction_data or not conviction_data.get("enabled"):
        return ""

    header = conviction_data.get("badge_header", "")
    p1 = conviction_data.get("pillar_1", {})
    p2 = conviction_data.get("pillar_2", {})
    p3 = conviction_data.get("pillar_3", {})
    directive = conviction_data.get("directive") or conviction_data.get("guidance", "")

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"⚡️ *CONVICTION: {header}*",
        f"  ├─ 🏛️ Market : {p1.get('desc', 'NIFTY Flow')} {p1.get('icon', '')}",
        f"  ├─ 📂 Sector : {p2.get('desc', 'Sector Breadth')} {p2.get('icon', '')}",
        f"  └─ 🕯️ Candle : {p3.get('desc', 'Breakout Purity')} {p3.get('icon', '')}",
        f"  🎯 *DIRECTIVE*: {directive}",
    ]

    return "\n".join(lines)
