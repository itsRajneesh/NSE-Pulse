"""
BUILD UNIVERSE 1000CR (RETRY & RATE-LIMIT RECOVERY VERSION)
===========================================================
Fetches all listed active NSE Equity stocks and filters strictly for
Market Cap >= ₹1,000 Crore with robust rate-limit recovery.

Key Fixes in this version:
1. Resilient Retry: Does NOT accept `mcap is None` as delisted on the first try.
   Retries up to 4 times with exponential backoff if crumb/session is temporarily frozen.
2. Smart Cache Recovery: Automatically picks up from the existing cache!
   Keeps the 1,032 already-verified stocks (860 qualified + 172 sub-1000) and ONLY
   re-queries the 1,524 stocks that were temporarily rate-limited.
3. Anti-Spam Throttling: Uses 5 workers with jitter delay (0.12s - 0.25s) to stay
   strictly under Yahoo Finance's rolling rate-limit window.
4. Dummy Symbol Filter: Automatically excludes exchange mock-trading symbols (e.g. DUMMYTRVN).
5. Real-Time `tqdm` Progress Bar: Shows % completion, qualified count, and dynamic ETA.

Usage:
    python build_universe_1000cr.py              # Resumes and fixes None stocks automatically
    python build_universe_1000cr.py --workers 4  # Extra conservative pacing
    python build_universe_1000cr.py --reset-cache # Start completely from scratch
"""

from __future__ import annotations

import argparse
import io
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd
import requests
import yfinance as yf

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, *args, **kwargs):
        total = kwargs.get("total", len(iterable) if hasattr(iterable, "__len__") else 0)
        desc = kwargs.get("desc", "Processing")
        for idx, item in enumerate(iterable, 1):
            if idx % 20 == 0 or idx == total:
                pct = (idx / total * 100) if total else 0
                print(f"[{desc}] {idx}/{total} ({pct:.1f}%)")
            yield item


# Directory & File Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "app" / "data"
OUTPUT_JSON = DATA_DIR / "universe_1000cr.json"
OUTPUT_CSV = DATA_DIR / "universe_1000cr.csv"
CACHE_JSON = DATA_DIR / "universe_mcap_cache.json"
LOCAL_EQUITY_L = BASE_DIR / "EQUITY_L.csv"

NSE_EQUITY_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_EQUITY_ALT_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_TOTAL_MARKET_URL = "https://archives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


# -----------------------------------------------------------------------------
# Cache Management (Resumes seamlessly & recovers None values)
# -----------------------------------------------------------------------------
def load_cache() -> Dict[str, Dict[str, Any]]:
    """Loads existing cached symbol results."""
    if CACHE_JSON.exists():
        try:
            with open(CACHE_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def save_cache(cache: Dict[str, Dict[str, Any]]) -> None:
    """Persists current cache to disk atomically."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = CACHE_JSON.with_suffix(".tmp")
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
        temp_file.replace(CACHE_JSON)
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Stock Discovery & Sourcing
# -----------------------------------------------------------------------------
def load_all_nse_equities() -> List[Dict[str, str]]:
    """Collects complete NSE universe."""
    print("=" * 85)
    print("STEP 1: Sourcing NSE Active Listed Equities...")
    print("=" * 85)

    stocks_dict: Dict[str, Dict[str, str]] = {}

    # 1. Baseline Nifty 500
    nifty500_file = DATA_DIR / "nifty500.json"
    if nifty500_file.exists():
        try:
            with open(nifty500_file, "r", encoding="utf-8") as f:
                n500 = json.load(f)
                for item in n500:
                    sym = str(item["symbol"]).strip().upper()
                    stocks_dict[sym] = {
                        "symbol": sym,
                        "name": item.get("name", sym),
                        "sector": item.get("sector", "Diversified"),
                    }
            print(f"✓ Loaded {len(stocks_dict)} seed stocks from Nifty 500 baseline.")
        except Exception:
            pass

    # 2. Nifty Total Market 750 (Top 750 Indian Equities)
    try:
        r = requests.get(NSE_TOTAL_MARKET_URL, headers=HEADERS, timeout=10)
        if r.status_code == 200 and "Symbol" in r.text:
            df_tm = pd.read_csv(io.StringIO(r.text))
            df_tm.columns = df_tm.columns.str.strip()
            for _, row in df_tm.iterrows():
                sym = str(row.get("Symbol", "")).strip().upper()
                if sym and sym not in stocks_dict:
                    stocks_dict[sym] = {
                        "symbol": sym,
                        "name": str(row.get("Company Name", sym)).strip(),
                        "sector": str(row.get("Industry", "Diversified")).strip(),
                    }
            print(f"✓ Total Market 750 processed: Total unique stocks now = {len(stocks_dict)}.")
    except Exception as e:
        print(f"Notice: Nifty Total Market list fetch skipped ({e}). Continuing...")

    # 3. Official NSE EQUITY_L.csv
    equity_df = None
    if LOCAL_EQUITY_L.exists():
        try:
            equity_df = pd.read_csv(LOCAL_EQUITY_L)
            print(f"✓ Found local EQUITY_L.csv ({len(equity_df)} rows).")
        except Exception:
            pass

    if equity_df is None:
        for url in [NSE_EQUITY_URL, NSE_EQUITY_ALT_URL]:
            try:
                print(f"Downloading active equity list from {url}...")
                session = requests.Session()
                try:
                    session.get("https://www.nseindia.com", headers=HEADERS, timeout=8)
                except Exception:
                    pass
                resp = session.get(url, headers=HEADERS, timeout=12)
                if resp.status_code == 200 and "SYMBOL" in resp.text:
                    equity_df = pd.read_csv(io.StringIO(resp.text))
                    equity_df.to_csv(LOCAL_EQUITY_L, index=False)
                    print(f"✓ Downloaded {len(equity_df)} stocks from NSE. Saved to {LOCAL_EQUITY_L}.")
                    break
            except Exception:
                continue

    if equity_df is not None:
        equity_df.columns = equity_df.columns.str.strip()
        series_col = "SERIES" if "SERIES" in equity_df.columns else None
        sym_col = "SYMBOL" if "SYMBOL" in equity_df.columns else equity_df.columns[0]
        name_col = "NAME OF COMPANY" if "NAME OF COMPANY" in equity_df.columns else sym_col

        for _, row in equity_df.iterrows():
            ser = str(row.get(series_col, "EQ")).strip().upper() if series_col else "EQ"
            sym = str(row.get(sym_col, "")).strip().upper()

            # Exclude exchange dummy symbols & non-equity series
            if ser in ("EQ", "BE") and sym and not sym.startswith("DUMMY") and not sym.endswith(("-RR", "-IV", "-RE", "-E1")):
                if sym not in stocks_dict:
                    stocks_dict[sym] = {
                        "symbol": sym,
                        "name": str(row.get(name_col, sym)).strip(),
                        "sector": "Diversified",
                    }

    stock_list = list(stocks_dict.values())
    print(f"✓ Sourcing complete: Total {len(stock_list)} distinct NSE equities identified.")
    return stock_list


# -----------------------------------------------------------------------------
# Resilient Market Cap Query with Retry & Anti-Freeze Backoff
# -----------------------------------------------------------------------------
def fetch_market_cap_with_retry(
    stock_item: Dict[str, str],
    max_retries: int = 4
) -> Tuple[str, Optional[float], Optional[float], str]:
    """
    Queries Yahoo Finance for market cap.
    CRITICAL FIX: If market_cap returns None, it does NOT give up!
    It waits with backoff and retries to recover from temporary crumb/session freezes.
    """
    symbol = stock_item["symbol"]
    name = stock_item["name"]
    sector = stock_item.get("sector", "Diversified")

    # Sanity check: Exclude mock trading symbols
    if symbol.startswith("DUMMY"):
        return symbol, None, None, sector

    ticker_str = f"{symbol}.NS"

    for attempt in range(max_retries):
        try:
            # Jitter delay: 0.12s to 0.25s per call prevents Yahoo bot triggers
            time.sleep(random.uniform(0.12, 0.25))

            t = yf.Ticker(ticker_str)
            mcap = None
            last_price = None

            # Primary: fast_info (much faster)
            try:
                fi = t.fast_info
                mcap = getattr(fi, "market_cap", None)
                last_price = getattr(fi, "last_price", None)
            except Exception:
                pass

            # Secondary fallback: standard info if fast_info is blank
            if not mcap or mcap <= 0:
                try:
                    info = t.info or {}
                    mcap = info.get("marketCap")
                    last_price = last_price or info.get("currentPrice") or info.get("regularMarketPrice")
                    if info.get("sector"):
                        sector = info["sector"]
                except Exception:
                    pass

            # If Market Cap found successfully, return immediately!
            if mcap and mcap > 0:
                mcap_cr = round(float(mcap) / 1e7, 2)
                l_price = round(float(last_price), 2) if last_price and last_price > 0 else 500.0
                return symbol, mcap_cr, l_price, sector

            # If mcap is None, Yahoo might have had a temporary crumb freeze.
            # Do NOT accept None on early attempts! Wait and retry.
            if attempt < max_retries - 1:
                sleep_secs = (2.5 * (attempt + 1)) + random.uniform(0.5, 1.5)
                time.sleep(sleep_secs)

        except Exception as exc:
            err_msg = str(exc).lower()
            if attempt < max_retries - 1:
                # Exponential backoff: 3s -> 6s -> 10s
                sleep_secs = (3.0 * (attempt + 1)) + random.uniform(0.5, 2.0)
                time.sleep(sleep_secs)

    # If all 4 retries genuinely return None, stock is truly untracked/delisted
    return symbol, None, None, sector


# -----------------------------------------------------------------------------
# Main Builder Pipeline
# -----------------------------------------------------------------------------
def build_universe(
    min_mcap_cr: float = 1000.0,
    max_workers: int = 5,
    reset_cache: bool = False
) -> List[Dict[str, Any]]:
    """
    Builds the complete universe with Market Cap >= min_mcap_cr.
    Smart recovery: Re-evaluates only None values from previous runs.
    """
    stocks = load_all_nse_equities()

    if reset_cache and CACHE_JSON.exists():
        try:
            CACHE_JSON.unlink()
            print("Notice: Cache reset requested. Starting fresh.")
        except Exception:
            pass

    cache = load_cache()

    # SMART RECOVERY: Keep already verified stocks (numeric market cap >= 0)
    # Only re-query stocks that are missing or have market_cap_cr == None!
    verified_count = sum(1 for v in cache.values() if v.get("market_cap_cr") is not None)
    qualified_initial = sum(1 for v in cache.values() if v.get("market_cap_cr") and v["market_cap_cr"] >= min_mcap_cr)

    to_query = [
        s for s in stocks
        if s["symbol"] not in cache or cache[s["symbol"]].get("market_cap_cr") is None
    ]

    print()
    print("=" * 85)
    print(f"STEP 2: Evaluating Market Caps (Target >= ₹{min_mcap_cr:,.0f} Cr)...")
    print(f"Total Universe Identified : {len(stocks)}")
    print(f"Already Verified In Cache : {verified_count} stocks ({qualified_initial} >= ₹{min_mcap_cr:,.0f} Cr)")
    print(f"To Scan / Recover         : {len(to_query)} stocks")
    print(f"Pacing & Concurrency      : {max_workers} worker threads (Anti-Rate-Limiting Throttled)")
    print("=" * 85)

    if to_query:
        save_counter = 0
        with tqdm(
            total=len(stocks),
            initial=verified_count,
            desc="Scanning Equities",
            unit="stock",
            dynamic_ncols=True
        ) as pbar:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_stock = {
                    executor.submit(fetch_market_cap_with_retry, item): item
                    for item in to_query
                }

                for future in as_completed(future_to_stock):
                    item = future_to_stock[future]
                    sym = item["symbol"]
                    try:
                        sym_ret, mcap_cr, last_price, sector = future.result()
                        cache[sym] = {
                            "symbol": sym,
                            "name": item["name"],
                            "sector": sector or item.get("sector", "Diversified"),
                            "market_cap_cr": mcap_cr,
                            "base_price": last_price or 500.0,
                        }
                    except Exception:
                        cache[sym] = {
                            "symbol": sym,
                            "name": item["name"],
                            "sector": item.get("sector", "Diversified"),
                            "market_cap_cr": None,
                            "base_price": 500.0,
                        }
                    finally:
                        pbar.update(1)
                        save_counter += 1
                        # Save checkpoint every 25 stocks
                        if save_counter % 25 == 0:
                            save_cache(cache)
                            current_qualified = sum(
                                1 for v in cache.values()
                                if v.get("market_cap_cr") and v["market_cap_cr"] >= min_mcap_cr
                            )
                            pbar.set_postfix({"Qualified": current_qualified})

        # Final cache save
        save_cache(cache)

    # Filter all qualified stocks (Market Cap >= min_mcap_cr)
    qualified_stocks: List[Dict[str, Any]] = []
    for sym, data in cache.items():
        mcap = data.get("market_cap_cr")
        if mcap and mcap >= min_mcap_cr:
            qualified_stocks.append({
                "symbol": sym,
                "yf_ticker": f"{sym}.NS",
                "name": data.get("name", sym),
                "sector": data.get("sector", "Diversified"),
                "base_price": data.get("base_price", 500.0),
                "market_cap_cr": mcap,
            })

    # Sort descending by Market Cap
    qualified_stocks.sort(key=lambda x: x["market_cap_cr"], reverse=True)

    print()
    print("=" * 85)
    print(f"STEP 3: Saving Universe ({len(qualified_stocks)} Stocks Qualified >= ₹{min_mcap_cr:,.0f} Cr)...")
    print("=" * 85)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Output JSON (Engine Format)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(qualified_stocks, f, indent=2)
    print(f"✓ Saved Engine JSON: {OUTPUT_JSON}")

    # 2. Output CSV (Spreadsheet Format)
    df_out = pd.DataFrame(qualified_stocks)
    df_out.to_csv(OUTPUT_CSV, index=False)
    print(f"✓ Saved Readable CSV: {OUTPUT_CSV}")

    # Display Top 15 Summary
    print()
    print("TOP 15 LARGEST CONSTITUENTS IN EXPANDED UNIVERSE:")
    print("-" * 80)
    print(f"{'Rank':<5} {'Symbol':<14} {'Market Cap (₹ Cr)':<22} {'Sector':<20} {'Company Name'}")
    print("-" * 80)
    for idx, s in enumerate(qualified_stocks[:15], 1):
        print(f"{idx:<5} {s['symbol']:<14} ₹{s['market_cap_cr']:>16,.1f} Cr   {s['sector'][:18]:<20} {s['name'][:25]}")
    print("-" * 80)
    print(f"Total Qualified Universe: {len(qualified_stocks)} stocks (Baseline Nifty 500 was 500 stocks).")
    print("=" * 85)

    return qualified_stocks


def main():
    parser = argparse.ArgumentParser(description="Build NSE Stock Universe with Market Cap >= ₹1,000 Cr")
    parser.add_argument("--min-mcap", type=float, default=1000.0, help="Minimum Market Cap in Crores (Default: 1000.0)")
    parser.add_argument("--workers", type=int, default=5, help="Concurrent workers with rate-limiting guard (Default: 5)")
    parser.add_argument("--reset-cache", action="store_true", help="Clear previous progress cache and start fresh")
    args = parser.parse_args()

    build_universe(min_mcap_cr=args.min_mcap, max_workers=args.workers, reset_cache=args.reset_cache)


if __name__ == "__main__":
    main()
