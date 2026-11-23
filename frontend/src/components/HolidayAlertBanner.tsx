"use client";

import React, { useState } from 'react';
import { CalendarX, AlertCircle, Clock, Info, X, ShieldAlert } from 'lucide-react';
import { MarketStatus } from '../types/screener';

interface HolidayAlertBannerProps {
  marketStatus?: MarketStatus | null;
}

export const HolidayAlertBanner: React.FC<HolidayAlertBannerProps> = ({ marketStatus }) => {
  const [dismissUpcoming, setDismissUpcoming] = useState(false);

  if (!marketStatus) return null;

  const isTodayHoliday = Boolean(marketStatus.is_holiday);
  const holidayName = marketStatus.holiday_name || "Official NSE Trading Holiday";
  const nextSession = marketStatus.next_trading_session || "Next Scheduled Trading Day at 09:15 AM IST";
  const upcomingNotice = marketStatus.next_holiday_notice;

  // CASE 1: Today IS an active NSE Trading Holiday (Prominent Non-Dismissible Screen Flash Banner)
  if (isTodayHoliday) {
    return (
      <div className="w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-4 pb-2">
        <div className="relative overflow-hidden rounded-2xl border-2 border-rose-500/50 bg-gradient-to-r from-rose-950/60 via-dark-850 to-amber-950/50 p-5 sm:p-6 shadow-2xl shadow-rose-950/50 backdrop-blur-xl">
          {/* Subtle animated background glow accent */}
          <div className="absolute -top-12 -right-12 w-48 h-48 bg-rose-500/10 rounded-full blur-3xl pointer-events-none" />
          <div className="absolute -bottom-12 -left-12 w-48 h-48 bg-amber-500/10 rounded-full blur-3xl pointer-events-none" />

          <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="flex items-start gap-4">
              <div className="p-3 rounded-xl bg-rose-500/20 border border-rose-500/40 text-rose-400 shrink-0 shadow-inner">
                <CalendarX className="w-7 h-7 animate-pulse text-rose-300" />
              </div>

              <div className="space-y-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="px-2.5 py-0.5 text-xs font-bold bg-rose-500/20 text-rose-300 border border-rose-500/40 rounded-full uppercase tracking-wider flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-rose-400 animate-ping inline-block" />
                    NSE TRADING HOLIDAY • MARKET CLOSED
                  </span>
                  <span className="px-2.5 py-0.5 text-xs font-medium bg-white/10 text-slate-300 border border-white/10 rounded-full">
                    No Exchange Ticks Today
                  </span>
                </div>

                <h2 className="text-xl sm:text-2xl font-extrabold text-white tracking-tight flex items-center gap-2">
                  <span>{holidayName}</span>
                </h2>

                <p className="text-sm text-slate-300 max-w-3xl leading-relaxed">
                  NSE & BSE Equity, Derivatives (F&amp;O) and Currency markets are officially closed today. 
                  Live scanning and realtime alerts are safely paused. Previous session data and portfolio metrics remain frozen and protected.
                </p>
              </div>
            </div>

            {/* Next session countdown info card */}
            <div className="shrink-0 flex flex-col sm:flex-row md:flex-col items-start md:items-end justify-center bg-dark-900/80 border border-white/10 rounded-xl px-4 py-3 gap-1.5 text-xs">
              <div className="flex items-center gap-1.5 text-amber-400 font-semibold uppercase tracking-wider">
                <Clock className="w-4 h-4 text-amber-300" />
                <span>Next Trading Session</span>
              </div>
              <div className="text-white font-bold text-sm sm:text-base font-mono">
                {nextSession}
              </div>
              <div className="text-slate-400 text-[11px]">
                Pre-market opens at 09:00 AM • Live trading at 09:15 AM
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // CASE 2: Advance Notification of an Upcoming Holiday (e.g. Thursday EOD warning about Friday holiday)
  if (upcomingNotice && !dismissUpcoming) {
    return (
      <div className="w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-3 pb-1">
        <div className="relative overflow-hidden rounded-xl border border-amber-500/40 bg-gradient-to-r from-amber-950/40 via-dark-850 to-dark-800 p-3.5 sm:p-4 shadow-lg backdrop-blur-md flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-amber-500/20 border border-amber-500/30 text-amber-400 shrink-0">
              <Info className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-amber-300 uppercase tracking-wider">
                  Upcoming Market Holiday Alert
                </span>
              </div>
              <p className="text-xs sm:text-sm text-slate-200">
                ⚠️ <span className="font-semibold">{upcomingNotice}</span>. Regular market operations and live scanning will be closed on that day.
              </p>
            </div>
          </div>

          <button
            onClick={() => setDismissUpcoming(true)}
            className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors shrink-0"
            title="Dismiss notice"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  return null;
};
