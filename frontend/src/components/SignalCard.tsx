"use client";

import React from 'react';
import { 
  TrendingUp, 
  TrendingDown, 
  Zap, 
  Target, 
  ExternalLink,
  Flame,
  LineChart 
} from 'lucide-react';
import { StockSignal } from '@/types/screener';
import { formatINR, cn } from '@/lib/utils';

interface SignalCardProps {
  stock: StockSignal;
  onOpenChart: (stock: StockSignal) => void;
}

export const SignalCard: React.FC<SignalCardProps> = ({ stock, onOpenChart }) => {
  const isBullish = stock.signal_type === 'BULLISH';
  const isBearish = stock.signal_type === 'BEARISH';
  const isActive = stock.is_active_signal;
  const tp = stock.trade_params;
  const ind = stock.indicators;

  const isPositiveChange = stock.price_change_pct >= 0;

  return (
    <div 
      className={cn(
        "glass-panel rounded-xl p-4 transition-all duration-300 relative overflow-hidden flex flex-col justify-between group hover:border-white/20",
        isBullish && isActive && "border-emerald-500/40 glow-bullish-card bg-emerald-950/10",
        isBearish && isActive && "border-rose-500/40 glow-bearish-card bg-rose-950/10",
        !isActive && "border-white/5 hover:bg-dark-800/80"
      )}
    >
      <div>
        <div className="flex items-start justify-between gap-2 mb-2">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-bold text-lg text-white tracking-tight group-hover:text-indigo-400 transition-colors">
                {stock.symbol}
              </h3>
              <span className="px-2 py-0.5 text-[10px] font-medium bg-dark-750 text-slate-300 rounded border border-white/5">
                {stock.sector}
              </span>
            </div>
            <p className="text-xs text-slate-400 truncate max-w-[200px] mt-0.5">
              {stock.name}
            </p>
          </div>

          {isBullish && isActive && (
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-sm animate-pulse-subtle">
              <Zap className="w-3 h-3 text-emerald-400" />
              BULLISH BREAKOUT
            </span>
          )}

          {isBearish && isActive && (
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-bold bg-rose-500/20 text-rose-300 border border-rose-500/40 shadow-sm animate-pulse-subtle">
              <TrendingDown className="w-3 h-3 text-rose-400" />
              BEARISH BREAKDOWN
            </span>
          )}

          {!isActive && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium bg-dark-700 text-slate-400 border border-white/5">
              WATCHLIST
            </span>
          )}
        </div>

        <div className="flex items-baseline justify-between py-2 border-y border-white/5 my-2.5">
          <div>
            <div className="text-2xl font-black font-mono tracking-tight text-white">
              {formatINR(stock.ltp)}
            </div>
            <div className="text-[10px] text-slate-400">Last Traded Price</div>
          </div>

          <div className="text-right">
            <div 
              className={cn(
                "inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold font-mono",
                isPositiveChange ? "text-emerald-400 bg-emerald-500/10" : "text-rose-400 bg-rose-500/10"
              )}
            >
              {isPositiveChange ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
              <span>{isPositiveChange ? '+' : ''}{stock.price_change_pct}%</span>
            </div>
            <div className="text-[10px] text-slate-400 mt-0.5">Session Return</div>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-1.5 mb-3 text-center text-[11px]">
          <div 
            className={cn(
              "p-1.5 rounded-lg border flex flex-col items-center justify-center",
              stock.rel_vol >= 1.5 
                ? "bg-amber-500/10 border-amber-500/30 text-amber-300" 
                : "bg-dark-800 border-white/5 text-slate-400"
            )}
          >
            <div className="flex items-center gap-1 font-bold font-mono">
              {stock.rel_vol >= 1.5 && <Flame className="w-3 h-3 text-amber-400" />}
              {stock.rel_vol}x
            </div>
            <span className="text-[9px] text-slate-400 mt-0.5">RelVol (10d)</span>
          </div>

          <div className="p-1.5 rounded-lg bg-dark-800 border border-white/5 text-slate-300 flex flex-col items-center justify-center">
            <div className="font-bold font-mono text-indigo-300">
              ?{ind.ema20}
            </div>
            <span className="text-[9px] text-slate-400 mt-0.5">20 EMA (15m)</span>
          </div>

          <div 
            className={cn(
              "p-1.5 rounded-lg border flex flex-col items-center justify-center",
              ind.rsi14 >= 60 ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-300" :
              ind.rsi14 <= 40 ? "bg-rose-500/10 border-rose-500/20 text-rose-300" :
              "bg-dark-800 border-white/5 text-slate-400"
            )}
          >
            <div className="font-bold font-mono">
              {ind.rsi14}
            </div>
            <span className="text-[9px] text-slate-400 mt-0.5">RSI (14)</span>
          </div>
        </div>

        {tp && (
          <div className="bg-dark-850/80 rounded-xl p-3 border border-white/5 mb-3 space-y-2">
            <div className="flex items-center justify-between text-[11px] font-semibold text-slate-300 border-b border-white/5 pb-1.5">
              <span className="flex items-center gap-1">
                <Target className="w-3.5 h-3.5 text-indigo-400" />
                Trade Execution Plan
              </span>
              <span className="text-[10px] text-indigo-400 font-mono">
                Risk: ?{tp.risk_amount}/sh
              </span>
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs font-mono">
              <div className="bg-dark-750/70 p-2 rounded-lg border border-cyan-500/20">
                <span className="text-[10px] text-cyan-400 block font-sans">
                  {isBearish ? 'Breakdown Entry' : 'Breakout Entry'}
                </span>
                <span className="font-bold text-cyan-200">?{tp.entry_price}</span>
              </div>

              <div className="bg-dark-750/70 p-2 rounded-lg border border-rose-500/20">
                <span className="text-[10px] text-rose-400 block font-sans">Stop Loss (SL)</span>
                <span className="font-bold text-rose-200">?{tp.stop_loss}</span>
              </div>

              <div className="bg-dark-750/70 p-2 rounded-lg border border-emerald-500/20">
                <div className="flex items-center justify-between text-[10px] text-emerald-400 font-sans">
                  <span>Target 1</span>
                  <span className="text-[9px] bg-emerald-900/60 px-1 rounded text-emerald-200">1:1.5 RR</span>
                </div>
                <span className="font-bold text-emerald-200">?{tp.target_1}</span>
              </div>

              <div className="bg-dark-750/70 p-2 rounded-lg border border-emerald-500/30">
                <div className="flex items-center justify-between text-[10px] text-emerald-400 font-sans">
                  <span>Target 2</span>
                  <span className="text-[9px] bg-emerald-900/60 px-1 rounded text-emerald-200">1:2.0 RR</span>
                </div>
                <span className="font-bold text-emerald-200">?{tp.target_2}</span>
              </div>
            </div>

            <div className="pt-1">
              <div className="flex justify-between text-[10px] text-slate-400 mb-1">
                <span className="text-rose-400">Risk: 1.0</span>
                <span className="text-cyan-300">Entry</span>
                <span className="text-emerald-400">Reward: 2.0x</span>
              </div>
              <div className="w-full h-1.5 bg-dark-700 rounded-full flex overflow-hidden">
                <div className="w-1/3 bg-rose-500/80" title="Risk Segment" />
                <div className="w-2/3 bg-emerald-500/90" title="Reward Segment" />
              </div>
            </div>

          </div>
        )}

      </div>

      <div className="pt-2 border-t border-white/5 flex items-center justify-between gap-2">
        <span className="text-[10px] text-slate-400 truncate max-w-[140px]">
          {stock.signal_reason.length > 0 ? stock.signal_reason[0] : 'Scanning momentum'}
        </span>
        
        <button
          onClick={() => onOpenChart(stock)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600/80 hover:bg-indigo-600 text-white text-xs font-semibold shadow-sm transition-all group-hover:shadow-indigo-500/25"
        >
          <LineChart className="w-3.5 h-3.5" />
          <span>15m Chart</span>
          <ExternalLink className="w-3 h-3 text-indigo-200" />
        </button>
      </div>

    </div>
  );
};
