"use client";

import React, { useState, useEffect, useMemo } from 'react';
import { Clock, Activity, Zap, CheckCircle2, AlertTriangle, ShieldCheck, Timer } from 'lucide-react';
import { cn } from '@/lib/utils';

interface CandleSyncBarProps {
  generatedAt?: string | null;
  marketStatus?: 'LIVE' | 'CLOSED' | null;
}

// Convert any Date to standard IST (UTC + 5:30)
function getNowIST(): Date {
  const now = new Date();
  const utcMs = now.getTime() + (now.getTimezoneOffset() * 60000);
  return new Date(utcMs + (5.5 * 3600000));
}

function padZero(num: number): string {
  return num < 10 ? `0${num}` : `${num}`;
}

function formatDateDDMMYYYY(d: Date): string {
  const day = padZero(d.getDate());
  const month = padZero(d.getMonth() + 1);
  const year = d.getFullYear();
  return `${day}/${month}/${year}`;
}

function getPreviousTradingDate(refDate: Date): Date {
  const d = new Date(refDate);
  d.setDate(d.getDate() - 1);
  while (d.getDay() === 0 || d.getDay() === 6) {
    d.setDate(d.getDate() - 1);
  }
  return d;
}

function getLastClosedBarDate(
  nowIst: Date,
  isMarketHours: boolean,
  currentBarIndex: number
): string {
  // 1. If during active market hours and past Bar 1: today's bar (Bar 1 to 24) has closed
  if (isMarketHours && currentBarIndex > 0) {
    return formatDateDDMMYYYY(nowIst);
  }

  // 2. If after market close (>= 15:30) on a weekday: today's Bar 25 has closed
  const hours = nowIst.getHours();
  const minutes = nowIst.getMinutes();
  const totalMins = hours * 60 + minutes;
  const isWeekday = nowIst.getDay() >= 1 && nowIst.getDay() <= 5;
  if (isWeekday && totalMins >= 15 * 60 + 30) {
    return formatDateDDMMYYYY(nowIst);
  }

  // 3. In all other cases (Pre-market 00:00-09:15, Bar 1 forming 09:15-09:30, or Weekend):
  // The last closed bar was Bar 25 of the previous trading day!
  return formatDateDDMMYYYY(getPreviousTradingDate(nowIst));
}

function formatMinutesToTimeStr(totalMinutes: number): string {
  const h = Math.floor(totalMinutes / 60);
  const m = Math.floor(totalMinutes % 60);
  return `${padZero(h)}:${padZero(m)}`;
}

export const CandleSyncBar: React.FC<CandleSyncBarProps> = ({
  generatedAt,
  marketStatus,
}) => {
  // Kill switch check via environment variable
  const isEnabled = process.env.NEXT_PUBLIC_ENABLE_CANDLE_SYNC_BAR !== 'false';

  const [mounted, setMounted] = useState<boolean>(false);
  const [nowIst, setNowIst] = useState<Date>(getNowIST);

  // 1-second client-side clock timer (runs strictly after client mount)
  useEffect(() => {
    setMounted(true);
    const timer = setInterval(() => {
      setNowIst(getNowIST());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  if (!isEnabled) {
    return null;
  }

  if (!mounted) {
    return (
      <div className="w-full bg-dark-850/90 backdrop-blur-md border-b border-white/5 py-1.5 px-4 font-mono text-[11px] select-none text-slate-400">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-slate-400">
            <Clock className="w-3.5 h-3.5 text-cyan-400 animate-pulse" />
            <span>Connecting Yahoo Data Sync...</span>
          </div>
        </div>
      </div>
    );
  }

  // Current IST Time components
  const hours = nowIst.getHours();
  const minutes = nowIst.getMinutes();
  const seconds = nowIst.getSeconds();
  const day = nowIst.getDay(); // 0 = Sun, 1 = Mon, ..., 6 = Sat

  const isWeekday = day >= 1 && day <= 5;
  const currentTotalMinutes = hours * 60 + minutes + seconds / 60;

  // NSE Market Boundaries (IST)
  const MARKET_OPEN_MINUTES = 9 * 60 + 15;   // 09:15 IST (555 mins)
  const MARKET_CLOSE_MINUTES = 15 * 60 + 30; // 15:30 IST (930 mins)

  const isMarketHours = isWeekday && currentTotalMinutes >= MARKET_OPEN_MINUTES && currentTotalMinutes < MARKET_CLOSE_MINUTES;

  // Running 15-Minute Candle Calculations
  let currentBarIndex = 0; // 0 to 24 (Bar 1 to Bar 25)
  let currentBarStartMin = MARKET_OPEN_MINUTES;
  let currentBarEndMin = MARKET_OPEN_MINUTES + 15;
  let elapsedSeconds = 0;
  let remainingSeconds = 0;
  let elapsedPercent = 0;

  let lastClosedBarStartStr = '15:15';
  let lastClosedBarEndStr = '15:30';
  let lastClosedBarNumber = 25;

  if (isMarketHours) {
    const minutesSinceOpen = currentTotalMinutes - MARKET_OPEN_MINUTES;
    currentBarIndex = Math.floor(minutesSinceOpen / 15);
    currentBarStartMin = MARKET_OPEN_MINUTES + currentBarIndex * 15;
    currentBarEndMin = currentBarStartMin + 15;

    elapsedSeconds = Math.max(0, Math.floor((currentTotalMinutes - currentBarStartMin) * 60));
    remainingSeconds = Math.max(0, 900 - elapsedSeconds);
    elapsedPercent = Math.min(100, Math.max(0, (elapsedSeconds / 900) * 100));

    if (currentBarIndex > 0) {
      const prevBarStart = currentBarStartMin - 15;
      lastClosedBarStartStr = formatMinutesToTimeStr(prevBarStart);
      lastClosedBarEndStr = formatMinutesToTimeStr(currentBarStartMin);
      lastClosedBarNumber = currentBarIndex;
    } else {
      // First bar (09:15 - 09:30): Previous bar is Yesterday's EOD
      lastClosedBarStartStr = '15:15';
      lastClosedBarEndStr = '15:30';
      lastClosedBarNumber = 25;
    }
  }

  // Parse scan generated_at to calculate Ingestion Latency (Exclusively during Live Market Hours)
  let ingestLagSeconds: number | null = null;
  let lagText = 'Offline (Session Settled)';
  let lagBadgeClass = 'text-slate-400 bg-dark-750 border-white/10 font-normal';

  if (!isMarketHours) {
    lagText = 'Offline (Session Settled)';
    lagBadgeClass = 'text-slate-400 bg-dark-750 border-white/10 font-normal';
  } else if (generatedAt) {
    try {
      const genDate = new Date(generatedAt);
      if (!isNaN(genDate.getTime())) {
        // If during market hours and past Bar 1: compare with lastClosedBarEnd
        if (currentBarIndex > 0) {
          const lastCloseDate = new Date(nowIst);
          const closeH = Math.floor(currentBarStartMin / 60);
          const closeM = Math.floor(currentBarStartMin % 60);
          lastCloseDate.setHours(closeH, closeM, 0, 0);

          const diffMs = genDate.getTime() - lastCloseDate.getTime();
          // Positive diff represents ingestion lag after candle close
          ingestLagSeconds = Math.max(0, Math.floor(diffMs / 1000));
        } else {
          // Bar 1 (09:15 - 09:30 AM): Opening range forming
          const diffMs = nowIst.getTime() - genDate.getTime();
          ingestLagSeconds = Math.max(0, Math.floor(diffMs / 1000));
        }

        const lagM = Math.floor(ingestLagSeconds / 60);
        const lagS = ingestLagSeconds % 60;
        
        if (ingestLagSeconds <= 180) { // <= 3 minutes
          lagText = `${lagM}m ${lagS}s [FAST]`;
          lagBadgeClass = 'text-emerald-400 bg-emerald-950/60 border-emerald-500/40 shadow-sm shadow-emerald-500/10';
        } else if (ingestLagSeconds <= 360) { // 3 to 6 minutes
          lagText = `${lagM}m ${lagS}s [NORMAL]`;
          lagBadgeClass = 'text-amber-400 bg-amber-950/60 border-amber-500/40';
        } else {
          lagText = `${lagM}m ${lagS}s [DELAYED]`;
          lagBadgeClass = 'text-rose-400 bg-rose-950/60 border-rose-500/40';
        }
      }
    } catch {
      // Ignore timestamp parsing error
    }
  }

  const lastClosedBarDateStr = getLastClosedBarDate(nowIst, isMarketHours, currentBarIndex);

  const countdownMin = Math.floor(remainingSeconds / 60);
  const countdownSec = remainingSeconds % 60;

  return (
    <div className="w-full bg-dark-850/90 backdrop-blur-md border-b border-white/5 py-1.5 px-4 font-mono text-[11px] select-none text-slate-300">
      <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-y-1.5 gap-x-4">
        
        {/* Left Segment: Live IST Clock & Feed Authority */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 text-slate-200 font-semibold">
            <Clock className="w-3.5 h-3.5 text-cyan-400 animate-pulse" />
            <span suppressHydrationWarning>{nowIst.toLocaleTimeString('en-IN', { hour12: false })} IST</span>
          </div>

          <span className="text-slate-600">|</span>

          {/* Yahoo Last Closed Candle Proof */}
          <div className="flex items-center gap-1.5">
            <span className="text-slate-400">📊 Yahoo Last Bar:</span>
            <span className="font-bold text-slate-200 bg-dark-750 px-1.5 py-0.5 rounded border border-white/10 flex items-center">
              <span className="text-cyan-400 font-medium mr-1.5" suppressHydrationWarning>{lastClosedBarDateStr}</span>
              <span>{lastClosedBarStartStr} - {lastClosedBarEndStr}</span>
              <span className="text-slate-500 ml-1 font-normal">(Bar {lastClosedBarNumber})</span>
            </span>
          </div>
        </div>

        {/* Center Segment: Live Ingestion Latency Badge */}
        <div className="flex items-center gap-2">
          <span className="text-slate-400">⚡ Ingest Lag:</span>
          <span className={cn("px-2 py-0.5 rounded border font-bold flex items-center gap-1", lagBadgeClass)}>
            <Activity className="w-3 h-3" />
            {lagText}
          </span>
        </div>

        {/* Right Segment: Running Candle & Close Countdown */}
        {isMarketHours ? (
          <div className="flex items-center gap-2">
            <span className="text-slate-400">⏳ Forming:</span>
            <span className="text-indigo-300 font-bold">
              {formatMinutesToTimeStr(currentBarStartMin)} - {formatMinutesToTimeStr(currentBarEndMin)}
              <span className="text-indigo-400/80 font-normal ml-1">({elapsedPercent.toFixed(0)}%)</span>
            </span>

            {/* Micro 30px Progress Bar */}
            <div className="w-10 h-1.5 bg-dark-700 rounded-full overflow-hidden border border-white/10 hidden sm:block">
              <div 
                className="h-full bg-gradient-to-r from-cyan-400 to-indigo-400 rounded-full transition-all duration-1000"
                style={{ width: `${elapsedPercent}%` }}
              />
            </div>

            <span className="text-slate-600">|</span>

            <div className="flex items-center gap-1 text-amber-300 font-bold">
              <Timer className="w-3 h-3 text-amber-400" />
              <span suppressHydrationWarning>Closes in {countdownMin}m {padZero(countdownSec)}s</span>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 text-slate-400">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            <span>Market Session Settled (Offline)</span>
          </div>
        )}

      </div>
    </div>
  );
};
