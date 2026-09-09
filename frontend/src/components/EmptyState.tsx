"use client";

import React from 'react';
import { SearchX, RefreshCw } from 'lucide-react';

interface EmptyStateProps {
  onReset: () => void;
}

export const EmptyState: React.FC<EmptyStateProps> = ({ onReset }) => {
  return (
    <div className="glass-panel rounded-2xl p-12 text-center max-w-md mx-auto border border-white/10 space-y-4 my-8">
      <div className="w-14 h-14 rounded-2xl bg-dark-800 border border-white/10 flex items-center justify-center mx-auto text-slate-400">
        <SearchX className="w-7 h-7" />
      </div>
      <div>
        <h3 className="text-lg font-bold text-white">No Stocks Matched Filters</h3>
        <p className="text-xs text-slate-400 mt-1 max-w-xs mx-auto">
          No Nifty 50 stocks currently match the specified search term, sector, or signal criteria.
        </p>
      </div>
      <button
        onClick={onReset}
        className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow-lg shadow-indigo-500/20 transition-all"
      >
        <RefreshCw className="w-3.5 h-3.5" />
        <span>Reset Filters</span>
      </button>
    </div>
  );
};
