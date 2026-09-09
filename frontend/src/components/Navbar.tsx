"use client";

import React, { useState, useEffect } from 'react';
import { 
  TrendingUp, 
  Clock, 
  Volume2, 
  VolumeX, 
  RefreshCw 
} from 'lucide-react';
import { MarketStatus } from '@/types/screener';

interface NavbarProps {
  marketStatus: MarketStatus | null;
  mode: 'live' | 'simulation' | 'auto';
  onModeChange: (mode: 'live' | 'simulation' | 'auto') => void;
  audioEnabled: boolean;
  onToggleAudio: () => void;
  onRefresh: () => void;
  isRefreshing: boolean;
  lastRefreshedTime: string;
}

export const Navbar: React.FC<NavbarProps> = ({
  marketStatus,
  mode,
  onModeChange,
  audioEnabled,
  onToggleAudio,
  onRefresh,
  isRefreshing,
  lastRefreshedTime,
}) => {
  const [istTime, setIstTime] = useState<string>('');

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      const options: Intl.DateTimeFormatOptions = {
        timeZone: 'Asia/Kolkata',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
      };
      setIstTime(now.toLocaleTimeString('en-IN', options) + ' IST');
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  const isOpen = marketStatus?.is_open ?? false;

  return (
    <header className="border-b border-white/10 bg-dark-850/90 backdrop-blur-md sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16 gap-4">
          
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 via-indigo-600 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20 border border-white/20">
              <TrendingUp className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-lg tracking-tight text-white flex items-center gap-1.5">
                  NSE Intraday Alpha
                </span>
                <span className="px-1.5 py-0.5 text-[10px] font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 rounded uppercase tracking-wider">
                  Nifty 500 ? 15m
                </span>
              </div>
              <p className="text-xs text-slate-400 hidden sm:block">
                Quantitative Momentum, RelVol & 20 EMA Breakout Engine
              </p>
            </div>
          </div>

          <div className="hidden md:flex items-center gap-3 bg-dark-800/80 px-3.5 py-1.5 rounded-full border border-white/5 text-xs">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${isOpen ? 'bg-emerald-500 animate-ping' : 'bg-amber-500'}`} />
              <span className={`font-medium ${isOpen ? 'text-emerald-400' : 'text-amber-400'}`}>
                {isOpen ? 'NSE Market Live' : 'Market Closed'}
              </span>
            </div>
            <div className="w-px h-3.5 bg-white/15" />
            <div className="flex items-center gap-1.5 text-slate-300 font-mono">
              <Clock className="w-3.5 h-3.5 text-slate-400" />
              <span>{istTime || 'Loading IST...'}</span>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <div className="bg-dark-800 p-0.5 rounded-lg border border-white/10 hidden sm:flex">
              <button
                onClick={() => onModeChange('live')}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-all flex items-center gap-1.5 ${
                  mode === 'live'
                    ? 'bg-emerald-600 text-white shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
                title="Real Live NSE Market Prices from Yahoo Finance / TradingView"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                <span>Live NSE Data</span>
              </button>
              <button
                onClick={() => onModeChange('simulation')}
                className={`px-2.5 py-1 text-xs font-medium rounded-md transition-all ${
                  mode === 'simulation'
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
                title="Synthetic Breakout Sandbox"
              >
                Demo Sandbox
              </button>
            </div>

            <button
              onClick={onToggleAudio}
              className={`p-2 rounded-lg border transition-all ${
                audioEnabled 
                  ? 'bg-indigo-500/20 border-indigo-500/40 text-indigo-300' 
                  : 'bg-dark-800 border-white/10 text-slate-400 hover:text-white'
              }`}
              title={audioEnabled ? "Audio Alerts Enabled" : "Audio Alerts Muted"}
            >
              {audioEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
            </button>

            <button
              onClick={onRefresh}
              disabled={isRefreshing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-dark-750 hover:bg-dark-700 border border-white/10 text-xs font-medium text-slate-200 transition-all disabled:opacity-50"
              title="Refresh screener data"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin text-indigo-400' : 'text-slate-400'}`} />
              <span className="hidden sm:inline">Refresh</span>
            </button>
          </div>

        </div>

        {marketStatus && !marketStatus.is_open && (
          <div className="py-1.5 px-3 mb-2 bg-amber-500/10 border border-amber-500/20 rounded-md flex items-center justify-between text-xs text-amber-300">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-amber-400" />
              <span>{marketStatus.session_message}</span>
            </div>
            <span className="text-amber-400/80 text-[11px] font-mono">
              Last Refreshed: {lastRefreshedTime || marketStatus.market_time_ist}
            </span>
          </div>
        )}

      </div>
    </header>
  );
};
