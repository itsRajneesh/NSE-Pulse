import json
import pandas as pd
import yfinance as yf
from datetime import datetime
import sys
sys.path.append('.')
from app.v13_engine import discover_v13_setups

def main():
    with open('scan_latest.json', 'r') as f:
        data = json.load(f)
    
    watchlist = data.get('watchlist', [])
    diagnostic = data.get('diagnostic_signals', [])
    
    print(f"Watchlist count: {len(watchlist)}")
    print(f"Diagnostic count: {len(diagnostic)}")
    
    # Filter for stocks with t1_progress_pct >= 80.0 or target hit
    wl_hitters = [s for s in watchlist if s.get('t1_progress_pct', 0) >= 80.0]
    diag_hitters = [s for s in diagnostic if s.get('t1_progress_pct', 0) >= 80.0]
    
    print(f"\nWatchlist stocks with >=80% T1: {len(wl_hitters)}")
    for s in wl_hitters:
        print(f"  {s['symbol']:<12} | {s['signal_type']:<7} | Score: {s['score']:<4} | Prog: {s['t1_progress_pct']:>6.1f}% | LTP: {s['ltp']} | Entry: {s['entry_price']} | T1: {s['target_1']}")
        
    print(f"\nDiagnostic stocks with >=80% T1 (TRAPPED < 72): {len(diag_hitters)}")
    for s in diag_hitters[:20]: # show top 20
        print(f"  {s['symbol']:<12} | {s['signal_type']:<7} | Score: {s['score']:<4} | Prog: {s['t1_progress_pct']:>6.1f}% | LTP: {s['ltp']} | Entry: {s['entry_price']} | T1: {s['target_1']}")

if __name__ == '__main__':
    main()
