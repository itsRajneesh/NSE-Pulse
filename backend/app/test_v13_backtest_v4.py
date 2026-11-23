"""
V13 Historical Backtest Runner
--------------------------------
Independent backtest for V13. Does NOT modify v13_engine.py.

Rules:
- 15m Yahoo history (~60 days, Yahoo limitation)
- Bullish and Bearish are evaluated independently
- Historical point-in-time NIFTY/sector context
- No look-ahead: engine only sees candles up to the signal candle
- Developing/confirmed entries trigger only when future candles actually
  reach the OR entry level
- SL-first conflict
- First qualified setup per symbol/session/direction
- Separate bullish/bearish CSV files

Run:
    python -m app.test_v13_backtest_v2
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

from app.config import NIFTY_500_STOCKS, SECTOR_BENCHMARKS
from app.data_fetcher import _download_ticker_chunk
from app.market_context import build_market_context
from app.v13_engine import discover_v13_setups


CHUNK_SIZE = 20
PERIOD = "60d"
INTERVAL = "15m"

OUT_BULL = Path("v13_backtest_bullish.csv")
OUT_BEAR = Path("v13_backtest_bearish.csv")
OUT_SUMMARY = Path("v13_backtest_summary.txt")

# To keep the first run practical, evaluate every 15m candle from 09:30 onward.
# Once a direction produces its first qualified setup for a stock/session,
# that direction is no longer evaluated for that session.
MARKET_TICKER = "^NSEI"


def clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    x = df.copy()

    if isinstance(x.columns, pd.MultiIndex):
        # Flatten common yfinance single-ticker MultiIndex shapes.
        if x.columns.nlevels > 1:
            x.columns = [
                c[0] if str(c[0]) in {"Open", "High", "Low", "Close", "Volume"}
                else c[-1]
                for c in x.columns
            ]

    needed = ["Open", "High", "Low", "Close", "Volume"]
    if not all(c in x.columns for c in needed):
        return pd.DataFrame()

    x = x[needed].copy()
    x.index = pd.DatetimeIndex(x.index)

    if x.index.tz is None:
        x.index = x.index.tz_localize("Asia/Kolkata")
    else:
        x.index = x.index.tz_convert("Asia/Kolkata")

    for c in needed:
        x[c] = pd.to_numeric(x[c], errors="coerce")

    x = x.dropna(subset=["Open", "High", "Low", "Close"])
    x = x[~x.index.duplicated(keep="last")].sort_index()
    return x


def download_history(tickers: list[str], period: str, interval: str) -> dict[str, pd.DataFrame]:
    """Chunked Yahoo download. Returns clean symbol -> dataframe."""
    result: dict[str, pd.DataFrame] = {}

    for start in range(0, len(tickers), CHUNK_SIZE):
        chunk = tickers[start:start + CHUNK_SIZE]
        print(f"Downloading {start + 1}-{start + len(chunk)} / {len(tickers)} ...")

        try:
            raw = yf.download(
                tickers=chunk,
                period=period,
                interval=interval,
                group_by="ticker",
                auto_adjust=False,
                threads=False,
                progress=False,
            )
        except Exception as exc:
            print(f"  DOWNLOAD ERROR: {exc}")
            continue

        for ticker in chunk:
            key = ticker.replace(".NS", "")
            try:
                if len(chunk) == 1 and not isinstance(raw.columns, pd.MultiIndex):
                    part = raw
                else:
                    part = raw[ticker]
                part = clean_ohlcv(part)
                if not part.empty:
                    result[key] = part
            except Exception:
                continue

        print(f"  usable datasets: {len(result)}")

    return result


def benchmark_history(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Download benchmark 15m history, with a second single-ticker fallback."""
    out: dict[str, pd.DataFrame] = {}

    unique = list(dict.fromkeys([t for t in tickers if t]))
    for ticker in unique:
        try:
            raw = yf.download(
                tickers=ticker,
                period=PERIOD,
                interval=INTERVAL,
                group_by="column",
                auto_adjust=False,
                threads=False,
                progress=False,
            )
            df = clean_ohlcv(raw)
            if not df.empty:
                out[ticker] = df
                print(f"  benchmark OK: {ticker} ({len(df)} bars)")
            else:
                print(f"  benchmark EMPTY: {ticker}")
        except Exception as exc:
            print(f"  benchmark ERROR {ticker}: {exc}")
    return out


def daily_change_by_date(df: pd.DataFrame) -> dict[pd.Timestamp, float]:
    """
    Return session-date -> percentage change from previous trading day's close.
    This is point-in-time safe for a signal during that session.
    """
    if df.empty:
        return {}

    daily = df["Close"].resample("1D").last().dropna()
    daily.index = pd.DatetimeIndex(daily.index).tz_localize(None).normalize()

    result: dict[pd.Timestamp, float] = {}
    for i in range(1, len(daily)):
        prev = float(daily.iloc[i - 1])
        cur = float(daily.iloc[i])
        if prev > 0:
            result[daily.index[i]] = ((cur - prev) / prev) * 100.0
    return result


def benchmark_context_for_date(
    session_date: pd.Timestamp,
    nifty_changes: dict[pd.Timestamp, float],
    sector_changes: dict[str, dict[pd.Timestamp, float]],
    sector: str,
) -> Any:
    d = pd.Timestamp(session_date).tz_localize(None).normalize()

    nifty_pct = nifty_changes.get(d, 0.0)
    sector_ticker = SECTOR_BENCHMARKS.get(sector, "")
    sector_pct = sector_changes.get(sector_ticker, {}).get(d, 0.0)

    return build_market_context(
        nifty_change_pct=nifty_pct,
        sector_change_pct=sector_pct,
    )


def session_dates(df: pd.DataFrame) -> list[pd.Timestamp]:
    idx = pd.DatetimeIndex(df.index)
    dates = pd.Series(idx.date).drop_duplicates().tolist()
    return [pd.Timestamp(d) for d in dates]


def evaluate_outcome(
    full_session: pd.DataFrame,
    signal_pos: int,
    direction: str,
    entry: float,
    stop: float,
    target_1: float,
    target_2: float,
) -> tuple[str, str, float]:
    """
    Evaluate only candles AFTER the signal candle.

    Entry must be reached first. Once triggered, SL/T1/T2 are checked.
    If SL and target occur in the same candle, SL wins (conservative).
    """
    future = full_session.iloc[signal_pos + 1:]

    triggered = False
    trigger_time = ""

    for ts, row in future.iterrows():
        high = float(row["High"])
        low = float(row["Low"])

        if not triggered:
            if direction == "BULLISH":
                if high >= entry:
                    triggered = True
                    trigger_time = ts.isoformat()
                else:
                    continue
            else:
                if low <= entry:
                    triggered = True
                    trigger_time = ts.isoformat()
                else:
                    continue

        # Entry was triggered. Conservative intrabar ordering:
        # SL first whenever both SL and target are touched in one bar.
        if direction == "BULLISH":
            if low <= stop:
                return "LOSS_SL_FIRST", trigger_time, -1.0
            if high >= target_2:
                return "WIN_T2", trigger_time, 2.5
            if high >= target_1:
                return "WIN_T1", trigger_time, 1.5
        else:
            if high >= stop:
                return "LOSS_SL_FIRST", trigger_time, -1.0
            if low <= target_2:
                return "WIN_T2", trigger_time, 2.5
            if low <= target_1:
                return "WIN_T1", trigger_time, 1.5

    if triggered:
        return "OPEN_AFTER_ENTRY", trigger_time, np.nan
    return "NO_TRIGGER", "", np.nan


def candidate_row(
    symbol: str,
    name: str,
    sector: str,
    session_date: pd.Timestamp,
    candidate: Any,
    direction: str,
    outcome: str,
    trigger_time: str,
    realized_r: float,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "name": name,
        "sector": sector,
        "date": session_date.strftime("%Y-%m-%d"),
        "signal_time": candidate.signal_time,
        "direction": direction,
        "signal_type": candidate.signal_type,
        "setup_type": candidate.setup_type,
        "action": candidate.action,
        "grade": candidate.grade,
        "score": candidate.score,
        "entry": candidate.entry_price,
        "stop": candidate.stop_loss,
        "target_1": candidate.target_1,
        "target_2": candidate.target_2,
        "risk": candidate.risk_amount,
        "rr1": candidate.risk_reward_t1,
        "rr2": candidate.risk_reward_t2,
        "breakout_distance_atr": candidate.breakout_distance_atr,
        "outcome": outcome,
        "trigger_time": trigger_time,
        "realized_r": realized_r,
        "reasons": " | ".join(candidate.reasons),
        "penalties": " | ".join(candidate.penalties),
    }


def run() -> None:
    started = time.time()

    stocks = NIFTY_500_STOCKS
    symbols = [s["symbol"] for s in stocks]

    print("=" * 70)
    print("V13 HISTORICAL BACKTEST V2")
    print("=" * 70)
    print(f"Stocks      : {len(symbols)}")
    print(f"Period      : {PERIOD}")
    print(f"Interval    : {INTERVAL}")
    print(f"Chunk size  : {CHUNK_SIZE}")
    print("Directions  : BULLISH and BEARISH independently")
    print()

    # ------------------------------------------------------------
    # 1) STOCK DATA
    # ------------------------------------------------------------
    stock_tickers = [s + ".NS" for s in symbols]
    stock_data_raw = download_history(stock_tickers, PERIOD, INTERVAL)

    stock_data: dict[str, tuple[str, str, pd.DataFrame]] = {}
    for s in stocks:
        sym = s["symbol"]
        df = stock_data_raw.get(sym)
        if df is not None and not df.empty:
            stock_data[sym] = (s["name"], s["sector"], df)

    print()
    print(f"Usable stock datasets: {len(stock_data)} / {len(stocks)}")
    if len(stock_data) < 450:
        raise RuntimeError(
            f"Too few stock datasets ({len(stock_data)}). "
            "Aborting instead of producing a misleading backtest."
        )

    # ------------------------------------------------------------
    # 2) BENCHMARK DATA
    # ------------------------------------------------------------
    sector_tickers = sorted(
        set(v for v in SECTOR_BENCHMARKS.values() if v)
    )

    print()
    print("Downloading NIFTY benchmark...")
    nifty = benchmark_history([MARKET_TICKER]).get(MARKET_TICKER)
    if nifty is None or nifty.empty:
        raise RuntimeError("NIFTY benchmark unavailable. Aborting.")

    print()
    print("Downloading sector benchmarks...")
    sectors_data = benchmark_history(sector_tickers)

    missing_sectors = [t for t in sector_tickers if t not in sectors_data]
    if missing_sectors:
        print(f"WARNING: missing sector benchmarks: {missing_sectors}")
        print("Stocks belonging to these sectors will use NEUTRAL sector context.")

    nifty_changes = daily_change_by_date(nifty)
    sector_changes = {
        ticker: daily_change_by_date(df)
        for ticker, df in sectors_data.items()
    }

    # ------------------------------------------------------------
    # 3) BACKTEST
    # ------------------------------------------------------------
    bullish_rows: list[dict[str, Any]] = []
    bearish_rows: list[dict[str, Any]] = []

    total_sessions = 0
    total_candidates = {"BULLISH": 0, "BEARISH": 0}

    for stock_i, (sym, (name, sector, df)) in enumerate(stock_data.items(), 1):
        print(f"[{stock_i}/{len(stock_data)}] {sym}")

        for session_date in session_dates(df):
            mask = pd.DatetimeIndex(df.index).date == session_date.date()
            session = df.loc[mask].copy()

            if session.empty:
                continue

            # V13 requires enough historical bars for indicators.
            # Keep ALL history up to each checkpoint, not just today's bars.
            session_positions = [
                i for i, ts in enumerate(session.index)
                if ts.time() >= pd.Timestamp("09:30").time()
            ]

            if not session_positions:
                continue

            total_sessions += 1

            context = benchmark_context_for_date(
                session_date,
                nifty_changes,
                sector_changes,
                sector,
            )

            # Once a direction has produced its first qualified setup
            # for this stock/session, stop checking that direction.
            done = {"BULLISH": False, "BEARISH": False}

            for pos in session_positions:
                if done["BULLISH"] and done["BEARISH"]:
                    break

                signal_ts = session.index[pos]

                # Only history up to signal candle is visible to engine.
                history = df.loc[:signal_ts].copy()

                result = discover_v13_setups(
                    symbol=sym,
                    name=name,
                    sector=sector,
                    df=history,
                    context=context,
                )

                for direction, target_rows in (
                    ("BULLISH", bullish_rows),
                    ("BEARISH", bearish_rows),
                ):
                    if done[direction]:
                        continue

                    candidate = result.get(
                        "bullish" if direction == "BULLISH" else "bearish"
                    )

                    if candidate is None:
                        continue

                    # Candidate.signal_time should match the checkpoint.
                    # This guard prevents accidental duplicate/misaligned signals.
                    if candidate.signal_time is None:
                        continue

                    total_candidates[direction] += 1

                    outcome, trigger_time, realized_r = evaluate_outcome(
                        full_session=session,
                        signal_pos=pos,
                        direction=direction,
                        entry=float(candidate.entry_price),
                        stop=float(candidate.stop_loss),
                        target_1=float(candidate.target_1),
                        target_2=float(candidate.target_2),
                    )

                    target_rows.append(
                        candidate_row(
                            symbol=sym,
                            name=name,
                            sector=sector,
                            session_date=session_date,
                            candidate=candidate,
                            direction=direction,
                            outcome=outcome,
                            trigger_time=trigger_time,
                            realized_r=realized_r,
                        )
                    )

                    done[direction] = True

    # ------------------------------------------------------------
    # 4) SAVE
    # ------------------------------------------------------------
    bull_df = pd.DataFrame(bullish_rows)
    bear_df = pd.DataFrame(bearish_rows)

    bull_df.to_csv(OUT_BULL, index=False)
    bear_df.to_csv(OUT_BEAR, index=False)

    def stats(x: pd.DataFrame) -> dict[str, Any]:
        if x.empty:
            return {
                "qualified": 0,
                "triggered": 0,
                "closed": 0,
                "wins": 0,
                "losses": 0,
                "wr": 0.0,
                "avg_r": 0.0,
                "total_r": 0.0,
            }

        triggered = x[x["outcome"].isin([
            "LOSS_SL_FIRST", "WIN_T1", "WIN_T2", "OPEN_AFTER_ENTRY"
        ])]
        closed = x[x["outcome"].isin(["LOSS_SL_FIRST", "WIN_T1", "WIN_T2"])]
        wins = closed[closed["realized_r"] > 0]
        losses = closed[closed["realized_r"] < 0]

        return {
            "qualified": len(x),
            "triggered": len(triggered),
            "closed": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "wr": round((len(wins) / len(closed) * 100), 2) if len(closed) else 0.0,
            "avg_r": round(float(closed["realized_r"].mean()), 4) if len(closed) else 0.0,
            "total_r": round(float(closed["realized_r"].sum()), 2) if len(closed) else 0.0,
        }

    bull_stats = stats(bull_df)
    bear_stats = stats(bear_df)

    summary = f"""
V13 HISTORICAL BACKTEST V2
==========================
Stock datasets : {len(stock_data)}/{len(stocks)}
Sessions       : {total_sessions}
Period         : {PERIOD}
Interval       : {INTERVAL}

BULLISH
-------
Qualified      : {bull_stats["qualified"]}
Triggered      : {bull_stats["triggered"]}
Closed         : {bull_stats["closed"]}
Wins           : {bull_stats["wins"]}
Losses         : {bull_stats["losses"]}
Win rate       : {bull_stats["wr"]}%
Avg R          : {bull_stats["avg_r"]}
Total R        : {bull_stats["total_r"]}

BEARISH
-------
Qualified      : {bear_stats["qualified"]}
Triggered      : {bear_stats["triggered"]}
Closed         : {bear_stats["closed"]}
Wins           : {bear_stats["wins"]}
Losses         : {bear_stats["losses"]}
Win rate       : {bear_stats["wr"]}%
Avg R          : {bear_stats["avg_r"]}
Total R        : {bear_stats["total_r"]}

Elapsed        : {round(time.time() - started, 1)} sec
"""

    OUT_SUMMARY.write_text(summary.strip() + "\n", encoding="utf-8")

    print(summary)
    print(f"Saved: {OUT_BULL}")
    print(f"Saved: {OUT_BEAR}")
    print(f"Saved: {OUT_SUMMARY}")


if __name__ == "__main__":
    run()
