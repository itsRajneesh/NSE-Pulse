from __future__ import annotations

import yfinance as yf
import app.v13_engine as v


def diagnose(symbol: str = "RELIANCE.NS") -> None:
    df = yf.download(
        symbol,
        period="5d",
        interval="15m",
        auto_adjust=False,
        progress=False,
    )

    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)

    clean = v._normalise_columns(df)
    session = v._latest_session(clean)
    opening_high, opening_low = v._opening_range(session)
    previous_high, previous_low, *prev_close = v._previous_day_levels(clean)

    ema20 = float(v._ema(clean["Close"], 20).iloc[-1])
    rsi14 = float(v._rsi(clean["Close"], 14).iloc[-1])
    atr14 = float(v._atr(clean, 14).iloc[-1])
    vwap = float(v._session_vwap(session).iloc[-1])
    rel_vol = float(v._relative_volume(clean, session))
    close = float(session["Close"].iloc[-1])

    print("=" * 70)
    print("V13 DISCOVERY DIAGNOSTIC")
    print("=" * 70)
    print(f"Symbol             : {symbol}")
    print(f"Bars               : {len(clean)}")
    print(f"Sessions           : {len(v._session_dates(clean))}")
    print(f"Latest session bars: {len(session)}")
    print(f"LTP                : {close:.2f}")
    print(f"Opening Range      : {opening_high:.2f} / {opening_low:.2f}")
    print(f"Previous Day H/L   : {previous_high:.2f} / {previous_low:.2f}")
    print(f"EMA20              : {ema20:.2f}")
    print(f"VWAP               : {vwap:.2f}")
    print(f"RSI14              : {rsi14:.2f}")
    print(f"ATR14              : {atr14:.2f}")
    print(f"Relative Volume    : {rel_vol:.2f}x")
    print("=" * 70)

    for direction in ("BULLISH", "BEARISH"):
        print(f"\n{'=' * 70}")
        print(direction)
        print("=" * 70)

        structure_score, structure_reasons, structure_penalties = (
            v._trend_structure(session, direction)
        )
        candle_score, candle_valid = v._candle_quality(
            session.iloc[-1],
            direction,
        )
        context_score, context_reasons, context_penalties = (
            v._context_alignment(direction, None)
        )

        score = 0.0

        # Structure
        score += structure_score
        print(f"Structure          : {structure_score:5.1f}/8")
        for x in structure_reasons:
            print(f"  + {x}")
        for x in structure_penalties:
            print(f"  - {x}")

        # EMA
        ema_points = 0.0
        if direction == "BULLISH":
            if close > ema20:
                ema_points = 10.0
            elif close >= ema20 - 0.25 * atr14:
                ema_points = 4.0
        else:
            if close < ema20:
                ema_points = 10.0
            elif close <= ema20 + 0.25 * atr14:
                ema_points = 4.0
        score += ema_points
        print(f"EMA20              : {ema_points:5.1f}/10")

        # VWAP
        vwap_points = 0.0
        if direction == "BULLISH":
            if close > vwap:
                vwap_points = 10.0
            elif close >= vwap - 0.20 * atr14:
                vwap_points = 4.0
        else:
            if close < vwap:
                vwap_points = 10.0
            elif close <= vwap + 0.20 * atr14:
                vwap_points = 4.0
        score += vwap_points
        print(f"VWAP               : {vwap_points:5.1f}/10")

        # RSI
        rsi_points = 0.0
        if direction == "BULLISH":
            if 55 <= rsi14 <= 68:
                rsi_points = 8.0
            elif 68 < rsi14 <= 75:
                rsi_points = 5.0
            elif 50 <= rsi14 < 55:
                rsi_points = 3.0
        else:
            if 32 <= rsi14 <= 45:
                rsi_points = 8.0
            elif 25 <= rsi14 < 32:
                rsi_points = 5.0
            elif 45 < rsi14 <= 50:
                rsi_points = 3.0
        score += rsi_points
        print(f"RSI14              : {rsi_points:5.1f}/8")

        # Volume
        volume_points = 0.0
        if rel_vol >= 3.0:
            volume_points = 12.0
        elif rel_vol >= 2.0:
            volume_points = 10.0
        elif rel_vol >= 1.5:
            volume_points = 8.0
        elif rel_vol >= 1.2:
            volume_points = 4.0
        score += volume_points
        print(f"Volume             : {volume_points:5.1f}/12")

        # Opening range
        if direction == "BULLISH":
            distance = (close - opening_high) / atr14
            if close > opening_high:
                or_points = 18.0
                setup_type = "CONFIRMED_BREAKOUT_LONG"
            elif distance >= -0.20:
                or_points = 10.0
                setup_type = "DEVELOPING_BREAKOUT_LONG"
            elif distance >= -0.50:
                or_points = 5.0
                setup_type = "DEVELOPING_BREAKOUT_LONG"
            else:
                or_points = 0.0
                setup_type = "DEVELOPING_BREAKOUT_LONG"
        else:
            distance = (opening_low - close) / atr14
            if close < opening_low:
                or_points = 18.0
                setup_type = "CONFIRMED_BREAKDOWN_SHORT"
            elif distance >= -0.20:
                or_points = 10.0
                setup_type = "DEVELOPING_BREAKDOWN_SHORT"
            elif distance >= -0.50:
                or_points = 5.0
                setup_type = "DEVELOPING_BREAKDOWN_SHORT"
            else:
                or_points = 0.0
                setup_type = "DEVELOPING_BREAKDOWN_SHORT"

        score += or_points
        print(f"OR breakout        : {or_points:5.1f}/18")
        print(f"  Setup type       : {setup_type}")
        print(f"  Distance ATR     : {distance:.2f}")

        # Previous day level
        prev_points = 0.0
        if direction == "BULLISH":
            if close > previous_high:
                prev_points = 7.0
            elif close >= previous_high - 0.25 * atr14:
                prev_points = 3.0
        else:
            if close < previous_low:
                prev_points = 7.0
            elif close <= previous_low + 0.25 * atr14:
                prev_points = 3.0
        score += prev_points
        print(f"Previous-day level : {prev_points:5.1f}/7")

        # Candle
        score += candle_score
        print(f"Candle             : {candle_score:5.1f}/5")

        # Context = neutral in this diagnostic
        print(f"Market/sector      : {context_score:5.1f}/10")
        print("  (No context passed in this isolated diagnostic)")

        # Penalties
        penalties = []
        vwap_distance_atr = abs(close - vwap) / atr14
        if vwap_distance_atr > 2.5:
            score -= 8.0
            penalties.append("Price extended >2.5 ATR from VWAP (-8)")
        elif vwap_distance_atr > 2.0:
            score -= 4.0
            penalties.append("Price extended >2 ATR from VWAP (-4)")

        or_width = opening_high - opening_low
        if or_width > 2.5 * atr14:
            score -= 5.0
            penalties.append("Opening range unusually wide (-5)")

        # Reconstruct trade risk exactly like engine.
        if direction == "BULLISH":
            entry = opening_high
            stop = min(opening_low, vwap, entry - atr14)
        else:
            entry = opening_low
            stop = max(opening_high, vwap, entry + atr14)

        risk = abs(entry - stop)

        if risk < 0.35 * atr14:
            score -= 3.0
            penalties.append("Stop distance too tight for ATR (-3)")

        for p in penalties:
            print(f"PENALTY            : {p}")

        print("-" * 70)
        print(f"RAW SCORE          : {score:.2f}/100")
        print(f"FINAL CLAMPED      : {max(0.0, min(100.0, score)):.2f}/100")
        print(f"V13 WATCH THRESHOLD: {v.WATCH_SCORE:.2f}")
        print(
            "RESULT             : "
            + ("CANDIDATE" if score >= v.WATCH_SCORE else "NO SETUP")
        )
        print("-" * 70)

    print("\nNOTE: This diagnostic intentionally uses NO market/sector context.")
    print("The production V13 scan will pass the correct sector context.")


if __name__ == "__main__":
    diagnose()
