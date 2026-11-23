import os
import sys
import json
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

sys.path.append('.')
from app.v13_engine import (
    discover_v13_setups,
    evaluate_v13_diagnostic
)

# Test list of stocks that hit T1/T2 today
SYMBOLS = [
    ("KPIGREEN", "BULLISH"),
    ("GOKEX", "BEARISH"),
    ("OFSS", "BEARISH"),
    ("ICICIGI", "BULLISH"),
    ("GKENERGY", "BULLISH"),
    ("ISGEC", "BULLISH"),
    ("JAYKAY", "BULLISH"),
    ("RATNAVEER", "BULLISH"),
    ("SAATVIKGL", "BULLISH"),
    ("FREDUN", "BULLISH"),
    ("MATRIMONY", "BULLISH"),
    ("BHAGYANGR", "BEARISH"),
    ("FAZE3Q", "BEARISH"),
    ("TEGA", "BULLISH"),
    ("CENTUM", "BULLISH"),
    ("SUPRIYA", "BULLISH"),
    ("JUBLCPL", "BULLISH"),
    ("KROSS", "BULLISH"),
    ("EMUDHRA", "BULLISH"),
    ("CHOICEIN", "BULLISH")
]

def main():
    ticker_list = [f"{s}.NS" for s, _ in SYMBOLS]
    print(f"Batch downloading 15m data for {len(ticker_list)} tickers...")
    try:
        data = yf.download(
            tickers=ticker_list,
            period="5d",
            interval="15m",
            group_by="ticker",
            threads=False,
            progress=False
        )
    except Exception as e:
        print(f"Batch download failed: {e}")
        return

    results = []
    
    for sym, expected_dir in SYMBOLS:
        tick = f"{sym}.NS"
        if tick not in data.columns.levels[0]:
            print(f"Skipping {sym}: not in downloaded data")
            continue
            
        df = data[tick].dropna(how="all").copy()
        df = df.dropna(subset=["Close", "High", "Low", "Open"])
        if df.empty or len(df) < 5:
            print(f"Skipping {sym}: empty or too few bars")
            continue
            
        df.columns = [c.lower() for c in df.columns]
        df.index = pd.to_datetime(df.index)
        today_date = df.index[-1].date()
        today_df = df[df.index.date == today_date]
        
        if len(today_df) < 2:
            print(f"Skipping {sym}: not enough today bars ({len(today_df)})")
            continue
            
        prior_bars_count = len(df[df.index.date < today_date])
        bar_results = []
        total_today_bars = len(today_df)
        
        for b_idx in range(1, total_today_bars + 1):
            sub_df = df.iloc[: prior_bars_count + b_idx]
            eval_time = sub_df.index[-1]
            
            # Discover
            setups = discover_v13_setups(symbol=sym, name=sym, sector="General", df=sub_df)
            cand = setups.get(expected_dir.lower())
            
            if not cand:
                diag = evaluate_v13_diagnostic(symbol=sym, name=sym, sector="General", df=sub_df)
                if isinstance(diag, list) and len(diag) > 0:
                    cand = diag[0]
                elif not isinstance(diag, list):
                    cand = diag
                    
            if cand:
                bar_results.append({
                    "bar_num": b_idx,
                    "time": str(eval_time.strftime("%H:%M")),
                    "score": cand.score,
                    "action": cand.action,
                    "status": cand.execution_status,
                    "ltp": cand.ltp,
                    "entry": cand.entry_price,
                    "t1": cand.target_1,
                    "t1_prog": cand.t1_progress_pct,
                    "penalties": cand.penalties,
                    "reasons": cand.reasons,
                    "breakdown": cand.score_breakdown
                })
            else:
                bar_results.append({
                    "bar_num": b_idx,
                    "time": str(eval_time.strftime("%H:%M")),
                    "score": 0,
                    "action": "NONE",
                    "status": "NONE",
                    "ltp": sub_df['close'].iloc[-1],
                    "entry": 0,
                    "t1": 0,
                    "t1_prog": 0,
                    "penalties": [],
                    "reasons": [],
                    "breakdown": {}
                })
                
        results.append({
            "symbol": sym,
            "direction": expected_dir,
            "bars": bar_results
        })

    with open('simulation_results.json', 'w') as f:
        json.dump(results, f, indent=2)
        
    print("\nSimulation complete. Summary Results:\n")
    print(f"{'Symbol':<10} | {'Dir':<7} | {'Brk Bar':<7} | {'Brk Scr':<7} | {'Brk Act':<10} | {'Qual Bar':<8} | {'Qual Scr':<8} | {'Prog@Qual':<10} | {'Max Prog':<8} | {'Primary Bottleneck'}")
    print("-" * 135)
    
    for r in results:
        sym = r["symbol"]
        dir_str = r["direction"]
        bars = r["bars"]
        
        breakout_bar = None
        qual_bar = None
        max_prog = max([b["t1_prog"] for b in bars]) if bars else 0
        
        for b in bars:
            if b["entry"] > 0 and b["t1_prog"] > 0 and breakout_bar is None:
                breakout_bar = b
            if b["score"] >= 72.0 and qual_bar is None:
                qual_bar = b
                
        brk_time = breakout_bar["time"] if breakout_bar else "N/A"
        brk_score = breakout_bar["score"] if breakout_bar else 0
        brk_act = breakout_bar["action"] if breakout_bar else "N/A"
        
        qual_time = qual_bar["time"] if qual_bar else "Never"
        qual_score = qual_bar["score"] if qual_bar else 0
        qual_prog = f"{qual_bar['t1_prog']:.1f}%" if qual_bar else "N/A"
        
        bottleneck = ""
        if breakout_bar:
            if brk_score < 72.0:
                missing = []
                bd = breakout_bar.get("breakdown", {})
                if bd.get("trend_structure", 0) == 0:
                    missing.append("TrendStruct=0")
                if "Opening range unusually wide" in str(breakout_bar.get("penalties", [])):
                    missing.append("WideOR(-2)")
                if "Breakout distance > 3 ATR" in str(breakout_bar.get("penalties", [])):
                    missing.append("ExtChs(-4)")
                if bd.get("candle_quality", 0) < 5:
                    missing.append("CndlQ<5")
                bottleneck = "68-71 Trap (" + ",".join(missing) + ")"
            elif qual_bar and qual_bar["t1_prog"] >= 80.0:
                bottleneck = "Single-Bar Velocity (Hit T1 in Brk Bar)"
            else:
                bottleneck = "Timely Watchlist Entry"
        else:
            bottleneck = "No Breakout"
            
        print(f"{sym:<10} | {dir_str:<7} | {brk_time:<7} | {brk_score:<7.1f} | {brk_act:<10} | {qual_time:<8} | {qual_score:<8.1f} | {qual_prog:<10} | {max_prog:>7.1f}% | {bottleneck}")

if __name__ == '__main__':
    main()
