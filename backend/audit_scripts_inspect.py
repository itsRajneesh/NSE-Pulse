# audit script
import os
import sys
import json
import urllib.request

def run():
    url = "http://127.0.0.1:8055/api/v13/scan"
    data = json.loads(urllib.request.urlopen(url).read())
    wl = data.get("watchlist", [])
    print(f"Total Watchlist Items: {len(wl)}")
    print("-" * 90)
    print(f"{'Symbol':<12} | {'Type':<7} | {'Score':<5} | {'Progress':<9} | {'Status':<18} | {'LTP':<9} | {'Entry':<9} | {'T1':<9}")
    print("-" * 90)
    
    t1_hitters = []
    for s in wl:
        prog = s.get("t1_progress_pct", 0)
        status = s.get("execution_status", "")
        ltp = s.get("ltp", 0)
        entry = s.get("entry_price", 0)
        t1 = s.get("target_1", 0)
        score = s.get("score", 0)
        sig = s.get("signal_type", "")
        sym = s.get("symbol", "")
        if prog >= 80.0:
            t1_hitters.append(s)
            print(f"{sym:<12} | {sig:<7} | {score:<5} | {prog:>7.1f}% | {status:<18} | {ltp:<9.2f} | {entry:<9.2f} | {t1:<9.2f}")

    print(f"\nTotal Watchlist stocks with >=80% T1 Progress: {len(t1_hitters)}")
    return [s["symbol"] for s in t1_hitters]

if __name__ == "__main__":
    run()
