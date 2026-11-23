from __future__ import annotations

import yfinance as yf

from app.config import NIFTY_500_STOCKS
from app.market_context import build_live_context_cache
from app.prediction_engine import evaluate_prediction_setup
from app.v13_engine import calculate_v13_score


def main():
    print("=" * 80)
    print("V13 CONTEXT-AWARE RANKING TEST")
    print("=" * 80)

    # ---------------------------------------------------------
    # Build NIFTY + sector context ONCE
    # ---------------------------------------------------------

    sectors = [
        stock.get("sector", "Unknown")
        for stock in NIFTY_500_STOCKS
    ]

    print("\nBuilding market / sector context...")

    try:
        context_cache = build_live_context_cache(sectors)

        print("Market context ready.")

        nifty_context = context_cache.get("__NIFTY__")

        if nifty_context:
            print(
                f"NIFTY: "
                f"{nifty_context.nifty_direction} "
                f"{nifty_context.nifty_change_pct:+.2f}%"
            )

    except Exception as exc:
        print(f"Context ERROR: {exc}")
        return

    bullish_results = []
    bearish_results = []

    # ---------------------------------------------------------
    # Scan stocks
    # ---------------------------------------------------------

    for index, stock in enumerate(NIFTY_500_STOCKS, start=1):
        try:
            symbol = stock.get("symbol", "")
            name = stock.get("name", symbol)
            sector = stock.get("sector", "Unknown")

            if not symbol:
                continue

            print(
                f"[{index}/{len(NIFTY_500_STOCKS)}] "
                f"{symbol}",
                end=" -> ",
                flush=True,
            )

            df = yf.download(
                f"{symbol}.NS",
                period="5d",
                interval="15m",
                auto_adjust=False,
                progress=False,
            )

            if df is None or df.empty:
                print("NO DATA")
                continue

            if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                df.columns = df.columns.droplevel(1)

            # -------------------------------------------------
            # Get sector-specific context
            # -------------------------------------------------

            context = context_cache.get(sector)

            # Fallback to NIFTY context if sector is unavailable
            if context is None:
                context = nifty_context

            setup = evaluate_prediction_setup(
                symbol=symbol,
                name=name,
                sector=sector,
                df=df,
                context=context,
            )

            if setup is None:
                print("NO SETUP")
                continue

            v13 = calculate_v13_score(
                setup,
                context=context,
            )

            if v13.action == "REJECT":
                print(
                    f"REJECT | "
                    f"{setup.signal_type} | "
                    f"Base {setup.confidence_score:.1f} | "
                    f"V13 {v13.final_score:.1f}"
                )
                continue

            result = {
                "setup": setup,
                "v13": v13,
            }

            direction = str(setup.signal_type).upper()

            if direction == "BULLISH":
                bullish_results.append(result)

            elif direction == "BEARISH":
                bearish_results.append(result)

            print(
                f"{direction} | "
                f"Base {setup.confidence_score:.1f} | "
                f"V13 {v13.final_score:.1f} | "
                f"{v13.grade} | "
                f"{v13.action}"
            )

        except Exception as exc:
            print(f"ERROR | {exc}")

    # ---------------------------------------------------------
    # Sort directions SEPARATELY
    # ---------------------------------------------------------

    bullish_results.sort(
        key=lambda item: item["v13"].final_score,
        reverse=True,
    )

    bearish_results.sort(
        key=lambda item: item["v13"].final_score,
        reverse=True,
    )

    # ---------------------------------------------------------
    # Summary
    # ---------------------------------------------------------

    print("\n")
    print("=" * 80)
    print("V13 RESULTS SUMMARY")
    print("=" * 80)

    print(f"BULLISH candidates: {len(bullish_results)}")
    print(f"BEARISH candidates: {len(bearish_results)}")

    # ---------------------------------------------------------
    # Bullish Top 10
    # ---------------------------------------------------------

    print("\n")
    print("=" * 80)
    print("TOP 10 BULLISH")
    print("=" * 80)

    if not bullish_results:
        print("NO BULLISH SETUP")

    for rank, item in enumerate(bullish_results[:10], start=1):
        setup = item["setup"]
        v13 = item["v13"]

        print(
            f"\n#{rank} {setup.symbol} | "
            f"V13 {v13.final_score:.1f}/100 | "
            f"{v13.grade} | "
            f"{v13.action}"
        )

        print(f"   Name       : {setup.name}")
        print(f"   Sector     : {setup.sector}")
        print(f"   Setup      : {setup.setup_type}")
        print(f"   Base Score : {setup.confidence_score:.1f}")
        print(f"   Rel Volume : {setup.rel_vol:.2f}x")
        print(f"   LTP        : {setup.ltp}")
        print(f"   Entry      : {setup.entry_price}")
        print(f"   Stop Loss  : {setup.stop_loss}")
        print(f"   Target 1   : {setup.target_1}")
        print(f"   Target 2   : {setup.target_2}")

        if v13.reasons:
            print("   Reasons:")
            for reason in v13.reasons:
                print(f"      + {reason}")

        if v13.penalties:
            print("   Penalties:")
            for penalty in v13.penalties:
                print(f"      - {penalty}")

    # ---------------------------------------------------------
    # Bearish Top 10
    # ---------------------------------------------------------

    print("\n")
    print("=" * 80)
    print("TOP 10 BEARISH")
    print("=" * 80)

    if not bearish_results:
        print("NO BEARISH SETUP")

    for rank, item in enumerate(bearish_results[:10], start=1):
        setup = item["setup"]
        v13 = item["v13"]

        print(
            f"\n#{rank} {setup.symbol} | "
            f"V13 {v13.final_score:.1f}/100 | "
            f"{v13.grade} | "
            f"{v13.action}"
        )

        print(f"   Name       : {setup.name}")
        print(f"   Sector     : {setup.sector}")
        print(f"   Setup      : {setup.setup_type}")
        print(f"   Base Score : {setup.confidence_score:.1f}")
        print(f"   Rel Volume : {setup.rel_vol:.2f}x")
        print(f"   LTP        : {setup.ltp}")
        print(f"   Entry      : {setup.entry_price}")
        print(f"   Stop Loss  : {setup.stop_loss}")
        print(f"   Target 1   : {setup.target_1}")
        print(f"   Target 2   : {setup.target_2}")

        if v13.reasons:
            print("   Reasons:")
            for reason in v13.reasons:
                print(f"      + {reason}")

        if v13.penalties:
            print("   Penalties:")
            for penalty in v13.penalties:
                print(f"      - {penalty}")


if __name__ == "__main__":
    main()