"use client";

import React, { useState, useEffect } from 'react';
import { 
  TrendingUp, 
  Clock, 
  Volume2, 
  VolumeX, 
  RefreshCw,
  Zap,
  Target
} from 'lucide-react';

import { MarketStatus } from '@/types/screener';
import { cn } from '@/lib/utils';

export interface NiftySpotSnapshot {
  spot_ltp: number;
  spot_change: number;
  spot_change_pct: number;
  feed_mode?: string;
}

interface NavbarProps {
  marketStatus: MarketStatus | 'LIVE' | 'CLOSED' | null;
  mode: 'live' | 'simulation' | 'auto';
  onModeChange: (mode: 'live' | 'simulation' | 'auto') => void;
  audioEnabled: boolean;
  onToggleAudio: () => void;
  onRefresh: () => void;
  isRefreshing: boolean;
  lastRefreshedTime: string;
  activeTab?: 'V13_UNIVERSE' | 'LIVE_MOVERS' | 'MARKET_PULSE' | 'NIFTY_OPTIONS';
  onTabChange?: (tab: 'V13_UNIVERSE' | 'LIVE_MOVERS' | 'MARKET_PULSE' | 'NIFTY_OPTIONS') => void;
  niftySpot?: NiftySpotSnapshot | null;
  onSelectNiftyOptions?: () => void;
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
  activeTab = 'V13_UNIVERSE',
  onTabChange,
  niftySpot,
  onSelectNiftyOptions,
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

  const isOpen = marketStatus === 'LIVE' || (typeof marketStatus === 'object' && marketStatus?.is_open === true);
  const isHoliday = typeof marketStatus === 'object' && Boolean(marketStatus?.is_holiday);
  const holidayName = typeof marketStatus === 'object' ? marketStatus?.holiday_name : null;

  return (
    <header className="border-b border-white/10 bg-dark-850/90 backdrop-blur-md sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16 gap-4">
          
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-500 via-indigo-600 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20 border border-white/20 shrink-0">
              <TrendingUp className="w-5 h-5 text-white" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-bold text-base sm:text-lg tracking-tight text-white whitespace-nowrap">
                  NSE Pulse
                </span>
                <span className="px-1.5 py-0.5 text-[9px] font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 rounded uppercase tracking-wider whitespace-nowrap">
                  1000CR • 15M
                </span>
                <span className="px-1.5 py-0.5 text-[9px] font-medium bg-white/5 text-slate-400 border border-white/10 rounded uppercase tracking-wider hidden sm:inline-block">
                  LTP: 15M CLOSE
                </span>
              </div>
              <p className="text-xs text-slate-400 hidden md:block">
                Quantitative Momentum, RelVol &amp; 20 EMA Breakout Engine
              </p>
            </div>
          </div>

          <div className="hidden md:flex items-center gap-3 bg-dark-800/80 px-3.5 py-1.5 rounded-full border border-white/5 text-xs">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${
                isHoliday 
                  ? 'bg-rose-500 animate-pulse' 
                  : isOpen 
                    ? 'bg-emerald-500 animate-ping' 
                    : 'bg-amber-500'
              }`} />
              <span className={`font-medium ${
                isHoliday 
                  ? 'text-rose-400 font-semibold' 
                  : isOpen 
                    ? 'text-emerald-400' 
                    : 'text-amber-400'
              }`}>
                {isHoliday 
                  ? `Market Closed (${holidayName || 'NSE Holiday'})` 
                  : isOpen 
                    ? 'NSE Market Live' 
                    : 'Market Closed'}
              </span>
            </div>
            <div className="w-px h-3.5 bg-white/15" />
            <div className="flex items-center gap-1.5 text-slate-300 font-mono">
              <Clock className="w-3.5 h-3.5 text-slate-400" />
              <span>{istTime || 'Loading IST...'}</span>
            <div className="text-slate-400 font-mono whitespace-nowrap" title="Last completed V13 scan">
              Updated {lastRefreshedTime ? new Date(lastRefreshedTime).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true }) + ' IST' : '—'}
            </div>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            {/* Live Fyers NIFTY 50 Index Ticker Widget */}
            {niftySpot && niftySpot.spot_ltp > 0 ? (
              <button
                onClick={onSelectNiftyOptions}
                className="h-8 px-2.5 rounded-lg bg-dark-800/90 border border-white/10 hover:border-cyan-500/40 hover:bg-dark-750 transition-all flex items-center gap-1.5 font-mono select-none whitespace-nowrap shrink-0 shadow-sm"
                title="Fyers Real-Time Nifty 50 Index (Click to open NIFTY Options Quant Panel)"
              >
                <span className="relative flex h-1.5 w-1.5 shrink-0">
                  <span
                    className={cn(
                      "animate-ping absolute inline-flex h-full w-full rounded-full opacity-75",
                      niftySpot.feed_mode === 'FULL' ? 'bg-emerald-400' : 'bg-amber-400'
                    )}
                  />
                  <span
                    className={cn(
                      "relative inline-flex rounded-full h-1.5 w-1.5",
                      niftySpot.feed_mode === 'FULL' ? 'bg-emerald-500' : 'bg-amber-500'
                    )}
                  />
                </span>
                <span className="text-[10px] font-bold text-cyan-300 tracking-tight whitespace-nowrap">NIFTY 50</span>
                <span className="text-xs font-bold text-white font-mono whitespace-nowrap">
                  ₹{niftySpot.spot_ltp.toLocaleString('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 2 })}
                </span>
                <span
                  className={cn(
                    "text-[10px] font-medium font-mono whitespace-nowrap",
                    niftySpot.spot_change >= 0 ? "text-emerald-400" : "text-rose-400"
                  )}
                >
                  {niftySpot.spot_change >= 0 ? '+' : ''}{niftySpot.spot_change.toFixed(1)} ({niftySpot.spot_change_pct >= 0 ? '+' : ''}{niftySpot.spot_change_pct.toFixed(2)}%)
                </span>
              </button>
            ) : null}

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


      </div>
    </header>
  );
};

