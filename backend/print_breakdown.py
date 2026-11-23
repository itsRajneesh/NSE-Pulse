import json

with open('simulation_results.json') as f:
    data = json.load(f)

print(f"{'Symbol':<10} | {'Qual Time':<9} | {'Score':<5} | {'Trend':<5} | {'EMA':<4} | {'VWAP':<4} | {'RSI':<4} | {'Vol':<4} | {'OR':<4} | {'PDL':<4} | {'Cndl':<4} | {'Vel':<4} | {'Penalties'}")
print("-" * 115)

for r in data:
    sym = r['symbol']
    qual_bar = None
    for b in r['bars']:
        if b['score'] >= 72.0:
            qual_bar = b
            break
    if qual_bar:
        bd = qual_bar.get('breakdown', {})
        pens = ", ".join(qual_bar.get('penalties', []))
        if not pens:
            pens = "None"
        print(f"{sym:<10} | {qual_bar['time']:<9} | {qual_bar['score']:<5.1f} | {bd.get('trend_structure', 0):<5.1f} | {bd.get('ema_alignment', 0):<4.1f} | {bd.get('vwap_alignment', 0):<4.1f} | {bd.get('rsi_momentum', 0):<4.1f} | {bd.get('volume', 0):<4.1f} | {bd.get('opening_range', 0):<4.1f} | {bd.get('previous_day_level', 0):<4.1f} | {bd.get('candle_quality', 0):<4.1f} | {bd.get('true_velocity', 0):<4.1f} | {pens}")
    else:
        # Check highest score bar
        best_bar = max(r['bars'], key=lambda x: x['score']) if r['bars'] else None
        if best_bar:
            bd = best_bar.get('breakdown', {})
            pens = ", ".join(best_bar.get('penalties', []))
            print(f"{sym:<10} | Max {best_bar['time']:<5} | {best_bar['score']:<5.1f} | {bd.get('trend_structure', 0):<5.1f} | {bd.get('ema_alignment', 0):<4.1f} | {bd.get('vwap_alignment', 0):<4.1f} | {bd.get('rsi_momentum', 0):<4.1f} | {bd.get('volume', 0):<4.1f} | {bd.get('opening_range', 0):<4.1f} | {bd.get('previous_day_level', 0):<4.1f} | {bd.get('candle_quality', 0):<4.1f} | {bd.get('true_velocity', 0):<4.1f} | {pens} (NEVER QUALIFIED)")
