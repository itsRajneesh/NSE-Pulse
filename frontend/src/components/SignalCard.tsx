"use client";

import React, { useState, useRef } from 'react';
import { 
  TrendingUp, 
  TrendingDown, 
  Zap, 
  Target, 
  ExternalLink, 
  Flame, 
  LineChart, 
  HelpCircle, 
  X,
  Activity,
  Clock,
  CheckCircle2,
  AlertTriangle,
  Radar
} from 'lucide-react';
import { V13Signal, V13UniverseStock, V13ChartTarget } from '@/types/screener';
import { formatINR, cn } from '@/lib/utils';

function getFactorRule(key: string, val: number, ind: any, isBullish: boolean, stock: V13UniverseStock) {
  const pointsText = val >= 0 ? `+${val}` : `${val}`;

  switch (key) {
    case 'volume': {
      const relVol = ind.rel_vol ?? stock.snapshot.rel_vol ?? '—';
      return {
        title: 'Volume Surge',
        valStr: `RelVol = ${relVol}x`,
        ruleStr: 'RelVol ≥ 3.0x → +12 | ≥ 2.0x → +10 | ≥ 1.5x → +8 | ≥ 1.2x → +4',
        soStr: `So: ${relVol}x → ${pointsText} pts`,
      };
    }
    case 'ema_alignment': {
      const ema = ind.ema20 ?? stock.snapshot.ema20 ?? '—';
      return {
        title: '20 EMA Alignment',
        valStr: `Price vs 20 EMA = ₹${ema}`,
        ruleStr: isBullish ? 'Price > EMA20 → +10 | Near EMA (-0.25 ATR) → +4' : 'Price < EMA20 → +10 | Near EMA (+0.25 ATR) → +4',
        soStr: `So: 20 EMA Alignment → ${pointsText} pts`,
      };
    }
    case 'vwap_alignment': {
      const vwap = ind.vwap ?? stock.snapshot.vwap ?? '—';
      return {
        title: 'VWAP Alignment',
        valStr: `Price vs VWAP = ₹${vwap}`,
        ruleStr: isBullish ? 'Price > VWAP → +10 | Near VWAP (-0.20 ATR) → +4' : 'Price < VWAP → +10 | Near VWAP (+0.20 ATR) → +4',
        soStr: `So: VWAP Alignment → ${pointsText} pts`,
      };
    }
    case 'rsi_momentum': {
      const rsi = ind.rsi14 ?? stock.snapshot.rsi14 ?? '—';
      return {
        title: 'RSI Momentum (14)',
        valStr: `RSI = ${rsi}`,
        ruleStr: isBullish ? '55 ≤ RSI ≤ 68 → +8 | 68–75 → +5 | 50–55 → +3' : '32 ≤ RSI ≤ 45 → +8 | 25–32 → +5 | 45–50 → +3',
        soStr: `So: RSI ${rsi} → ${pointsText} pts`,
      };
    }
    case 'opening_range': {
      const dist = ind.breakout_distance_atr != null ? `${ind.breakout_distance_atr} ATR` : 'Confirmed';
      return {
        title: 'Opening Range (OR)',
        valStr: `Breakout Distance = ${dist}`,
        ruleStr: isBullish ? 'Cross OR High → +18 | Dist ≥ -0.20 ATR → +10 | ≥ -0.50 ATR → +5' : 'Cross OR Low → +18 | Dist ≥ -0.20 ATR → +10 | ≥ -0.50 ATR → +5',
        soStr: `So: Opening Range → ${pointsText} pts`,
      };
    }
    case 'previous_day_level': {
      return {
        title: 'Prev Day High/Low',
        valStr: 'Price vs Prior Day Extreme',
        ruleStr: isBullish ? 'Cross PDH → +7 | Within 0.25 ATR → +3' : 'Cross PDL → +7 | Within 0.25 ATR → +3',
        soStr: `So: Prior Day Level → ${pointsText} pts`,
      };
    }
    case 'candle_quality': {
      return {
        title: 'Candle Quality',
        valStr: 'Expansion Body %',
        ruleStr: 'Strong Body (≥60% range) → +5 | Supportive Candle → +3',
        soStr: `So: Candle Quality → ${pointsText} pts`,
      };
    }
    case 'nifty_alignment': {
      const dirText = val > 0 
        ? (isBullish ? 'Aligned Bullish' : 'Aligned Bearish') 
        : val < 0 
          ? (isBullish ? 'Opposing (Nifty Bearish)' : 'Opposing (Nifty Bullish)') 
          : 'Neutral / Range-bound';
      return {
        title: 'NIFTY 50 Alignment',
        valStr: `Nifty Trend: ${dirText}`,
        ruleStr: 'Nifty Aligned → +5 | Opposing → -2.5 | Neutral → 0',
        soStr: `So: NIFTY Alignment → ${pointsText} pts`,
      };
    }
    case 'sector_alignment': {
      const secName = stock.sector || 'NSE Sector';
      const dirText = val > 0 
        ? (isBullish ? 'Aligned Bullish (Breadth ≥60%)' : 'Aligned Bearish (Breadth ≥60%)') 
        : val < 0 
          ? 'Opposing Sector Headwind' 
          : 'Neutral / Gate Locked (<60)';
      return {
        title: 'Sector Breadth Alignment',
        valStr: `${secName}: ${dirText}`,
        ruleStr: 'Sector Aligned (Own Score ≥60) → +5 | Opposing → -2.5 | Neutral → 0',
        soStr: `So: Sector Breadth → ${pointsText} pts`,
      };
    }
    case 'market_context':
    case 'context_alignment':
    case 'market_sector_alignment': {
      return {
        title: 'Market & Sector Alignment',
        valStr: `Sector: ${stock.sector || 'Market'}`,
        ruleStr: 'Nifty (+5/-2.5) + Sector (+5/-2.5) Combined',
        soStr: `So: Market & Sector Alignment → ${pointsText} pts`,
      };
    }
    case 'trend_structure': {
      const stateStr = val >= 12
        ? (isBullish ? 'Full 3-Pillar Trend Expansion (HH+HL+Close/VWAP Hold)' : 'Full 3-Pillar Bear Expansion (LL+LH+Close/VWAP Hold)')
        : val >= 8 
          ? (isBullish ? 'Higher-Highs & Higher-Lows (HH+HL)' : 'Lower-Lows & Lower-Highs (LL+LH)')
          : val >= 4 
            ? (isBullish ? 'Higher-Lows / Structure Hold (+4)' : 'Lower-Highs / Structure Hold (+4)')
            : 'Structure not expanding (No HH / HL)';
      return {
        title: '15m Trend Structure',
        valStr: stateStr,
        ruleStr: isBullish 
          ? 'HH (+4) + Progressive HL (+4) + Multi-Bar Close / 3-Bar VWAP Hold (+4) → Max +12'
          : 'LL (+4) + Progressive LH (+4) + Multi-Bar Close / 3-Bar VWAP Hold (+4) → Max +12',
        soStr: `So: Trend Structure → ${pointsText} pts`,
      };
    }
    case 'true_velocity': {
      const vel = ind.true_velocity ?? stock.snapshot.true_velocity ?? '?';
      return {
        title: 'True Velocity',
        valStr: `True Velocity = ${typeof vel === 'number' ? vel.toFixed(2) : vel}`,
        ruleStr: 'Vel ≥ 5.0 → +8 | ≥ 3.0 → +6 | ≥ 2.0 → +4 | ≥ 1.0 → +2',
        soStr: `So: True Velocity → ${pointsText} pts`,
      };
    }
    case 'extension_chase': {
      return {
        title: 'Extension / Chase Penalty',
        valStr: val < 0 ? (val <= -8 ? 'Overextended > 2.5 ATR from VWAP' : 'Extended > 2.0 ATR from VWAP') : 'Optimal distance from VWAP',
        ruleStr: 'Extended > 2.5 ATR → -8 | > 2.0 ATR → -4 | Normal → 0',
        soStr: `So: Extension Penalty → ${pointsText} pts`,
      };
    }
    case 'trade_risk_penalties': {
      return {
        title: 'Trade Risk Penalties',
        valStr: val < 0 ? 'Risk / OR width penalty applied' : 'Optimal Stop & OR Width',
        ruleStr: 'OR Width > 2.5 ATR → -5 | Stop < 0.35 ATR → -3',
        soStr: `So: Risk Penalties → ${pointsText} pts`,
      };
    }
    default: {
      const title = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
      return {
        title,
        valStr: `Factor Evaluation`,
        ruleStr: 'Quantitative engine factor weighting',
        soStr: `So: ${title} → ${pointsText} pts`,
      };
    }
  }
}

function parseSignalBar(signalTimeStr?: string | null): { timeDisplay: string; barNum: number | null } {
  if (!signalTimeStr) return { timeDisplay: '', barNum: null };
  try {
    let hours = 0;
    let mins = 0;
    if (signalTimeStr.includes('T') || signalTimeStr.includes('-')) {
      const d = new Date(signalTimeStr);
      if (!isNaN(d.getTime())) {
        hours = d.getHours();
        mins = d.getMinutes();
      }
    } else {
      const parts = signalTimeStr.split(':');
      if (parts.length >= 2) {
        hours = parseInt(parts[0], 10);
        mins = parseInt(parts[1], 10);
      }
    }
    const timeDisplay = `${hours < 10 ? '0' + hours : hours}:${mins < 10 ? '0' + mins : mins}`;
    const totalMinutes = hours * 60 + mins;
    const marketOpen = 9 * 60 + 15; // 09:15 IST
    if (totalMinutes >= marketOpen && totalMinutes <= 15 * 60 + 30) {
      const barNum = Math.floor((totalMinutes - marketOpen) / 15) + 1;
      return { timeDisplay, barNum: Math.min(25, Math.max(1, barNum)) };
    }
    return { timeDisplay, barNum: null };
  } catch {
    return { timeDisplay: signalTimeStr.slice(0, 5), barNum: null };
  }
}

interface SignalCardProps {
  stock: V13UniverseStock;
  onOpenChart: (stock: V13ChartTarget) => void;
}

export const SignalCard: React.FC<SignalCardProps> = ({ stock, onOpenChart }) => {
  const signal = stock.signals[0] ?? null;
  const score = signal?.score ?? 0;
  // Score >= 72 is the strict threshold for Bullish or Bearish categorization badge & card styling
  const isBullish = signal?.direction === 'BULLISH' && score >= 72;
  const isBearish = signal?.direction === 'BEARISH' && score >= 72;
  const isActive = score >= 72 && signal !== null;
  const isDiagnostic = signal !== null && score > 0 && score < 72;
  
  // Toggle for Card Trigger Timestamps
  const isCardTimestampsEnabled = process.env.NEXT_PUBLIC_ENABLE_CARD_TIMESTAMPS !== 'false';

  const tp = signal?.risk ?? null;
  const ind = signal?.indicators ?? {
    ema20: stock.snapshot.ema20,
    rsi14: stock.snapshot.rsi14,
    rel_vol: stock.snapshot.rel_vol,
    vwap: stock.snapshot.vwap,
    atr14: stock.snapshot.atr14,
    true_velocity: stock.snapshot.true_velocity,
    breakout_distance_atr: null,
  };

  const classification = signal?.score_classification ?? (
    score >= 85 ? 'HIGH CONFIDENCE' :
    score >= 80 ? 'STRONG' :
    score >= 72 ? 'WATCH' : 'BELOW THRESHOLD'
  );

  // Click state for Score Breakdown Overlay
  const [showBreakdown, setShowBreakdown] = useState<boolean>(false);

  const scoreBreakdown = signal?.score_breakdown ?? {};

  // Live Target Tracker (P&L Bar) Calculation
  const currentLtp = signal?.price ?? stock.snapshot.price ?? 0;
  const relVolNum = typeof ind.rel_vol === 'number' 
    ? ind.rel_vol 
    : (typeof stock.snapshot?.rel_vol === 'number' ? stock.snapshot.rel_vol : 0);
  const sessionVol = typeof stock.snapshot?.volume === 'number' ? stock.snapshot.volume : 0;
  const sessionTurnoverCr = (sessionVol * currentLtp) / 10_000_000;
  const isSub20Exempt = currentLtp > 0 && currentLtp < 20.0 && sessionTurnoverCr >= 50.0;
  const isPennyBelowFloor = currentLtp > 0 && currentLtp < 20.0 && !isSub20Exempt;
  const isVolQualified = relVolNum >= 1.20;

  // Opening Range & Breakout Targets
  const openingRangeHigh = signal?.confirmation?.opening_range_high ?? stock.snapshot?.opening_range_high ?? stock.snapshot?.high ?? 0;
  const openingRangeLow = signal?.confirmation?.opening_range_low ?? stock.snapshot?.opening_range_low ?? stock.snapshot?.low ?? 0;

  // Boundary Cross Detection & Multi-Factor Intraday Direction Inference (Pillar 3)
  const isAboveOrHigh = openingRangeHigh > 0 && currentLtp > openingRangeHigh;
  const isBelowOrLow = openingRangeLow > 0 && currentLtp < openingRangeLow;
  const hasCrossedOr = isAboveOrHigh || isBelowOrLow;

  const snapVwap = stock.snapshot?.vwap ?? null;
  const snapEma20 = stock.snapshot?.ema20 ?? null;
  const snapRsi = stock.snapshot?.rsi14 ?? 50;
  const snapChg = stock.snapshot?.latest_session_change_pct ?? 0;

  const aboveVwap = snapVwap !== null && snapVwap > 0 ? currentLtp >= snapVwap : snapChg >= 0;
  const aboveEma = snapEma20 !== null && snapEma20 > 0 ? currentLtp >= snapEma20 : snapChg >= 0;
  const bullishRsi = snapRsi >= 50;
  const techBullVotes = (aboveVwap ? 1 : 0) + (aboveEma ? 1 : 0) + (bullishRsi ? 1 : 0);
  const inferredBullish = techBullVotes >= 2;

  const isLongTrade = signal
    ? signal.direction === 'BULLISH'
    : (isBelowOrLow ? false : (isAboveOrHigh ? true : inferredBullish));
  const isSignalBullish = signal ? signal.direction === 'BULLISH' : isLongTrade;

  // Wide Opening Range Exhaustion Guard (> 4.0x ATR14 rejects in v13_engine.py)
  const atrVal = typeof ind.atr14 === 'number' && ind.atr14 > 0 ? ind.atr14 : 0;
  const orWidth = openingRangeHigh > openingRangeLow ? (openingRangeHigh - openingRangeLow) : 0;
  const isOrExhausted = atrVal > 0 && orWidth > 4.0 * atrVal;

  // Pre-Breakout Radar Candidate vs Safety Gate Filtered (No Setup)
  const isRadarCandidate = !isActive && signal === null && isVolQualified && !isPennyBelowFloor && !hasCrossedOr && !isOrExhausted;
  const isSafetyGateFiltered = !isActive && signal === null && isVolQualified && !isPennyBelowFloor && (hasCrossedOr || isOrExhausted);

  // Radar Proximity Calculation (Direction-Aware: OR High for Bullish, OR Low for Bearish)
  const breakoutTarget = isLongTrade
    ? (openingRangeHigh > 0 ? openingRangeHigh : 0)
    : (openingRangeLow > 0 ? openingRangeLow : 0);
  const distToBreakout = (breakoutTarget > 0 && currentLtp > 0)
    ? (isLongTrade ? (breakoutTarget - currentLtp) : (currentLtp - breakoutTarget))
    : 0;
  const distToBreakoutPct = (breakoutTarget > 0 && currentLtp > 0)
    ? (distToBreakout / currentLtp) * 100
    : 0;

  let proximityGaugePct = 50;
  if (openingRangeHigh > 0 && openingRangeLow > 0 && openingRangeHigh > openingRangeLow) {
    const rawPos = ((currentLtp - openingRangeLow) / (openingRangeHigh - openingRangeLow)) * 100;
    proximityGaugePct = Math.min(100, Math.max(5, isLongTrade ? rawPos : (100 - rawPos)));
  } else if (breakoutTarget > 0 && currentLtp > 0) {
    proximityGaugePct = Math.min(95, Math.max(10, 100 - (Math.max(0, distToBreakout) / currentLtp) * 100));
  }

  // Classic 15m Candle Breakout Plan (Test Feature: 2-Second Hold)
  const isClassicOrbPreviewEnabled = process.env.NEXT_PUBLIC_ENABLE_CLASSIC_ORB_PREVIEW !== 'false';
  const [isClassicMode, setIsClassicMode] = useState<boolean>(false);
  const [isHolding, setIsHolding] = useState<boolean>(false);
  const holdTimerRef = useRef<NodeJS.Timeout | null>(null);

  React.useEffect(() => {
    return () => {
      if (holdTimerRef.current) clearTimeout(holdTimerRef.current);
    };
  }, []);

  const orHigh = signal?.confirmation?.opening_range_high ?? (openingRangeHigh > 0 ? openingRangeHigh : (isLongTrade ? tp?.entry : tp?.stop_loss));
  const orLow = signal?.confirmation?.opening_range_low ?? (openingRangeLow > 0 ? openingRangeLow : (isLongTrade ? tp?.stop_loss : tp?.entry));

  const classicPlan = React.useMemo(() => {
    if (!orHigh || !orLow || orHigh <= orLow) return null;
    const isBull = isLongTrade;
    const cEntry = isBull ? orHigh : orLow;
    const cSl = isBull ? orLow : orHigh;
    const cRisk = Math.abs(cEntry - cSl);
    if (cRisk <= 0) return null;
    const roundTick = (v: number) => Math.round(v * 20) / 20;
    const cT1 = roundTick(isBull ? cEntry + (1.5 * cRisk) : cEntry - (1.5 * cRisk));
    const cT2 = roundTick(isBull ? cEntry + (2.5 * cRisk) : cEntry - (2.5 * cRisk));
    const cLiveRisk = currentLtp > 0 ? Math.abs(currentLtp - cSl) : cRisk;
    return {
      entry: cEntry,
      stop_loss: cSl,
      risk_amount: cRisk,
      target_1: cT1,
      target_2: cT2,
      risk_reward_t1: '1:1.5',
      risk_reward_t2: '1:2.5',
      live_risk: cLiveRisk,
    };
  }, [orHigh, orLow, isLongTrade, currentLtp]);

  // Display Plan: Strict engine risk plan ONLY when signal is present (Never fabricate classicPlan for Score 0 / NO_SETUP)
  const displayTp = tp;

  const entry = displayTp?.entry ?? currentLtp;
  const sl = displayTp?.stop_loss ?? entry;
  const t1 = displayTp?.target_1 ?? entry;
  const t2 = displayTp?.target_2 ?? entry;
  const liveRisk = (displayTp?.stop_loss != null && currentLtp > 0)
    ? Math.abs(currentLtp - displayTp.stop_loss)
    : null;

  const startHold = () => {
    if (!isClassicOrbPreviewEnabled || !classicPlan) return;
    setIsHolding(true);
    if (holdTimerRef.current) clearTimeout(holdTimerRef.current);
    holdTimerRef.current = setTimeout(() => {
      setIsClassicMode(true);
    }, 2000);
  };

  const cancelHold = () => {
    setIsHolding(false);
    if (holdTimerRef.current) {
      clearTimeout(holdTimerRef.current);
      holdTimerRef.current = null;
    }
    setIsClassicMode(false);
  };

  // Active values: seamlessly switches to classicPlan during 2s hold preview
  const activeEntry = isClassicMode && classicPlan ? classicPlan.entry : entry;
  const activeSl = isClassicMode && classicPlan ? classicPlan.stop_loss : sl;
  const activeT1 = isClassicMode && classicPlan ? classicPlan.target_1 : t1;
  const activeT2 = isClassicMode && classicPlan ? classicPlan.target_2 : t2;
  const activeRisk = isClassicMode && classicPlan ? classicPlan.risk_amount : (displayTp?.risk_amount ?? null);
  const activeLiveRisk = isClassicMode && classicPlan ? classicPlan.live_risk : liveRisk;
  const activeRr1 = isClassicMode && classicPlan ? classicPlan.risk_reward_t1 : (displayTp?.risk_reward_t1 || '?');
  const activeRr2 = isClassicMode && classicPlan ? classicPlan.risk_reward_t2 : (displayTp?.risk_reward_t2 || '?');

  let pnlDiff = 0;
  let pnlPct = 0;
  let t1Progress = 0;
  let trackerStatus = '';
  let trackerColor = 'text-slate-400';

  const isPullback = Boolean(
    activeEntry > 0 && activeSl > 0 && (
      isLongTrade
        ? (currentLtp < activeEntry && currentLtp >= activeSl)
        : (currentLtp > activeEntry && currentLtp <= activeSl)
    )
  );

  if (activeEntry > 0) {
    if (isLongTrade) {
      pnlDiff = currentLtp - activeEntry;
      pnlPct = (pnlDiff / activeEntry) * 100;
      const t1Dist = activeT1 - activeEntry;

      if (currentLtp >= activeT1 && activeT1 > activeEntry) {
        t1Progress = 100;
        trackerStatus = `🚀 T1 Hit! (+₹${pnlDiff.toFixed(2)} | +${pnlPct.toFixed(1)}%)`;
        trackerColor = 'text-emerald-400 font-bold';
      } else if (currentLtp >= activeEntry) {
        t1Progress = t1Dist > 0 ? Math.min(100, Math.max(0, ((currentLtp - activeEntry) / t1Dist) * 100)) : 0;
        trackerStatus = `🎯 T1: ${t1Progress.toFixed(0)}% reached (+₹${pnlDiff.toFixed(2)} | +${pnlPct.toFixed(1)}%)`;
        trackerColor = 'text-emerald-300 font-bold';
      } else if (currentLtp >= activeSl) {
        t1Progress = 0;
        trackerStatus = `🔄 Pullback in Zone (-₹${Math.abs(pnlDiff).toFixed(2)} | ${pnlPct.toFixed(1)}%)`;
        trackerColor = 'text-amber-400 font-semibold';
      } else {
        t1Progress = 0;
        trackerStatus = `⚠️ Below SL (-₹${Math.abs(pnlDiff).toFixed(2)})`;
        trackerColor = 'text-rose-400 font-bold';
      }
    } else {
      pnlDiff = activeEntry - currentLtp;
      pnlPct = (pnlDiff / activeEntry) * 100;
      const t1Dist = activeEntry - activeT1;

      if (currentLtp <= activeT1 && activeT1 > 0 && activeT1 < activeEntry) {
        t1Progress = 100;
        trackerStatus = `🚀 T1 Hit! (+₹${pnlDiff.toFixed(2)} | +${pnlPct.toFixed(1)}%)`;
        trackerColor = 'text-emerald-400 font-bold';
      } else if (currentLtp <= activeEntry) {
        t1Progress = t1Dist > 0 ? Math.min(100, Math.max(0, ((activeEntry - currentLtp) / t1Dist) * 100)) : 0;
        trackerStatus = `🎯 T1: ${t1Progress.toFixed(0)}% reached (+₹${pnlDiff.toFixed(2)} | +${pnlPct.toFixed(1)}%)`;
        trackerColor = 'text-emerald-300 font-bold';
      } else if (currentLtp <= activeSl) {
        t1Progress = 0;
        trackerStatus = `🔄 Pullback in Zone (-₹${Math.abs(pnlDiff).toFixed(2)} | ${pnlPct.toFixed(1)}%)`;
        trackerColor = 'text-amber-400 font-semibold';
      } else {
        t1Progress = 0;
        trackerStatus = `⚠️ Above SL (-₹${Math.abs(pnlDiff).toFixed(2)})`;
        trackerColor = 'text-rose-400 font-bold';
      }
    }
  }

  return (
    <div 
      className={cn(
        "glass-panel rounded-xl p-3 sm:p-3.5 transition-all duration-300 relative overflow-hidden flex flex-col justify-between group select-none",
        isBullish && isActive && "border-emerald-500/40 glow-bullish-card bg-emerald-950/15 hover:border-emerald-400/60",
        isBearish && isActive && "border-rose-500/40 glow-bearish-card bg-rose-950/15 hover:border-rose-400/60",
        isRadarCandidate && "border-cyan-500/35 bg-gradient-to-b from-dark-850/95 via-dark-900 to-cyan-950/10 shadow-lg shadow-cyan-950/20 hover:border-cyan-400/50 hover:bg-dark-800/90",
        !isActive && !isRadarCandidate && "border-white/5 bg-dark-850/50 hover:bg-dark-800/70 hover:border-white/10 opacity-90 hover:opacity-100"
      )}
    >
      {/* Dynamic Animated Score Breakdown Overlay (Opens on Click, Closes on 'X' or backdrop) */}
      {showBreakdown && (
        <div 
          onClick={(e) => e.stopPropagation()}
          className="absolute inset-0 bg-dark-900/95 backdrop-blur-md z-30 p-3 flex flex-col justify-between animate-fade-in border border-indigo-500/50 rounded-xl select-none shadow-2xl h-full"
        >
          <div className="flex items-center justify-between border-b border-white/10 pb-2 mb-2 flex-shrink-0">
            <div className="flex items-center gap-1.5 text-xs font-bold text-indigo-300">
              <Zap className="w-3.5 h-3.5 text-amber-400 animate-bounce" />
              <span>Score Breakdown: {stock.symbol} ({score}/100)</span>
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation();
                setShowBreakdown(false);
              }}
              className="p-1 rounded-md bg-dark-750 hover:bg-dark-700 text-slate-400 hover:text-white border border-white/10 transition-colors"
              title="Close Breakdown"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto pr-1 space-y-1.5 custom-scrollbar">
            {Object.entries(scoreBreakdown).length > 0 ? (
              Object.entries(scoreBreakdown)
                .filter(([key]) => {
                  if (key === 'market_sector_alignment' && ('nifty_alignment' in scoreBreakdown || 'sector_alignment' in scoreBreakdown)) {
                    return false;
                  }
                  return true;
                })
                .map(([key, rawVal]) => {
                const val = rawVal ?? 0;
                const factor = getFactorRule(key, val, ind, isSignalBullish, stock);
                return (
                  <div key={key} className="p-1.5 rounded-lg bg-dark-800/90 border border-white/10 text-[10px]">
                    <div className="flex justify-between items-center">
                      <span className="font-bold text-slate-200">{factor.title}</span>
                      <span className={cn("font-bold font-mono px-1.5 py-0.2 rounded text-[10px]", val >= 0 ? "bg-emerald-950/80 text-emerald-400 border border-emerald-500/30" : "bg-rose-950/80 text-rose-400 border border-rose-500/30")}>
                        {val >= 0 ? `+${val}` : val}
                      </span>
                    </div>
                    <div className="text-cyan-300 font-mono text-[9.5px] mt-0.5">{factor.valStr}</div>
                    <div className="text-slate-400 text-[8.5px] mt-0.5">rule: {factor.ruleStr}</div>
                    <div className="text-amber-300 font-bold font-mono text-[9px] mt-0.5">{factor.soStr}</div>
                  </div>
                );
              })
            ) : (
              <div className="text-slate-400 text-center py-4 text-xs font-sans">
                Score components: 
                <div className="mt-1 text-[11px] text-indigo-300 font-mono">
                  Trend, EMA, VWAP, RSI, Volume, OR, PDL, Velocity
                </div>
              </div>
            )}
          </div>

          <div className="text-[9px] text-slate-400 text-center border-t border-white/10 pt-1.5 mt-2 flex justify-between items-center flex-shrink-0">
            <span className="text-slate-400">Click ✕ to close</span>
            <span className={cn(
              "px-1.5 py-0.5 rounded font-bold text-[10px]",
              classification === 'HIGH CONFIDENCE' ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40" :
              classification === 'STRONG' ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40" :
              classification === 'WATCH' ? "bg-amber-500/20 text-amber-300 border border-amber-500/40" :
              "bg-slate-800 text-rose-300 border border-rose-500/30"
            )}>
              {classification}
            </span>
          </div>
        </div>
      )}

      <div>
        <div className="mb-2 space-y-1">
          {/* Line 1: Symbol & Universe Badge on Left, Classification Badge on Right */}
          <div className="flex items-center justify-between gap-1.5 min-h-[26px]">
            <div className="flex items-center gap-1.5 min-w-0">
              <h3 className="font-bold text-base sm:text-lg text-white tracking-tight group-hover:text-indigo-400 transition-colors whitespace-nowrap">
                {stock.symbol}
              </h3>
              {stock.is_nifty500 ? (
                <span className="px-1.5 py-0.2 text-[8.5px] font-semibold bg-blue-950/80 text-blue-300 rounded border border-blue-500/30 whitespace-nowrap flex-shrink-0" title="Nifty 500 Index Constituent">
                  NIFTY 500
                </span>
              ) : (
                <span className="px-1.5 py-0.2 text-[8.5px] font-semibold bg-purple-950/80 text-purple-300 rounded border border-purple-500/30 whitespace-nowrap flex-shrink-0" title="NSE Expanded Equity (≥ 1,000 Cr)">
                  ≥1000 CR
                </span>
              )}
            </div>

            {/* Setup Classification / Target Hit Badge (Top Right - Strictly Gated by isActive for Active Badges) */}
            <div className="flex-shrink-0">
              {isActive && t1Progress >= 100 ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9.5px] font-bold bg-emerald-500/25 text-emerald-300 border border-emerald-400/50 shadow-sm animate-pulse whitespace-nowrap" title="Target 1 Achieved!">
                  🏆 TARGET 1 HIT
                </span>
              ) : isActive && classification === 'EARLY TRIGGER' ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9.5px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-sm animate-pulse whitespace-nowrap">
                  ⚡ EARLY TRIGGER
                </span>
              ) : isActive && classification === 'HIGH CONFIDENCE' ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9.5px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 shadow-sm animate-pulse-subtle whitespace-nowrap">
                  🚀 HIGH CONFIDENCE
                </span>
              ) : isActive && classification === 'STRONG' ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9.5px] font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm whitespace-nowrap">
                  ⚡ STRONG
                </span>
              ) : isActive && classification === 'WATCH' ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9.5px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40 shadow-sm whitespace-nowrap">
                  👀 WATCH
                </span>
              ) : isDiagnostic ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9.5px] font-bold bg-slate-800 text-rose-300 border border-rose-500/30 shadow-sm whitespace-nowrap" title="Diagnostic setup below V13 threshold (<72)">
                  📊 BELOW THRESHOLD
                </span>
              ) : isRadarCandidate ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9.5px] font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-400/40 shadow-sm whitespace-nowrap animate-pulse" title="Pre-Breakout Volume Surge Surveillance">
                  <Radar className="w-2.5 h-2.5 text-cyan-400" />
                  SURGE RADAR
                </span>
              ) : isPennyBelowFloor ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9.5px] font-bold bg-rose-950/60 text-rose-300 border border-rose-500/30 shadow-sm whitespace-nowrap" title="Micro-Penny Filter: LTP < ₹20.00 base floor guard">
                  ⚠️ FLOOR &lt; ₹20
                </span>
              ) : isSafetyGateFiltered ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9.5px] font-bold bg-slate-800 text-amber-300/90 border border-amber-500/30 shadow-sm whitespace-nowrap" title="Filtered by V13 Safety Gates (Wide OR / ATR Exhaustion / VWAP or Non-F&O Short Guard)">
                  🚫 GATE FILTERED
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9.5px] font-bold bg-dark-750 text-slate-400 border border-white/5 shadow-sm whitespace-nowrap">
                  📊 MONITORING
                </span>
              )}
            </div>
          </div>

          {/* Line 2: Company Name on Left, Sector Badge on Right */}
          <div className="flex items-center justify-between gap-1.5 min-h-[20px]">
            <p className="text-[11px] text-slate-400 truncate flex-1 min-w-0" title={stock.name}>
              {stock.name}
            </p>

            {stock.sector && (
              <span className="px-1.5 py-0.2 text-[9px] font-medium bg-dark-750 text-slate-300 rounded border border-white/5 whitespace-nowrap flex-shrink-0 max-w-[110px] sm:max-w-[130px] truncate" title={stock.sector}>
                {stock.sector}
              </span>
            )}
          </div>

          {/* Active Direction Badge & Pullback Status (Only if active signal >= 72) */}
          {score >= 72 && (
            <div className="flex items-center justify-end gap-1.5 pt-0.5">
              {isPullback && (
                <span className="px-1.5 py-0.5 text-[9.5px] font-bold rounded border flex items-center gap-1 shadow-sm bg-amber-500/20 text-amber-300 border-amber-500/40 animate-pulse whitespace-nowrap" title="Retesting / Pullback in Zone">
                  🔄 PULLBACK IN ZONE
                </span>
              )}
              <span className={cn(
                "px-1.5 py-0.5 text-[9.5px] font-bold rounded border flex items-center gap-1 shadow-sm whitespace-nowrap",
                isLongTrade 
                  ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40" 
                  : "bg-rose-500/20 text-rose-300 border-rose-500/40"
              )}>
                {isLongTrade ? "🟢 BULLISH LONG" : "🔴 BEARISH SHORT"}
              </span>
            </div>
          )}
        </div>

        <div className="flex items-baseline justify-between py-1.5 border-y border-white/5 my-2">
          <div>
            <div className="text-xl sm:text-2xl font-black font-mono tracking-tight text-white">
              {signal?.price !== null && signal?.price !== undefined
                ? formatINR(signal.price)
                : stock.snapshot.price !== null && stock.snapshot.price !== undefined
                  ? formatINR(stock.snapshot.price)
                  : '—'}
            </div>
            <div className="text-[9.5px] text-slate-400">Last Traded Price</div>
          </div>

          <div 
            className="text-right cursor-pointer"
            onClick={(e) => {
              e.stopPropagation();
              setShowBreakdown(true);
            }}
            title="Click to view Score Breakdown detail"
          >
            {isActive ? (
              <div className={cn(
                "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10.5px] font-bold font-mono transition-transform hover:scale-105",
                score >= 85 ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30" :
                score >= 80 ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/30" :
                "bg-amber-500/20 text-amber-300 border border-amber-500/30"
              )}>
                <Zap className="w-2.5 h-2.5" />
                <span>Score {score}</span>
              </div>
            ) : isRadarCandidate ? (
              <div className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10.5px] font-bold font-mono bg-cyan-500/20 text-cyan-300 border border-cyan-400/40 transition-transform hover:scale-105">
                <Radar className="w-2.5 h-2.5 text-cyan-400 animate-pulse" />
                <span>Pending Breakout</span>
              </div>
            ) : (
              <div className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10.5px] font-bold font-mono bg-slate-800 text-slate-400 border border-white/10 transition-transform hover:scale-105">
                <Zap className="w-2.5 h-2.5 text-slate-500" />
                <span>Score {score}</span>
              </div>
            )}
            <div className={cn(
              "text-[8.5px] mt-0.5 flex items-center justify-end gap-0.5",
              isRadarCandidate ? "text-cyan-300/80 font-mono" : "text-indigo-300"
            )}>
              <HelpCircle className="w-2.5 h-2.5" />
              <span>{isRadarCandidate ? `Score ${score} • Inspect` : 'Click to inspect'}</span>
            </div>
          </div>
        </div>

        {/* Technical Indicators Row */}
        <div className="grid grid-cols-3 gap-1 mb-2.5 text-center text-[10.5px]">
          <div 
            className={cn(
              "p-1 sm:p-1.5 rounded-lg border flex flex-col items-center justify-center",
              (ind.rel_vol ?? 0) >= 1.5 
                ? "bg-amber-500/10 border-amber-500/30 text-amber-300" 
                : "bg-dark-800 border-white/5 text-slate-400"
            )}
          >
            <div className="flex items-center gap-0.5 font-bold font-mono text-xs">
              {(ind.rel_vol ?? 0) >= 1.5 && <Flame className="w-3 h-3 text-amber-400" />}
              {ind.rel_vol ?? '?'}x
            </div>
            <span className="text-[8.5px] text-slate-400 mt-0.5 whitespace-nowrap">RelVol (20d)</span>
          </div>

          <div className="p-1 sm:p-1.5 rounded-lg bg-dark-800 border border-white/5 text-slate-300 flex flex-col items-center justify-center">
            <div className="font-bold font-mono text-indigo-300 text-xs">
              {ind.ema20 ?? '?'}
            </div>
            <span className="text-[8.5px] text-slate-400 mt-0.5 whitespace-nowrap">20 EMA (15m)</span>
          </div>

          <div 
            className={cn(
              "p-1 sm:p-1.5 rounded-lg border flex flex-col items-center justify-center",
              (ind.rsi14 ?? 50) >= 60 ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-300" :
              (ind.rsi14 ?? 50) <= 40 ? "bg-rose-500/10 border-rose-500/20 text-rose-300" :
              "bg-dark-800 border-white/5 text-slate-400"
            )}
          >
            <div className="font-bold font-mono text-xs">
              {ind.rsi14 ?? '?'}
            </div>
            <span className="text-[8.5px] text-slate-400 mt-0.5 whitespace-nowrap">RSI (14)</span>
          </div>
        </div>

        {/* Trade Execution Plan (Rendered strictly for setups with native engine risk plan) */}
        {displayTp ? (
          <div 
            onMouseEnter={startHold}
            onMouseLeave={cancelHold}
            onMouseDown={startHold}
            onMouseUp={cancelHold}
            onTouchStart={startHold}
            onTouchEnd={cancelHold}
            className={cn(
              "rounded-xl p-2.5 sm:p-3 border mb-2.5 space-y-1.5 transition-all duration-300 select-none",
              isClassicMode 
                ? "bg-amber-950/25 border-amber-500/50 shadow-md shadow-amber-500/10 ring-1 ring-amber-500/30" 
                : (isHolding ? "bg-dark-850/90 border-amber-500/30 ring-1 ring-amber-500/20" : "bg-dark-850/80 border-white/5")
            )}
            title={isClassicOrbPreviewEnabled ? "Hold for 2 seconds to preview Pure 15m Candle Breakout Plan" : undefined}
          >
            <div className="flex items-center justify-between text-[10.5px] font-semibold border-b border-white/5 pb-1">
              <span className="flex items-center gap-1">
                {isClassicMode ? (
                  <>
                    <Zap className="w-3.5 h-3.5 text-amber-400 animate-pulse" />
                    <span className="text-amber-300 font-bold">Pure 15m Candle Plan</span>
                    <span className="text-[8.5px] bg-amber-500/20 text-amber-300 px-1 py-0.2 rounded border border-amber-500/30 font-sans ml-1">
                      15m High/Low
                    </span>
                  </>
                ) : (
                  <>
                    <Target className="w-3.5 h-3.5 text-indigo-400" />
                    <span className="text-slate-300">
                      {isActive ? 'Trade Execution Plan' : 'Diagnostic Levels (<72)'}
                    </span>
                    {isHolding && (
                      <span className="text-[9px] text-amber-400/90 animate-pulse font-sans ml-1 font-normal">
                        (Holding 2s...)
                      </span>
                    )}
                  </>
                )}
              </span>
              <div className="flex items-center gap-1 text-[9.5px] font-mono">
                {activeLiveRisk !== null && (
                  <>
                    <span 
                      className={cn("font-bold", isClassicMode ? "text-amber-400" : "text-amber-300")}
                      title={`Live Risk per share: |LTP (${formatINR(currentLtp)}) - SL (${activeSl !== null ? formatINR(activeSl) : '?'})|`}
                    >
                      Live: {formatINR(activeLiveRisk)}/sh
                    </span>
                    <span className="text-slate-500 font-normal">|</span>
                  </>
                )}
                <span 
                  className={isClassicMode ? "text-amber-200" : "text-indigo-400"}
                  title="Planned Risk per share: |Entry - SL|"
                >
                  Plan: {activeRisk !== null ? formatINR(activeRisk) : '?'}/sh
                </span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-1.5 text-xs font-mono">
              <div className={cn("p-1.5 rounded-lg border", isClassicMode ? "bg-amber-950/40 border-amber-500/30" : "bg-dark-750/70 border-cyan-500/20")}>
                <span className={cn("text-[9.5px] block font-sans", isClassicMode ? "text-amber-300 font-medium" : "text-cyan-400")}>
                  {isClassicMode 
                    ? (!isSignalBullish ? '15m Candle Low (Entry)' : '15m Candle High (Entry)') 
                    : (score >= 72 ? (!isSignalBullish ? 'Breakdown Entry' : 'Breakout Entry') : 'Evaluation Entry')}
                </span>
                <span className={cn("font-bold text-xs", isClassicMode ? "text-amber-200" : "text-cyan-200")}>
                  {activeEntry !== null ? formatINR(activeEntry) : '?'}
                </span>
              </div>

              <div className={cn("p-1.5 rounded-lg border", isClassicMode ? "bg-rose-950/40 border-rose-500/40" : "bg-dark-750/70 border-rose-500/20")}>
                <span className="text-[9.5px] text-rose-400 block font-sans">
                  {isClassicMode ? (!isSignalBullish ? '15m Candle High (SL)' : '15m Candle Low (SL)') : 'Stop Loss (SL)'}
                </span>
                <span className="font-bold text-xs text-rose-200">
                  {activeSl !== null ? formatINR(activeSl) : '?'}
                </span>
              </div>

              <div className="bg-dark-750/70 p-1.5 rounded-lg border border-emerald-500/20">
                <div className="flex items-center justify-between text-[9.5px] text-emerald-400 font-sans">
                  <span>Target 1</span>
                  <span className="text-[8.5px] bg-emerald-900/60 px-1 rounded text-emerald-200">{activeRr1} RR</span>
                </div>
                <span className="font-bold text-xs text-emerald-200">{activeT1 !== null ? formatINR(activeT1) : '?'}</span>
              </div>

              <div className="bg-dark-750/70 p-1.5 rounded-lg border border-emerald-500/30">
                <div className="flex items-center justify-between text-[9.5px] text-emerald-400 font-sans">
                  <span>Target 2</span>
                  <span className="text-[8.5px] bg-emerald-900/60 px-1 rounded text-emerald-200">{activeRr2} RR</span>
                </div>
                <span className="font-bold text-xs text-emerald-200">{activeT2 !== null ? formatINR(activeT2) : '?'}</span>
              </div>
            </div>

            {/* Live Target Tracker (P&L Bar) */}
            <div className="pt-1.5 border-t border-white/5 space-y-1">
              <div className="flex items-center justify-between text-[9.5px]">
                <span className="text-slate-400 font-sans flex items-center gap-1">
                  <Activity className="w-3 h-3 text-indigo-400" />
                  Live Target Tracker:
                </span>
                <span className={cn("font-mono text-[9px]", trackerColor)}>
                  {trackerStatus}
                </span>
              </div>

              {/* Dynamic Gradient Progress Bar */}
              <div className="w-full h-1.5 bg-dark-750 rounded-full overflow-hidden border border-white/10 relative">
                <div 
                  className={cn(
                    "h-full rounded-full transition-all duration-500",
                    t1Progress >= 100 ? "bg-gradient-to-r from-emerald-500 to-teal-400 shadow-sm shadow-emerald-500/50 animate-pulse" :
                    t1Progress > 0 ? "bg-gradient-to-r from-cyan-500 to-emerald-400 shadow-sm shadow-cyan-500/40" :
                    isPullback ? "bg-amber-500/40" : (pnlDiff < 0 ? "bg-rose-500/30" : "bg-dark-700")
                  )}
                  style={{ width: `${Math.max(4, t1Progress)}%` }}
                />
              </div>

              <div className="flex justify-between text-[8.5px] text-slate-500 font-mono">
                <span>SL: {activeSl !== null ? formatINR(activeSl) : '?'}</span>
                <span className="text-slate-400 font-medium">Entry: {activeEntry !== null ? formatINR(activeEntry) : '?'}</span>
                <span>T1: {activeT1 !== null ? formatINR(activeT1) : '?'}</span>
              </div>
            </div>
          </div>
        ) : isRadarCandidate ? (
          /* Pre-Breakout Proximity Meter (Idea 1 & Idea 3) */
          <div className="rounded-xl p-2.5 sm:p-3 border border-cyan-500/35 bg-gradient-to-b from-dark-850/95 to-cyan-950/20 mb-2.5 space-y-2 select-none shadow-md shadow-cyan-950/20 ring-1 ring-cyan-500/20">
            {/* Radar Header */}
            <div className="flex items-center justify-between text-[11px] border-b border-cyan-500/20 pb-1">
              <span className="flex items-center gap-1.5 font-bold text-cyan-300">
                <Radar className="w-3.5 h-3.5 text-cyan-400 animate-pulse flex-shrink-0" />
                <span className="truncate">Pre-Breakout Radar</span>
              </span>
              <span className="inline-flex items-center gap-1 px-1.5 py-0.2 rounded text-[9px] font-bold font-mono bg-amber-500/20 text-amber-300 border border-amber-500/30 flex-shrink-0">
                <Flame className="w-2.5 h-2.5 text-amber-400" />
                {relVolNum.toFixed(1)}x Vol Surge
              </span>
            </div>

            {/* Target Breakout Level & Distance */}
            <div className="grid grid-cols-2 gap-1.5 text-xs font-mono">
              <div className="p-1.5 rounded-lg bg-dark-800/90 border border-cyan-500/25">
                <span className="text-[9px] text-cyan-400 block font-sans font-medium">
                  {isLongTrade ? 'Breakout Level (OR High)' : 'Breakdown Level (OR Low)'}
                </span>
                <span className="font-bold text-white text-xs">
                  {breakoutTarget > 0 ? formatINR(breakoutTarget) : 'Pending OR'}
                </span>
              </div>

              <div className="p-1.5 rounded-lg bg-dark-800/90 border border-white/10">
                <span className="text-[9px] text-slate-400 block font-sans">
                  Distance to Trigger
                </span>
                <span className={cn(
                  "font-bold text-xs",
                  distToBreakout <= 0 ? "text-emerald-400" : "text-amber-300"
                )}>
                  {breakoutTarget > 0 
                    ? (distToBreakout <= 0 
                        ? (isLongTrade ? 'At Breakout ⚡' : 'At Breakdown ⚡') 
                        : `₹${distToBreakout.toFixed(2)} (${distToBreakoutPct.toFixed(1)}%)`) 
                    : '—'}
                </span>
              </div>
            </div>

            {/* Visual Proximity Progress Bar */}
            <div className="space-y-1">
              <div className="flex items-center justify-between text-[9.5px]">
                <span className="text-slate-400 font-sans flex items-center gap-1">
                  <Activity className="w-3 h-3 text-cyan-400" />
                  {isLongTrade ? 'Breakout Proximity:' : 'Breakdown Proximity:'}
                </span>
                <span className="font-mono text-cyan-300 font-bold">
                  {Math.round(proximityGaugePct)}% to Trigger
                </span>
              </div>

              {/* Progress Bar Gauge */}
              <div className="w-full h-1.5 bg-dark-750 rounded-full overflow-hidden border border-cyan-500/25 relative">
                <div 
                  className="h-full rounded-full transition-all duration-500 bg-gradient-to-r from-cyan-500 via-indigo-400 to-emerald-400 shadow-sm shadow-cyan-500/50"
                  style={{ width: `${Math.round(proximityGaugePct)}%` }}
                />
              </div>

              <div className="flex justify-between text-[8.5px] text-slate-400 font-mono">
                <span>OR Low: {openingRangeLow > 0 ? formatINR(openingRangeLow) : '—'}</span>
                <span className="text-cyan-300 font-medium">LTP: {formatINR(currentLtp)}</span>
                <span>OR High: {openingRangeHigh > 0 ? formatINR(openingRangeHigh) : '—'}</span>
              </div>
            </div>

            {/* Context Note */}
            <div className="text-[9px] text-cyan-200/90 text-center font-sans bg-cyan-950/40 rounded p-1 border border-cyan-500/20">
              💡 Institutional {isLongTrade ? 'accumulation' : 'distribution'} ({relVolNum.toFixed(1)}x vol). Setup triggers on candle cross {isLongTrade ? 'above' : 'below'} {breakoutTarget > 0 ? formatINR(breakoutTarget) : (isLongTrade ? 'OR High' : 'OR Low')}.
            </div>
          </div>
        ) : (() => {
          // Subdued Baseline Card
          return (
            <div className="rounded-xl p-2.5 sm:p-3 border border-white/5 bg-dark-850/60 mb-2.5 space-y-2 select-none">
              {/* Header Title */}
              <div className="flex items-center justify-between text-[11px] border-b border-white/5 pb-1">
                <span className="flex items-center gap-1.5 font-semibold">
                  {isPennyBelowFloor ? (
                    <>
                      <AlertTriangle className="w-3.5 h-3.5 text-rose-400 flex-shrink-0" />
                      <span className="text-rose-300 truncate">Below Base Floor (&lt; ₹20)</span>
                    </>
                  ) : isSafetyGateFiltered ? (
                    <>
                      <AlertTriangle className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />
                      <span className="text-amber-200 truncate">Safety Gate Filtered (No Setup)</span>
                    </>
                  ) : (
                    <>
                      <Clock className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                      <span className="text-slate-300 truncate">Awaiting Breakout Setup</span>
                    </>
                  )}
                </span>
                <span className="text-[9px] font-mono text-slate-400 flex-shrink-0">
                  {isPennyBelowFloor ? 'Penny Guard' : isSafetyGateFiltered ? 'Gate Guard' : 'Monitoring'}
                </span>
              </div>

              {/* Two-Pillar Visual Checklist Badges */}
              <div className="grid grid-cols-2 gap-1.5 text-[9.5px]">
                {/* Pillar 1: Institutional Volume */}
                <div 
                  className={cn(
                    "p-1.5 rounded-lg border flex items-center justify-center gap-1 font-mono",
                    isVolQualified 
                      ? "bg-emerald-950/50 border-emerald-500/30 text-emerald-300" 
                      : "bg-dark-750/70 border-white/5 text-slate-400"
                  )}
                  title={`Institutional Relative Volume: ${relVolNum.toFixed(2)}x (Target: >= 1.20x)`}
                >
                  {isVolQualified ? (
                    <CheckCircle2 className="w-3 h-3 text-emerald-400 flex-shrink-0" />
                  ) : (
                    <Clock className="w-3 h-3 text-amber-400 flex-shrink-0" />
                  )}
                  <span className="truncate">
                    Vol: {relVolNum.toFixed(1)}x {isVolQualified ? '✅' : '⏳'}
                  </span>
                </div>

                {/* Pillar 2: Trigger & Structure */}
                <div 
                  className={cn(
                    "p-1.5 rounded-lg border flex items-center justify-center gap-1 font-mono",
                    isPennyBelowFloor
                      ? "bg-rose-950/50 border-rose-500/30 text-rose-300"
                      : isSafetyGateFiltered
                      ? "bg-amber-950/40 border-amber-500/30 text-amber-300"
                      : "bg-dark-750/70 border-white/5 text-slate-400"
                  )}
                  title={
                    isPennyBelowFloor 
                      ? `LTP ₹${currentLtp} is below ₹20.00 base floor guard`
                      : isSafetyGateFiltered
                      ? (isOrExhausted ? `Opening Range width (₹${orWidth.toFixed(2)}) exceeds 4.0x ATR exhaustion limit` : 'Filtered by V13 safety gates (ATR exhaustion, VWAP counter-trend, or F&O short guard)')
                      : 'Price is consolidating inside 15m opening range'
                  }
                >
                  {isPennyBelowFloor ? (
                    <AlertTriangle className="w-3 h-3 text-rose-400 flex-shrink-0" />
                  ) : isSafetyGateFiltered ? (
                    <AlertTriangle className="w-3 h-3 text-amber-400 flex-shrink-0" />
                  ) : (
                    <Clock className="w-3 h-3 text-slate-500 flex-shrink-0" />
                  )}
                  <span className="truncate">
                    {isPennyBelowFloor
                      ? 'Floor < ₹20'
                      : isSafetyGateFiltered
                      ? (isOrExhausted ? 'Wide OR > 4x ATR' : 'Gate Filtered 🚫')
                      : 'Consolidation ⏳'}
                  </span>
                </div>
              </div>

              {/* Informative Micro-Footnote */}
              <div className="text-[9px] text-slate-400 text-center font-sans">
                {isPennyBelowFloor 
                  ? `LTP (${formatINR(currentLtp)}) below ₹20 guard to protect against tick slippage.` 
                  : isSafetyGateFiltered
                  ? (isOrExhausted
                      ? `OR width (${formatINR(orWidth)}) exceeds 4.0x ATR exhaustion limit.`
                      : `Filtered by V13 safety gates (ATR budget, VWAP, or Non-F&O short guard).`)
                  : `Monitoring 15m opening range • RelVol: ${relVolNum.toFixed(2)}x / 1.20x req.`}
              </div>
            </div>
          );
        })()}

      </div>

      <div className="pt-2 border-t border-white/5 flex items-center justify-between gap-1.5">
        <div className="flex items-center gap-1.5 truncate max-w-[170px] sm:max-w-[190px]">
          <span className="text-[9.5px] text-slate-400 truncate">
            {signal?.confirmation.reasons.length ? signal.confirmation.reasons[0] : (signal?.setup ?? stock.status)}
          </span>
          {isCardTimestampsEnabled && (
            signal?.signal_time ? (() => {
              const { timeDisplay, barNum } = parseSignalBar(signal.signal_time);
              if (!timeDisplay) return null;
              return (
                <span 
                  className="inline-flex items-center gap-1 text-[8.5px] font-mono px-1.5 py-0.5 rounded bg-dark-750 border border-white/10 text-cyan-300 flex-shrink-0"
                  title={`Signal Triggered at ${timeDisplay} IST ${barNum ? `(Session Bar #${barNum}: 15m candle)` : ''}`}
                >
                  <Zap className="w-2.5 h-2.5 text-amber-400" />
                  <span>Trig: {timeDisplay}{barNum ? ` (B${barNum})` : ''}</span>
                </span>
              );
            })() : isRadarCandidate && breakoutTarget > 0 ? (
              <span 
                className="inline-flex items-center gap-1 text-[8.5px] font-mono px-1.5 py-0.5 rounded bg-cyan-950/60 border border-cyan-500/30 text-cyan-300 flex-shrink-0"
                title={`Pre-Breakout Surveillance: Awaiting price trigger ${isLongTrade ? 'above' : 'below'} ${formatINR(breakoutTarget)}`}
              >
                <Radar className="w-2.5 h-2.5 text-cyan-400" />
                <span>Watch: {formatINR(breakoutTarget)}</span>
              </span>
            ) : (
              <span 
                className="inline-flex items-center gap-1 text-[8.5px] font-mono px-1.5 py-0.5 rounded bg-dark-750/60 border border-white/5 text-slate-500 flex-shrink-0"
                title="No active breakout trigger for this stock (Scanning for setup)"
              >
                <span>Trig: —</span>
              </span>
            )
          )}
        </div>
        
        <button
          onClick={(e) => {
            e.stopPropagation();
            onOpenChart(stock);
          }}
          disabled={false}
          className="flex items-center gap-1.5 px-2.5 py-1 sm:px-3 sm:py-1.5 rounded-lg bg-indigo-600/80 hover:bg-indigo-600 text-white text-xs font-semibold shadow-sm transition-all group-hover:shadow-indigo-500/25 flex-shrink-0"
        >
          <LineChart className="w-3.5 h-3.5" />
          <span>15m Chart</span>
          <ExternalLink className="w-3 h-3 text-indigo-200" />
        </button>
      </div>
    </div>
  );
};
