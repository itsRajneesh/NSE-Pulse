"use client";

import React from 'react';
import { 
  TrendingUp, 
  TrendingDown, 
  Zap, 
  Gauge, 
  BarChart3, 
  Flame 
} from 'lucide-react';
import { ScreenerResponse } from '@/types/screener';

interface OverviewStatsProps {
  data: ScreenerResponse | null;
  loading: boolean;
}

export const OverviewStats: React.FC<OverviewStatsProps> = ({ data, loading }) => {
  if (loading && !data) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-24 rounded-xl bg-dark-800/60 border border-white/5 animate-pulse" />
        ))}
      </div>
    );
  }

  const totalScanned = data?.total_scanned ?? 500;
  const activeSignals = data?.active_signals_count ?? 0;
  const bullishCount = data?.bullish_count ?? 0;
  const bearishCount = data?.bearish_count ?? 0;
  const bullishRatio = data?.bullish_ratio ?? 50;
  const sentiment = data?.market_sentiment ?? 'Neutral';

  const topRelVolStock = data?.stocks
    ? [...data.stocks].sort((a, b) => b.rel_vol - a.rel_vol)[0]
    : null;

  return (
    <section className="mb-6 space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        
        <div className="glass-panel p-4 rounded-xl relative overflow-hidden group hover:border-white/20 transition-all">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                Universe Monitored
              </p>
              <h3 className="text-2xl font-bold text-white mt-1">
                {totalScanned} <span className="text-xs font-normal text-slate-400">Stocks</span>
              </h3>
            </div>
            <div className="w-11 h-11 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
              <BarChart3 className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3 flex items-center gap-2 text-xs text-slate-400">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
            <span>Nifty 500 Index Constituents</span>
          </div>
        </div>

        <div className="glass-panel p-4 rounded-xl relative overflow-hidden group hover:border-white/20 transition-all">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                Active Breakout Signals
              </p>
              <div className="flex items-baseline gap-2 mt-1">
                <h3 className="text-2xl font-bold text-white">{activeSignals}</h3>
                <span className="text-xs text-slate-400">triggered now</span>
              </div>
            </div>
            <div className="w-11 h-11 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
              <Zap className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3 flex items-center gap-3 text-xs">
            <span className="inline-flex items-center gap-1 text-emerald-400 font-medium">
              <TrendingUp className="w-3 h-3" /> {bullishCount} Bullish
            </span>
            <span className="inline-flex items-center gap-1 text-rose-400 font-medium">
              <TrendingDown className="w-3 h-3" /> {bearishCount} Bearish
            </span>
          </div>
        </div>

        <div className="glass-panel p-4 rounded-xl relative overflow-hidden group hover:border-white/20 transition-all">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                Market Sentiment
              </p>
              <h3 className={`text-lg font-bold mt-1 ${
                bullishRatio >= 60 ? 'text-emerald-400' : bullishRatio <= 40 ? 'text-rose-400' : 'text-amber-400'
              }`}>
                {sentiment}
              </h3>
            </div>
            <div className="w-11 h-11 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
              <Gauge className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3 space-y-1.5">
            <div className="flex justify-between text-[11px] font-mono text-slate-400">
              <span className="text-emerald-400">{bullishRatio}% Bull</span>
              <span className="text-rose-400">{Math.round(100 - bullishRatio)}% Bear</span>
            </div>
            <div className="w-full h-2 bg-dark-750 rounded-full overflow-hidden flex border border-white/5">
              <div 
                className="bg-gradient-to-r from-emerald-600 to-emerald-400 h-full transition-all duration-500" 
                style={{ width: `${bullishRatio}%` }}
              />
              <div 
                className="bg-gradient-to-r from-rose-400 to-rose-600 h-full transition-all duration-500" 
                style={{ width: `${100 - bullishRatio}%` }}
              />
            </div>
          </div>
        </div>

        <div className="glass-panel p-4 rounded-xl relative overflow-hidden group hover:border-white/20 transition-all">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                Top Volume Surge
              </p>
              {topRelVolStock ? (
                <div className="flex items-baseline gap-2 mt-1">
                  <h3 className="text-xl font-bold text-white">{topRelVolStock.symbol}</h3>
                  <span className="text-xs font-mono font-bold text-amber-400">
                    {topRelVolStock.rel_vol}x Vol
                  </span>
                </div>
              ) : (
                <h3 className="text-xl font-bold text-white mt-1">Scanning...</h3>
              )}
            </div>
            <div className="w-11 h-11 rounded-lg bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400">
              <Flame className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3 flex items-center justify-between text-xs text-slate-400">
            <span>{topRelVolStock?.sector || 'NSE Sector'}</span>
            <span className={topRelVolStock && topRelVolStock.price_change_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
              {topRelVolStock ? `${topRelVolStock.price_change_pct >= 0 ? '+' : ''}${topRelVolStock.price_change_pct}%` : ''}
            </span>
          </div>
        </div>

      </div>
    </section>
  );
};
