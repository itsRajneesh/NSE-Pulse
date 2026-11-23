"use client";

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { 
  Activity, 
  ShieldAlert, 
  CheckCircle2, 
  AlertTriangle, 
  XCircle, 
  TrendingUp, 
  TrendingDown, 
  Compass, 
  RefreshCw, 
  BarChart2, 
  Gauge, 
  Zap, 
  Flame, 
  Globe, 
  ArrowUpRight, 
  ArrowDownRight, 
  Minus,
  Lock,
  Layers,
  Info
} from 'lucide-react';
import { V13MarketPulseResponse } from '@/types/screener';
import { cn } from '@/lib/utils';
import { MarketPulseTooltip } from './MarketPulseTooltip';

interface MarketPulsePanelProps {
  onOpenChart?: (stock: any) => void;
  initialData?: V13MarketPulseResponse | null;
  onDataUpdate?: (data: V13MarketPulseResponse) => void;
}

export function MarketPulsePanel({ onOpenChart, initialData, onDataUpdate }: MarketPulsePanelProps) {
  const [data, setData] = useState<V13MarketPulseResponse | null>(initialData || null);
  const [loading, setLoading] = useState<boolean>(!initialData);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [refreshCooldown, setRefreshCooldown] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialData) {
      setData(initialData);
      setLoading(false);
    }
  }, [initialData]);

  // Fetch Market Pulse Data
  const fetchMarketPulse = useCallback(async (force: boolean = false) => {
    if (force) {
      setIsRefreshing(true);
      setRefreshCooldown(15);
    }
    try {
      const res = await fetch(`/api/v13/market-pulse${force ? '?force=true' : ''}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: V13MarketPulseResponse = await res.json();
      setData(json);
      onDataUpdate?.(json);
      setError(null);
    } catch (err: any) {
      console.error("Failed to load Market Pulse data:", err);
      setError(err?.message || "Failed to load market pulse data");
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  }, [onDataUpdate]);

  // Initial load & 90s auto-refresh
  useEffect(() => {
    if (!initialData) {
      fetchMarketPulse(false);
    }
    const interval = setInterval(() => {
      // Pause polling if tab is backgrounded
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
      fetchMarketPulse(false);
    }, 90000);
    return () => clearInterval(interval);
  }, [fetchMarketPulse, initialData]);

  // Cooldown countdown timer for force refresh
  useEffect(() => {
    if (refreshCooldown <= 0) return;
    const timer = setInterval(() => {
      setRefreshCooldown((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [refreshCooldown]);

  if (loading && !data) {
    return (
      <div className="flex flex-col items-center justify-center p-12 bg-dark-900 border border-white/5 rounded-2xl space-y-4">
        <RefreshCw className="w-8 h-8 text-indigo-400 animate-spin" />
        <p className="text-sm font-mono text-slate-400">Loading Quantitative Market Pulse & Radar...</p>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="p-6 bg-rose-950/30 border border-rose-500/20 rounded-2xl text-center space-y-3">
        <AlertTriangle className="w-8 h-8 text-rose-400 mx-auto" />
        <p className="text-sm text-rose-200">Unable to load Market Pulse.</p>
        <button
          onClick={() => fetchMarketPulse(true)}
          className="px-4 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded-lg text-xs font-semibold"
        >
          Retry Fetch
        </button>
      </div>
    );
  }

  if (!data) return null;

  const { tradeability, radar } = data;
  const { factors } = tradeability;

  // Traffic Light Color Styling
  const trafficLightStyles = {
    GREEN: {
      bg: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400',
      badge: 'bg-emerald-500 text-black',
      glow: 'shadow-[0_0_25px_rgba(16,185,129,0.25)]',
      border: 'border-emerald-500/30',
      heroBg: 'from-emerald-950/40 via-dark-900 to-dark-900',
    },
    YELLOW: {
      bg: 'bg-amber-500/10 border-amber-500/30 text-amber-400',
      badge: 'bg-amber-500 text-black',
      glow: 'shadow-[0_0_25px_rgba(245,158,11,0.25)]',
      border: 'border-amber-500/30',
      heroBg: 'from-amber-950/40 via-dark-900 to-dark-900',
    },
    RED: {
      bg: 'bg-rose-500/10 border-rose-500/30 text-rose-400',
      badge: 'bg-rose-500 text-white',
      glow: 'shadow-[0_0_25px_rgba(244,63,94,0.25)]',
      border: 'border-rose-500/30',
      heroBg: 'from-rose-950/40 via-dark-900 to-dark-900',
    },
  }[tradeability.traffic_light] || {
    bg: 'bg-slate-800 border-white/10 text-slate-300',
    badge: 'bg-slate-600 text-white',
    glow: '',
    border: 'border-white/10',
    heroBg: 'from-slate-900 to-dark-900',
  };

  return (
    <div className="space-y-5">
      {/* Top Header / Status Strip */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3.5 bg-dark-900 border border-white/10 rounded-xl shadow-lg">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-indigo-500/10 border border-indigo-500/20 rounded-lg">
            <Compass className="w-5 h-5 text-indigo-400" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-white tracking-wide">Market Pulse & Strategic Radar</h2>
              <span className={cn(
                "px-2 py-0.5 rounded-full text-[10px] font-bold tracking-wider uppercase border",
                data.market_status === 'LIVE' 
                  ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30 animate-pulse" 
                  : "bg-slate-800 text-slate-400 border-white/10"
              )}>
                {data.market_status === 'LIVE' ? '● LIVE SESSION' : '○ CLOSED / EOD'}
              </span>
            </div>
            <p className="text-[11px] text-slate-400 font-mono">
              Nifty 50: <strong className="text-slate-100 font-sans">₹{data.current_nifty_price.toLocaleString('en-IN', { maximumFractionDigits: 1 })}</strong> ({data.nifty_session_change_pts >= 0 ? '+' : ''}{data.nifty_session_change_pts} pts | {data.nifty_session_change_pct >= 0 ? '+' : ''}{data.nifty_session_change_pct}%) • 14D ATR: <span className="text-slate-200">₹{data.nifty_atr_14}</span> • Updated: {data.generated_at}
            </p>
          </div>
        </div>

        {/* Force Refresh Button */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => fetchMarketPulse(true)}
            disabled={isRefreshing || refreshCooldown > 0}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all border",
              isRefreshing || refreshCooldown > 0
                ? "bg-white/5 text-slate-500 border-white/5 cursor-not-allowed"
                : "bg-indigo-600 hover:bg-indigo-500 text-white border-indigo-500 shadow-sm shadow-indigo-500/30"
            )}
          >
            <RefreshCw className={cn("w-3.5 h-3.5", isRefreshing && "animate-spin")} />
            <span>{isRefreshing ? "Evaluating..." : refreshCooldown > 0 ? `Wait ${refreshCooldown}s` : "Force Refresh"}</span>
          </button>
        </div>
      </div>

      {/* Main 2-Column Institutional Cockpit */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        
        {/* ========================================================================= */}
        {/* LEFT COLUMN: Idea #2 - "Should I Trade Today?" (Live Tradeability Filter) */}
        {/* ========================================================================= */}
        <div className="lg:col-span-7 space-y-4">
          
          {/* Big Hero Decision Banner */}
          <div className={cn(
            "p-5 rounded-2xl border bg-gradient-to-b transition-all space-y-4",
            trafficLightStyles.heroBg,
            trafficLightStyles.border,
            trafficLightStyles.glow
          )}>
            <div className="flex items-start justify-between gap-3">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-mono uppercase tracking-widest text-slate-400 font-semibold">
                    Live Tradeability Environment Filter
                  </span>
                  {tradeability.opening_discovery && (
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                      ORB Discovery (9:15-9:30)
                    </span>
                  )}
                </div>
                <h3 className="text-xl sm:text-2xl font-black text-white tracking-tight flex items-center gap-2">
                  {tradeability.verdict}
                </h3>
              </div>

              {/* 0-100 Big Dial Badge */}
              <div className="flex flex-col items-end">
                <div className={cn(
                  "px-3.5 py-1.5 rounded-xl border text-center font-mono font-black text-2xl tracking-tight shadow-md",
                  trafficLightStyles.bg
                )}>
                  {tradeability.score}<span className="text-xs font-sans text-slate-400 font-normal">/100</span>
                </div>
                <div className="flex items-center gap-1 mt-0.5">
                  <span className="text-[10px] font-mono text-slate-400">Tradeability Score</span>
                  <MarketPulseTooltip
                    title="Live Intraday Tradeability Score"
                    align="right"
                    formula="0 - 100 Composite Score"
                    meaning="Yeh score batata hai ki aaj live intraday market mein breakout trading karna kitna safe hai. Yeh Trend Efficiency, 1,468 Stocks Breadth, Candle Wicks, Range Exhaustion aur India VIX ko combine karke banta hai."
                    rule=">= 68: Green Light (Normal Breakout Sizing) | 45-67: Yellow Light (Selective 50% Sizing) | < 45: Red Light (Sit on Cash, 0% Long Exposure)."
                  />
                </div>
                {tradeability.cap_reason ? (
                  <span className="mt-1 px-1.5 py-0.5 text-[9.5px] font-mono font-semibold rounded bg-rose-950/80 text-rose-300 border border-rose-500/40 text-right whitespace-nowrap shadow-sm">
                    [{tradeability.cap_reason}]
                  </span>
                ) : (
                  (() => {
                    const rawSum = Object.values(factors).reduce((acc: number, f: any) => acc + (f?.score || 0), 0);
                    const roundedSum = Math.round(rawSum * 10) / 10;
                    if (roundedSum > tradeability.score && (factors.vwap_breadth?.vwap_breadth_pct ?? 100) < 38) {
                      return (
                        <span className="mt-1 px-1.5 py-0.5 text-[9.5px] font-mono font-semibold rounded bg-rose-950/80 text-rose-300 border border-rose-500/40 text-right whitespace-nowrap shadow-sm">
                          [Capped from {roundedSum.toFixed(1)} by Bearish Breadth]
                        </span>
                      );
                    }
                    return null;
                  })()
                )}
              </div>
            </div>

            {/* Position Sizing & Action Guidance */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 pt-2 border-t border-white/10">
              <div className="p-2.5 rounded-xl bg-black/30 border border-white/5 space-y-0.5">
                <span className="text-[10px] font-mono text-slate-400 uppercase flex items-center justify-between">
                  <span>Recommended Sizing</span>
                  <MarketPulseTooltip
                    title="Dynamic Position Sizing Multiplier"
                    meaning="Aapko apne normal capital ka kitna hissa deploy karna chahiye. Market volatility aur broad distribution ke mutabiq algorithm capital protect karta hai."
                    rule="1.0x = Normal Breakout Size | 0.5x = Half Capital Size | 0.0x = Cash Preservation Mode (No Longs)."
                  />
                </span>
                <p className="text-xs font-bold text-slate-100 flex items-center gap-1">
                  <Zap className="w-3.5 h-3.5 text-amber-400" />
                  {tradeability.position_sizing}
                </p>
              </div>

              <div className="sm:col-span-2 p-2.5 rounded-xl bg-black/30 border border-white/5 space-y-0.5">
                <span className="text-[10px] font-mono text-slate-400 uppercase flex items-center justify-between">
                  <span>Operational Directive</span>
                  <MarketPulseTooltip
                    title="Real-Time Trading Directive"
                    meaning="Engine ka live operational command jo market regime ke mutabiq buy, sell ya hold karne ki exact tactical guidance deta hai."
                  />
                </span>
                <p className="text-xs text-slate-200 leading-snug">
                  {tradeability.action_summary}
                </p>
              </div>
            </div>

            {/* Breadth Divergence Warning Banner if active */}
            {factors.vwap_breadth.divergence_flag && (
              <div className="p-3 bg-amber-950/40 border border-amber-500/30 rounded-xl flex items-start gap-2.5 text-xs text-amber-200">
                <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                <span>{factors.vwap_breadth.divergence_flag}</span>
              </div>
            )}
          </div>

          {/* 5 Sub-Factors Breakdown Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            
            {/* 1. Dual-Window Efficiency Ratio Card */}
            <div className="p-3.5 bg-dark-900 border border-white/10 rounded-xl space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <Activity className="w-4 h-4 text-cyan-400" />
                  <span className="text-xs font-bold text-slate-200">Efficiency Ratio (ER)</span>
                  <MarketPulseTooltip
                    title="Kaufman's Trend Efficiency Ratio"
                    formula="ER = |Net Travel| / Sum(Ranges)"
                    meaning="Yeh market ke noise vs direct trend ko naapta hai (0 se 1). 0 matlab pure sideways chop, 1 matlab straight directional trend. Low ER (< 0.22) mein breakout traps lagte hain."
                    rule=">= 0.42: Strong Trend Impulse | 0.22-0.42: Normal Efficiency | < 0.22: Severe Chop (Breakouts Fail)."
                  />
                </div>
                <span className="text-xs font-mono font-bold text-cyan-400">
                  {factors.efficiency_ratio.score} / {factors.efficiency_ratio.max_score} pts
                </span>
              </div>
              <div className="flex items-baseline justify-between text-xs font-mono">
                <span className="text-slate-400">Effective ER:</span>
                <strong className={cn(
                  "font-bold",
                  factors.efficiency_ratio.er_effective >= 0.42 ? "text-emerald-400" :
                  factors.efficiency_ratio.er_effective >= 0.22 ? "text-amber-400" : "text-rose-400"
                )}>
                  {factors.efficiency_ratio.er_effective.toFixed(3)}
                </strong>
              </div>
              <div className="text-[11px] text-slate-400 flex items-center justify-between">
                <span>Session: {factors.efficiency_ratio.er_session.toFixed(3)}</span>
                <span>30m Impulse: {factors.efficiency_ratio.er_impulse_6.toFixed(3)}</span>
              </div>
              <div className="pt-1 flex items-center justify-between text-[10px]">
                <span className={cn(
                  "px-1.5 py-0.5 rounded font-mono",
                  factors.efficiency_ratio.mode === '6_BAR_IMPULSE_ACTIVE' 
                    ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-bold" 
                    : factors.efficiency_ratio.mode === 'BEARISH_IMPULSE_REJECT'
                    ? "bg-rose-500/20 text-rose-300 border border-rose-500/30 font-bold"
                    : "bg-white/5 text-slate-400"
                )}>
                  {factors.efficiency_ratio.mode === '6_BAR_IMPULSE_ACTIVE' ? '⚡ V-Reversal Active' : 
                   factors.efficiency_ratio.mode === 'BEARISH_IMPULSE_REJECT' ? '↘ Bearish Impulse' : 'Session Trend'}
                </span>
                <span className="text-slate-400 font-mono">
                  {factors.efficiency_ratio.bars_count} bars (5m{data.session_date ? ` • ${data.session_date}` : ''})
                </span>
              </div>
            </div>

            {/* 2. 1,468-Stock Institutional VWAP Breadth Card */}
            <div className="p-3.5 bg-dark-900 border border-white/10 rounded-xl space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <BarChart2 className="w-4 h-4 text-indigo-400" />
                  <span className="text-xs font-bold text-slate-200">1,468 Universe Breadth</span>
                  <MarketPulseTooltip
                    title="Institutional Session VWAP Breadth"
                    formula="% Stocks > Session VWAP"
                    meaning="Poore 1,468 NSE liquid stocks mein se kitne percent stocks session VWAP ke upar hain. A/D ratio batata hai kitne stocks badh vs gir rahe hain."
                    rule=">= 65%: Strong Bullish Wave | 48-65%: Rotational | < 38%: Severe Institutional Dumping (Longs Strictly Blocked)."
                  />
                </div>
                <span className="text-xs font-mono font-bold text-indigo-400">
                  {factors.vwap_breadth.score} / {factors.vwap_breadth.max_score} pts
                </span>
              </div>
              <div className="flex items-baseline justify-between text-xs font-mono">
                <span className="text-slate-400">&gt; Intraday VWAP:</span>
                <strong className={cn(
                  "font-bold",
                  factors.vwap_breadth.vwap_breadth_pct >= 58 ? "text-emerald-400" :
                  factors.vwap_breadth.vwap_breadth_pct <= 42 ? "text-rose-400" : "text-amber-400"
                )}>
                  {factors.vwap_breadth.vwap_breadth_pct}%
                </strong>
              </div>
              <div className="text-[11px] text-slate-400 flex items-center justify-between">
                <span>&gt; 20-EMA: {factors.vwap_breadth.ema20_breadth_pct}%</span>
                <span>A/D: {factors.vwap_breadth.adv_decline_ratio}x</span>
              </div>
              <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden flex">
                <div 
                  className="bg-emerald-500 h-full" 
                  style={{ width: `${factors.vwap_breadth.vwap_breadth_pct}%` }} 
                />
                <div 
                  className="bg-rose-500 h-full flex-1" 
                />
              </div>
            </div>

            {/* 3. Range-Weighted Wick Ratio Card */}
            <div className="p-3.5 bg-dark-900 border border-white/10 rounded-xl space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <Flame className="w-4 h-4 text-orange-400" />
                  <span className="text-xs font-bold text-slate-200">Candle Quality (Wick Ratio)</span>
                  <MarketPulseTooltip
                    title="Range-Weighted Wick Ratio"
                    formula="Sum(Wicks) / Sum(Candle Ranges)"
                    meaning="5-minute candles mein wicks (shadows) ka percentage. Zyada wick ratio ka matlab fake breakouts aur stop-loss hunting chal rahi hai."
                    rule="<= 42%: Clean Trend Bodies | 42-58%: Balanced | > 58%: Heavy Rejection / Stop-Loss Hunting."
                  />
                </div>
                <span className="text-xs font-mono font-bold text-orange-400">
                  {factors.wick_ratio.score} / {factors.wick_ratio.max_score} pts
                </span>
              </div>
              <div className="flex items-baseline justify-between text-xs font-mono">
                <span className="text-slate-400">RW Wick Ratio:</span>
                <strong className={cn(
                  "font-bold",
                  factors.wick_ratio.wick_ratio_rw <= 0.42 ? "text-emerald-400" :
                  factors.wick_ratio.wick_ratio_rw > 0.58 ? "text-rose-400" : "text-amber-400"
                )}>
                  {factors.wick_ratio.wick_pct}%
                </strong>
              </div>
              <div className="flex items-center justify-between text-[11px] text-slate-400">
                <span>Structure:</span>
                <span className={cn(
                  "font-semibold",
                  factors.wick_ratio.quality === 'CLEAN_BODIES' ? "text-emerald-400" :
                  factors.wick_ratio.quality === 'STOP_HUNT_WICKS' ? "text-rose-400" : "text-slate-300"
                )}>
                  {factors.wick_ratio.quality === 'CLEAN_BODIES' ? 'Institutional Solid Bodies' :
                   factors.wick_ratio.quality === 'STOP_HUNT_WICKS' ? 'Heavy Whipsaw Wicks' : 'Balanced Candles'}
                </span>
              </div>
            </div>

            {/* 4. Wilder's True Day Range Consumed (TDRC) Card */}
            <div className="p-3.5 bg-dark-900 border border-white/10 rounded-xl space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <Gauge className="w-4 h-4 text-purple-400" />
                  <span className="text-xs font-bold text-slate-200">Fuel Consumed (TDRC)</span>
                  <MarketPulseTooltip
                    title="Wilder's True Day Range Consumed"
                    formula="(Today Range / 14D ATR) * 100%"
                    meaning="Nifty ne apne average 14-day daily range ka kitna percentage travel kar liya hai. Yeh batata hai ki din mein abhi aur kitni move bachi hai."
                    rule="< 35%: Compression / Expansion Due | 35-90%: Healthy Trending Fuel | > 100%: EXHAUSTED (Late breakouts chase mat karein)."
                  />
                </div>
                <span className="text-xs font-mono font-bold text-purple-400">
                  {factors.range_consumed.score} / {factors.range_consumed.max_score} pts
                </span>
              </div>
              <div className="flex items-baseline justify-between text-xs font-mono">
                <span className="text-slate-400">% 14D ATR Used:</span>
                <strong className={cn(
                  "font-bold",
                  factors.range_consumed.status === 'HEALTHY' ? "text-emerald-400" :
                  factors.range_consumed.status === 'EXHAUSTED' ? "text-rose-400" : "text-amber-400"
                )}>
                  {factors.range_consumed.tdrc_pct}%
                </strong>
              </div>
              <div className="flex items-center justify-between text-[11px] text-slate-400">
                <span>Today Range: {factors.range_consumed.intraday_true_range} pts</span>
                <span className={cn(
                  "font-semibold uppercase text-[10px] px-1.5 py-0.2 rounded",
                  factors.range_consumed.status === 'HEALTHY' ? "bg-emerald-500/10 text-emerald-300" :
                  factors.range_consumed.status === 'EXHAUSTED' ? "bg-rose-500/10 text-rose-300" : "bg-amber-500/10 text-amber-300"
                )}>
                  {factors.range_consumed.status}
                </span>
              </div>
            </div>
          </div>

          {/* 5. India VIX & Sector Leadership Panel */}
          <div className="p-4 bg-dark-900 border border-white/10 rounded-xl space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ShieldAlert className="w-4 h-4 text-amber-400" />
                <span className="text-xs font-bold text-slate-200">India VIX Fear Meter</span>
                <MarketPulseTooltip
                  title="India VIX Fear Meter & Volatility Velocity"
                  meaning="Market ka panic index. VIX badhne ka matlab option premiums mehnge ho rahe hain aur market downside crash ko lekar nervous hai."
                  rule="<= 17.5 & Chg <= 3%: Favorable Bulls | VIX Spike > 5%: High Panic Risk, Long Breakouts Fail."
                />
              </div>
              <div className="flex items-center gap-2 font-mono text-xs">
                <span className="text-slate-400">Level: <strong className="text-slate-100">{factors.india_vix.vix_level}</strong></span>
                <span className={cn(
                  "font-bold",
                  factors.india_vix.vix_change_pct <= 0 ? "text-emerald-400" : "text-rose-400"
                )}>
                  ({factors.india_vix.vix_change_pct >= 0 ? '+' : ''}{factors.india_vix.vix_change_pct}%)
                </span>
                <span className="text-xs font-mono font-bold text-amber-400">
                  {factors.india_vix.score} / {factors.india_vix.max_score} pts
                </span>
              </div>
            </div>

            {/* Leading & Lagging Sectors from 1,468 Universe */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2 border-t border-white/5">
              <div className="space-y-1.5">
                <span className="text-[10px] font-mono uppercase text-emerald-400 font-bold flex items-center gap-1">
                  <TrendingUp className="w-3 h-3" /> Top Accumulating Sectors
                  <MarketPulseTooltip
                    title="Intraday Sector Accumulation"
                    meaning="Institutions kis sector ke stocks ko actively session VWAP ke upar accumulate kar rahe hain."
                  />
                </span>
                <div className="space-y-1">
                  {tradeability.leading_sectors.slice(0, 3).map((sec) => (
                    <div key={sec.sector} className="flex items-center justify-between text-xs bg-black/20 px-2 py-1 rounded border border-white/5 font-mono">
                      <span className="text-slate-300 font-sans truncate">{sec.sector}</span>
                      <span className="text-emerald-400 font-bold">{sec.breadth_pct}% &gt; VWAP</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="space-y-1.5">
                <span className="text-[10px] font-mono uppercase text-rose-400 font-bold flex items-center gap-1">
                  <TrendingDown className="w-3 h-3" /> Bleeding Sectors
                  <MarketPulseTooltip
                    title="Intraday Sector Bleeding"
                    meaning="Institutions kis sector ke stocks ko aggressively dump kar rahe hain (VWAP ke niche collapse)."
                  />
                </span>
                <div className="space-y-1">
                  {tradeability.lagging_sectors.slice(0, 3).map((sec) => (
                    <div key={sec.sector} className="flex items-center justify-between text-xs bg-black/20 px-2 py-1 rounded border border-white/5 font-mono">
                      <span className="text-slate-300 font-sans truncate">{sec.sector}</span>
                      <span className="text-rose-400 font-bold">{sec.breadth_pct}% &gt; VWAP</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ========================================================================= */}
        {/* RIGHT COLUMN: Idea #1 - Next-Day & Session Structural Radar (Conditional Zones) */}
        {/* ========================================================================= */}
        <div className="lg:col-span-5 space-y-4">
          
          {/* Next-Day / Tomorrow Directional Hero Banner (Fix #6) */}
          <div className={cn(
            "p-5 rounded-2xl border bg-gradient-to-b transition-all space-y-3.5",
            radar.next_day_color === 'GREEN'
              ? "from-emerald-950/40 via-dark-900 to-dark-900 border-emerald-500/30 shadow-[0_0_25px_rgba(16,185,129,0.2)]"
              : radar.next_day_color === 'RED'
              ? "from-rose-950/40 via-dark-900 to-dark-900 border-rose-500/30 shadow-[0_0_25px_rgba(244,63,94,0.2)]"
              : "from-amber-950/40 via-dark-900 to-dark-900 border-amber-500/30 shadow-[0_0_25px_rgba(245,158,11,0.15)]"
          )}>
            <div className="flex items-start justify-between gap-2.5">
              <div className="space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[10px] font-mono uppercase tracking-widest text-indigo-300 font-semibold flex items-center gap-1">
                    {radar.stage_mode === 'LIVE_SESSION_PLAYBOOK' ? '● LIVE SESSION STRUCTURAL BIAS' : '🔮 TOMORROW / NEXT-SESSION OUTLOOK'}
                    <MarketPulseTooltip
                      title="Next-Day Directional Forecast Engine"
                      formula="5-Pillar Weighted Score (-100 to +100)"
                      meaning="Agle trading session ke liye directional roadmap. CLV Momentum, EMAs, 1,468 Breadth, Global Macro aur VIX ko combine karke conviction nikalta hai."
                      rule="Score > +18: Bullish Bias | Score < -18: Bearish Bias | -18 to +18: Sideways Chop."
                    />
                  </span>
                  <span className={cn(
                    "px-2 py-0.5 rounded text-[9px] font-mono font-bold border",
                    radar.compression_tag.includes('COMPRESSION') || radar.compression_tag.includes('COILING')
                      ? "bg-purple-500/20 text-purple-300 border-purple-500/40 animate-pulse"
                      : "bg-white/5 text-slate-400 border-white/10"
                  )}>
                    {radar.compression_tag.replace(/_/g, ' ')}
                  </span>
                </div>
                <h3 className={cn(
                  "text-lg sm:text-xl font-black tracking-tight flex flex-wrap items-center gap-2",
                  radar.next_day_color === 'GREEN' ? "text-emerald-400" :
                  radar.next_day_color === 'RED' ? "text-rose-400" : "text-amber-400"
                )}>
                  <span>
                    {radar.next_day_direction === 'BULLISH' ? '🟢 TOMORROW BIAS: BULLISH' :
                     radar.next_day_direction === 'BEARISH' ? '🔴 TOMORROW BIAS: BEARISH' :
                     '🟡 TOMORROW BIAS: SIDEWAYS'}
                  </span>
                  {radar.target_session_date && (
                    <span className="text-xs font-mono font-medium text-slate-300 bg-black/50 px-2 py-0.5 rounded-md border border-white/10">
                      (For {radar.target_session_date})
                    </span>
                  )}
                </h3>
              </div>

              {/* Conviction % & 5-Pillar Weighted Score Badge */}
              <div className="flex flex-col items-end shrink-0">
                <div className={cn(
                  "px-3 py-1 rounded-xl border text-center font-mono font-black text-lg tracking-tight shadow-md",
                  radar.next_day_color === 'GREEN' ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300" :
                  radar.next_day_color === 'RED' ? "bg-rose-500/15 border-rose-500/40 text-rose-300" :
                  "bg-amber-500/15 border-amber-500/40 text-amber-300"
                )}>
                  {radar.next_day_conviction_pct ?? 65}%
                  <span className="text-[10px] font-sans font-normal block -mt-1 opacity-80">Conviction</span>
                </div>
                <span className="text-[10px] font-mono text-slate-400 mt-1">
                  Score: {(radar.next_day_score ?? 0) >= 0 ? '+' : ''}{radar.next_day_score ?? 0}/100
                </span>
              </div>
            </div>

            {/* Next-Day Executive Summary */}
            {radar.next_day_summary && (
              <div className="p-2.5 bg-black/35 border border-white/10 rounded-xl text-xs text-slate-200 leading-snug">
                {radar.next_day_summary}
              </div>
            )}

            {/* 5-Pillar Directional Score Breakdown */}
            {radar.pillar_scores && (
              <div className="pt-2 border-t border-white/10 space-y-1.5">
                <span className="text-[10px] font-mono uppercase text-slate-400 flex items-center gap-1">
                  5-Pillar Next-Day Directional Attribution (-100 to +100)
                  <MarketPulseTooltip
                    title="5-Pillar Attribution Engine"
                    meaning="Score -100 (Max Bearish) se +100 (Max Bullish) ke beech calculate hota hai. Har pillar ka specific weight contribution niche cards mein dikh raha hai."
                  />
                </span>
                <div className="grid grid-cols-5 gap-1.5 text-center font-mono text-[10px]">
                  <div className="p-1.5 rounded bg-black/30 border border-white/5 relative group">
                    <div className="flex items-center justify-center gap-0.5">
                      <span className="text-slate-400 block truncate">CLV/Close</span>
                      <MarketPulseTooltip
                        title="Pillar 1: CLV / Close (±25 pts)"
                        meaning="Close Location Value. Candle din ke absolute low ke paas close hui (13.3%), buyers bilkul maujood nahi the."
                      />
                    </div>
                    <strong className={radar.pillar_scores.clv_momentum >= 0 ? "text-emerald-400" : "text-rose-400"}>
                      {radar.pillar_scores.clv_momentum >= 0 ? '+' : ''}{radar.pillar_scores.clv_momentum}
                    </strong>
                  </div>
                  <div className="p-1.5 rounded bg-black/30 border border-white/5 relative group">
                    <div className="flex items-center justify-center gap-0.5">
                      <span className="text-slate-400 block truncate">Daily EMA</span>
                      <MarketPulseTooltip
                        title="Pillar 2: Daily EMA Structure (±20 pts)"
                        meaning="Nifty apne Daily 20-EMA aur 50-EMA dono ke niche slip ho chuka hai, medium trend weak hai."
                      />
                    </div>
                    <strong className={radar.pillar_scores.ema_structure >= 0 ? "text-emerald-400" : "text-rose-400"}>
                      {radar.pillar_scores.ema_structure >= 0 ? '+' : ''}{radar.pillar_scores.ema_structure}
                    </strong>
                  </div>
                  <div className="p-1.5 rounded bg-black/30 border border-white/5 relative group">
                    <div className="flex items-center justify-center gap-0.5">
                      <span className="text-slate-400 block truncate">Breadth</span>
                      <MarketPulseTooltip
                        title="Pillar 3: 1,468 Universe Breadth (±25 pts)"
                        meaning="72.1% stocks VWAP ke niche close hue hain. Large caps ko broad universe ka support nahi hai."
                      />
                    </div>
                    <strong className={radar.pillar_scores.universe_breadth >= 0 ? "text-emerald-400" : "text-rose-400"}>
                      {radar.pillar_scores.universe_breadth >= 0 ? '+' : ''}{radar.pillar_scores.universe_breadth}
                    </strong>
                  </div>
                  <div className="p-1.5 rounded bg-black/30 border border-white/5 relative group">
                    <div className="flex items-center justify-center gap-0.5">
                      <span className="text-slate-400 block truncate">Macro</span>
                      <MarketPulseTooltip
                        title="Pillar 4: Global Macro Tailwind (±20 pts)"
                        meaning="US markets (S&P 500 +0.28%) aur falling crude oil (-0.48%) Bharat ke liye support de rahe hain."
                      />
                    </div>
                    <strong className={radar.pillar_scores.global_macro >= 0 ? "text-emerald-400" : "text-rose-400"}>
                      {radar.pillar_scores.global_macro >= 0 ? '+' : ''}{radar.pillar_scores.global_macro}
                    </strong>
                  </div>
                  <div className="p-1.5 rounded bg-black/30 border border-white/5 relative group">
                    <div className="flex items-center justify-center gap-0.5">
                      <span className="text-slate-400 block truncate">India VIX</span>
                      <MarketPulseTooltip
                        title="Pillar 5: India VIX Regime (±10 pts)"
                        align="right"
                        meaning="VIX mein +5.05% spike aane se options selling aur downside risk badha hai."
                      />
                    </div>
                    <strong className={radar.pillar_scores.vix_regime >= 0 ? "text-emerald-400" : "text-rose-400"}>
                      {radar.pillar_scores.vix_regime >= 0 ? '+' : ''}{radar.pillar_scores.vix_regime}
                    </strong>
                  </div>
                </div>
              </div>
            )}

            {/* Gap Warning Banner if any */}
            {radar.gap_warning && (
              <div className="p-2.5 bg-amber-950/40 border border-amber-500/30 rounded-lg text-[11px] text-amber-200 flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                <span>{radar.gap_warning}</span>
              </div>
            )}

            {/* Zone Guidance */}
            <div className="p-2.5 bg-black/40 border border-white/5 rounded-lg text-xs text-slate-300 flex items-start gap-2">
              <Info className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
              <span>{radar.zone_guidance}</span>
            </div>
          </div>

          {/* Visual 3-Zone Conditional Price Ladder */}
          <div className="p-4 bg-dark-900 border border-white/10 rounded-xl space-y-3">
            <div className="flex items-center justify-between text-xs">
              <span className="font-bold text-slate-200 flex items-center gap-1.5">
                <span>Static Locked Execution Ladder</span>
                <MarketPulseTooltip
                  title="Session-Anchored Conditional Ladder"
                  meaning="Pichle trading session ke settlement par calculated static levels jo pure din badalte nahi hain. Ye false intraday noise aur whipsaw se bachate hain."
                />
              </span>
              <span className="text-[10px] font-mono text-slate-500 flex items-center gap-1">
                <Lock className="w-3 h-3 text-slate-400" /> Anchored to {radar.anchored_reference_date}
              </span>
            </div>

            <div className="space-y-2 font-mono text-xs">
              
              {/* Bullish Acceptance Zone */}
              <div className={cn(
                "p-3 rounded-xl border transition-all space-y-1.5",
                radar.current_zone === 'BULLISH_ACCEPTANCE'
                  ? "bg-emerald-950/40 border-emerald-500/50 shadow-md shadow-emerald-950/40"
                  : "bg-emerald-950/10 border-emerald-500/20 opacity-80"
              )}>
                <div className="flex items-center justify-between">
                  <span className="font-bold text-emerald-400 flex items-center gap-1 font-sans">
                    <ArrowUpRight className="w-4 h-4 text-emerald-400" /> 
                    <span>Bullish Acceptance (Longs Active)</span>
                    <MarketPulseTooltip
                      title="Bullish Acceptance Trigger"
                      meaning="Yeh upper resistance breakout trigger hai. Is level ke upar 15m candle close aane par hi longs activate honge."
                      rule="Entry >= Bullish Trigger. Targets: Target 1 (+0.40 ATR) & Target 2 (+0.80 ATR)."
                    />
                  </span>
                  <span className="font-bold text-emerald-300">
                    &ge; ₹{radar.conditional_zones.bullish_trigger.toLocaleString('en-IN')}
                  </span>
                </div>
                <div className="flex items-center justify-between text-[11px] text-emerald-200/70 pt-0.5 border-t border-emerald-500/10">
                  <span>Target 1: ₹{radar.conditional_zones.target_1.toLocaleString('en-IN')}</span>
                  <span>Target 2: ₹{radar.conditional_zones.target_2.toLocaleString('en-IN')}</span>
                </div>
              </div>

              {/* No-Trade Chop Trap Zone */}
              <div className={cn(
                "p-3 rounded-xl border transition-all space-y-1.5",
                radar.current_zone === 'NO_TRADE_CHOP_ZONE'
                  ? "bg-amber-950/40 border-amber-500/50 shadow-md shadow-amber-950/40"
                  : "bg-amber-950/10 border-amber-500/20 opacity-70"
              )}>
                <div className="flex items-center justify-between">
                  <span className="font-bold text-amber-400 flex items-center gap-1 font-sans">
                    <Minus className="w-4 h-4 text-amber-400" /> 
                    <span>No-Trade Chop Zone (Wait &amp; Protect)</span>
                    <MarketPulseTooltip
                      title="No-Trade Chop Trap Zone"
                      meaning="Yeh trap zone hai. Dono triggers ke beech mein price random noise karti hai aur fake breakouts deti hai. Iske andar trading strictly avoid karein."
                      rule="Wait & Protect Capital. Breakouts tabhi lein jab price is range se bahar nikal kar accept ho."
                    />
                  </span>
                  <span className="font-bold text-amber-300">
                    ₹{radar.conditional_zones.chop_zone_low.toLocaleString('en-IN')} ↔ ₹{radar.conditional_zones.chop_zone_high.toLocaleString('en-IN')}
                  </span>
                </div>
                <p className="text-[11px] text-amber-200/70 font-sans">
                  Trapped between value boundaries. Breakouts fail with high frequency.
                </p>
              </div>

              {/* Bearish Breakdown Zone */}
              <div className={cn(
                "p-3 rounded-xl border transition-all space-y-1.5",
                radar.current_zone === 'BEARISH_BREAKDOWN'
                  ? "bg-rose-950/40 border-rose-500/50 shadow-md shadow-rose-950/40"
                  : "bg-rose-950/10 border-rose-500/20 opacity-80"
              )}>
                <div className="flex items-center justify-between">
                  <span className="font-bold text-rose-400 flex items-center gap-1 font-sans">
                    <ArrowDownRight className="w-4 h-4 text-rose-400" /> 
                    <span>Bearish Breakdown (Short/Cash)</span>
                    <MarketPulseTooltip
                      title="Bearish Breakdown Trigger"
                      meaning="Yeh lower breakdown trigger hai. Is level ke niche fisalne par fresh institutional sell-off shuru hota hai."
                      rule="Trigger <= Lower Level. Supports: Support 1 (-0.40 ATR) & Support 2 (-0.80 ATR)."
                    />
                  </span>
                  <span className="font-bold text-rose-300">
                    &le; ₹{radar.conditional_zones.bearish_trigger.toLocaleString('en-IN')}
                  </span>
                </div>
                <div className="flex items-center justify-between text-[11px] text-rose-200/70 pt-0.5 border-t border-rose-500/10">
                  <span>Support 1: ₹{radar.conditional_zones.support_1.toLocaleString('en-IN')}</span>
                  <span>Support 2: ₹{radar.conditional_zones.support_2.toLocaleString('en-IN')}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Stage 1 vs Stage 2 Deep Metrics */}
          <div className="p-4 bg-dark-900 border border-white/10 rounded-xl space-y-3">
            <span className="text-xs font-bold text-slate-200 flex items-center gap-1.5">
              <Layers className="w-4 h-4 text-indigo-400" /> 
              <span>Stage 1 EOD Structure vs Stage 2 Macro Overlay</span>
              <MarketPulseTooltip
                title="EOD Structure vs Macro Overlay"
                meaning="Pichle trading session ki internal closing candle shape (CLV) ko overnight global cues (US indices, Dollar, Crude Oil) ke sath synthesize karta hai."
              />
            </span>

            <div className="grid grid-cols-2 gap-2 text-xs font-mono">
              <div className="p-2 bg-black/20 rounded border border-white/5 space-y-0.5">
                <span className="text-[10px] text-slate-400 uppercase flex items-center justify-between">
                  <span>Daily Close Location (CLV)</span>
                  <MarketPulseTooltip
                    title="Daily Close Location Value (CLV)"
                    formula="(Close - Low) / (High - Low) * 100%"
                    meaning="0% = Low par close, 100% = High par close. 13.3% batata hai bears ne market ko end tak control mein rakha aur EOD recovery bilkul nahi aayi."
                  />
                </span>
                <p className={cn(
                  "font-bold",
                  radar.stage_1_eod_structure.clv_pct >= 75 ? "text-emerald-400" :
                  radar.stage_1_eod_structure.clv_pct <= 25 ? "text-rose-400" : "text-slate-300"
                )}>
                  {radar.stage_1_eod_structure.clv_pct}%
                </p>
              </div>

              <div className="p-2 bg-black/20 rounded border border-white/5 space-y-0.5">
                <span className="text-[10px] text-slate-400 uppercase flex items-center justify-between">
                  <span>Macro Tailwind Score</span>
                  <MarketPulseTooltip
                    title="Global Macro Tailwind Score"
                    formula="-100 to +100 Scale"
                    meaning="US indices, US Dollar Index (DXY) aur Brent Crude ka composite impact. Crude aur Dollar ka girna Indian equities ke liye positive tailwind deta hai."
                  />
                </span>
                <p className={cn(
                  "font-bold",
                  radar.stage_2_global_macro.macro_tailwind_score > 0 ? "text-emerald-400" : "text-rose-400"
                )}>
                  {radar.stage_2_global_macro.macro_tailwind_score >= 0 ? '+' : ''}{radar.stage_2_global_macro.macro_tailwind_score} / 100
                </p>
              </div>
            </div>

            {/* Global Tickers Summary */}
            <div className="grid grid-cols-4 gap-1.5 text-center text-[10px] font-mono pt-1">
              <div className="p-1.5 bg-black/30 rounded border border-white/5">
                <div className="flex items-center justify-center gap-0.5">
                  <span className="text-slate-400 block truncate">S&amp;P 500</span>
                  <MarketPulseTooltip
                    title="S&P 500"
                    meaning="US Benchmark Equity Index. US market positive hone se opening sentiment ko boost milta hai."
                  />
                </div>
                <strong className={radar.stage_2_global_macro.sp500_chg_pct >= 0 ? "text-emerald-400" : "text-rose-400"}>
                  {radar.stage_2_global_macro.sp500_chg_pct >= 0 ? '+' : ''}{radar.stage_2_global_macro.sp500_chg_pct}%
                </strong>
              </div>
              <div className="p-1.5 bg-black/30 rounded border border-white/5">
                <div className="flex items-center justify-center gap-0.5">
                  <span className="text-slate-400 block truncate">Nasdaq</span>
                  <MarketPulseTooltip
                    title="Nasdaq Composite"
                    meaning="US Tech Index. Indian IT sector stocks Nasdaq ke price action ke sath correlated rehte hain."
                  />
                </div>
                <strong className={radar.stage_2_global_macro.nasdaq_chg_pct >= 0 ? "text-emerald-400" : "text-rose-400"}>
                  {radar.stage_2_global_macro.nasdaq_chg_pct >= 0 ? '+' : ''}{radar.stage_2_global_macro.nasdaq_chg_pct}%
                </strong>
              </div>
              <div className="p-1.5 bg-black/30 rounded border border-white/5">
                <div className="flex items-center justify-center gap-0.5">
                  <span className="text-slate-400 block truncate">DXY (USD)</span>
                  <MarketPulseTooltip
                    title="US Dollar Index (DXY)"
                    meaning="Dollar Index ka girna emerging markets aur Indian Rupee ke liye positive (Green) hota hai."
                  />
                </div>
                <strong className={radar.stage_2_global_macro.dxy_chg_pct <= 0 ? "text-emerald-400" : "text-rose-400"}>
                  {radar.stage_2_global_macro.dxy_chg_pct >= 0 ? '+' : ''}{radar.stage_2_global_macro.dxy_chg_pct}%
                </strong>
              </div>
              <div className="p-1.5 bg-black/30 rounded border border-white/5">
                <div className="flex items-center justify-center gap-0.5">
                  <span className="text-slate-400 block truncate">Brent Crude</span>
                  <MarketPulseTooltip
                    title="Brent Crude Oil"
                    align="right"
                    meaning="Crude oil ka girna Bharat ke import bill, fiscal deficit aur inflation ke liye bohot acha (Green) hota hai."
                  />
                </div>
                <strong className={radar.stage_2_global_macro.crude_chg_pct <= 0 ? "text-emerald-400" : "text-rose-400"}>
                  {radar.stage_2_global_macro.crude_chg_pct >= 0 ? '+' : ''}{radar.stage_2_global_macro.crude_chg_pct}%
                </strong>
              </div>
            </div>
          </div>

        </div>

      </div>
    </div>
  );
}
