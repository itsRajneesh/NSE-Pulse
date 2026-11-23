"use client";

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { 
  Zap, 
  Target, 
  Flame, 
  LineChart, 
  ExternalLink, 
  AlertTriangle, 
  CheckCircle2, 
  Clock, 
  RefreshCw, 
  TrendingUp, 
  TrendingDown, 
  ShieldAlert,
  Search,
  Activity,
  ArrowUpDown,
  Droplets,
  Ruler,
  ShieldCheck,
  RotateCcw,
  Info,
  HelpCircle
} from 'lucide-react';
import { LiveMoverItem, LiveMoversResponse, V13ChartTarget } from '@/types/screener';
import { formatINR, cn } from '@/lib/utils';

interface LiveMoversPanelProps {
  onOpenChart: (stock: V13ChartTarget) => void;
}

type MoverFilterType = 'ALL' | 'RUNNERS' | 'SHORT_RUNNERS' | 'EXHAUSTION' | 'GAINERS' | 'LOSERS';

export type MoverCategory = 
  | 'COMBINED'
  | 'V13_ACTIVE'
  | 'ALL'
  | 'NIFTY_50'
  | 'BANK_NIFTY'
  | 'NIFTY_NEXT_50'
  | 'FNO'
  | 'ABOVE_20'
  | 'BELOW_20';

export type MoverSortType = 
  | 'NSE_RANK'
  | 'V13_SCORE_DESC'
  | 'CHANGE_DESC'
  | 'CHANGE_ASC'
  | 'REL_VOL_DESC'
  | 'TURNOVER_DESC'
  | 'PRICE_DESC'
  | 'PRICE_ASC'
  | 'SYMBOL_ASC';

const SORT_OPTIONS: { value: MoverSortType; label: string }[] = [
  { value: 'NSE_RANK', label: '🥇 NSE Rank' },
  { value: 'V13_SCORE_DESC', label: '⚡ V13 Score (High → Low)' },
  { value: 'CHANGE_DESC', label: '📈 % Change (High → Low)' },
  { value: 'CHANGE_ASC', label: '📉 % Change (Low → High)' },
  { value: 'REL_VOL_DESC', label: '⚡ RelVol (High → Low)' },
  { value: 'TURNOVER_DESC', label: '💰 Turnover (High → Low)' },
  { value: 'PRICE_DESC', label: '🏷️ Price (High → Low)' },
  { value: 'PRICE_ASC', label: '🏷️ Price (Low → High)' },
  { value: 'SYMBOL_ASC', label: '🔤 Symbol (A → Z)' },
];

const v13MinScoreConfig = typeof process !== 'undefined' && process.env?.NEXT_PUBLIC_V13_ACTIVE_RUNNER_MIN_SCORE 
  ? Number(process.env.NEXT_PUBLIC_V13_ACTIVE_RUNNER_MIN_SCORE) || 65 
  : 65;

const CATEGORY_LABELS: Record<MoverCategory, { label: string; badge: string }> = {
  COMBINED: { label: '🌟 Master Pulse (All Indices Combined)', badge: 'MASTER' },
  V13_ACTIVE: { label: `⚡ V13 Active Runners (Score ≥${v13MinScoreConfig} ∩ 20-EMA)`, badge: 'V13 CONFLUENCE' },
  ALL: { label: 'All Securities (1,468)', badge: 'ALL' },
  NIFTY_50: { label: 'NIFTY 50 (Bluechips)', badge: 'NIFTY 50' },
  BANK_NIFTY: { label: 'BANK NIFTY (12 Banks)', badge: 'BANK NIFTY' },
  NIFTY_NEXT_50: { label: 'NIFTY NEXT 50', badge: 'NEXT 50' },
  FNO: { label: 'F&O Securities (~181)', badge: 'F&O' },
  ABOVE_20: { label: 'Securities > ₹20 (Safe Floor)', badge: '> ₹20' },
  BELOW_20: { label: 'Securities < ₹20 (Penny)', badge: '< ₹20' },
};

export const LiveMoversPanel: React.FC<LiveMoversPanelProps> = ({ onOpenChart }) => {
  const [data, setData] = useState<LiveMoversResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [selectedCategory, setSelectedCategory] = useState<MoverCategory>('COMBINED');
  const [sortBy, setSortBy] = useState<MoverSortType>('NSE_RANK');
  const [activeFilter, setActiveFilter] = useState<MoverFilterType>('RUNNERS');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [lastRefreshedAt, setLastRefreshedAt] = useState<string>('');
  const effectiveMinScore = data?.min_v13_score != null ? data.min_v13_score : v13MinScoreConfig;

  const fetchLiveMovers = useCallback(async (isManual: boolean = false, categoryOverride?: MoverCategory) => {
    if (isManual) setIsRefreshing(true);
    const startTs = Date.now();
    try {
      const cat = categoryOverride || selectedCategory;
      const forceParam = isManual ? '&force=1' : '';
      const res = await fetch(`/api/v13/live-movers?category=${cat}${forceParam}`);
      if (res.ok) {
        const json: LiveMoversResponse = await res.json();
        setData(json);
        if (json.updated_at) {
          try {
            const d = new Date(json.updated_at);
            if (!isNaN(d.getTime())) {
              setLastRefreshedAt(d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
            } else {
              setLastRefreshedAt(json.updated_at);
            }
          } catch {
            setLastRefreshedAt(json.updated_at);
          }
        }
      }
    } catch (err) {
      console.error('Failed to fetch live movers:', err);
    } finally {
      setLoading(false);
      if (isManual) {
        const elapsed = Date.now() - startTs;
        if (elapsed < 450) {
          await new Promise((r) => setTimeout(r, 450 - elapsed));
        }
        setIsRefreshing(false);
      }
    }
  }, [selectedCategory]);

  // Re-fetch when category changes
  const handleCategoryChange = (cat: MoverCategory) => {
    setSelectedCategory(cat);
    if (cat === 'V13_ACTIVE' && sortBy === 'NSE_RANK') {
      setSortBy('V13_SCORE_DESC');
    }
    setLoading(true);
    fetchLiveMovers(false, cat);
  };

  // Poll every 45s during active use
  useEffect(() => {
    fetchLiveMovers(false);
    const interval = setInterval(() => {
      fetchLiveMovers(false);
    }, 45000);
    return () => clearInterval(interval);
  }, [fetchLiveMovers]);

  // Filter and sort items based on active sub-tab, search query, and sort dropdown
  const displayedItems = useMemo(() => {
    if (!data) return [];
    let list: LiveMoverItem[] = [];

    if (activeFilter === 'ALL') {
      // Merge unique gainers + losers + qualified runners + short runners + exhaustion
      const seen = new Set<string>();
      const combined = [
        ...data.runners, 
        ...(data.short_runners ?? []), 
        ...data.exhaustion, 
        ...data.gainers, 
        ...data.losers
      ];
      list = combined.filter(item => {
        if (seen.has(item.symbol)) return false;
        seen.add(item.symbol);
        return true;
      });
    } else if (activeFilter === 'RUNNERS') {
      list = [...data.runners];
    } else if (activeFilter === 'SHORT_RUNNERS') {
      list = [...(data.short_runners ?? [])];
    } else if (activeFilter === 'EXHAUSTION') {
      list = [...data.exhaustion];
    } else if (activeFilter === 'GAINERS') {
      // Include any registered runner or gainer that is positive
      const seen = new Set<string>();
      const combined = [...data.gainers, ...data.runners.filter(r => r.change_pct > 0)];
      list = combined.filter(item => {
        if (seen.has(item.symbol)) return false;
        seen.add(item.symbol);
        return true;
      });
    } else if (activeFilter === 'LOSERS') {
      const seen = new Set<string>();
      const combined = [...data.losers, ...(data.short_runners ?? []).filter(r => r.change_pct < 0)];
      list = combined.filter(item => {
        if (seen.has(item.symbol)) return false;
        seen.add(item.symbol);
        return true;
      });
    }

    if (selectedCategory === 'V13_ACTIVE') {
      list = list.filter(item => item.v13_score != null && item.v13_score > 0);
    }

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      list = list.filter(item => 
        item.symbol.toLowerCase().includes(q) || 
        item.name.toLowerCase().includes(q) ||
        item.sector.toLowerCase().includes(q)
      );
    }

    // Apply sorting
    list.sort((a, b) => {
      switch (sortBy) {
        case 'NSE_RANK': {
          const rankA = a.nse_rank ?? a.rank ?? 9999;
          const rankB = b.nse_rank ?? b.rank ?? 9999;
          if (rankA !== rankB) return rankA - rankB;
          return Math.abs(b.change_pct) - Math.abs(a.change_pct);
        }
        case 'V13_SCORE_DESC': {
          const scoreA = a.v13_score ?? -1;
          const scoreB = b.v13_score ?? -1;
          if (scoreB !== scoreA) return scoreB - scoreA;
          return Math.abs(b.change_pct) - Math.abs(a.change_pct);
        }
        case 'CHANGE_DESC':
          return b.change_pct - a.change_pct;
        case 'CHANGE_ASC':
          return a.change_pct - b.change_pct;
        case 'REL_VOL_DESC':
          return (b.rel_vol ?? 0) - (a.rel_vol ?? 0);
        case 'TURNOVER_DESC':
          return (b.turnover_cr ?? 0) - (a.turnover_cr ?? 0);
        case 'PRICE_DESC':
          return b.price - a.price;
        case 'PRICE_ASC':
          return a.price - b.price;
        case 'SYMBOL_ASC':
          return a.symbol.localeCompare(b.symbol);
        default:
          return 0;
      }
    });

    return list;
  }, [data, activeFilter, searchQuery, sortBy, selectedCategory]);

  const isV13ActiveCategory = selectedCategory === 'V13_ACTIVE';
  const runnerCount = data?.runners.length ?? 0;
  const shortRunnerCount = data?.short_runners?.length ?? 0;
  const exhaustionCount = isV13ActiveCategory
    ? (data?.exhaustion.filter(e => e.v13_score != null && e.v13_score > 0).length ?? 0)
    : (data?.exhaustion.length ?? 0);
  const gainerCount = isV13ActiveCategory
    ? (data?.gainers.filter(g => g.v13_score != null && g.v13_score > 0).length ?? 0)
    : (data?.gainers.length ?? 0);
  const loserCount = isV13ActiveCategory
    ? (data?.losers.filter(l => l.v13_score != null && l.v13_score > 0).length ?? 0)
    : (data?.losers.length ?? 0);
  const allCount = useMemo(() => {
    if (!data) return 0;
    const seen = new Set<string>();
    const allItems = [
      ...data.runners, 
      ...(data.short_runners ?? []), 
      ...data.exhaustion, 
      ...data.gainers, 
      ...data.losers
    ];
    allItems.forEach(item => {
      if (item?.symbol) {
        if (!isV13ActiveCategory || (item.v13_score != null && item.v13_score > 0)) {
          seen.add(item.symbol);
        }
      }
    });
    return seen.size;
  }, [data, isV13ActiveCategory]);

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Top Controls Bar - Two Structured Clean Rows */}
      <div className="glass-panel rounded-2xl p-4 border border-white/10 space-y-3">
        {/* Row 1: Index / Category Selector + Sort Dropdown + Search Input + Refresh Button */}
        <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3 pb-3 border-b border-white/5">
          {/* Left: Index / Category Selector + Sort Dropdown */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-2 bg-dark-800/95 border border-white/10 rounded-xl px-3 py-1.5 shadow-sm max-w-fit">
              <span className="text-xs font-semibold text-slate-400 whitespace-nowrap">Index:</span>
              <select
                value={selectedCategory}
                onChange={(e) => handleCategoryChange(e.target.value as MoverCategory)}
                className="bg-transparent text-xs font-bold text-indigo-300 focus:outline-none cursor-pointer pr-2"
              >
                <option value="COMBINED" className="bg-dark-850 text-amber-300 font-bold">🌟 Master Pulse (All Indices Combined)</option>
                <option value="V13_ACTIVE" className="bg-dark-850 text-emerald-400 font-bold">
                  ⚡ V13 Active Runners (Score ≥{effectiveMinScore} ∩ 20-EMA)
                </option>
                <option value="ALL" className="bg-dark-850 text-white">All Securities (1,468)</option>
                <option value="NIFTY_50" className="bg-dark-850 text-white">NIFTY 50 (Bluechips)</option>
                <option value="BANK_NIFTY" className="bg-dark-850 text-white">BANK NIFTY (12 Banks)</option>
                <option value="NIFTY_NEXT_50" className="bg-dark-850 text-white">NIFTY NEXT 50</option>
                <option value="FNO" className="bg-dark-850 text-white">F&O Securities (~181)</option>
                <option value="ABOVE_20" className="bg-dark-850 text-white">Securities &gt; ₹20 (Base Floor)</option>
                <option value="BELOW_20" className="bg-dark-850 text-white">Securities &lt; ₹20 (Penny)</option>
              </select>
            </div>

            <div className="flex items-center gap-1.5 bg-dark-800/95 border border-white/10 rounded-xl px-3 py-1.5 shadow-sm max-w-fit">
              <ArrowUpDown className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
              <span className="text-xs font-semibold text-slate-400 whitespace-nowrap">Sort:</span>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as MoverSortType)}
                className="bg-transparent text-xs font-bold text-slate-200 focus:outline-none cursor-pointer pr-1"
              >
                {SORT_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value} className="bg-dark-850 text-white font-medium">
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Right: Search + Refresh + Time */}
          <div className="flex items-center gap-2.5 justify-end">
            <div className="relative w-full sm:w-64">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                placeholder="Search symbol or sector..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-dark-800 border border-white/10 rounded-xl pl-8 pr-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition-colors"
              />
            </div>

            <button
              onClick={() => fetchLiveMovers(true)}
              disabled={isRefreshing}
              className="p-2 rounded-xl bg-dark-800 hover:bg-dark-750 text-slate-300 border border-white/10 transition-colors disabled:opacity-50 shrink-0 flex items-center justify-center"
              title="Refresh Live Movers"
            >
              <RefreshCw className={cn("w-4 h-4", isRefreshing && "animate-spin text-indigo-400")} />
            </button>

            {lastRefreshedAt && (
              <span className="text-[11px] text-slate-400 font-mono hidden md:inline whitespace-nowrap pl-1">
                Updated: {lastRefreshedAt}
              </span>
            )}
          </div>
        </div>

        {/* Row 2: Sub-tabs */}
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            onClick={() => setActiveFilter('RUNNERS')}
            className={cn(
              "px-3 py-1.5 rounded-xl text-xs font-semibold transition-all flex items-center gap-1.5",
              activeFilter === 'RUNNERS'
                ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-lg shadow-emerald-500/10"
                : "bg-dark-800 text-slate-400 hover:text-slate-200 border border-white/5"
            )}
          >
            <Zap className="w-3.5 h-3.5 text-emerald-400" />
            <span>🏆 20-EMA Long</span>
            {runnerCount > 0 && (
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-emerald-500/30 text-emerald-200 font-mono">
                {runnerCount}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveFilter('SHORT_RUNNERS')}
            className={cn(
              "px-3 py-1.5 rounded-xl text-xs font-semibold transition-all flex items-center gap-1.5",
              activeFilter === 'SHORT_RUNNERS'
                ? "bg-rose-500/20 text-rose-300 border border-rose-500/40 shadow-lg shadow-rose-500/10"
                : "bg-dark-800 text-slate-400 hover:text-slate-200 border border-white/5"
            )}
          >
            <TrendingDown className="w-3.5 h-3.5 text-rose-400" />
            <span>📉 20-EMA Short</span>
            {shortRunnerCount > 0 && (
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-rose-500/30 text-rose-200 font-mono">
                {shortRunnerCount}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveFilter('EXHAUSTION')}
            className={cn(
              "px-3 py-1.5 rounded-xl text-xs font-semibold transition-all flex items-center gap-1.5",
              activeFilter === 'EXHAUSTION'
                ? "bg-amber-500/20 text-amber-300 border border-amber-500/40 shadow-lg shadow-amber-500/10"
                : "bg-dark-800 text-slate-400 hover:text-slate-200 border border-white/5"
            )}
          >
            <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
            <span>⚠️ Exhaustion Warnings</span>
            {exhaustionCount > 0 && (
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-amber-500/30 text-amber-200 font-mono">
                {exhaustionCount}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveFilter('GAINERS')}
            className={cn(
              "px-3 py-1.5 rounded-xl text-xs font-semibold transition-all flex items-center gap-1.5",
              activeFilter === 'GAINERS'
                ? "bg-teal-500/20 text-teal-300 border border-teal-500/40 shadow-lg shadow-teal-500/10"
                : "bg-dark-800 text-slate-400 hover:text-slate-200 border border-white/5"
            )}
          >
            <TrendingUp className="w-3.5 h-3.5 text-teal-400" />
            <span>Top Gainers ({gainerCount})</span>
          </button>

          <button
            onClick={() => setActiveFilter('LOSERS')}
            className={cn(
              "px-3 py-1.5 rounded-xl text-xs font-semibold transition-all flex items-center gap-1.5",
              activeFilter === 'LOSERS'
                ? "bg-rose-500/20 text-rose-300 border border-rose-500/40 shadow-lg shadow-rose-500/10"
                : "bg-dark-800 text-slate-400 hover:text-slate-200 border border-white/5"
            )}
          >
            <TrendingDown className="w-3.5 h-3.5 text-rose-400" />
            <span>Top Losers ({loserCount})</span>
          </button>

          <button
            onClick={() => setActiveFilter('ALL')}
            className={cn(
              "px-3 py-1.5 rounded-xl text-xs font-semibold transition-all",
              activeFilter === 'ALL'
                ? "bg-indigo-600/30 text-indigo-300 border border-indigo-500/40"
                : "bg-dark-800 text-slate-400 hover:text-slate-200 border border-white/5"
            )}
          >
            All Live Movers ({allCount})
          </button>
        </div>
      </div>

      {/* Grid of Cards */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
            <div key={i} className="glass-panel rounded-xl p-4 h-64 animate-pulse bg-dark-850/40 border border-white/5" />
          ))}
        </div>
      ) : displayedItems.length === 0 ? (
        <div className="glass-panel rounded-2xl p-12 text-center border border-white/10 space-y-3">
          <Activity className="w-8 h-8 text-slate-500 mx-auto" />
          <h4 className="text-sm font-semibold text-slate-300">
            {selectedCategory === 'V13_ACTIVE'
              ? (activeFilter === 'SHORT_RUNNERS'
                  ? `No V13 Bear Movers (Score ≥${effectiveMinScore}) Active`
                  : `No V13 Active Movers (Score ≥${effectiveMinScore}) Active`)
              : activeFilter === 'RUNNERS' 
              ? 'No 20-EMA High-Tight Long Runners Active' 
              : activeFilter === 'SHORT_RUNNERS'
              ? 'No 20-EMA Bear Flag Short Breakdowns Active'
              : 'No Movers Found'}
          </h4>
          <p className="text-xs text-slate-500 max-w-md mx-auto">
            {selectedCategory === 'V13_ACTIVE'
              ? `Stocks must pass both V13 status (Score ≥${effectiveMinScore}) and 20-EMA flag alignment to appear here. Other V13 scrips are visible under Top Gainers/Losers.`
              : activeFilter === 'RUNNERS' 
              ? 'Top gainers are currently extended from 20-EMA or in consolidation. Check back as high-tight flags form.' 
              : activeFilter === 'SHORT_RUNNERS'
              ? 'Top losers are currently extended or consolidating. Check back as bear flag breakdown patterns develop.'
              : 'Try selecting "All Live Movers" or clearing your search filter.'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {displayedItems.map((mover) => (
            <LiveMoverCard key={mover.symbol} mover={mover} onOpenChart={onOpenChart} />
          ))}
        </div>
      )}
    </div>
  );
};

interface LiveMoverCardProps {
  mover: LiveMoverItem;
  onOpenChart: (stock: V13ChartTarget) => void;
}

const LiveMoverCard: React.FC<LiveMoverCardProps> = ({ mover, onOpenChart }) => {
  const isRunner = mover.archetype === 'RUNNER';
  const isShortRunner = mover.archetype === 'SHORT_RUNNER';
  const isExhaustion = mover.archetype === 'EXHAUSTION_WARNING';
  const isPenny = mover.price < 20.0 && (mover.turnover_cr < 50.0);
  const isBullish = mover.change_pct >= 0;
  const isConsolidation = !isRunner && !isShortRunner && !isExhaustion;
  const tp = mover.trade_plan;

  // Chart Target Adapter with populated trade_plan for visual ChartDrawer lines
  const chartTarget: V13ChartTarget = {
    symbol: mover.symbol,
    name: mover.name,
    sector: mover.sector,
    status: (isRunner || isShortRunner) ? 'SIGNAL' : 'NO_SETUP',
    signals: tp ? [
      {
        signal_id: `mover-${mover.symbol}`,
        symbol: mover.symbol,
        name: mover.name,
        sector: mover.sector,
        direction: isShortRunner ? 'BEARISH' : (isBullish ? 'BULLISH' : 'BEARISH'),
        setup: isShortRunner 
          ? '20_EMA_BEAR_FLAG_BREAKDOWN' 
          : isRunner 
          ? '20_EMA_HIGH_TIGHT_FLAG' 
          : (isBullish ? '20_EMA_CONSOLIDATION' : '20_EMA_BEAR_CONSOLIDATION'),
        setup_type: isShortRunner 
          ? '20_EMA_BEAR_FLAG_BREAKDOWN' 
          : isRunner 
          ? '20_EMA_HIGH_TIGHT_FLAG' 
          : (isBullish ? '20_EMA_CONSOLIDATION' : '20_EMA_BEAR_CONSOLIDATION'),
        action: (isShortRunner || (!isBullish && isConsolidation)) ? 'SELL' : 'BUY',
        grade: 'GRADE_A',
        score: (isRunner || isShortRunner) ? 85 : 65,
        score_classification: (isRunner || isShortRunner) ? 'HIGH CONFIDENCE' : 'MONITORING',
        price: mover.price,
        risk: {
          entry: tp.entry,
          stop_loss: tp.stop_loss,
          target_1: tp.target_1,
          target_2: tp.target_2,
          risk_amount: tp.risk_amount,
          risk_reward_t1: tp.risk_reward_t1,
          risk_reward_t2: tp.risk_reward_t2,
        },
        indicators: {
          ema20: mover.ema20,
          rsi14: mover.rsi14 ?? 50,
          rel_vol: mover.rel_vol,
          vwap: mover.vwap,
          atr14: mover.atr14,
          true_velocity: 0,
          breakout_distance_atr: mover.dist_to_ema20 ?? (mover.atr14 && mover.atr14 > 0 && mover.ema20 ? Number((Math.abs(mover.price - mover.ema20) / mover.atr14).toFixed(2)) : 0.4),
          breakout_candle_range: mover.bar_range ?? (mover.atr14 ? Number((mover.atr14 * 0.75).toFixed(2)) : null),
        },
        confirmation: {
          is_valid: true,
          reasons: mover.reasons,
        },
        market: {},
        is_nifty500: mover.is_nifty500,
      } as any
    ] : [],
    snapshot: {
      price: mover.price,
      ema20: mover.ema20,
      rsi14: mover.rsi14 ?? 50,
      rel_vol: mover.rel_vol,
      vwap: mover.vwap,
      atr14: mover.atr14,
      true_velocity: 0,
      latest_session_change_pct: mover.change_pct,
    },
    is_nifty500: mover.is_nifty500,
  };

  // Live P&L tracker calculations
  let t1Progress = 0;
  let trackerStatus = '';
  if (tp && mover.price > 0) {
    if (isShortRunner || (!isBullish && isConsolidation)) {
      // In short trade: entry > target_1, stop_loss > entry
      const t1Dist = tp.entry - tp.target_1;
      if (mover.price <= tp.target_1) {
        t1Progress = 100;
        trackerStatus = `🚀 Short T1 Hit!`;
      } else if (mover.price <= tp.entry) {
        t1Progress = t1Dist > 0 ? Math.min(100, Math.max(0, ((tp.entry - mover.price) / t1Dist) * 100)) : 0;
        trackerStatus = `🎯 Short T1: ${t1Progress.toFixed(0)}% reached`;
      } else if (mover.price <= tp.stop_loss) {
        t1Progress = 0;
        trackerStatus = isConsolidation ? `🔄 Holding 15m Range` : `🔄 In 20-EMA Bear Zone`;
      } else {
        t1Progress = 0;
        trackerStatus = `⚠️ Above SL`;
      }
    } else {
      const t1Dist = tp.target_1 - tp.entry;
      if (mover.price >= tp.target_1) {
        t1Progress = 100;
        trackerStatus = `🚀 T1 Hit!`;
      } else if (mover.price >= tp.entry) {
        t1Progress = t1Dist > 0 ? Math.min(100, Math.max(0, ((mover.price - tp.entry) / t1Dist) * 100)) : 0;
        trackerStatus = `🎯 T1: ${t1Progress.toFixed(0)}% reached`;
      } else if (mover.price >= tp.stop_loss) {
        t1Progress = 0;
        trackerStatus = isConsolidation ? `🔄 Holding 15m Range` : `🔄 In 20-EMA Flag Zone`;
      } else {
        t1Progress = 0;
        trackerStatus = `⚠️ Below SL`;
      }
    }
  }

  // Diagnostic Inspector calculations
  const [isFlipped, setIsFlipped] = useState(false);
  const turnoverPass = mover.turnover_cr >= 25.0 || Boolean(mover.is_v13_active);
  const relVolPass = mover.rel_vol >= 1.50;
  const distAtr = mover.dist_to_ema20 !== undefined 
    ? Math.abs(mover.dist_to_ema20) 
    : (mover.atr14 && mover.atr14 > 0 && mover.ema20 ? Math.abs(mover.price - mover.ema20) / mover.atr14 : 0.5);
  const emaDistPass = distAtr <= 1.50;
  const vwapPass = isBullish 
    ? (mover.vwap ? mover.price >= mover.vwap : true) 
    : (mover.vwap ? mover.price <= mover.vwap : true);
  const emaPass = isBullish
    ? (mover.ema20 ? mover.price >= mover.ema20 : true)
    : (mover.ema20 ? mover.price <= mover.ema20 : true);

  const diagnosticHinglishReason = useMemo(() => {
    if (mover.price < 20.0 && mover.turnover_cr < 50.0) {
      return `Stock price (₹${mover.price.toFixed(2)}) ₹20 ke base floor guard se kam hai aur turnover (₹${mover.turnover_cr} Cr) ₹50 Cr institutional limit se kam hai.`;
    }
    if (isExhaustion) {
      return "Yeh stock subah Bar 1 me hi apna intraday move exhaust kar chuka hai (Blow-off candle). Peak par buy karne se bachein.";
    }
    if (!turnoverPass) {
      return `Session turnover (₹${mover.turnover_cr} Cr) institutional limit (₹25 Cr) se kam hai. Low liquidity me order slippage ka risk rehta hai.`;
    }
    if (isRunner || isShortRunner) {
      if (mover.is_v13_active && mover.v13_score) {
        return isRunner 
          ? `⚡ V13 Dual-Confluence Active! Yeh stock V13 screener me bhi high score (${mover.v13_score}) ke saath active setup trigger kar raha hai aur 20-EMA high-tight flag par perfect holding hai!`
          : `⚡ V13 Dual-Confluence Bear Breakdown! Yeh stock V13 screener me score (${mover.v13_score}) ke saath active hai aur 20-EMA bear flag breakdown de raha hai!`;
      }
      return isRunner 
        ? "Textbook High-Tight Flag setup! Stock VWAP aur 20-EMA ke upar tight flag bana raha hai with heavy volume."
        : "Textbook Bear Breakdown setup! Stock VWAP aur 20-EMA resistance ke niche fresh breakdown de raha hai.";
    }
    if (mover.is_v13_active) {
      return `⚡ V13 Active Setup (Score ${mover.v13_score ?? 72})! Yeh stock V13 screener me active hai (Turnover floor exempt). 20-EMA execution trade plan tabhi trigger hoga jab price 20-EMA high-tight flag range (≤1.5 ATR) me aayega.`;
    }
    if (isBullish && !vwapPass) {
      return `Stock overall gainer zaroor hai par abhi intraday VWAP (${mover.vwap ? formatINR(mover.vwap) : 'resistance'}) ke neeche pullback me hai. Breakout entry VWAP reclaim hone par hi active hogi.`;
    }
    if (!isBullish && !vwapPass) {
      return `Stock overall loser hai par abhi intraday VWAP (${mover.vwap ? formatINR(mover.vwap) : 'support'}) ke upar bounce me hai. Short entry VWAP break hone par hi active hogi.`;
    }
    if (isBullish && !emaPass) {
      return `Price 20-EMA trendline ke neeche trade kar raha hai. Fresh bullish trade ke liye 20-EMA reclaim zaroori hai.`;
    }
    if (!emaDistPass) {
      const slDistPct = mover.ema20 ? ((Math.abs(mover.price - mover.ema20) / mover.price) * 100).toFixed(1) : '2.0';
      return isBullish
        ? `Stock me buyers active hain, lekin price 20-EMA line se ${distAtr.toFixed(1)}x ATR door hai. Abhi buy karne par Stop-Loss (~${slDistPct}%) bada hoga. Retest ka wait karein.`
        : `Stock me selling pressure hai, lekin price 20-EMA resistance se ${distAtr.toFixed(1)}x ATR door hai. Pullback ka wait karein.`;
    }
    if (!relVolPass) {
      return `Stock me structure theek hai lekin volume normal din se kam (${mover.rel_vol}x) hai. Big players ke confirmation ka wait hai.`;
    }
    return "Stock 15-minute range me consolidate kar raha hai. Breakout ya pullback level trigger hone par trade execute karein.";
  }, [mover.price, isExhaustion, turnoverPass, isRunner, isShortRunner, vwapPass, emaPass, emaDistPass, distAtr, isBullish, mover.turnover_cr, mover.ema20, mover.vwap, relVolPass, mover.rel_vol, mover.is_v13_active, mover.v13_score]);

  const traderRecommendation = useMemo(() => {
    if (mover.price < 20.0 && mover.turnover_cr < 50.0) {
      return "Notice: ₹20 base floor & ₹50 Cr turnover ke niche liquidity risk.";
    }
    if (isRunner || isShortRunner) {
      if (mover.is_v13_active && mover.v13_score) {
        return `High-Conviction: V13 Score ${mover.v13_score} + 20-EMA Flag Dual Confluence.`;
      }
      return "Actionable: Flag Entry aur tight 20-EMA SL ke sath trade plan ready hai.";
    }
    if (mover.is_v13_active) {
      return `V13 Active: 20-EMA High-Tight Flag (${mover.ema20 ? formatINR(mover.ema20) : 'Support'}) alignment ka wait karein.`;
    }
    if (isBullish && (!vwapPass || !emaPass)) {
      return `Wait: VWAP/EMA Reclaim (${tp?.entry ? formatINR(tp.entry) : 'Trigger'}) cross hone ka wait karein.`;
    }
    if (!isBullish && (!vwapPass || !emaPass)) {
      return `Wait: VWAP/EMA Breakdown (${tp?.entry ? formatINR(tp.entry) : 'Floor'}) break hone ka wait karein.`;
    }
    if (!emaDistPass) {
      return `Wait: 20-EMA (${mover.ema20 ? formatINR(mover.ema20) : 'Support'}) ke paas pullback aane dein.`;
    }
    if (!turnoverPass) {
      return "Caution: ₹25 Cr turnover cross hone tak trade skip karein.";
    }
    return "Holding: 15m Consolidation range breakout ka wait karein.";
  }, [mover.price, isRunner, isShortRunner, isBullish, vwapPass, emaPass, tp?.entry, emaDistPass, turnoverPass, mover.ema20]);

  return (
    <div
      className={cn(
        "glass-panel rounded-xl p-4 transition-all duration-300 relative overflow-hidden flex flex-col justify-between group hover:border-white/20 select-none min-h-[390px]",
        isRunner && "border-emerald-500/50 glow-bullish-card bg-emerald-950/15 ring-1 ring-emerald-500/20",
        isShortRunner && "border-rose-500/50 glow-bearish-card bg-rose-950/15 ring-1 ring-rose-500/20",
        isExhaustion && "border-amber-500/40 bg-amber-950/10",
        !isRunner && !isShortRunner && !isExhaustion && "border-white/5 hover:bg-dark-800/80"
      )}
    >
      {isFlipped ? (
        /* BACK FACE: Diagnostic Inspector View */
        <div className="flex flex-col justify-between h-full space-y-2.5 animate-in fade-in zoom-in-95 duration-200">
          <div>
            {/* Back Header */}
            <div className="flex items-center justify-between border-b border-white/10 pb-2 mb-2">
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="p-1 rounded bg-indigo-500/20 text-indigo-400">
                  <Search className="w-3.5 h-3.5" />
                </span>
                <div>
                  <h4 className="text-xs font-bold text-white flex items-center gap-1">
                    <span>Diagnostic Inspector</span>
                    <span className="text-[9.5px] px-1.5 py-0.2 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 font-mono font-bold">
                      {mover.symbol}
                    </span>
                  </h4>
                  <p className="text-[9px] text-slate-400">Algorithmic Setup Health Audit</p>
                </div>
              </div>

              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setIsFlipped(false);
                }}
                className="text-[9.5px] px-2 py-1 rounded bg-dark-750 hover:bg-dark-700 text-indigo-300 border border-indigo-500/30 flex items-center gap-1 transition-all shadow-sm active:scale-95 cursor-pointer"
              >
                <RotateCcw className="w-2.5 h-2.5 text-indigo-400" />
                <span></span>
              </button>
            </div>

            {/* 4-Pillar Live Scorecard */}
            <div className="space-y-1.5 text-[10px] mb-2.5">
              {/* Pillar 1: Turnover */}
              <div className="flex items-center justify-between p-1.5 rounded-lg bg-dark-800/80 border border-white/5">
                <div className="flex items-center gap-1.5 text-slate-300">
                  <Droplets className="w-3 h-3 text-cyan-400 shrink-0" />
                  <span>Turnover Floor (₹25 Cr min):</span>
                </div>
                <div className="flex items-center gap-1 font-mono">
                  <span className={turnoverPass ? "text-emerald-300 font-bold" : "text-rose-400 font-bold"}>
                    ₹{mover.turnover_cr} Cr
                  </span>
                  <span className={cn(
                    "text-[8.5px] px-1 py-0.2 rounded font-sans font-semibold",
                    mover.turnover_cr >= 25.0 
                      ? "bg-emerald-500/20 text-emerald-300" 
                      : mover.is_v13_active 
                      ? "bg-amber-500/20 text-amber-300" 
                      : "bg-rose-500/20 text-rose-300"
                  )}>
                    {mover.turnover_cr >= 25.0 ? "PASS ✅" : mover.is_v13_active ? "V13 EXEMPT ⚡" : "LOW ❌"}
                  </span>
                </div>
              </div>

              {/* Pillar 2: 20-EMA Distance */}
              <div className="flex items-center justify-between p-1.5 rounded-lg bg-dark-800/80 border border-white/5">
                <div className="flex items-center gap-1.5 text-slate-300">
                  <Ruler className="w-3 h-3 text-indigo-400 shrink-0" />
                  <span>20-EMA Distance (≤1.5 ATR):</span>
                </div>
                <div className="flex items-center gap-1 font-mono">
                  <span className={emaDistPass ? "text-emerald-300 font-bold" : "text-amber-300 font-bold"}>
                    {distAtr.toFixed(2)}x ATR
                  </span>
                  <span className={cn(
                    "text-[8.5px] px-1 py-0.2 rounded font-sans font-semibold",
                    emaDistPass ? "bg-emerald-500/20 text-emerald-300" : "bg-amber-500/20 text-amber-300"
                  )}>
                    {emaDistPass ? "TIGHT FLAG ✅" : "EXTENDED ⏳"}
                  </span>
                </div>
              </div>

              {/* Pillar 3: VWAP Institutional Alignment */}
              <div className="flex items-center justify-between p-1.5 rounded-lg bg-dark-800/80 border border-white/5">
                <div className="flex items-center gap-1.5 text-slate-300">
                  <ShieldCheck className="w-3 h-3 text-emerald-400 shrink-0" />
                  <span>VWAP Alignment:</span>
                </div>
                <div className="flex items-center gap-1 font-mono">
                  <span className={vwapPass ? "text-emerald-300 font-bold" : "text-rose-400 font-bold"}>
                    {formatINR(mover.price)} vs {formatINR(mover.vwap || mover.price)}
                  </span>
                  <span className={cn(
                    "text-[8.5px] px-1 py-0.2 rounded font-sans font-semibold",
                    vwapPass ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300"
                  )}>
                    {vwapPass ? "HOLDING ✅" : "BREACHED ❌"}
                  </span>
                </div>
              </div>

              {/* Pillar 4: Relative Volume Surge */}
              <div className="flex items-center justify-between p-1.5 rounded-lg bg-dark-800/80 border border-white/5">
                <div className="flex items-center gap-1.5 text-slate-300">
                  <Flame className="w-3 h-3 text-amber-400 shrink-0" />
                  <span>Relative Volume (≥1.50x):</span>
                </div>
                <div className="flex items-center gap-1 font-mono">
                  <span className={relVolPass ? "text-emerald-300 font-bold" : "text-slate-400 font-bold"}>
                    {mover.rel_vol}x
                  </span>
                  <span className={cn(
                    "text-[8.5px] px-1 py-0.2 rounded font-sans font-semibold",
                    relVolPass ? "bg-emerald-500/20 text-emerald-300" : "bg-dark-750 text-slate-400"
                  )}>
                    {relVolPass ? "SURGE ✅" : "MODERATE ⏳"}
                  </span>
                </div>
              </div>

              {/* Pillar 5: V13 Institutional Confluence */}
              {mover.v13_score != null && (
                <div className="flex items-center justify-between p-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20">
                  <div className="flex items-center gap-1.5 text-amber-200">
                    <Zap className="w-3 h-3 text-amber-400 shrink-0" />
                    <span>V13 Dual Confluence:</span>
                  </div>
                  <div className="flex items-center gap-1 font-mono">
                    <span className="text-amber-300 font-bold">
                      Score {mover.v13_score}
                    </span>
                    <span className={cn(
                      "text-[8.5px] px-1 py-0.2 rounded font-sans font-semibold",
                      mover.is_v13_active ? "bg-emerald-500/20 text-emerald-300" : "bg-dark-750 text-slate-400"
                    )}>
                      {mover.is_v13_active ? "ACTIVE QUALIFIED ✅" : "OBSERVED ⏳"}
                    </span>
                  </div>
                </div>
              )}
            </div>

            {/* Dynamic Hinglish Analysis Box */}
            <div className="p-2.5 rounded-xl bg-indigo-950/40 border border-indigo-500/30 space-y-1 mb-2">
              <div className="text-[10px] font-bold text-indigo-300 flex items-center gap-1">
                <Info className="w-3 h-3 text-indigo-400 shrink-0" />
                <span>Hinglish Setup Diagnosis:</span>
              </div>
              <p className="text-[9.5px] text-slate-300 leading-relaxed">
                {diagnosticHinglishReason}
              </p>
            </div>
          </div>

          {/* Action Recommendation & Flip Back */}
          <div className="pt-2 border-t border-white/10 flex items-center justify-between gap-2">
            <div className="text-[9px] text-amber-300 font-medium truncate max-w-[180px]">
              💡 <span className="text-slate-300">{traderRecommendation}</span>
            </div>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setIsFlipped(false);
              }}
              className="text-[9.5px] px-2.5 py-1 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold shrink-0 transition-all shadow-sm cursor-pointer"
            >
              BACK↩️
            </button>
          </div>
        </div>
      ) : (
        /* FRONT FACE: Standard Mover & Trade Plan View */
        <>
          <div>
        {/* Line 1: Symbol + NSE Rank Badge (Left) & Archetype Badge (Right) */}
        <div className="flex items-center justify-between gap-1.5 mb-1.5">
          <div className="flex items-center gap-1.5 min-w-0 flex-wrap">
            <h3 className="font-bold text-base sm:text-lg text-white tracking-tight group-hover:text-indigo-400 transition-colors whitespace-nowrap">
              {mover.symbol}
            </h3>
            <span className="text-[9.5px] px-1.5 py-0.2 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 font-mono font-bold whitespace-nowrap" title="Official NSE Live Rank">
              #{mover.nse_rank ?? mover.rank}
            </span>
            {mover.v13_score != null && mover.v13_score > 0 && (
              <span 
                className="text-[9.5px] px-1.5 py-0.2 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40 font-mono font-bold whitespace-nowrap flex items-center gap-0.5 shadow-sm"
                title={`V13 Algorithmic Screener Score: ${mover.v13_score}${mover.is_v13_active ? ' (Active Qualified)' : ''}`}
              >
                ⚡ V13 {mover.v13_score}
              </span>
            )}
          </div>

          {/* Archetype Badge */}
          <div className="shrink-0">
            {mover.is_v13_active && (isRunner || isShortRunner) ? (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9.5px] font-bold bg-amber-500/25 text-amber-300 border border-amber-400/50 shadow-sm animate-pulse whitespace-nowrap">
                🏆 DUAL CONFLUENCE
              </span>
            ) : isRunner ? (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9.5px] font-bold bg-emerald-500/25 text-emerald-300 border border-emerald-400/50 shadow-sm animate-pulse whitespace-nowrap">
                🏆 20-EMA Long
              </span>
            ) : isShortRunner ? (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9.5px] font-bold bg-rose-500/25 text-rose-300 border border-rose-400/50 shadow-sm animate-pulse whitespace-nowrap">
                📉 20-EMA Short
              </span>
            ) : isExhaustion ? (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9.5px] font-bold bg-amber-500/25 text-amber-300 border border-amber-500/40 whitespace-nowrap">
                ⚠️ EXHAUSTION
              </span>
            ) : isPenny ? (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9.5px] font-bold bg-purple-500/20 text-purple-300 border border-purple-500/30 whitespace-nowrap">
                🏷️ &lt; ₹20
              </span>
            ) : mover.is_v13_active ? (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9.5px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30 whitespace-nowrap">
                ⚡ V13 Active
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9.5px] font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 whitespace-nowrap">
                🔄 15m Retest
              </span>
            )}
          </div>
        </div>

        {/* Line 2: Full Company Name (Uncluttered) */}
        <p className="text-xs text-slate-300 font-medium truncate mb-2" title={mover.name}>
          {mover.name}
        </p>

        {/* Line 3: Sector & Index Tags Strip */}
        <div className="flex flex-wrap items-center gap-1.5 mb-2">
          <span className="text-[10px] px-2 py-0.5 bg-dark-750 text-slate-300 rounded border border-white/10 font-medium">
            {mover.sector}
          </span>
          {mover.index_tags && mover.index_tags.length > 0 && (
            <span className="text-[9px] px-1.5 py-0.5 bg-indigo-500/20 text-indigo-300 font-semibold rounded border border-indigo-500/30">
              {mover.index_tags.join(' • ')}
            </span>
          )}
        </div>

        {/* Price & Change Banner */}
        <div className="flex items-baseline justify-between py-2 border-y border-white/5 my-2">
          <div>
            <div className="text-2xl font-black font-mono tracking-tight text-white">
              {formatINR(mover.price)}
            </div>
            <div className="text-[10px] text-slate-400 font-mono">
              Turnover: ₹{mover.turnover_cr} Cr
            </div>
          </div>

          <div className="text-right">
            <div className={cn(
              "text-sm font-black font-mono px-2 py-0.5 rounded inline-flex items-center gap-1",
              isBullish 
                ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30" 
                : "bg-rose-500/20 text-rose-300 border border-rose-500/30"
            )}>
              {isBullish ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
              <span>{isBullish ? `+${mover.change_pct}%` : `${mover.change_pct}%`}</span>
            </div>
            <div className="text-[9.5px] text-slate-400 font-mono mt-0.5">
              RelVol: <span className="text-amber-300 font-bold">{mover.rel_vol}x</span>
            </div>
          </div>
        </div>

        {/* Indicators Row */}
        <div className="grid grid-cols-3 gap-1.5 mb-3 text-center text-[10px] font-mono">
          <div className="p-1 rounded bg-dark-800 border border-white/5">
            <span className="text-slate-500 block text-[8.5px]">20 EMA</span>
            <span className="text-indigo-300 font-bold">{mover.ema20 ? formatINR(mover.ema20) : '—'}</span>
          </div>
          <div className="p-1 rounded bg-dark-800 border border-white/5">
            <span className="text-slate-500 block text-[8.5px]">VWAP</span>
            <span className="text-cyan-300 font-bold">{mover.vwap ? formatINR(mover.vwap) : '—'}</span>
          </div>
          <div className="p-1 rounded bg-dark-800 border border-white/5">
            <span className="text-slate-500 block text-[8.5px]">RSI(14)</span>
            <span className={cn(
              "font-bold",
              (mover.rsi14 ?? 50) >= 75
                ? "text-amber-400"
                : (mover.rsi14 ?? 50) >= 60
                ? "text-emerald-400"
                : (mover.rsi14 ?? 50) <= 40
                ? "text-rose-400"
                : "text-indigo-300"
            )}>
              {mover.rsi14 != null ? Number(mover.rsi14).toFixed(1) : '50.0'}
            </span>
          </div>
        </div>

        {/* Middle Section: Execution Plan OR Warning Box */}
        {tp && !isExhaustion ? (
          <div className={cn(
            "rounded-xl p-3 border mb-3 space-y-2 shadow-sm bg-dark-850/90",
            isShortRunner 
              ? "border-rose-500/40" 
              : isRunner 
              ? "border-emerald-500/40" 
              : mover.is_v13_active
              ? "border-amber-500/30"
              : "border-indigo-500/30"
          )}>
            <div className="flex items-center justify-between text-[11px] font-semibold border-b border-white/5 pb-1.5">
              <span className={cn(
                "flex items-center gap-1.5 min-w-0", 
                isShortRunner 
                  ? "text-rose-300" 
                  : isRunner 
                  ? "text-emerald-300" 
                  : mover.is_v13_active
                  ? "text-amber-300"
                  : "text-indigo-300"
              )}>
                {isShortRunner ? (
                  <>
                    <TrendingDown className="w-3.5 h-3.5 text-rose-400 animate-pulse shrink-0" />
                    <span className="whitespace-nowrap">{mover.is_v13_active ? '🏆 Dual Confluence Bear' : '20-EMA Bear'}</span>
                  </>
                ) : isRunner ? (
                  <>
                    <Zap className="w-3.5 h-3.5 text-amber-400 animate-pulse shrink-0" />
                    <span className="whitespace-nowrap">{mover.is_v13_active ? '🏆 Dual Confluence Flag' : '20-EMA High-Tight Plan'}</span>
                  </>
                ) : (
                  <>
                    <Clock className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
                    <span className="whitespace-nowrap">{mover.is_v13_active ? '⚡ V13 Active Plan' : '15m Consolidation'}</span>
                  </>
                )}
              </span>

              {isConsolidation ? (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setIsFlipped(true);
                  }}
                  className="text-[9px] px-1.5 py-0.5 rounded bg-indigo-500/20 hover:bg-indigo-500/35 text-indigo-300 border border-indigo-500/30 font-mono font-medium whitespace-nowrap shrink-0 flex items-center gap-1 transition-all hover:scale-105 active:scale-95 cursor-pointer"
                  title="Click to view Diagnostic Health Audit (Kyu?)"
                >
                  <span>Monitoring ⏳</span>
                  <Info className="w-2.5 h-2.5 text-indigo-400" />
                </button>
              ) : (
                <span className={cn(
                  "text-[10px] font-mono shrink-0 whitespace-nowrap", 
                  isShortRunner ? "text-rose-400" : "text-emerald-400"
                )}>
                  Risk: {formatINR(tp.risk_amount)}/sh
                </span>
              )}
            </div>

            <div className="grid grid-cols-2 gap-1.5 text-xs font-mono">
              <div className="p-1.5 rounded-lg bg-dark-750/70 border border-cyan-500/20">
                <span className="text-[9.5px] text-cyan-400 block font-sans">
                  {isShortRunner 
                    ? 'Breakdown Entry' 
                    : isRunner 
                    ? 'Flag Entry' 
                    : isBullish 
                    ? (!vwapPass || !emaPass ? 'Reclaim Trigger ⚡' : 'Breakout Entry')
                    : (!vwapPass || !emaPass ? 'Breakdown Floor ⚡' : 'Short Entry')}
                </span>
                <span className="font-bold text-cyan-200">{formatINR(tp.entry)}</span>
              </div>
              <div className="p-1.5 rounded-lg bg-dark-750/70 border border-rose-500/20">
                <div className="flex items-center justify-between text-[9.5px] font-sans">
                  <span className="text-rose-400">
                    {isShortRunner || (!isBullish && isConsolidation) ? 'SL↗' : 'SL'}
                  </span>
                  <span className="text-[8.5px] text-rose-300/80 font-mono" title="Max Risk Per Share">
                    Risk: ₹{tp.risk_amount}
                  </span>
                </div>
                <span className="font-bold text-rose-200">{formatINR(tp.stop_loss)}</span>
              </div>
              <div className={cn(
                "p-1.5 rounded-lg bg-dark-750/70 border",
                (isShortRunner || (!isBullish && isConsolidation)) ? "border-rose-500/20" : isRunner ? "border-emerald-500/20" : "border-indigo-500/20"
              )}>
                <div className="flex items-center justify-between text-[9.5px] font-sans">
                  <span className={(isShortRunner || (!isBullish && isConsolidation)) ? "text-rose-400" : isRunner ? "text-emerald-400" : "text-indigo-300"}>Target 1</span>
                  <span className={cn("text-[8.5px]", (isShortRunner || (!isBullish && isConsolidation)) ? "text-rose-300" : isRunner ? "text-emerald-300" : "text-indigo-300")}>{tp.risk_reward_t1}</span>
                </div>
                <span className={cn("font-bold", (isShortRunner || (!isBullish && isConsolidation)) ? "text-rose-200" : isRunner ? "text-emerald-200" : "text-indigo-200")}>{formatINR(tp.target_1)}</span>
              </div>
              <div className={cn(
                "p-1.5 rounded-lg bg-dark-750/70 border",
                (isShortRunner || (!isBullish && isConsolidation)) ? "border-rose-500/20" : isRunner ? "border-emerald-500/20" : "border-indigo-500/20"
              )}>
                <div className="flex items-center justify-between text-[9.5px] font-sans">
                  <span className={(isShortRunner || (!isBullish && isConsolidation)) ? "text-rose-400" : isRunner ? "text-emerald-400" : "text-indigo-300"}>Target 2</span>
                  <span className={cn("text-[8.5px]", (isShortRunner || (!isBullish && isConsolidation)) ? "text-rose-300" : isRunner ? "text-emerald-300" : "text-indigo-300")}>{tp.risk_reward_t2}</span>
                </div>
                <span className={cn("font-bold", (isShortRunner || (!isBullish && isConsolidation)) ? "text-rose-200" : isRunner ? "text-emerald-200" : "text-indigo-200")}>{formatINR(tp.target_2)}</span>
              </div>
            </div>

            {/* Target Tracker */}
            <div className="pt-1.5 border-t border-white/5 space-y-1">
              <div className="flex items-center justify-between text-[9.5px]">
                <span className="text-slate-400 font-sans flex items-center gap-1">
                  <Activity className="w-2.5 h-2.5 text-indigo-400" />
                  Live Tracker:
                </span>
                <span className={cn(
                  "font-mono font-bold", 
                  (isShortRunner || (!isBullish && isConsolidation)) 
                    ? "text-rose-300" 
                    : isRunner 
                    ? "text-emerald-300" 
                    : "text-indigo-300"
                )}>
                  {trackerStatus}
                </span>
              </div>
              <div className="w-full h-1 bg-dark-750 rounded-full overflow-hidden">
                <div 
                  className={cn(
                    "h-full rounded-full transition-all duration-500",
                    (isShortRunner || (!isBullish && isConsolidation))
                      ? "bg-gradient-to-r from-rose-500 to-amber-500" 
                      : isRunner
                      ? "bg-gradient-to-r from-emerald-500 to-teal-400"
                      : "bg-gradient-to-r from-indigo-500 to-cyan-400"
                  )} 
                  style={{ width: `${Math.max(5, t1Progress)}%` }}
                />
              </div>
            </div>
          </div>
        ) : isExhaustion ? (
          <div className="rounded-xl p-3 border border-amber-500/30 bg-amber-950/20 mb-3 space-y-1.5 text-center">
            <div className="flex items-center justify-center gap-1.5 text-xs text-amber-300 font-bold">
              <ShieldAlert className="w-4 h-4 text-amber-400 animate-pulse" />
              <span>Blow-off Exhaustion Warning</span>
            </div>
            <p className="text-[10px] text-amber-200/80 leading-relaxed">
              {mover.warning ?? 'Move exceeded safe intraday bounds. Avoid buying at peak.'}
            </p>
            <div className="text-[9px] text-slate-400 font-sans pt-1 border-t border-amber-500/20">
              💡 Advisory: Wait for 20-EMA / VWAP mean reversion before entry.
            </div>
          </div>
        ) : mover.is_v13_active ? (
          <div className="rounded-xl p-3 border border-amber-500/30 bg-amber-950/20 mb-3 space-y-2">
            <div className="flex items-center justify-between text-xs border-b border-white/5 pb-1.5">
              <span className="flex items-center gap-1.5 text-amber-300 font-bold">
                <Zap className="w-3.5 h-3.5 text-amber-400" />
                <span>V13 Active Setup ({mover.v13_score ? `Score ${mover.v13_score}` : 'Active'})</span>
              </span>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setIsFlipped(true);
                }}
                className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/20 hover:bg-amber-500/35 text-amber-300 border border-amber-500/30 font-mono font-medium whitespace-nowrap shrink-0 flex items-center gap-1 transition-all hover:scale-105 active:scale-95 cursor-pointer"
                title="Click to view Diagnostic Health Audit"
              >
                <span>20-EMA Pending ⏳</span>
                <Info className="w-2.5 h-2.5 text-amber-400" />
              </button>
            </div>
            <div className="grid grid-cols-2 gap-1.5 text-[9.5px] font-mono text-center">
              <div className="p-1.5 rounded bg-dark-800/80 border border-white/5 text-slate-300">
                <span className="text-[8.5px] text-slate-400 block font-sans">20-EMA Trend</span>
                <span className="font-bold text-indigo-300">{mover.ema20 ? formatINR(mover.ema20) : '—'}</span>
                <span className="text-[8px] text-slate-400 block">({distAtr.toFixed(1)}x ATR)</span>
              </div>
              <div className="p-1.5 rounded bg-dark-800/80 border border-white/5 text-slate-300">
                <span className="text-[8.5px] text-slate-400 block font-sans">VWAP Floor</span>
                <span className="font-bold text-cyan-300">{mover.vwap ? formatINR(mover.vwap) : '—'}</span>
                <span className="text-[8px] block">{vwapPass ? '✅ Holding' : '⏳ Pullback'}</span>
              </div>
            </div>
            <p className="text-[9px] text-slate-400 leading-snug">
              💡 20-EMA execution trade plan triggers when price tightens within 1.5 ATR of 20-EMA with RelVol ≥ 1.5x.
            </p>
          </div>
        ) : (
          <div className="rounded-xl p-3 border border-white/5 bg-dark-850/60 mb-3 space-y-2">
            <div className="flex items-center justify-between text-xs border-b border-white/5 pb-1">
              <span className="flex items-center gap-1 text-slate-300 font-semibold">
                <Clock className="w-3.5 h-3.5 text-slate-400" />
                <span>15m Consolidation</span>
              </span>
              <span className="text-[9px] font-mono text-slate-500">Monitoring</span>
            </div>
            <div className="grid grid-cols-2 gap-1.5 text-[9.5px] font-mono text-center">
              <div className="p-1 rounded bg-dark-750 border border-white/5 text-slate-300">
                Vol: {mover.rel_vol}x {mover.rel_vol >= 1.5 ? '✅' : '⏳'}
              </div>
              <div className="p-1 rounded bg-dark-750 border border-white/5 text-slate-300">
                Range: Holding ⏳
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Footer: Status + 15m Chart Button */}
      <div className="pt-2 border-t border-white/5 flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setIsFlipped(true);
          }}
          className="text-[10px] text-slate-400 hover:text-indigo-300 flex items-center gap-1 truncate max-w-[170px] text-left transition-colors cursor-pointer group"
          title="Click to inspect setup diagnostic details"
        >
          <span className="truncate">{mover.reasons[0] ?? mover.status}</span>
          <HelpCircle className="w-2.5 h-2.5 shrink-0 text-slate-500 group-hover:text-indigo-400" />
        </button>

        <button
          onClick={(e) => {
            e.stopPropagation();
            onOpenChart(chartTarget);
          }}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-indigo-600/80 hover:bg-indigo-600 text-white text-xs font-semibold shadow-sm transition-all flex-shrink-0 cursor-pointer"
        >
          <LineChart className="w-3.5 h-3.5" />
          <span>15m Chart</span>
          <ExternalLink className="w-2.5 h-2.5 text-indigo-200" />
        </button>
      </div>
    </>
  )}
</div>
  );
};
