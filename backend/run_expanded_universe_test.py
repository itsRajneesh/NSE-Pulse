import os
import sys
import time
import json
import pandas as pd
from datetime import datetime

# Windows UTF-8 console output fix
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.append('.')
from app.config import UNIVERSE_1000CR_FILE, NIFTY_500_SYMBOLS, IST_TZ
from app.v13_scanner import scan_v13_universe
import yfinance as yf

def fetch_nifty_benchmark():
    try:
        df = yf.download("^NSEI", period="1mo", interval="15m", progress=False)
        if df is not None and not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            df.columns = [str(c).strip().title() for c in df.columns]
            return df
    except Exception:
        pass
    return None

def run_expanded_universe_test():
    print("=" * 85)
    print(">> NSE-PULSE V13: EXPANDED UNIVERSE (1,468 STOCKS >= 1,000 CR) VERIFICATION")
    print(f"Time (IST): {datetime.now(IST_TZ).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 85)
    
    if not os.path.exists(UNIVERSE_1000CR_FILE):
        print(f"Error: Universe file not found at {UNIVERSE_1000CR_FILE}")
        return
        
    with open(UNIVERSE_1000CR_FILE, "r", encoding="utf-8") as f:
        raw_stocks = json.load(f)
        
    stocks = []
    for s in raw_stocks:
        s["is_nifty500"] = s.get("symbol") in NIFTY_500_SYMBOLS
        stocks.append(s)
        
    print(f"Loaded {len(stocks)} stocks in Expanded Universe (>= 1,000 Cr Cap).")
    n500_count = sum(1 for s in stocks if s["is_nifty500"])
    exp_only_count = len(stocks) - n500_count
    print(f"  * Nifty 500 Constituents      : {n500_count}")
    print(f"  * Mid/Small-Cap Tier (>=1K Cr): {exp_only_count}")
    
    print("\nFetching NIFTY 50 benchmark context...")
    nifty_df = None
    try:
        nifty_df = fetch_nifty_benchmark()
        if nifty_df is not None and not nifty_df.empty:
            print(f"NIFTY 50 context active (Last close: {nifty_df['Close'].iloc[-1]:.2f})")
    except Exception as e:
        print(f"Note: Running without live Nifty context: {e}")
        
    print("\nScanning Expanded Universe with upgraded V13 Institutional Engine...")
    start_t = time.monotonic()
    result = scan_v13_universe(stocks, nifty_df=nifty_df)
    elapsed = time.monotonic() - start_t
    
    valid = result.get("valid", 0)
    returned = result.get("returned", 0)
    candidates = result.get("candidates", [])
    diagnostics = result.get("diagnostic_signals", [])
    
    def get_cand_attr(c, attr, default=None):
        return getattr(c, attr, default) if not isinstance(c, dict) else c.get(attr, default)
        
    bullish = [c for c in candidates if get_cand_attr(c, "signal_type") == "BULLISH"]
    bearish = [c for c in candidates if get_cand_attr(c, "signal_type") == "BEARISH"]
    
    high_conf = [c for c in candidates if get_cand_attr(c, "score", 0) >= 85.0]
    strong = [c for c in candidates if 80.0 <= get_cand_attr(c, "score", 0) < 85.0]
    watchlist = [c for c in candidates if 72.0 <= get_cand_attr(c, "score", 0) < 80.0]
    
    early_triggers = [c for c in candidates if get_cand_attr(c, "execution_status") == "EARLY_TRIGGER"]
    actionable = [c for c in candidates if get_cand_attr(c, "execution_status") == "ACTIONABLE_IN_PLAY"]
    target_hits = [c for c in candidates if get_cand_attr(c, "execution_status") == "TARGET_HIT" or get_cand_attr(c, "t1_progress_pct", 0) >= 100.0]
    
    print("\n" + "=" * 85)
    print(f"[+] TEST RESULTS (Completed in {elapsed:.2f} seconds)")
    print("=" * 85)
    print(f"Total Universe Requested: {len(stocks)} | Returned: {returned} | Valid: {valid}")
    print(f"Total Qualified Setups (Score >= 72): {len(candidates)}")
    print(f"  * Bullish Setups : {len(bullish)}")
    print(f"  * Bearish Setups : {len(bearish)}")
    print("-" * 85)
    print("QUALITY TIER BREAKDOWN:")
    print(f"  * HIGH CONFIDENCE (>=85.0) : {len(high_conf)}")
    print(f"  * STRONG SETUP (80.0-84.9)  : {len(strong)}")
    print(f"  * WATCHLIST (72.0-79.9)     : {len(watchlist)}")
    print("-" * 85)
    print("EXECUTION LIFECYCLE BREAKDOWN:")
    print(f"  * EARLY TRIGGER (0-25% Prog) : {len(early_triggers)}")
    print(f"  * ACTIONABLE (25-75% Prog)   : {len(actionable)}")
    print(f"  * TARGET 1 HIT (>=100% Prog) : {len(target_hits)}")
    print("=" * 85)
    
    if candidates:
        print("\nTOP QUALIFIED TRADES:")
        print(f"{'Symbol':<12} | {'Univ':<10} | {'Dir':<7} | {'Score':<5} | {'Status':<18} | {'Progress':<9} | {'LTP':<9} | {'Entry':<9} | {'T1':<9}")
        print("-" * 105)
        sorted_cands = sorted(candidates, key=lambda c: get_cand_attr(c, "score", 0), reverse=True)
        for c in sorted_cands[:35]:
            sym = get_cand_attr(c, "symbol")
            is_n5 = "NIFTY500" if sym in NIFTY_500_SYMBOLS else ">=1000CR"
            s_type = get_cand_attr(c, "signal_type")
            score = get_cand_attr(c, "score")
            status = get_cand_attr(c, "execution_status")
            prog = get_cand_attr(c, "t1_progress_pct", 0)
            ltp = get_cand_attr(c, "ltp")
            entry = get_cand_attr(c, "entry_price")
            t1 = get_cand_attr(c, "target_1")
            print(f"{sym:<12} | {is_n5:<10} | {s_type:<7} | {score:<5.1f} | {status:<18} | {prog:>7.1f}% | {ltp:<9.2f} | {entry:<9.2f} | {t1:<9.2f}")
    else:
        print("\nNo qualified setups >= 72 in current session.")
        
    print("\n" + "=" * 85)
    print("[SUCCESS] EXPANDED UNIVERSE TEST COMPLETE")
    print("=" * 85)

if __name__ == "__main__":
    run_expanded_universe_test()
