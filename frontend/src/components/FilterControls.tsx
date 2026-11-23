"use client";

import React from 'react';
import { 
  Search, 
  Filter, 
  ArrowUpDown, 
  Clock, 
  Sparkles,
  TrendingUp,
  TrendingDown,
  Layers,
  ChevronDown,
  X
} from 'lucide-react';

export type SignalFilterType = 'ALL' | 'ACTIVE_ONLY' | 'BELOW_THRESHOLD' | 'NO_SETUP' | 'WATCH' | 'STRONG' | 'HIGH_CONFIDENCE' | 'BULLISH' | 'BEARISH';
export type SortOptionType = 
  | 'SCORE_DESC_T1_ASC'
  | 'SCORE_DESC' 
  | 'SCORE_ASC' 
  | 'REL_VOL_DESC' 
  | 'CHANGE_DESC' 
  | 'CHANGE_ASC' 
  | 'RR_DESC' 
  | 'SYMBOL_ASC'
  | 'T1_PROGRESS_ASC'
  | 'T1_PROGRESS_DESC'
  | 'NIFTY500_FIRST'
  | 'MCAP_DESC';
export type RefreshIntervalType = 30 | 45 | 60 | 180 | 300 | 0;

interface FilterControlsProps {
  searchQuery: string;
  onSearchChange: (q: string) => void;
  selectedSector: string;
  onSectorChange: (sector: string) => void;
  sectors: string[];
  signalFilter: SignalFilterType;
  onSignalFilterChange: (f: SignalFilterType) => void;
  sortBy: SortOptionType;
  onSortChange: (sort: SortOptionType) => void;
  refreshInterval: RefreshIntervalType;
  onRefreshIntervalChange: (sec: RefreshIntervalType) => void;
  countdown: number;
  totalCount: number;
  activeCount: number;
  bullishCount: number;
  bearishCount: number;
  belowThresholdCount?: number;
  noSetupCount?: number;
  watchCount?: number;
  strongCount?: number;
  highConfidenceCount?: number;
}

export const FilterControls: React.FC<FilterControlsProps> = ({
  searchQuery,
  onSearchChange,
  selectedSector,
  onSectorChange,
  sectors,
  signalFilter,
  onSignalFilterChange,
  sortBy,
  onSortChange,
  refreshInterval,
  onRefreshIntervalChange,
  countdown,
  totalCount,
  activeCount,
  bullishCount,
  bearishCount,
  belowThresholdCount = 0,
  noSetupCount = 0,
  watchCount = 0,
  strongCount = 0,
  highConfidenceCount = 0,
}) => {
  return (
    <div className="glass-panel p-4 rounded-xl mb-6 space-y-4">
      
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/5 pb-3">
        
        <div className="flex flex-wrap items-center gap-1.5 bg-dark-800/90 p-1 rounded-xl border border-white/10">
          <button
            onClick={() => onSignalFilterChange('ALL')}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
              signalFilter === 'ALL'
                ? 'bg-white/10 text-white shadow-sm'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>All Stocks</span>
            <span className="ml-1 px-1.5 py-0.2 bg-dark-700 rounded-full text-[10px] text-slate-300">
              {totalCount}
            </span>
          </button>

          <button
            onClick={() => onSignalFilterChange('ACTIVE_ONLY')}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
              signalFilter === 'ACTIVE_ONLY'
                ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-500/20'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5 text-amber-400" />
            <span>Active Signals</span>
            <span className="ml-1 px-1.5 py-0.2 bg-indigo-900/60 rounded-full text-[10px] text-indigo-200 font-bold">
              {activeCount}
            </span>
          </button>

          <button
            onClick={() => onSignalFilterChange('HIGH_CONFIDENCE')}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
              signalFilter === 'HIGH_CONFIDENCE'
                ? 'bg-emerald-600 text-white shadow-sm'
                : 'text-emerald-400 hover:text-emerald-200'
            }`}
          >
            <span>🚀 High Confidence (85+)</span>
            <span className="ml-1 px-1.5 py-0.2 bg-emerald-950/80 rounded-full text-[10px] text-emerald-200 font-bold">
              {highConfidenceCount}
            </span>
          </button>

          <button
            onClick={() => onSignalFilterChange('STRONG')}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
              signalFilter === 'STRONG'
                ? 'bg-cyan-600 text-white shadow-sm'
                : 'text-cyan-400 hover:text-cyan-200'
            }`}
          >
            <span>⚡ Strong (80-84)</span>
            <span className="ml-1 px-1.5 py-0.2 bg-cyan-950/80 rounded-full text-[10px] text-cyan-200 font-bold">
              {strongCount}
            </span>
          </button>

          <button
            onClick={() => onSignalFilterChange('WATCH')}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
              signalFilter === 'WATCH'
                ? 'bg-amber-600 text-white shadow-sm'
                : 'text-amber-400 hover:text-amber-200'
            }`}
          >
            <span>👀 Watchlist (72-79)</span>
            <span className="ml-1 px-1.5 py-0.2 bg-amber-950/80 rounded-full text-[10px] text-amber-200 font-bold">
              {watchCount}
            </span>
          </button>

          <button
            onClick={() => onSignalFilterChange('BELOW_THRESHOLD')}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
              signalFilter === 'BELOW_THRESHOLD'
                ? 'bg-slate-700 text-rose-300 border border-rose-500/30 shadow-sm'
                : 'text-slate-400 hover:text-rose-300'
            }`}
          >
            <span>📊 Below Threshold (&lt;72)</span>
            <span className="ml-1 px-1.5 py-0.2 bg-dark-900 rounded-full text-[10px] text-rose-300 font-bold">
              {belowThresholdCount}
            </span>
          </button>

          <button
            onClick={() => onSignalFilterChange('NO_SETUP')}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
              signalFilter === 'NO_SETUP'
                ? 'bg-slate-700 text-slate-200 border border-slate-500 shadow-sm'
                : 'text-slate-400 hover:text-slate-200'
            }`}
            title="Safety Filtered: Penny stocks < ₹30, Circuit freeze, or Low volume"
          >
            <span>🚫 No Setup / Filtered</span>
            <span className="ml-1 px-1.5 py-0.2 bg-dark-900 rounded-full text-[10px] text-slate-300 font-bold">
              {noSetupCount ?? 0}
            </span>
          </button>

          <button
            onClick={() => onSignalFilterChange('BULLISH')}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
              signalFilter === 'BULLISH'
                ? 'bg-emerald-600/90 text-white shadow-sm shadow-emerald-500/20'
                : 'text-slate-400 hover:text-emerald-400'
            }`}
          >
            <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
            <span>Bullish</span>
            <span className="ml-1 px-1.5 py-0.2 bg-emerald-950/60 rounded-full text-[10px] text-emerald-300 font-bold">
              {bullishCount}
            </span>
          </button>

          <button
            onClick={() => onSignalFilterChange('BEARISH')}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
              signalFilter === 'BEARISH'
                ? 'bg-rose-600/90 text-white shadow-sm shadow-rose-500/20'
                : 'text-slate-400 hover:text-rose-400'
            }`}
          >
            <TrendingDown className="w-3.5 h-3.5 text-rose-400" />
            <span>Bearish</span>
            <span className="ml-1 px-1.5 py-0.2 bg-rose-950/60 rounded-full text-[10px] text-rose-300 font-bold">
              {bearishCount}
            </span>
          </button>
        </div>

        <div className="flex items-center gap-2 bg-dark-800 px-3 py-1.5 rounded-xl border border-white/10 text-xs">
          <Clock className="w-3.5 h-3.5 text-indigo-400" />
          <span className="text-slate-400 text-[11px]">Auto-Refresh:</span>
          
          <select
            suppressHydrationWarning
            value={refreshInterval}
            onChange={(e) => onRefreshIntervalChange(Number(e.target.value) as RefreshIntervalType)}
            className="bg-dark-750 text-slate-200 rounded px-2 py-0.5 border border-white/10 text-xs focus:outline-none focus:border-indigo-500"
          >
            <option value={30}>30 sec (Fast)</option>
            <option value={45}>45 sec</option>
            <option value={60}>1 min</option>
            <option value={180}>3 mins</option>
            <option value={300}>5 mins</option>
            <option value={0}>Manual</option>
          </select>

          {refreshInterval > 0 && (
            <div className="flex items-center gap-1.5 pl-2 border-l border-white/10 font-mono text-[11px] text-indigo-300">
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
              <span suppressHydrationWarning>{countdown}s</span>
            </div>
          )}
        </div>

      </div>

      <div className="grid grid-cols-1 md:grid-cols-12 gap-3">
        
        <div className="md:col-span-5 relative">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search by symbol or company (e.g. RELIANCE, TCS, HDFC)..."
            className="w-full pl-9 pr-4 py-2 bg-dark-800/90 border border-white/10 rounded-xl text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all"
          />
          {searchQuery && (
            <button
              onClick={() => onSearchChange('')}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white transition-colors"
              title="Clear search"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        <div className="md:col-span-4 relative">
          <div className="relative flex items-center">
            <Filter className="w-3.5 h-3.5 text-slate-400 absolute left-3 pointer-events-none" />
            <select
              value={selectedSector}
              onChange={(e) => onSectorChange(e.target.value)}
              className="w-full pl-9 pr-8 py-2 bg-dark-800/90 border border-white/10 rounded-xl text-xs text-slate-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 appearance-none cursor-pointer"
            >
              <option value="ALL">All Sectors ({totalCount} Stocks)</option>
              {sectors.map((sec) => (
                <option key={sec} value={sec}>
                  {sec}
                </option>
              ))}
            </select>
            <div className="absolute right-3 pointer-events-none text-slate-400">
              <ChevronDown className="w-3.5 h-3.5" />
            </div>
          </div>
        </div>

        <div className="md:col-span-3 relative">
          <div className="relative flex items-center">
            <ArrowUpDown className="w-3.5 h-3.5 text-slate-400 absolute left-3 pointer-events-none" />
            <select
              value={sortBy}
              onChange={(e) => onSortChange(e.target.value as SortOptionType)}
              className="w-full pl-9 pr-8 py-2 bg-dark-800/90 border border-white/10 rounded-xl text-xs text-slate-200 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 appearance-none cursor-pointer font-medium"
            >
              <option value="REL_VOL_DESC">Sort: Relative Volume (High to Low) [Default]</option>
              <option value="SCORE_DESC_T1_ASC">🎯 Sort: Best Alpha Entry (High Score + Fresh Base First)</option>
              <option value="SCORE_DESC">Sort: V13 Score (High to Low)</option>
              <option value="SCORE_ASC">Sort: V13 Score (Low to High)</option>
              <option value="T1_PROGRESS_ASC">Sort: Target Tracker (Early Trigger → T1 Hit / Low to High %)</option>
              <option value="T1_PROGRESS_DESC">Sort: Target Tracker (T1 Hit → Early Trigger / High to Low %)</option>
              <option value="NIFTY500_FIRST">Sort: Nifty 500 First (then &gt;1000 Cr Universe)</option>
              <option value="MCAP_DESC">Sort: Market Cap (&gt;1000 Cr High to Low)</option>
              <option value="CHANGE_DESC">Sort: Session Change % (Highest Gainers)</option>
              <option value="CHANGE_ASC">Sort: Session Change % (Top Losers)</option>
              <option value="RR_DESC">Sort: Risk / Reward Potential</option>
              <option value="SYMBOL_ASC">Sort: Alphabetical (A to Z)</option>
            </select>
            <div className="absolute right-3 pointer-events-none text-slate-400">
              <ChevronDown className="w-3.5 h-3.5" />
            </div>
          </div>
        </div>

      </div>

    </div>
  );
};
