"use client";

import React from 'react';
import { Zap, TrendingDown, X } from 'lucide-react';
import { StockSignal } from '@/types/screener';

interface ToastProps {
  signals: StockSignal[];
  onDismiss: (symbol: string) => void;
  onView: (stock: StockSignal) => void;
}

export const ToastContainer: React.FC<ToastProps> = ({ signals, onDismiss, onView }) => {
  if (signals.length === 0) return null;

  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none">
      {signals.map((stock) => {
        const isBullish = stock.signal_type === 'BULLISH';
        return (
          <div
            key={stock.symbol}
            className={`pointer-events-auto p-3.5 rounded-xl shadow-2xl border flex items-start justify-between gap-3 animate-in slide-in-from-right duration-300 backdrop-blur-lg ${
              isBullish
                ? 'bg-emerald-950/90 border-emerald-500/40 text-emerald-100 shadow-emerald-500/10'
                : 'bg-rose-950/90 border-rose-500/40 text-rose-100 shadow-rose-500/10'
            }`}
          >
            <div className="flex items-start gap-2.5">
              <div className={`p-1.5 rounded-lg ${isBullish ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400'}`}>
                {isBullish ? <Zap className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-bold text-sm text-white">{stock.symbol}</span>
                  <span className="text-[10px] font-semibold uppercase px-1.5 py-0.2 bg-white/10 rounded">
                    {isBullish ? 'Bullish Breakout' : 'Bearish Breakdown'}
                  </span>
                </div>
                <p className="text-xs text-slate-300 mt-0.5">
                  {stock.rel_vol}x Vol ? Price: ?{stock.ltp} ({stock.price_change_pct >= 0 ? '+' : ''}{stock.price_change_pct}%)
                </p>
                <button
                  onClick={() => onView(stock)}
                  className="text-xs font-semibold underline mt-1 text-white hover:text-indigo-300"
                >
                  View 15m Chart & Execution Levels ?
                </button>
              </div>
            </div>

            <button
              onClick={() => onDismiss(stock.symbol)}
              className="text-slate-400 hover:text-white p-1"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
};
