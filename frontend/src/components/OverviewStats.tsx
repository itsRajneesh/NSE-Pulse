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
import { V13ScanResponse, V13MarketPulseResponse } from '@/types/screener';
import { cn } from '@/lib/utils';

interface OverviewStatsProps {
  data: V13ScanResponse | null;
  marketPulse?: V13MarketPulseResponse | null;
  loading: boolean;
}

export const OverviewStats: React.FC<OverviewStatsProps> = ({ data, marketPulse, loading }) => {
  if (loading && !data) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-24 rounded-xl bg-dark-800/60 border border-white/5 animate-pulse" />
        ))}
      </div>
    );
  }

  const totalScanned = data?.universe.length ?? 1468;
  const bullishCount = data?.watchlist.filter((signal) => signal.score >= 72 && signal.direction === 'BULLISH').length ?? 0;
  const bearishCount = data?.watchlist.filter((signal) => signal.score >= 72 && signal.direction === 'BEARISH').length ?? 0;
  const activeSignals = data?.watchlist.filter((signal) => signal.score >= 72).length ?? 0;
  const diagnosticCount = data?.diagnostic_signals?.length ?? 0;
  const noSetupCount = Math.max(0, totalScanned - activeSignals - diagnosticCount);
  const rawSentiment = (data?.market_regime ?? 'NEUTRAL').toUpperCase();

  const trafficLight = marketPulse?.tradeability?.traffic_light;
  const pulseScore = marketPulse?.tradeability?.score;
  const vwapBreadthPct = marketPulse?.tradeability?.factors?.vwap_breadth?.vwap_breadth_pct;

  // Synchronized Market Sentiment & Tradeability Regime (Pillar 1B)
  let sentimentLabel = data?.market_regime ?? 'Unavailable';
  let sentimentColor = 'text-amber-400';
  let iconBoxColor = 'bg-amber-500/10 border-amber-500/20 text-amber-400';
  let subtextContent: React.ReactNode = 'Based on the latest verified NIFTY market context.';

  if (trafficLight === 'RED') {
    const regimePrefix = rawSentiment === 'BULLISH' ? 'CAUTION' : rawSentiment;
    sentimentLabel = `${regimePrefix} • SIT ON CASH`;
    sentimentColor = 'text-rose-400';
    iconBoxColor = 'bg-rose-500/10 border-rose-500/20 text-rose-400';
    subtextContent = (
      <span className="flex items-center justify-between gap-2">
        <span>Pulse: <strong className="text-rose-300 font-mono">{pulseScore}/100 (0.0x)</strong></span>
        {vwapBreadthPct !== undefined && (
          <span className="font-mono text-[11px] text-slate-400">VWAP Breadth: {vwapBreadthPct}%</span>
        )}
      </span>
    );
  } else if (trafficLight === 'YELLOW') {
    sentimentLabel = `${rawSentiment} • SELECTIVE`;
    sentimentColor = 'text-amber-400';
    iconBoxColor = 'bg-amber-500/10 border-amber-500/20 text-amber-400';
    subtextContent = (
      <span className="flex items-center justify-between gap-2">
        <span>Pulse: <strong className="text-amber-300 font-mono">{pulseScore}/100 (0.5x)</strong></span>
        {vwapBreadthPct !== undefined && (
          <span className="font-mono text-[11px] text-slate-400">VWAP Breadth: {vwapBreadthPct}%</span>
        )}
      </span>
    );
  } else if (trafficLight === 'GREEN') {
    sentimentLabel = `${rawSentiment === 'BEARISH' ? 'BEARISH' : 'BULLISH'} • GO`;
    sentimentColor = 'text-emerald-400';
    iconBoxColor = 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400';
    subtextContent = (
      <span className="flex items-center justify-between gap-2">
        <span>Pulse: <strong className="text-emerald-300 font-mono">{pulseScore}/100 (1.0x)</strong></span>
        {vwapBreadthPct !== undefined && (
          <span className="font-mono text-[11px] text-slate-400">VWAP Breadth: {vwapBreadthPct}%</span>
        )}
      </span>
    );
  } else {
    if (rawSentiment === 'BULLISH') {
      sentimentColor = 'text-emerald-400';
      iconBoxColor = 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400';
    } else if (rawSentiment === 'BEARISH') {
      sentimentColor = 'text-rose-400';
      iconBoxColor = 'bg-rose-500/10 border-rose-500/20 text-rose-400';
    }
  }

  const topRelVolStock = data?.universe
    ? data.universe
        .filter((stock) => stock.snapshot.rel_vol !== null)
        .sort(
          (a, b) =>
            (b.snapshot.rel_vol ?? -Infinity) -
            (a.snapshot.rel_vol ?? -Infinity)
        )[0] ?? null
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
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[11px]">
            <span className="px-1.5 py-0.5 rounded bg-indigo-500/15 text-indigo-300 font-medium" title="Active signals (Score >= 72)">
              Active: {activeSignals}
            </span>
            <span className="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 font-medium" title="Below threshold setups (Score < 72)">
              Below: {diagnosticCount}
            </span>
            <span className="px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-300 font-medium" title="Safety filtered: Penny stocks < ₹20, Circuit freeze, Exhaustion, or Low volume">
              No Setup: {noSetupCount}
            </span>
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
                <span className="text-xs text-slate-400">latest session</span>
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
              <h3 className={cn("text-lg font-bold mt-1 tracking-tight", sentimentColor)}>
                {sentimentLabel}
              </h3>
            </div>
            <div className={cn("w-11 h-11 rounded-lg border flex items-center justify-center", iconBoxColor)}>
              <Gauge className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3 text-xs text-slate-400">
            {subtextContent}
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
                    {topRelVolStock.snapshot.rel_vol}x Vol
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
            <span className="text-slate-400">
              {topRelVolStock ? 'V13 Relative Volume' : ''}
            </span>
          </div>
        </div>

      </div>
    </section>
  );
};
