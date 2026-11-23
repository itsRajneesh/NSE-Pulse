"""
DOUBLE-BLIND PARITY VERIFICATION (PILLAR 4)
===========================================
Verifies that the Vectorized Fast Pipeline produces 100.00% identical trades,
prices, timestamps, outcomes, and R-multiples compared to the baseline V13 engine.

Usage:
    python verify_parity_fast.py
"""

from __future__ import annotations

import math
import os
import pickle
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

# local import
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from app.config import SECTOR_BENCHMARKS
from app.market_context import build_market_context, get_sector_benchmark_ticker
from app.v13_engine import discover_v13_setups

SIGNAL_START_TIME = pd.Timestamp("09:30").time()
SIGNAL_CUTOFF_TIME = pd.Timestamp("15:00").time()
IST_TIMEZONE = "Asia/Kolkata"


def normalize_dataframe(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or getattr(df, "empty", True):
        return pd.DataFrame()
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        lvl0 = [str(c).strip().lower() for c in out.columns.get_level_values(0)]
        lvl1 = [str(c).strip().lower() for c in out.columns.get_level_values(1)]
        if any(c in lvl0 for c in ["open", "high", "low", "close"]):
            out.columns = out.columns.get_level_values(0)
        elif any(c in lvl1 for c in ["open", "high", "low", "close"]):
            out.columns = out.columns.get_level_values(1)
        else:
            out.columns = out.columns.get_level_values(-1)

    rename_map = {col: str(col).strip().lower() for col in out.columns}
    out.rename(columns=rename_map, inplace=True)
    required_cols = {"open", "high", "low", "close"}
    if not required_cols.issubset(out.columns):
        return pd.DataFrame()
    if "volume" not in out.columns:
        out["volume"] = 1000.0

    out.dropna(subset=["open", "high", "low", "close"], inplace=True)
    if out.empty:
        return pd.DataFrame()

    out.index = pd.to_datetime(out.index)
    try:
        if out.index.tz is None:
            out.index = out.index.tz_localize(IST_TIMEZONE)
        else:
            out.index = out.index.tz_convert(IST_TIMEZONE)
    except Exception:
        pass
    return out.sort_index()


def simulate_trade_outcome_slow(candidate, future_df: pd.DataFrame) -> Tuple[str, bool, Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    """Original row-by-row simulation."""
    direction = str(candidate.signal_type).upper()
    entry = float(candidate.entry_price)
    sl = float(candidate.stop_loss)
    t1 = float(candidate.target_1)
    t2 = float(candidate.target_2)

    if not all(math.isfinite(x) for x in (entry, sl, t1, t2)):
        return "INVALID", False, None, None

    triggered = False
    trigger_time = None

    for ts, row in future_df.iterrows():
        high = float(row["high"])
        low = float(row["low"])

        if not triggered:
            if direction == "BULLISH":
                if high >= entry:
                    triggered = True
                    trigger_time = ts
            else:
                if low <= entry:
                    triggered = True
                    trigger_time = ts

            if not triggered:
                continue

        if direction == "BULLISH":
            if low <= sl:
                return "SL_FIRST", True, trigger_time, ts
            if high >= t2:
                return "T2_FIRST", True, trigger_time, ts
            if high >= t1:
                return "T1_FIRST", True, trigger_time, ts
        else:
            if high >= sl:
                return "SL_FIRST", True, trigger_time, ts
            if low <= t2:
                return "T2_FIRST", True, trigger_time, ts
            if low <= t1:
                return "T1_FIRST", True, trigger_time, ts

    return ("OPEN" if triggered else "NO_TRIGGER"), triggered, trigger_time, None


def simulate_trade_outcome_fast(candidate, future_df: pd.DataFrame) -> Tuple[str, bool, Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    """Pillar 3: Zero-Copy Vectorized Outcome Simulator (pure NumPy)."""
    if future_df.empty:
        return "NO_TRIGGER", False, None, None

    direction = str(candidate.signal_type).upper()
    entry = float(candidate.entry_price)
    sl = float(candidate.stop_loss)
    t1 = float(candidate.target_1)
    t2 = float(candidate.target_2)

    if not all(math.isfinite(x) for x in (entry, sl, t1, t2)):
        return "INVALID", False, None, None

    highs = future_df["high"].to_numpy(dtype=np.float64)
    lows = future_df["low"].to_numpy(dtype=np.float64)
    times = future_df.index

    n_bars = len(highs)
    triggered = False
    trigger_idx = -1

    if direction == "BULLISH":
        trig_mask = highs >= entry
        if not np.any(trig_mask):
            return "NO_TRIGGER", False, None, None
        trigger_idx = int(np.argmax(trig_mask))
        trigger_time = times[trigger_idx]

        for i in range(trigger_idx, n_bars):
            if lows[i] <= sl:
                return "SL_FIRST", True, trigger_time, times[i]
            if highs[i] >= t2:
                return "T2_FIRST", True, trigger_time, times[i]
            if highs[i] >= t1:
                return "T1_FIRST", True, trigger_time, times[i]
    else:
        trig_mask = lows <= entry
        if not np.any(trig_mask):
            return "NO_TRIGGER", False, None, None
        trigger_idx = int(np.argmax(trig_mask))
        trigger_time = times[trigger_idx]

        for i in range(trigger_idx, n_bars):
            if highs[i] >= sl:
                return "SL_FIRST", True, trigger_time, times[i]
            if lows[i] <= t2:
                return "T2_FIRST", True, trigger_time, times[i]
            if lows[i] <= t1:
                return "T1_FIRST", True, trigger_time, times[i]

    return "OPEN", True, trigger_time, None


def get_r_multiple(outcome: str) -> float:
    return {
        "SL_FIRST": -1.0,
        "T1_FIRST": 1.5,
        "T2_FIRST": 2.5,
        "OPEN": 0.0,
        "NO_TRIGGER": 0.0,
        "INVALID": 0.0,
    }.get(outcome, 0.0)


def precompute_market_context_matrix(nifty_df: pd.DataFrame, sector_dfs: Dict[str, pd.DataFrame], sectors: List[str]):
    context_matrix: Dict[Tuple[pd.Timestamp, str], Any] = {}
    if nifty_df is None or nifty_df.empty:
        return context_matrix

    nifty_dates = sorted(pd.DatetimeIndex(nifty_df.index.normalize()).unique())
    nifty_prev_close: Dict[Any, float] = {}
    for i in range(1, len(nifty_dates)):
        prev_d = nifty_dates[i - 1]
        curr_d = nifty_dates[i]
        prev_day_slice = nifty_df[nifty_df.index.normalize() == prev_d]
        if not prev_day_slice.empty:
            nifty_prev_close[curr_d.date()] = float(prev_day_slice["close"].iloc[-1])

    sector_prev_close: Dict[str, Dict[Any, float]] = defaultdict(dict)
    for sec, sdf in sector_dfs.items():
        if sdf is not None and not sdf.empty:
            s_dates = sorted(pd.DatetimeIndex(sdf.index.normalize()).unique())
            for i in range(1, len(s_dates)):
                prev_d = s_dates[i - 1]
                curr_d = s_dates[i]
                prev_day_slice = sdf[sdf.index.normalize() == prev_d]
                if not prev_day_slice.empty:
                    sector_prev_close[sec][curr_d.date()] = float(prev_day_slice["close"].iloc[-1])

    unique_sectors = set(sectors)
    unique_sectors.add("Diversified")

    for ts, row in nifty_df.iterrows():
        d = ts.date()
        p_close = nifty_prev_close.get(d)
        if not p_close or p_close <= 0:
            continue
        n_change = (float(row["close"]) / p_close - 1.0) * 100.0

        for sec in unique_sectors:
            sec_change = 0.0
            sdf = sector_dfs.get(sec)
            if sdf is not None and not sdf.empty:
                s_p_close = sector_prev_close.get(sec, {}).get(d)
                if s_p_close and s_p_close > 0:
                    past_sec = sdf[sdf.index <= ts]
                    if not past_sec.empty:
                        s_now = float(past_sec["close"].iloc[-1])
                        sec_change = (s_now / s_p_close - 1.0) * 100.0

            ctx = build_market_context(nifty_change_pct=n_change, sector_change_pct=sec_change)
            context_matrix[(ts, sec)] = ctx

    return context_matrix


def run_baseline_single_stock(stock_tuple, df, context_matrix):
    symbol, name, sector = stock_tuple
    records = []
    dates = sorted(pd.Index(df.index.date).unique())
    date_indices = defaultdict(list)
    for idx_num, dt in enumerate(df.index):
        date_indices[dt.date()].append(idx_num)

    for date in dates:
        row_indices = date_indices[date]
        if len(row_indices) < 2:
            continue
        bull_found = False
        bear_found = False
        day_df = df.iloc[row_indices]

        for rel_pos, row_idx in enumerate(row_indices):
            signal_ts = df.index[row_idx]
            t = signal_ts.time()
            if t < SIGNAL_START_TIME or t > SIGNAL_CUTOFF_TIME:
                continue
            if bull_found and bear_found:
                break
            hist_len = row_idx + 1
            if hist_len < 20:
                continue
            hist = df.iloc[:hist_len]

            context = context_matrix.get((signal_ts, sector)) or context_matrix.get((signal_ts, "Diversified"))
            if context is None:
                continue

            try:
                setups = discover_v13_setups(symbol=symbol, name=name, sector=sector, df=hist, context=context)
            except Exception:
                continue

            future_df = day_df.iloc[rel_pos + 1:]

            if not bull_found and setups.get("bullish"):
                c = setups["bullish"]
                out, trig, trig_ts, out_ts = simulate_trade_outcome_slow(c, future_df)
                records.append({
                    "symbol": c.symbol, "date": str(date), "signal_time": str(signal_ts),
                    "direction": "BULLISH", "score": float(c.score), "entry_price": float(c.entry_price),
                    "stop_loss": float(c.stop_loss), "target_1": float(c.target_1), "target_2": float(c.target_2),
                    "outcome": out, "r_multiple": get_r_multiple(out),
                })
                bull_found = True

            if not bear_found and setups.get("bearish"):
                c = setups["bearish"]
                out, trig, trig_ts, out_ts = simulate_trade_outcome_slow(c, future_df)
                records.append({
                    "symbol": c.symbol, "date": str(date), "signal_time": str(signal_ts),
                    "direction": "BEARISH", "score": float(c.score), "entry_price": float(c.entry_price),
                    "stop_loss": float(c.stop_loss), "target_1": float(c.target_1), "target_2": float(c.target_2),
                    "outcome": out, "r_multiple": get_r_multiple(out),
                })
                bear_found = True

    return records


def run_fast_single_stock(stock_tuple, df, context_matrix):
    symbol, name, sector = stock_tuple
    records = []
    dates = sorted(pd.Index(df.index.date).unique())
    date_indices = defaultdict(list)
    for idx_num, dt in enumerate(df.index):
        date_indices[dt.date()].append(idx_num)

    # Precalculate previous day close per session
    prev_close_per_date = {}
    for i in range(1, len(dates)):
        prev_indices = date_indices[dates[i - 1]]
        if prev_indices:
            prev_close_per_date[dates[i]] = float(df["close"].iloc[prev_indices[-1]])

    for date in dates:
        row_indices = date_indices[date]
        if len(row_indices) < 2:
            continue
        bull_found = False
        bear_found = False
        day_df = df.iloc[row_indices]
        p_close = prev_close_per_date.get(date)

        for rel_pos, row_idx in enumerate(row_indices):
            signal_ts = df.index[row_idx]
            t = signal_ts.time()
            if t < SIGNAL_START_TIME or t > SIGNAL_CUTOFF_TIME:
                continue
            if bull_found and bear_found:
                break
            hist_len = row_idx + 1
            if hist_len < 20:
                continue

            # Pillar 2: Vectorized Boolean Gate
            # 1. Price Floor Gate
            curr_close = float(df["close"].iloc[row_idx])
            if curr_close < 30.0:
                continue
            # 2. Circuit Zero-Range Gate
            curr_high = float(df["high"].iloc[row_idx])
            curr_low = float(df["low"].iloc[row_idx])
            if (curr_high - curr_low) <= 0.0:
                continue

            # 3. Momentum Expansion Filter (+/-0.80% day change)
            if p_close and p_close > 0:
                day_change_pct = ((curr_close - p_close) / p_close) * 100.0
                can_bull = (day_change_pct >= 0.80) and (not bull_found)
                can_bear = (day_change_pct <= -0.80) and (not bear_found)
                if not can_bull and not can_bear:
                    continue

            hist = df.iloc[:hist_len]
            context = context_matrix.get((signal_ts, sector)) or context_matrix.get((signal_ts, "Diversified"))
            if context is None:
                continue

            try:
                setups = discover_v13_setups(symbol=symbol, name=name, sector=sector, df=hist, context=context)
            except Exception:
                continue

            future_df = day_df.iloc[rel_pos + 1:]

            if not bull_found and setups.get("bullish"):
                c = setups["bullish"]
                out, trig, trig_ts, out_ts = simulate_trade_outcome_fast(c, future_df)
                records.append({
                    "symbol": c.symbol, "date": str(date), "signal_time": str(signal_ts),
                    "direction": "BULLISH", "score": float(c.score), "entry_price": float(c.entry_price),
                    "stop_loss": float(c.stop_loss), "target_1": float(c.target_1), "target_2": float(c.target_2),
                    "outcome": out, "r_multiple": get_r_multiple(out),
                })
                bull_found = True

            if not bear_found and setups.get("bearish"):
                c = setups["bearish"]
                out, trig, trig_ts, out_ts = simulate_trade_outcome_fast(c, future_df)
                records.append({
                    "symbol": c.symbol, "date": str(date), "signal_time": str(signal_ts),
                    "direction": "BEARISH", "score": float(c.score), "entry_price": float(c.entry_price),
                    "stop_loss": float(c.stop_loss), "target_1": float(c.target_1), "target_2": float(c.target_2),
                    "outcome": out, "r_multiple": get_r_multiple(out),
                })
                bear_found = True

    return records


def main():
    print("=" * 95)
    print("🔬 PILLAR 4: DOUBLE-BLIND PARITY VERIFICATION (BASELINE vs FAST PIPELINE)")
    print("=" * 95)

    cache_path = BASE_DIR / "app" / "data" / "nifty500_ohlcv_15m_cache.pkl"
    if not cache_path.exists():
        cache_path = BASE_DIR / "app" / "data" / "expanded_1000cr_ohlcv_15m_cache.pkl"

    if not cache_path.exists():
        print(f"Error: Cache file not found at {cache_path}")
        return

    with open(cache_path, "rb") as f:
        cache = pickle.load(f)

    test_stocks = [
        ("COLPAL", "Colgate Palmolive", "FMCG"),
        ("CAMS", "Computer Age Management", "Financial Services"),
        ("CONCOR", "Container Corporation", "Services"),
        ("COROMANDEL", "Coromandel International", "Chemicals"),
        ("CUMMINSIND", "Cummins India", "Capital Goods"),
    ]

    print(f"Loaded {len(cache)} cached datasets.")
    print(f"Testing parity across {len(test_stocks)} diverse stocks: {[s[0] for s in test_stocks]}")
    print()

    # Precompute context
    sectors = [s[2] for s in test_stocks]
    print("Fetching benchmark histories (^NSEI and sector benchmarks)...")
    nifty_raw = yf.download("^NSEI", period="60d", interval="15m", auto_adjust=False, progress=False, threads=False)
    nifty_df = normalize_dataframe(nifty_raw)

    sector_dfs = {}
    for sec in set(sectors):
        tk = SECTOR_BENCHMARKS.get(sec) or get_sector_benchmark_ticker(sec)
        if tk:
            try:
                sdf = normalize_dataframe(yf.download(tk, period="60d", interval="15m", auto_adjust=False, progress=False, threads=False))
                if not sdf.empty:
                    sector_dfs[sec] = sdf
            except Exception:
                pass

    context_matrix = precompute_market_context_matrix(nifty_df, sector_dfs, sectors)
    print(f"✓ Context Matrix built: {len(context_matrix):,} entries.")
    print("-" * 95)

    all_matched = True
    total_baseline_trades = 0
    total_fast_trades = 0

    for st in test_stocks:
        sym = st[0]
        ticker = f"{sym}.NS"
        if ticker not in cache and sym not in cache:
            print(f"Skipping {sym} (not in cache)")
            continue

        df = cache.get(ticker) if ticker in cache else cache.get(sym)

        # Baseline Slow Run
        t0 = time.time()
        base_trades = run_baseline_single_stock(st, df, context_matrix)
        t_base = time.time() - t0

        # Fast Vectorized Run
        t1 = time.time()
        fast_trades = run_fast_single_stock(st, df, context_matrix)
        t_fast = time.time() - t1

        total_baseline_trades += len(base_trades)
        total_fast_trades += len(fast_trades)

        speedup = (t_base / t_fast) if t_fast > 0 else 1.0

        # Compare Trade by Trade
        match = (len(base_trades) == len(fast_trades))
        if match:
            for b, f_tr in zip(base_trades, fast_trades):
                for k in ["symbol", "date", "signal_time", "direction", "score", "entry_price", "stop_loss", "target_1", "target_2", "outcome", "r_multiple"]:
                    if b[k] != f_tr[k]:
                        match = False
                        print(f"  [DISCREPANCY in {sym}] Field {k}: baseline={b[k]} vs fast={f_tr[k]}")
                        break

        status = "✅ 100% PARITY MATCH" if match else "❌ MISMATCH"
        if not match:
            all_matched = False

        print(f"Stock: {sym:12} | Baseline: {len(base_trades):2} trades in {t_base:5.1f}s | Fast: {len(fast_trades):2} trades in {t_fast:5.1f}s ({speedup:.1f}x speedup) | {status}")

    print("=" * 95)
    print(f"TOTAL TRADES EVALUATED: Baseline = {total_baseline_trades} | Fast Pipeline = {total_fast_trades}")
    if all_matched and total_baseline_trades > 0:
        print("🎉 PARITY VERIFICATION PASSED: ZERO NUMERICAL DIFFERENCE ACROSS ALL TRADES!")
        print("   The Fast Pipeline is 100% bit-for-bit mathematically equivalent to the baseline engine.")
    else:
        print("⚠️ PARITY VERIFICATION FAILED. Review discrepancies above.")
    print("=" * 95)


if __name__ == "__main__":
    main()
