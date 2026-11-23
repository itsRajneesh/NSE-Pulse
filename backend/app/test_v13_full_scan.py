from __future__ import annotations

from collections import Counter
from typing import Any

from .config import NIFTY_500_STOCKS
from .data_fetcher import fetch_nifty500_low_memory
from .market_context import build_live_context_cache
from .v13_engine import (
    V13Candidate,
    discover_v13_setups,
    rank_v13_bullish,
    rank_v13_bearish,
)


TOP_N = 10
DOWNLOAD_CHUNK_SIZE = 20


def _fmt(candidate: V13Candidate) -> str:
    return (
        f"{candidate.symbol:<16} "
        f"{candidate.score:5.1f} "
        f"{candidate.action:<16} "
        f"{candidate.setup_type:<30} "
        f"LTP {candidate.ltp:.2f} | "
        f"Entry {candidate.entry_price:.2f} | "
        f"SL {candidate.stop_loss:.2f} | "
        f"T1 {candidate.target_1:.2f} | "
        f"T2 {candidate.target_2:.2f} | "
        f"RVOL {candidate.rel_vol:.2f}x"
    )


def _print_candidate_details(candidate: V13Candidate) -> None:
    print(f"\n{candidate.symbol} — {candidate.name}")
    print(f"  Score      : {candidate.score:.1f}/100")
    print(f"  Grade      : {candidate.grade}")
    print(f"  Action     : {candidate.action}")
    print(f"  Direction  : {candidate.signal_type}")
    print(f"  Setup      : {candidate.setup_type}")
    print(f"  LTP        : {candidate.ltp:.2f}")
    print(f"  Entry      : {candidate.entry_price:.2f}")
    print(f"  Stop Loss  : {candidate.stop_loss:.2f}")
    print(f"  Target 1   : {candidate.target_1:.2f}")
    print(f"  Target 2   : {candidate.target_2:.2f}")
    print(f"  Risk       : {candidate.risk_amount:.2f}")
    print(f"  RVOL       : {candidate.rel_vol:.2f}x")
    print(f"  RSI        : {candidate.rsi14:.2f}")
    print(f"  EMA20      : {candidate.ema20:.2f}")
    print(f"  VWAP       : {candidate.vwap:.2f}")
    print(f"  ATR14      : {candidate.atr14:.2f}")
    print(
        f"  OR         : "
        f"{candidate.opening_range_high:.2f} / "
        f"{candidate.opening_range_low:.2f}"
    )
    print(
        f"  Prev Day   : "
        f"{candidate.previous_day_high:.2f} / "
        f"{candidate.previous_day_low:.2f}"
    )
    print("  Reasons:")
    for reason in candidate.reasons:
        print(f"    + {reason}")

    if candidate.penalties:
        print("  Penalties:")
        for penalty in candidate.penalties:
            print(f"    - {penalty}")


def main() -> None:
    print("=" * 100)
    print("V13 NIFTY 500 INDEPENDENT DISCOVERY SCAN")
    print("=" * 100)
    print()
    print("Bullish and Bearish are evaluated independently.")
    print("V5/V12 qualification gates are NOT used.")
    print("Score is a QUALITY SCORE, not a probability.")
    print()

    sectors = sorted(
        {
            str(stock.get("sector", "")).strip()
            for stock in NIFTY_500_STOCKS
            if stock.get("sector")
        }
    )

    print(f"Stocks configured : {len(NIFTY_500_STOCKS)}")
    print(f"Sectors configured: {len(sectors)}")
    print("Building NIFTY + sector context cache...")

    context_cache = build_live_context_cache(sectors)

    # build_live_context_cache stores the NIFTY snapshot inside each
    # sector MarketContext; it does not use a "__NIFTY__" cache key.
    # So use any available context only for REPORTING the shared NIFTY state.
    # This does not change the context passed to individual stocks.
    sample_context = next(iter(context_cache.values()), None)

    print(
        "Context cache ready:",
        len(context_cache),
        "entries",
    )

    if sample_context is not None:
        print(
            f"NIFTY direction: "
            f"{getattr(sample_context, 'nifty_direction', 'UNKNOWN')} "
            f"({getattr(sample_context, 'nifty_change_pct', 0):.2f}%)"
        )
    else:
        print("NIFTY context: unavailable")

    print()
    print(
        f"Starting low-memory scan "
        f"(chunk size={DOWNLOAD_CHUNK_SIZE})..."
    )
    print()

    bullish_candidates: list[V13Candidate] = []
    bearish_candidates: list[V13Candidate] = []

    scanned = 0
    data_ok = 0
    data_failed = 0
    engine_failed = 0

    action_counts: Counter[str] = Counter()
    bullish_actions: Counter[str] = Counter()
    bearish_actions: Counter[str] = Counter()

    for sym, df_15m in fetch_nifty500_low_memory(
        NIFTY_500_STOCKS,
        chunk_size=DOWNLOAD_CHUNK_SIZE,
    ):
        scanned += 1

        stock_info = next(
            (
                stock
                for stock in NIFTY_500_STOCKS
                if stock["symbol"] == sym
            ),
            None,
        )

        if not stock_info:
            data_failed += 1
            continue

        if df_15m is None or df_15m.empty or len(df_15m) < 5:
            data_failed += 1
            continue

        data_ok += 1

        name = stock_info["name"]
        sector = stock_info["sector"]

        # IMPORTANT:
        # Never fall back to NIFTY context for an unmapped sector.
        # An unmapped sector remains context-neutral.
        context = context_cache.get(sector)

        try:
            result = discover_v13_setups(
                symbol=sym,
                name=name,
                sector=sector,
                df=df_15m,
                context=context,
            )

            bullish = result["bullish"]
            bearish = result["bearish"]

            if bullish is not None:
                bullish_candidates.append(bullish)
                action_counts[bullish.action] += 1
                bullish_actions[bullish.action] += 1

            if bearish is not None:
                bearish_candidates.append(bearish)
                action_counts[bearish.action] += 1
                bearish_actions[bearish.action] += 1

        except Exception as exc:
            engine_failed += 1
            print(f"V13 evaluation failed for {sym}: {exc}")

        finally:
            del df_15m

    bullish_ranked = rank_v13_bullish(bullish_candidates)
    bearish_ranked = rank_v13_bearish(bearish_candidates)

    print()
    print("=" * 100)
    print("SCAN SUMMARY")
    print("=" * 100)
    print(f"Stocks scanned       : {scanned}/{len(NIFTY_500_STOCKS)}")
    print(f"Data OK              : {data_ok}")
    print(f"Data unavailable     : {data_failed}")
    print(f"Engine errors        : {engine_failed}")
    print()
    print(f"Bullish candidates   : {len(bullish_candidates)}")
    print(f"Bearish candidates   : {len(bearish_candidates)}")
    print()
    print(f"Bullish actions      : {dict(bullish_actions)}")
    print(f"Bearish actions      : {dict(bearish_actions)}")

    print()
    print("=" * 100)
    print("TOP 10 BULLISH — SEPARATE RANKING")
    print("=" * 100)

    if not bullish_ranked:
        print("NO BULLISH SETUP")
    else:
        print(
            f"{'SYMBOL':<16} {'SCORE':>5} {'ACTION':<16} "
            f"{'SETUP':<30} DETAILS"
        )
        print("-" * 100)

        for candidate in bullish_ranked[:TOP_N]:
            print(_fmt(candidate))

    print()
    print("=" * 100)
    print("TOP 10 BEARISH — SEPARATE RANKING")
    print("=" * 100)

    if not bearish_ranked:
        print("NO BEARISH SETUP")
    else:
        print(
            f"{'SYMBOL':<16} {'SCORE':>5} {'ACTION':<16} "
            f"{'SETUP':<30} DETAILS"
        )
        print("-" * 100)

        for candidate in bearish_ranked[:TOP_N]:
            print(_fmt(candidate))

    # Detailed view only for the strongest 3 from each direction.
    print()
    print("=" * 100)
    print("TOP 3 BULLISH — DETAILED")
    print("=" * 100)

    for candidate in bullish_ranked[:3]:
        _print_candidate_details(candidate)

    print()
    print("=" * 100)
    print("TOP 3 BEARISH — DETAILED")
    print("=" * 100)

    for candidate in bearish_ranked[:3]:
        _print_candidate_details(candidate)

    print()
    print("=" * 100)
    print("END OF V13 DISCOVERY SCAN")
    print("=" * 100)


if __name__ == "__main__":
    main()
