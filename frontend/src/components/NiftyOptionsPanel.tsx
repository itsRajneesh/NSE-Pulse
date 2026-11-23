"use client";

import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  ShieldCheck,
  ShieldAlert,
  Activity,
  RefreshCw,
  KeyRound,
  ExternalLink,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Wallet,
  Target,
  Clock,
  TrendingUp,
  TrendingDown,
  Play,
  Square,
  RotateCcw,
  Layers,
  Gauge,
  Info,
  ChevronDown,
  ChevronUp,
  Bell,
  Volume2,
  VolumeX,
} from 'lucide-react';
import {
  NiftyOptionsDashboardResponse,
  NiftyOptionsPaperLedger,
  NiftyOptionsLedgerSessionsResponse,
} from '@/types/niftyOptions';
import { cn, playAlphaSound, speakAlphaAlert, formatOptionSymbol, formatOptionSymbolInText } from '@/lib/utils';
import AlphaToastNotification, { AlphaToastItem } from './AlphaToastNotification';

interface NiftyOptionsPanelProps {
  isActive: boolean;
  onSwitchToAlphaTab?: () => void;
  onSpotUpdate?: (data: { spot_ltp: number; spot_change: number; spot_change_pct: number; feed_mode?: string }) => void;
}

const CAPITAL_PRESETS = [25000, 50000, 100000, 250000, 500000, 1000000, 2500000];

function formatInrSigned(val: number, decimals = 0): string {
  const num = Number(val) || 0;
  const sign = num >= 0 ? '+' : '-';
  const absVal = Math.abs(num);
  const formatted =
    decimals > 0
      ? absVal.toLocaleString('en-IN', {
          minimumFractionDigits: decimals,
          maximumFractionDigits: decimals,
        })
      : Math.round(absVal).toLocaleString('en-IN');
  return `${sign}₹${formatted}`;
}

function formatIndianCompact(val: number): string {
  const num = Math.abs(Number(val) || 0);
  if (num >= 10000000) {
    return `₹${(num / 10000000).toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1')} Cr`;
  }
  if (num >= 100000) {
    return `₹${(num / 100000).toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1')}L`;
  }
  if (num >= 1000) {
    return `₹${(num / 1000).toFixed(0)}k`;
  }
  return `₹${num.toLocaleString('en-IN')}`;
}

function handleIndianNumberInputChange(
  e: React.ChangeEvent<HTMLInputElement>,
  currentVal: number,
  setter: (nextVal: number) => void
): void {
  const el = e.target;
  const rawVal = el.value;
  const caret = el.selectionStart ?? rawVal.length;
  const prevFormatted = currentVal > 0 ? currentVal.toLocaleString('en-IN') : '';
  let digitsBeforeCaret = rawVal.slice(0, caret).replace(/[^0-9]/g, '').length;
  let rawDigits = rawVal.replace(/[^0-9]/g, '');

  // Handle Backspace/Delete pressed directly on a comma separator so cursor never gets trapped
  if (
    currentVal > 0 &&
    rawDigits === String(currentVal) &&
    rawVal.length === prevFormatted.length - 1 &&
    digitsBeforeCaret > 0
  ) {
    rawDigits =
      rawDigits.slice(0, digitsBeforeCaret - 1) + rawDigits.slice(digitsBeforeCaret);
    digitsBeforeCaret = Math.max(0, digitsBeforeCaret - 1);
  }

  const nextNum = rawDigits ? Number(rawDigits) : 0;
  setter(nextNum);

  const nextFormatted = nextNum > 0 ? nextNum.toLocaleString('en-IN') : '';
  if (typeof window !== 'undefined') {
    window.requestAnimationFrame(() => {
      try {
        if (document.activeElement !== el) return;
        if (!nextFormatted || digitsBeforeCaret <= 0) {
          el.setSelectionRange(0, 0);
          return;
        }
        let seenDigits = 0;
        let targetPos = nextFormatted.length;
        for (let i = 0; i < nextFormatted.length; i++) {
          if (/[0-9]/.test(nextFormatted[i])) {
            seenDigits++;
            if (seenDigits === digitsBeforeCaret) {
              targetPos = i + 1;
              break;
            }
          }
        }
        el.setSelectionRange(targetPos, targetPos);
      } catch {
        // Ignore selection range errors on unmounted inputs
      }
    });
  }
}

const QUANT_TOKEN_REGEX =
  /(\b(?:Bullish Alignment|Bearish Alignment|5m Bullish Breakout|5m Bearish Breakdown|5m Bullish Pullback Rejection|5m Bearish Pullback Rejection|Momentum & Vol Healthy|Internals Aligned|Active Intraday Entry Window|THETA TRAP DETECTED|ADX Momentum Cooling|Low Momentum|Local 5-Strike PCR|Delta Sweet Spot|Dynamic Zone|Opening Range Breakout|3-Bar Box|5m\/15m EMA20|5m EMA20|15m EMA20|5m EMA|15m EMA|EMA20|Straddle VWAP|ATM Straddle|VWAP|Anchor|5m ADX\(14\)|ADX\(14\)|ADX|India VIX|VIX|RSI|Body|Spread|BankNifty|ALIGNED|Bullish|Bearish|Spot|PCR|IV|T1|T2)\b|\|Delta\||₹\d+(?:,\d+)*(?:\.\d+)?|[+-]?\d+(?:\.\d+)?R\b|[+-]?\d+(?:\.\d+)?%|\b\d{4,5}(?:\.\d+)?(?:\/\d{4,5}(?:\.\d+)?)?\b)/g;

function highlightQuantText(text: string | null | undefined): React.ReactNode {
  if (!text) return null;
  const parts = text.split(QUANT_TOKEN_REGEX);
  return parts.map((part, idx) => {
    if (!part) return null;

    if (
      part === 'Bullish Alignment' ||
      part === '5m Bullish Breakout' ||
      part === '5m Bullish Pullback Rejection' ||
      part === 'Momentum & Vol Healthy' ||
      part === 'Internals Aligned' ||
      part === 'Active Intraday Entry Window' ||
      part === 'ALIGNED' ||
      part === 'Bullish' ||
      part === 'T1'
    ) {
      return (
        <span key={idx} className="text-emerald-300 font-semibold">
          {part}
        </span>
      );
    }

    if (
      part === 'Bearish Alignment' ||
      part === '5m Bearish Breakdown' ||
      part === '5m Bearish Pullback Rejection' ||
      part === 'THETA TRAP DETECTED' ||
      part === 'ADX Momentum Cooling' ||
      part === 'Low Momentum' ||
      part === 'Bearish'
    ) {
      return (
        <span key={idx} className="text-rose-300 font-semibold">
          {part}
        </span>
      );
    }

    if (part === 'VWAP' || part === 'Straddle VWAP' || part === 'Anchor') {
      return (
        <span key={idx} className="text-amber-300 font-semibold">
          {part}
        </span>
      );
    }

    if (
      part === '5m/15m EMA20' ||
      part === '5m EMA20' ||
      part === '5m EMA' ||
      part === 'EMA20' ||
      part === 'Dynamic Zone' ||
      part === '|Delta|' ||
      part === 'Delta Sweet Spot' ||
      part === 'ATM Straddle' ||
      part === 'Spread' ||
      part === 'T2'
    ) {
      return (
        <span key={idx} className="text-cyan-300 font-semibold">
          {part}
        </span>
      );
    }

    if (part === '15m EMA20' || part === '15m EMA') {
      return (
        <span key={idx} className="text-purple-300 font-semibold">
          {part}
        </span>
      );
    }

    if (
      part === 'IV' ||
      part === 'India VIX' ||
      part === 'VIX' ||
      part === '3-Bar Box' ||
      part === 'Opening Range Breakout'
    ) {
      return (
        <span key={idx} className="text-fuchsia-300 font-semibold">
          {part}
        </span>
      );
    }

    if (
      part === '5m ADX(14)' ||
      part === 'ADX(14)' ||
      part === 'ADX' ||
      part === 'RSI' ||
      part === 'Body' ||
      part === 'Local 5-Strike PCR' ||
      part === 'PCR' ||
      part === 'BankNifty'
    ) {
      return (
        <span key={idx} className="text-amber-200 font-semibold">
          {part}
        </span>
      );
    }

    if (part === 'Spot') {
      return (
        <span key={idx} className="text-white font-semibold">
          {part}
        </span>
      );
    }

    if (part.startsWith('₹')) {
      return (
        <span key={idx} className="font-mono font-bold text-amber-300">
          {part}
        </span>
      );
    }

    if (part.endsWith('R') && /^[+-]?\d/.test(part)) {
      const isNeg = part.startsWith('-');
      return (
        <span
          key={idx}
          className={cn('font-mono font-bold', isNeg ? 'text-rose-300' : 'text-emerald-300')}
        >
          {part}
        </span>
      );
    }

    if (part.endsWith('%')) {
      const isNeg = part.startsWith('-');
      return (
        <span
          key={idx}
          className={cn('font-mono font-bold', isNeg ? 'text-rose-300' : 'text-cyan-200')}
        >
          {part}
        </span>
      );
    }

    if (/^\d{4,5}/.test(part)) {
      if (part.includes('/')) {
        const [fastEma, slowEma] = part.split('/');
        return (
          <span key={idx} className="font-mono font-bold">
            <span className="text-cyan-300">{fastEma}</span>
            <span className="text-slate-400">/</span>
            <span className="text-purple-300">{slowEma}</span>
          </span>
        );
      }
      return (
        <span key={idx} className="font-mono font-bold text-white">
          {part}
        </span>
      );
    }

    return part;
  });
}

export const NiftyOptionsPanel: React.FC<NiftyOptionsPanelProps> = ({
  isActive,
  onSwitchToAlphaTab,
  onSpotUpdate,
}) => {
  const [dashboard, setDashboard] = useState<NiftyOptionsDashboardResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Alpha Real-Time Notification Flash, Audio & Voice States
  const [alphaAudioEnabled, setAlphaAudioEnabled] = useState<boolean>(true);
  const [alphaToasts, setAlphaToasts] = useState<AlphaToastItem[]>([]);
  const hasHydratedRef = useRef<boolean>(false);

  const pushAlphaToast = useCallback((item: AlphaToastItem) => {
    setAlphaToasts((prev) => [item, ...prev.filter((x) => x.id !== item.id)].slice(0, 4));
    setTimeout(() => {
      setAlphaToasts((prev) => prev.filter((x) => x.id !== item.id));
    }, 9000);
  }, []);

  const dismissAlphaToast = useCallback((id: string) => {
    setAlphaToasts((prev) => prev.filter((x) => x.id !== id));
  }, []);

  const processLedgerNotifications = useCallback(
    (json: NiftyOptionsDashboardResponse) => {
      if (typeof window === 'undefined') return;
      const op = json.paper_ledger?.open_trade;
      const closedList = json.paper_ledger?.closed_trades || [];
      const latestClosed = closedList[0];

      // Catch #3 Fix: Silent Hydration on initial load / F5 page reload (Zero Ghost Alerts!)
      if (!hasHydratedRef.current) {
        try {
          if (op) {
            sessionStorage.setItem(`alpha_evt_${op.trade_id}_ENTRY`, '1');
            if (op.pre_t1_shield_active) sessionStorage.setItem(`alpha_evt_${op.trade_id}_SHIELD`, '1');
            if (op.t1_booked) sessionStorage.setItem(`alpha_evt_${op.trade_id}_T1`, '1');
            if (op.stage2_notified) sessionStorage.setItem(`alpha_evt_${op.trade_id}_STAGE2`, '1');
            if (op.doorstep_notified) sessionStorage.setItem(`alpha_evt_${op.trade_id}_DOORSTEP`, '1');
            if (op.sl_45m_tightened) sessionStorage.setItem(`alpha_evt_${op.trade_id}_45M`, '1');
          }
          closedList.forEach((ct) => {
            sessionStorage.setItem(`alpha_evt_${ct.trade_id}_EXIT`, '1');
          });
        } catch {
          // Ignore sessionStorage quota errors
        }
        hasHydratedRef.current = true;
        return;
      }

      const nowStr =
        json.quant_engine?.ist_time_str ||
        new Date().toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' });

      try {
        // 1. Live Open Trade Transitions: ENTRY, SHIELD, T1, STAGE2, 45M
        if (op) {
          const entryKey = `alpha_evt_${op.trade_id}_ENTRY`;
          if (!sessionStorage.getItem(entryKey)) {
            sessionStorage.setItem(entryKey, '1');
            pushAlphaToast({
              id: entryKey,
              kind: 'ENTRY',
              title: '⚡ ALPHA AUTO ENTRY',
              contract: `${op.symbol} (${op.strike} ${op.opt_type})`,
              subtitle: `Setup: ${op.trigger_type} • ${op.lots}L (${op.qty} Qty)`,
              metricsLine: `Entry ₹${op.entry_premium.toFixed(2)} | SL ₹${op.current_sl_premium.toFixed(2)} | T1 ₹${op.t1_premium.toFixed(2)}`,
              timestamp: nowStr,
            });
            if (alphaAudioEnabled) {
              playAlphaSound('ENTRY');
              speakAlphaAlert(
                `Alpha entry triggered in Nifty ${op.strike} ${op.opt_type} at ${op.entry_premium.toFixed(0)} rupees`
              );
            }
          }

          if (op.pre_t1_doorstep_active && !op.t1_booked) {
            const doorstep1cKey = `alpha_evt_${op.trade_id}_DOORSTEP1C`;
            if (!sessionStorage.getItem(doorstep1cKey)) {
              sessionStorage.setItem(doorstep1cKey, '1');
              const lockedR =
                op.sl_points > 0
                  ? ((op.current_sl_premium - op.entry_premium) / op.sl_points).toFixed(2)
                  : '0.95';
              pushAlphaToast({
                id: doorstep1cKey,
                kind: 'SHIELD',
                title: '⚡ +1.35R T1 DOORSTEP LOCK',
                contract: `${op.symbol} (${op.strike} ${op.opt_type})`,
                subtitle: `Peak ₹${op.high_watermark.toFixed(2)} (>= +1.35R) • T1 Doorstep Secured`,
                metricsLine: `SL Trailed to ₹${op.current_sl_premium.toFixed(2)} (+${lockedR}R Locked on 100% Lots)`,
                timestamp: nowStr,
              });
              if (alphaAudioEnabled) {
                playAlphaSound('SHIELD');
                speakAlphaAlert(
                  `Alpha T1 doorstep lock engaged at plus ${lockedR} R for ${op.strike} ${op.opt_type}`
                );
              }
            }
          } else if (op.pre_t1_shield_active && !op.t1_booked) {
            const shieldKey = `alpha_evt_${op.trade_id}_SHIELD`;
            if (!sessionStorage.getItem(shieldKey)) {
              sessionStorage.setItem(shieldKey, '1');
              const lockedR =
                op.sl_points > 0
                  ? ((op.current_sl_premium - op.entry_premium) / op.sl_points).toFixed(2)
                  : '0.75';
              pushAlphaToast({
                id: shieldKey,
                kind: 'SHIELD',
                title: '🛡️ +1.20R CHANDELIER SHIELD',
                contract: `${op.symbol} (${op.strike} ${op.opt_type})`,
                subtitle: `Peak ₹${op.high_watermark.toFixed(2)} (>= +1.20R) • Progressive Lock`,
                metricsLine: `SL Trailed to ₹${op.current_sl_premium.toFixed(2)} (+${lockedR}R Locked)`,
                timestamp: nowStr,
              });
              if (alphaAudioEnabled) {
                playAlphaSound('SHIELD');
                speakAlphaAlert(
                  `Alpha chandelier shield locked at plus ${lockedR} R for ${op.strike} ${op.opt_type}`
                );
              }
            }
          } else if (op.stage1b0_shield_active && !op.t1_booked) {
            const shield1b0Key = `alpha_evt_${op.trade_id}_SHIELD1B0`;
            if (!sessionStorage.getItem(shield1b0Key)) {
              sessionStorage.setItem(shield1b0Key, '1');
              const lockedR =
                op.sl_points > 0
                  ? ((op.current_sl_premium - op.entry_premium) / op.sl_points).toFixed(2)
                  : '0.25';
              pushAlphaToast({
                id: shield1b0Key,
                kind: 'SHIELD',
                title: '🛡️ +1.00R GREEN SHIELD',
                contract: `${op.symbol} (${op.strike} ${op.opt_type})`,
                subtitle: `Peak ₹${op.high_watermark.toFixed(2)} (>= +1.00R) • Green Floor Locked`,
                metricsLine: `SL Trailed to ₹${op.current_sl_premium.toFixed(2)} (+${lockedR}R Guaranteed Green)`,
                timestamp: nowStr,
              });
              if (alphaAudioEnabled) {
                playAlphaSound('SHIELD');
              }
            }
          }

          if (op.t1_booked) {
            const t1Key = `alpha_evt_${op.trade_id}_T1`;
            if (!sessionStorage.getItem(t1Key)) {
              sessionStorage.setItem(t1Key, '1');
              const t1Lots = op.t1_lots ?? (op.lots === 1 ? 0 : Math.ceil(op.lots / 2));
              const runnerLots = op.runner_lots ?? (op.lots - t1Lots);
              const splitDesc =
                op.lots === 1 || t1Lots === 0
                  ? `1L Single Runner riding for T2 (+2.5R)`
                  : `Booked ${t1Lots}L @ ₹${op.t1_premium.toFixed(2)} • ${runnerLots}L Runner Active`;
              pushAlphaToast({
                id: t1Key,
                kind: 'T1',
                title: '🎯 TARGET 1 (+1.5R) HIT',
                contract: `${op.symbol} (${op.strike} ${op.opt_type})`,
                subtitle: splitDesc,
                metricsLine: `Runner SL Locked @ ₹${op.current_sl_premium.toFixed(2)} | T2 ₹${op.t2_premium.toFixed(2)}`,
                timestamp: nowStr,
              });
              if (alphaAudioEnabled) {
                playAlphaSound('T1_WIN');
                speakAlphaAlert(
                  `Alpha Target 1 hit in Nifty ${op.strike} ${op.opt_type}. Stop loss trailed to cost.`
                );
              }
            }
          }

          if (op.stage2_notified) {
            const stage2Key = `alpha_evt_${op.trade_id}_STAGE2`;
            if (!sessionStorage.getItem(stage2Key)) {
              sessionStorage.setItem(stage2Key, '1');
              pushAlphaToast({
                id: stage2Key,
                kind: 'STAGE2',
                title: '🚀 STAGE 2 (+2.0R) TRAIL',
                contract: `${op.symbol} (${op.strike} ${op.opt_type})`,
                subtitle: `Peak ₹${op.high_watermark.toFixed(2)} • Step-Trail Engaged`,
                metricsLine: `Locked Runner SL @ ₹${op.current_sl_premium.toFixed(2)} (+1.0R+)`,
                timestamp: nowStr,
              });
              if (alphaAudioEnabled) {
                playAlphaSound('T1_WIN');
                speakAlphaAlert(
                  `Alpha Stage 2 step trail locked at plus 1 R for ${op.strike} ${op.opt_type}`
                );
              }
            }
          }

          if (op.doorstep_notified) {
            const doorstepKey = `alpha_evt_${op.trade_id}_DOORSTEP`;
            if (!sessionStorage.getItem(doorstepKey)) {
              sessionStorage.setItem(doorstepKey, '1');
              pushAlphaToast({
                id: doorstepKey,
                kind: 'STAGE2',
                title: '⚡ +2.20R DOORSTEP TRAIL',
                contract: `${op.symbol} (${op.strike} ${op.opt_type})`,
                subtitle: `Peak ₹${op.high_watermark.toFixed(2)} • Doorstep Locked`,
                metricsLine: `Locked Runner SL @ ₹${op.current_sl_premium.toFixed(2)} (+1.60R Locked above T1)`,
                timestamp: nowStr,
              });
              if (alphaAudioEnabled) {
                playAlphaSound('T1_WIN');
                speakAlphaAlert(
                  `Alpha plus 2.2 R doorstep trail locked at plus 1.6 R for ${op.strike} ${op.opt_type}`
                );
              }
            }
          }

          if (op.sl_45m_tightened) {
            const lock45Key = `alpha_evt_${op.trade_id}_45M`;
            if (!sessionStorage.getItem(lock45Key)) {
              sessionStorage.setItem(lock45Key, '1');
              pushAlphaToast({
                id: lock45Key,
                kind: '45M',
                title: '⏱️ 45-MIN SL STEP-UP',
                contract: `${op.symbol} (${op.strike} ${op.opt_type})`,
                subtitle: `Post-T1 45m Theta Protection Engaged`,
                metricsLine: `Tightened Runner SL @ ₹${op.current_sl_premium.toFixed(2)}`,
                timestamp: nowStr,
              });
              if (alphaAudioEnabled) {
                playAlphaSound('SHIELD');
              }
            }
          }
        }

        // 2. Bug #5 Fix: Always check latestClosed (`closed_trades[0]`) so fast exits during 6.0s background polls never get missed!
        if (latestClosed) {
          const exitKey = `alpha_evt_${latestClosed.trade_id}_EXIT`;
          if (!sessionStorage.getItem(exitKey)) {
            sessionStorage.setItem(exitKey, '1');
            const isWin = latestClosed.net_pnl_inr >= 0;
            const sign = isWin ? '+' : '';
            const rMult = latestClosed.r_multiple ?? 0;
            pushAlphaToast({
              id: exitKey,
              kind: isWin ? 'EXIT_WIN' : 'EXIT_LOSS',
              title: isWin ? '✅ ALPHA TRADE CLOSED (WIN)' : '🛑 ALPHA TRADE CLOSED',
              contract: `${latestClosed.symbol} (${latestClosed.strike} ${latestClosed.opt_type})`,
              subtitle: `Reason: ${latestClosed.exit_reason || 'CLOSED'} • ${latestClosed.lots}L (${latestClosed.qty} Qty)`,
              metricsLine: `Net PnL: ${sign}₹${latestClosed.net_pnl_inr.toFixed(0)} (${sign}${rMult.toFixed(2)}R) | ₹${latestClosed.entry_premium.toFixed(2)} → ₹${(latestClosed.exit_premium ?? latestClosed.current_ltp).toFixed(2)}`,
              timestamp: latestClosed.exit_time_str || nowStr,
            });
            if (alphaAudioEnabled) {
              playAlphaSound(isWin ? 'EXIT_WIN' : 'EXIT_LOSS');
              speakAlphaAlert(
                `Alpha trade closed in Nifty ${latestClosed.strike} ${latestClosed.opt_type}. Net ${
                  isWin ? 'profit' : 'loss'
                } ${Math.abs(Math.round(latestClosed.net_pnl_inr))} rupees.`
              );
            }
          }
        }
      } catch {
        // Ignore sessionStorage errors
      }
    },
    [alphaAudioEnabled, pushAlphaToast]
  );

  // Universal Capital & Risk Form States
  const [capitalInput, setCapitalInput] = useState<number>(100000);
  const [riskModeInput, setRiskModeInput] = useState<'PERCENT' | 'FIXED_INR'>('PERCENT');
  const [riskValueInput, setRiskValueInput] = useState<number>(2.0);
  const [lotSizeInput, setLotSizeInput] = useState<number>(65);
  const [prefsSynced, setPrefsSynced] = useState<boolean>(false);

  // Fyers Daily Token Drawer States
  const [showFyersDrawer, setShowFyersDrawer] = useState<boolean>(false);
  const [fyersAppId, setFyersAppId] = useState<string>('');
  const [fyersSecretId, setFyersSecretId] = useState<string>('');
  const [fyersRedirectUri, setFyersRedirectUri] = useState<string>('https://127.0.0.1');
  const [fyersAuthCodeUrl, setFyersAuthCodeUrl] = useState<string>('');
  const [fyersDirectToken, setFyersDirectToken] = useState<string>('');
  const [fyersMessage, setFyersMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [fyersSubmitting, setFyersSubmitting] = useState<boolean>(false);

  // Action feedback
  const [actionToast, setActionToast] = useState<string | null>(null);
  const [isCalculating, setIsCalculating] = useState<boolean>(false);
  const isFetchingRef = useRef<boolean>(false);

  // Historical Session Ledger Viewer States
  const [ledgerSessions, setLedgerSessions] = useState<NiftyOptionsLedgerSessionsResponse | null>(null);
  const [selectedSessionDate, setSelectedSessionDate] = useState<string | null>(null);
  const [historicalLedger, setHistoricalLedger] = useState<NiftyOptionsPaperLedger | null>(null);
  const [loadingHistory, setLoadingHistory] = useState<boolean>(false);
  const [cumulativeFromDate, setCumulativeFromDate] = useState<string>('ALL');

  useEffect(() => {
    try {
      const savedFrom = localStorage.getItem('alpha_ledger_cum_from_date');
      if (savedFrom) {
        setCumulativeFromDate(savedFrom);
      }
    } catch {
      // Ignore localStorage read errors
    }
  }, []);

  const handleSelectCumulativeFromDate = useCallback((nextFrom: string) => {
    const val = nextFrom || 'ALL';
    setCumulativeFromDate(val);
    try {
      localStorage.setItem('alpha_ledger_cum_from_date', val);
    } catch {
      // Ignore localStorage write errors
    }
  }, []);

  // Catch #2: Committed Capital Priority (prevents mid-typing ROI % spikes while editing the input box)
  const activeCapitalInr =
    Number(dashboard?.sizing_preferences?.capital_inr) > 0
      ? Number(dashboard?.sizing_preferences?.capital_inr)
      : Number(dashboard?.quant_engine?.position_sizing?.capital_inr) > 0
      ? Number(dashboard?.quant_engine?.position_sizing?.capital_inr)
      : Number(capitalInput) > 0
      ? Number(capitalInput)
      : 100000;

  const fetchLedgerSessions = useCallback(async (capInr: number) => {
    try {
      const res = await fetch(
        `/api/v13/nifty-options/ledger/sessions?capital_inr=${encodeURIComponent(String(capInr))}`,
        { cache: 'no-store' }
      );
      if (!res.ok) return;
      const data: NiftyOptionsLedgerSessionsResponse = await res.json();
      setLedgerSessions(data);
    } catch {
      // Ignore transient session list errors
    }
  }, []);

  const handleSelectSessionDate = useCallback(
    async (targetDate: string) => {
      const liveDate = dashboard?.paper_ledger?.session_date;
      if (!targetDate || targetDate === liveDate) {
        setSelectedSessionDate(null);
        setHistoricalLedger(null);
        return;
      }
      setSelectedSessionDate(targetDate);
      setLoadingHistory(true);
      try {
        const res = await fetch(
          `/api/v13/nifty-options/ledger/history?session_date=${encodeURIComponent(targetDate)}`,
          { cache: 'no-store' }
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (data?.paper_ledger) {
          setHistoricalLedger(data.paper_ledger);
        }
      } catch (err: any) {
        setActionToast(`Unable to load ledger for ${targetDate}: ${err?.message || 'Error'}`);
        setTimeout(() => setActionToast(null), 4000);
      } finally {
        setLoadingHistory(false);
      }
    },
    [dashboard?.paper_ledger?.session_date]
  );

  // Catch #3: Auto-refresh /ledger/sessions whenever Committed Capital changes (Recalculate button)
  // or when a live trade closes / session rolls over.
  useEffect(() => {
    if (!dashboard?.paper_ledger) return;
    fetchLedgerSessions(activeCapitalInr);
  }, [
    activeCapitalInr,
    dashboard?.paper_ledger?.session_date,
    dashboard?.paper_ledger?.stats?.total_closed,
    dashboard?.paper_ledger?.stats?.net_realized_pnl_inr,
    fetchLedgerSessions,
  ]);

  const fetchDashboard = useCallback(
    async (
      forceRefresh = false,
      overridePrefs?: {
        capital_inr: number;
        risk_mode: 'PERCENT' | 'FIXED_INR';
        risk_value: number;
        lot_size: number;
      },
      silent = false
    ) => {
      // Only skip routine background polls if an in-flight request is already active.
      // Explicit user actions (Recalculate, manual Refresh, trade actions) must NEVER be dropped!
      if (silent && isFetchingRef.current) return;
      isFetchingRef.current = true;
      try {
        if (!dashboard) setLoading(true);
        else if (!silent) setRefreshing(true);

        const params = new URLSearchParams();
        if (forceRefresh) params.set('force_refresh', 'true');
        if (overridePrefs) {
          params.set('capital_inr', String(overridePrefs.capital_inr));
          params.set('risk_mode', overridePrefs.risk_mode);
          params.set('risk_value', String(overridePrefs.risk_value));
          params.set('lot_size', String(overridePrefs.lot_size));
        }

        const res = await fetch(`/api/v13/nifty-options/dashboard?${params.toString()}`, {
          cache: 'no-store',
        });
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const json: NiftyOptionsDashboardResponse = await res.json();
        setDashboard(json);
        setError(null);
        processLedgerNotifications(json);

        if (json.quant_engine?.market_snapshot) {
          const ms = json.quant_engine.market_snapshot;
          onSpotUpdate?.({
            spot_ltp: ms.spot_ltp,
            spot_change: ms.spot_change ?? 0.0,
            spot_change_pct: ms.spot_change_pct ?? 0.0,
            feed_mode: json.quant_engine.feed_mode,
          });
        }

        if (!prefsSynced && json.sizing_preferences) {
          setCapitalInput(json.sizing_preferences.capital_inr);
          setRiskModeInput(json.sizing_preferences.risk_mode);
          setRiskValueInput(json.sizing_preferences.risk_value);
          setLotSizeInput(json.sizing_preferences.lot_size);
          if (json.fyers_status?.app_id) {
            setFyersAppId(json.fyers_status.app_id);
          }
          if (json.fyers_status?.redirect_uri) {
            setFyersRedirectUri(json.fyers_status.redirect_uri);
          }
          setPrefsSynced(true);
        }
      } catch (err: any) {
        setError(err?.message || 'Unable to load NIFTY 50 Options Quant Engine');
      } finally {
        setLoading(false);
        if (!silent) setRefreshing(false);
        isFetchingRef.current = false;
      }
    },
    [dashboard, prefsSynced, processLedgerNotifications, onSpotUpdate]
  );

  // Cross-Tab Single Source of Truth Polling:
  // - 2.0s ultra-fast polling when Tab 4 (`⚡ Alpha`) is active
  // - 2.5s background polling when user is on Tab 1, 2, or 3 so Top Navbar Spot Ticker & Alpha Toasts stay live!
  useEffect(() => {
    const pollMs = isActive ? 2000 : 2500;
    fetchDashboard(false, undefined, !isActive);
    const interval = setInterval(() => {
      fetchDashboard(false, undefined, true);
    }, pollMs);
    return () => clearInterval(interval);
  }, [isActive, fetchDashboard]);

  const handleApplySizing = async (
    nextCapital = capitalInput,
    nextMode = riskModeInput,
    nextVal = riskValueInput,
    nextLot = lotSizeInput
  ) => {
    setIsCalculating(true);
    setCapitalInput(nextCapital);
    setRiskModeInput(nextMode);
    setRiskValueInput(nextVal);
    setLotSizeInput(nextLot);
    try {
      await fetchDashboard(true, {
        capital_inr: nextCapital,
        risk_mode: nextMode,
        risk_value: nextVal,
        lot_size: nextLot,
      }, false);
      setActionToast(`⚡ Sizing recalculated: ₹${Number(nextCapital).toLocaleString('en-IN')} (${nextMode === 'PERCENT' ? `${nextVal}%` : `₹${nextVal}`})`);
      setTimeout(() => setActionToast(null), 3000);
    } catch (err: any) {
      setActionToast(`Error: ${err?.message || 'Failed to recalculate sizing'}`);
      setTimeout(() => setActionToast(null), 4000);
    } finally {
      setIsCalculating(false);
    }
  };

  const handleFyersSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFyersSubmitting(true);
    setFyersMessage(null);
    try {
      const res = await fetch('/api/v13/nifty-options/fyers-auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          app_id: fyersAppId,
          secret_id: fyersSecretId || undefined,
          redirect_uri: fyersRedirectUri,
          auth_code_or_url: fyersAuthCodeUrl || undefined,
          direct_access_token: fyersDirectToken || undefined,
        }),
      });
      const data = await res.json();
      if (data.status === 'success') {
        setFyersMessage({ type: 'success', text: data.message });
        setFyersAuthCodeUrl('');
        setFyersDirectToken('');
        await fetchDashboard(true);
      } else {
        setFyersMessage({ type: 'error', text: data.message || 'Fyers token exchange failed' });
      }
    } catch (err: any) {
      setFyersMessage({ type: 'error', text: err?.message || 'Network error saving Fyers credentials' });
    } finally {
      setFyersSubmitting(false);
    }
  };

  const handlePaperEnter = async () => {
    try {
      const res = await fetch('/api/v13/nifty-options/paper-trade/enter', { method: 'POST' });
      const data = await res.json();
      setActionToast(data.message || 'Paper trade action processed');
      setTimeout(() => setActionToast(null), 5000);
      await fetchDashboard(false);
    } catch (err: any) {
      setActionToast(`Error: ${err?.message}`);
    }
  };

  const handlePaperClose = async () => {
    try {
      const res = await fetch('/api/v13/nifty-options/paper-trade/close', { method: 'POST' });
      const data = await res.json();
      setActionToast(data.message || 'Paper trade squared off');
      setTimeout(() => setActionToast(null), 5000);
      await fetchDashboard(false);
    } catch (err: any) {
      setActionToast(`Error: ${err?.message}`);
    }
  };

  const handlePaperReset = async () => {
    try {
      const res = await fetch('/api/v13/nifty-options/paper-trade/reset', { method: 'POST' });
      const data = await res.json();
      setActionToast(data.message || 'Paper ledger reset');
      setTimeout(() => setActionToast(null), 4000);
      await fetchDashboard(false);
    } catch (err: any) {
      setActionToast(`Error: ${err?.message}`);
    }
  };

  if (loading && !dashboard) {
    return (
      <div className="p-8 rounded-2xl bg-dark-850 border border-white/10 text-center space-y-3">
        <RefreshCw className="w-7 h-7 text-cyan-400 animate-spin mx-auto" />
        <p className="text-sm font-semibold text-white">
          Initializing ⚡ ALPHA QUANT v3.0 Institutional Options Engine...
        </p>
        <p className="text-xs text-slate-400">
          Solving Pure-Python Black-76 Greeks, Put-Call Parity Forward &amp; 4 Hard Regime Gates
        </p>
      </div>
    );
  }

  if (error && !dashboard) {
    return (
      <div className="p-6 rounded-2xl bg-rose-950/30 border border-rose-500/40 text-rose-200 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0" />
          <div>
            <p className="text-sm font-bold">⚡ Alpha Options Engine Error</p>
            <p className="text-xs text-rose-300/80">{error}</p>
          </div>
        </div>
        <button
          onClick={() => fetchDashboard(true)}
          className="px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-xs font-bold"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!dashboard) return null;

  const { fyers_status, quant_engine, paper_ledger } = dashboard;
  const ms = quant_engine.market_snapshot;
  const rg = quant_engine.regime_gates;
  const sc = quant_engine.selected_contract;
  const et = quant_engine.entry_trigger;
  const tp = quant_engine.trade_plan;
  const sz = quant_engine.position_sizing;
  const isFull = quant_engine.feed_mode === 'FULL';
  const isBull = rg.directional_bias === 'BULLISH_CE';

  // Historical Archive Selection & Displayed Ledger Binding
  const isHistoricalSelected = Boolean(
    selectedSessionDate && selectedSessionDate !== paper_ledger.session_date
  );
  const displayedLedger: NiftyOptionsPaperLedger =
    isHistoricalSelected && historicalLedger ? historicalLedger : paper_ledger;

  const netRealizedRoiPct =
    activeCapitalInr > 0
      ? (displayedLedger.stats.net_realized_pnl_inr / activeCapitalInr) * 100
      : 0;

  const openTradeRoiPct =
    paper_ledger.open_trade && activeCapitalInr > 0
      ? (paper_ledger.open_trade.net_pnl_inr / activeCapitalInr) * 100
      : 0;

  // Dynamic Cumulative Scorecard Options ("ALL" + "From YYYY-MM-DD" for every traded session)
  const tradedSessionsAsc = (ledgerSessions?.sessions ?? [])
    .filter((s) => s.total_closed > 0)
    .slice()
    .sort((a, b) => a.session_date.localeCompare(b.session_date));

  const buildCumulativeOption = (fromKey: string) => {
    const subset =
      fromKey === 'ALL'
        ? tradedSessionsAsc
        : tradedSessionsAsc.filter((s) => s.session_date >= fromKey);
    const days = subset.length;
    const trades = subset.reduce((acc, s) => acc + s.total_closed, 0);
    const wins = subset.reduce((acc, s) => acc + s.wins, 0);
    const losses = subset.reduce((acc, s) => acc + s.losses, 0);
    const wrPct = trades > 0 ? Number(((wins / trades) * 100).toFixed(1)) : 0;
    const netPnl = Number(subset.reduce((acc, s) => acc + s.net_realized_pnl_inr, 0).toFixed(2));
    const roiPct = activeCapitalInr > 0 ? Number(((netPnl / activeCapitalInr) * 100).toFixed(2)) : 0;
    const cumR = Number(subset.reduce((acc, s) => acc + s.cum_r_multiple, 0).toFixed(2));
    const pnlSign = netPnl >= 0 ? '+' : '';
    const roiSign = roiPct >= 0 ? '+' : '';
    const prefix = fromKey === 'ALL' ? `All ${days}D` : `From ${fromKey} (${days}D)`;
    return {
      key: fromKey,
      days,
      trades,
      wins,
      losses,
      wrPct,
      netPnl,
      roiPct,
      cumR,
      label: `${prefix}: ${pnlSign}₹${Math.round(netPnl).toLocaleString('en-IN')} (${roiSign}${roiPct.toFixed(2)}%) • ${trades}T (${wins}W/${losses}L)`,
    };
  };

  const cumulativeRangeOptions =
    tradedSessionsAsc.length > 0
      ? [
          buildCumulativeOption('ALL'),
          ...tradedSessionsAsc.map((s) => buildCumulativeOption(s.session_date)),
        ]
      : [];

  const effectiveCumulativeFromDate = cumulativeRangeOptions.some(
    (opt) => opt.key === cumulativeFromDate
  )
    ? cumulativeFromDate
    : 'ALL';

  const activeCumulativeOption =
    cumulativeRangeOptions.find((opt) => opt.key === effectiveCumulativeFromDate) ??
    (cumulativeRangeOptions.length > 0 ? cumulativeRangeOptions[0] : null);

  return (
    <div className="space-y-4">
      {/* Portal-Backed In-App Notification Flash (Renders directly into document.body across all 4 tabs!) */}
      <AlphaToastNotification
        toasts={alphaToasts}
        onDismiss={dismissAlphaToast}
        onSwitchToAlphaTab={onSwitchToAlphaTab}
        isAlphaTabActive={isActive}
      />

      {/* ===================================================================== */}
      {/* 1. TOP INSTITUTIONAL HEADER + FYERS 1-CLICK DAILY CONNECTOR           */}
      {/* ===================================================================== */}
      <div className="rounded-xl bg-dark-850 border border-white/10 p-3.5 shadow-lg">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center shadow-md shadow-cyan-500/20 border border-white/20">
              <Target className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-sm sm:text-base font-bold text-white tracking-tight">
                  ⚡ ALPHA QUANT ENGINE v3.0
                </h2>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">
                  BLACK-76 • SECONDS-TO-EXPIRY
                </span>
                <span
                  className={cn(
                    "px-2 py-0.5 rounded-full text-[10px] font-bold border flex items-center gap-1",
                    isFull
                      ? "bg-emerald-950/60 border-emerald-500/40 text-emerald-300"
                      : "bg-amber-950/60 border-amber-500/40 text-amber-300"
                  )}
                >
                  <span
                    className={cn(
                      "w-1.5 h-1.5 rounded-full",
                      isFull ? "bg-emerald-400 animate-pulse" : "bg-amber-400"
                    )}
                  />
                  {isFull ? 'FULL MODE (FYERS v3 LIVE)' : 'DEGRADED MODE (FREE FALLBACK)'}
                </span>
              </div>
              <p className="text-[11px] text-slate-400 mt-0.5">
                {quant_engine.ist_time_str} • Expiry:{' '}
                <span className="text-slate-200 font-mono font-semibold">{ms.expiry_str}</span> ({ms.dte_days} DTE)
                • Forward ({ms.forward_source}):{' '}
                <span className="text-cyan-300 font-mono font-semibold">₹{ms.futures_ltp.toLocaleString('en-IN')}</span>
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => setAlphaAudioEnabled((v) => !v)}
              className={cn(
                "px-2.5 py-1.5 rounded-lg text-xs font-bold border transition-all flex items-center gap-1.5",
                alphaAudioEnabled
                  ? "bg-cyan-950/50 border-cyan-500/40 text-cyan-300 hover:bg-cyan-900/60"
                  : "bg-dark-800 border-white/10 text-slate-400 hover:text-white"
              )}
              title={alphaAudioEnabled ? "Alpha Audio & Voice Alerts Enabled" : "Alpha Audio & Voice Alerts Muted"}
            >
              {alphaAudioEnabled ? <Volume2 className="w-3.5 h-3.5" /> : <VolumeX className="w-3.5 h-3.5" />}
              <span>{alphaAudioEnabled ? 'Alerts ON' : 'Muted'}</span>
            </button>

            <button
              onClick={() => setShowFyersDrawer((v) => !v)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-bold border transition-all flex items-center gap-1.5",
                fyers_status.connected
                  ? "bg-emerald-950/40 border-emerald-500/40 text-emerald-300 hover:bg-emerald-950/70"
                  : "bg-cyan-950/50 border-cyan-500/40 text-cyan-200 hover:bg-cyan-900/60"
              )}
            >
              <KeyRound className="w-3.5 h-3.5" />
              <span>
                {fyers_status.connected
                  ? `Fyers Connected (${fyers_status.user_name || 'Live'})`
                  : 'Connect Fyers Daily Token'}
              </span>
              {showFyersDrawer ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>

            <button
              onClick={() => fetchDashboard(true)}
              disabled={refreshing}
              className="px-3 py-1.5 rounded-lg bg-dark-800 hover:bg-white/10 text-slate-200 border border-white/10 text-xs font-semibold flex items-center gap-1.5 transition-all"
            >
              <RefreshCw className={cn("w-3.5 h-3.5", refreshing && "animate-spin text-cyan-400")} />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {actionToast && (
          <div className="mt-2.5 px-3 py-1.5 rounded-lg bg-cyan-950/40 border border-cyan-500/30 text-xs text-cyan-200 font-medium flex items-center justify-between">
            <span>{actionToast}</span>
            <button onClick={() => setActionToast(null)} className="text-slate-400 hover:text-white ml-2">✕</button>
          </div>
        )}

        {/* Degraded Mode Transparent Notice */}
        {!isFull && quant_engine.degraded_bypassed_checks.length > 0 && (
          <div className="mt-3 p-2.5 rounded-lg bg-amber-950/25 border border-amber-500/30 flex items-start gap-2.5 text-[11px] text-amber-200/90">
            <Info className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
            <div className="space-y-0.5">
              <p className="font-semibold text-amber-300">
                Running in Degraded Free Fallback Mode (Yahoo 5m + Exact Strike Put-Call Parity Forward):
              </p>
              <p className="text-amber-200/80">
                Connect your Fyers Non-Trading App (<span className="font-mono">NSE Paper Trade Lab</span>) above to unlock:{' '}
                {quant_engine.degraded_bypassed_checks.join(' • ')}.
              </p>
            </div>
          </div>
        )}

        {/* Expandable Fyers 1-Click Daily Auth Helper Drawer */}
        {showFyersDrawer && (
          <form
            onSubmit={handleFyersSubmit}
            className="mt-3 pt-3 border-t border-white/10 bg-dark-900/70 rounded-xl p-3.5 space-y-3"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-xs font-bold text-white flex items-center gap-1.5">
                  <KeyRound className="w-3.5 h-3.5 text-cyan-400" />
                  Fyers v3 Non-Trading App Connector (`NSE Paper Trade Lab`)
                </h3>
                <p className="text-[11px] text-slate-400">
                  Step 1: Save App ID &amp; Secret once → Step 2: Click &ldquo;Open Fyers Login&rdquo; → Step 3: Paste the redirected{' '}
                  <code className="text-cyan-300">https://127.0.0.1/?s=ok&amp;auth_code=...</code> URL below.
                </p>
              </div>
              {fyers_status.login_url && (
                <a
                  href={fyers_status.login_url}
                  target="_blank"
                  rel="noreferrer"
                  className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold flex items-center gap-1.5 shadow-sm"
                >
                  <span>1. Open Fyers Login</span>
                  <ExternalLink className="w-3.5 h-3.5" />
                </a>
              )}
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
              <div>
                <label className="block text-[10px] font-semibold uppercase text-slate-400 mb-1">
                  Fyers App ID (Client ID)
                </label>
                <input
                  type="text"
                  value={fyersAppId}
                  onChange={(e) => setFyersAppId(e.target.value)}
                  placeholder="e.g. ABCD123456-100"
                  className="w-full px-2.5 py-1.5 rounded-lg bg-dark-800 border border-white/10 text-xs text-white font-mono focus:outline-none focus:border-cyan-500"
                />
              </div>
              <div>
                <label className="block text-[10px] font-semibold uppercase text-slate-400 mb-1">
                  Secret ID {fyers_status.secret_configured && <span className="text-emerald-400">(Saved ✓)</span>}
                </label>
                <input
                  type="password"
                  value={fyersSecretId}
                  onChange={(e) => setFyersSecretId(e.target.value)}
                  placeholder={fyers_status.secret_configured ? '•••••••• (Leave blank to keep)' : 'Enter Fyers Secret ID'}
                  className="w-full px-2.5 py-1.5 rounded-lg bg-dark-800 border border-white/10 text-xs text-white font-mono focus:outline-none focus:border-cyan-500"
                />
              </div>
              <div>
                <label className="block text-[10px] font-semibold uppercase text-slate-400 mb-1">
                  Redirect URL
                </label>
                <input
                  type="text"
                  value={fyersRedirectUri}
                  onChange={(e) => setFyersRedirectUri(e.target.value)}
                  placeholder="https://127.0.0.1"
                  className="w-full px-2.5 py-1.5 rounded-lg bg-dark-800 border border-white/10 text-xs text-white font-mono focus:outline-none focus:border-cyan-500"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-4 gap-2.5 items-end">
              <div className="sm:col-span-3">
                <label className="block text-[10px] font-semibold uppercase text-cyan-300 mb-1">
                  Paste Redirected URL (`https://127.0.0.1/?auth_code=...`) or Raw `auth_code`
                </label>
                <input
                  type="text"
                  value={fyersAuthCodeUrl}
                  onChange={(e) => setFyersAuthCodeUrl(e.target.value)}
                  placeholder="Paste full https://127.0.0.1/?s=ok&code=200&auth_code=eyJ... URL here"
                  className="w-full px-2.5 py-1.5 rounded-lg bg-dark-800 border border-cyan-500/40 text-xs text-white font-mono focus:outline-none focus:border-cyan-400"
                />
              </div>
              <button
                type="submit"
                disabled={fyersSubmitting}
                className="w-full py-1.5 px-3 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-bold transition-all shadow-sm"
              >
                {fyersSubmitting ? 'Verifying...' : '2. Save & Activate Token'}
              </button>
            </div>

            {fyersMessage && (
              <div
                className={cn(
                  "p-2 rounded-lg text-xs font-medium flex items-center gap-2",
                  fyersMessage.type === 'success'
                    ? "bg-emerald-950/50 border border-emerald-500/40 text-emerald-300"
                    : "bg-rose-950/50 border border-rose-500/40 text-rose-300"
                )}
              >
                {fyersMessage.type === 'success' ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                ) : (
                  <XCircle className="w-4 h-4 text-rose-400 shrink-0" />
                )}
                <span>{fyersMessage.text}</span>
              </div>
            )}
          </form>
        )}
      </div>

      {actionToast && (
        <div className="p-2.5 rounded-xl bg-cyan-950/60 border border-cyan-500/40 text-cyan-200 text-xs font-semibold flex items-center justify-between">
          <span>⚡ {actionToast}</span>
          <button onClick={() => setActionToast(null)} className="text-slate-400 hover:text-white">
            ✕
          </button>
        </div>
      )}

      {/* ===================================================================== */}
      {/* 2. UNIVERSAL CAPITAL & RISK SIZER BAR (WORKS FOR ANY CAPITAL & RISK)  */}
      {/* ===================================================================== */}
      <div className="rounded-xl bg-dark-850 border border-white/10 p-3.5 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Wallet className="w-4 h-4 text-emerald-400" />
            <h3 className="text-xs font-bold uppercase tracking-wider text-white">
              Universal Capital &amp; All-In Risk Sizer (Dynamic Lot &amp; Statutory Charges Engine)
            </h3>
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[10px] text-slate-400 mr-1">Quick Capital:</span>
            {CAPITAL_PRESETS.map((cap) => (
              <button
                key={cap}
                type="button"
                disabled={isCalculating}
                onClick={() => handleApplySizing(cap, riskModeInput, riskValueInput, lotSizeInput)}
                className={cn(
                  "px-2 py-0.5 rounded text-[10px] font-mono font-bold border transition-all",
                  isCalculating && "opacity-60 cursor-not-allowed",
                  Math.abs(capitalInput - cap) < 1
                    ? "bg-emerald-600 text-white border-emerald-400"
                    : "bg-dark-800 text-slate-300 border-white/10 hover:bg-white/10"
                )}
              >
                {formatIndianCompact(cap)}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2.5 items-end">
          <div>
            <label className="flex items-center justify-between text-[10px] font-semibold uppercase text-slate-400 mb-1">
              <span>Trading Capital (₹)</span>
              <span className="text-emerald-400 font-mono font-bold">
                {formatIndianCompact(capitalInput)}
              </span>
            </label>
            <input
              type="text"
              inputMode="numeric"
              value={capitalInput > 0 ? capitalInput.toLocaleString('en-IN') : ''}
              onChange={(e) => handleIndianNumberInputChange(e, capitalInput, setCapitalInput)}
              placeholder="25,00,000"
              className="w-full px-2.5 py-1.5 rounded-lg bg-dark-800 border border-white/10 text-xs font-mono font-bold text-white focus:outline-none focus:border-emerald-500"
            />
          </div>

          <div>
            <label className="block text-[10px] font-semibold uppercase text-slate-400 mb-1">
              Risk Mode
            </label>
            <select
              value={riskModeInput}
              onChange={(e) => {
                const nextMode = e.target.value as 'PERCENT' | 'FIXED_INR';
                const nextVal = nextMode === 'PERCENT' ? 2.0 : Math.round(capitalInput * 0.02);
                setRiskModeInput(nextMode);
                setRiskValueInput(nextVal);
              }}
              className="w-full px-2.5 py-1.5 rounded-lg bg-dark-800 border border-white/10 text-xs font-semibold text-white focus:outline-none focus:border-emerald-500"
            >
              <option value="PERCENT">% of Capital per Trade</option>
              <option value="FIXED_INR">Fixed ₹ per Trade</option>
            </select>
          </div>

          <div>
            <label className="block text-[10px] font-semibold uppercase text-slate-400 mb-1">
              {riskModeInput === 'PERCENT' ? 'Risk % per Trade' : 'Max Risk (₹) per Trade'}
            </label>
            {riskModeInput === 'PERCENT' ? (
              <input
                type="number"
                min={0.25}
                max={25.0}
                step={0.25}
                value={riskValueInput}
                onChange={(e) => setRiskValueInput(Number(e.target.value))}
                className="w-full px-2.5 py-1.5 rounded-lg bg-dark-800 border border-white/10 text-xs font-mono font-bold text-white focus:outline-none focus:border-emerald-500"
              />
            ) : (
              <input
                type="text"
                inputMode="numeric"
                value={riskValueInput > 0 ? Math.round(riskValueInput).toLocaleString('en-IN') : ''}
                onChange={(e) => handleIndianNumberInputChange(e, Math.round(riskValueInput), setRiskValueInput)}
                placeholder="50,000"
                className="w-full px-2.5 py-1.5 rounded-lg bg-dark-800 border border-white/10 text-xs font-mono font-bold text-white focus:outline-none focus:border-emerald-500"
              />
            )}
          </div>

          <div>
            <label className="block text-[10px] font-semibold uppercase text-slate-400 mb-1">
              NIFTY Lot Size
            </label>
            <input
              type="number"
              min={1}
              step={25}
              value={lotSizeInput}
              onChange={(e) => setLotSizeInput(Number(e.target.value))}
              className="w-full px-2.5 py-1.5 rounded-lg bg-dark-800 border border-white/10 text-xs font-mono font-bold text-white focus:outline-none focus:border-emerald-500"
            />
          </div>

          <button
            type="button"
            onClick={() => handleApplySizing(capitalInput, riskModeInput, riskValueInput, lotSizeInput)}
            disabled={isCalculating}
            className={cn(
              "w-full py-1.5 px-3 rounded-lg text-white text-xs font-bold transition-all shadow-sm flex items-center justify-center gap-1.5",
              isCalculating
                ? "bg-emerald-800 cursor-not-allowed opacity-80"
                : "bg-emerald-600 hover:bg-emerald-500 active:scale-[0.98]"
            )}
          >
            {isCalculating ? (
              <>
                <RefreshCw className="w-3.5 h-3.5 animate-spin text-white" />
                <span>Calculating...</span>
              </>
            ) : (
              <span>Recalculate Lots &amp; Risk</span>
            )}
          </button>
        </div>

        {/* Universal Sizing Output Summary Strip */}
        <div
          className={cn(
            "p-2.5 rounded-lg border text-xs flex flex-wrap items-center justify-between gap-3",
            sz.allowed_lots > 0
              ? "bg-emerald-950/20 border-emerald-500/30 text-emerald-200"
              : "bg-amber-950/30 border-amber-500/40 text-amber-200"
          )}
        >
          <div className="flex items-center gap-2">
            {sz.allowed_lots > 0 ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            ) : (
              <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
            )}
            <span className="font-semibold">{sz.sizing_note}</span>
          </div>
          <div className="flex items-center gap-3 font-mono text-[11px]">
            <span>
              Allowed: <strong className="text-white">{sz.allowed_lots} Lot(s)</strong> ({sz.allowed_qty.toLocaleString('en-IN')} Qty)
              {sz.is_iceberg && sz.entry_slices && (
                <span className="ml-1 text-cyan-300">
                  • 🧊 {sz.entry_legs} Legs [{sz.entry_slices.join('+')}]
                </span>
              )}
            </span>
            <span>•</span>
            <span>
              1-Lot Margin: <strong className="text-white">₹{sz.capital_per_lot_inr.toLocaleString('en-IN')}</strong>
            </span>
            <span>•</span>
            <span>
              All-In Risk/Lot: <strong className="text-rose-300">₹{sz.all_in_risk_per_lot_inr.toLocaleString('en-IN')}</strong>
            </span>
            <span>•</span>
            <span>
              Breakeven: <strong className="text-cyan-300">+{sz.breakeven_points} pts</strong>
            </span>
          </div>
        </div>
      </div>

      {/* ===================================================================== */}
      {/* 3. MODULE 1: LIVE MARKET SNAPSHOT & 4 HARD REGIME GATES               */}
      {/* ===================================================================== */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Left 5 Cols: 4 Hard Regime Gates Checklist */}
        <div className="lg:col-span-5 rounded-xl bg-dark-850 border border-white/10 p-3.5 space-y-2.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Gauge className="w-4 h-4 text-indigo-400" />
              <h3 className="text-xs font-bold uppercase tracking-wider text-white">
                Module 1: 4 Hard Regime Gates
              </h3>
            </div>
            <span
              className={cn(
                "px-2 py-0.5 rounded text-[10px] font-mono font-bold border",
                 isBull
                  ? "bg-emerald-950/50 border-emerald-500/40 text-emerald-300"
                  : "bg-rose-950/50 border-rose-500/40 text-rose-300"
              )}
            >
              BIAS: {isBull ? 'BULLISH (CALLS)' : 'BEARISH (PUTS)'}
            </span>
          </div>

          <div className="space-y-2">
            {rg.gates.map((g) => (
              <div
                key={g.id}
                className={cn(
                  "p-2.5 rounded-lg border text-xs transition-all",
                  g.passed
                    ? "bg-emerald-950/20 border-emerald-500/30"
                    : g.status === 'AFTER_HOURS'
                    ? "bg-slate-900/80 border-white/10"
                    : "bg-rose-950/20 border-rose-500/30"
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-bold text-white">{g.name}</span>
                  <span
                    className={cn(
                      "px-1.5 py-0.5 rounded text-[10px] font-mono font-bold",
                      g.passed
                        ? "bg-emerald-500/20 text-emerald-300"
                        : g.status === 'AFTER_HOURS'
                        ? "bg-slate-700 text-slate-300"
                        : "bg-rose-500/20 text-rose-300"
                    )}
                  >
                    {g.status}
                  </span>
                </div>
                <p className="text-[11px] text-slate-300 mt-1 leading-relaxed">{highlightQuantText(g.detail)}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Right 7 Cols: Module 2, 3 & 4 Smart Strike + Execution Signal Card */}
        <div className="lg:col-span-7 rounded-xl bg-dark-850 border border-white/10 p-3.5 space-y-3">
          {/* Live Anti-Whipsaw Guard Status Banner */}
          {paper_ledger.entry_guard_blocked && (
            <div className="p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs flex items-center gap-2">
              <span className="text-base animate-pulse">⏸️</span>
              <div className="flex-1 min-w-0">
                <span className="font-bold text-amber-300 mr-1.5 uppercase tracking-wide">
                  {tp.signal_state === 'EXECUTE_BUY' ? 'Auto-Buy Paused by Guard:' : 'Active Guard Protection:'}
                </span>
                <span className="opacity-95">{highlightQuantText(paper_ledger.entry_guard_reason)}</span>
              </div>
            </div>
          )}

          {/* Signal Headline Banner */}
          <div
            className={cn(
              "p-3 rounded-xl border flex flex-wrap items-center justify-between gap-2",
              tp.signal_state === 'EXECUTE_BUY'
                ? paper_ledger.entry_guard_blocked
                  ? "bg-amber-950/40 border-amber-500/40 text-amber-200"
                  : "bg-emerald-950/50 border-emerald-500/50 text-emerald-200"
                : tp.signal_state === 'ARMED_WAITING_TRIGGER' || tp.signal_state === 'READY_AFTER_HOURS_STUDY'
                ? "bg-indigo-950/40 border-indigo-500/40 text-indigo-200"
                : "bg-dark-900 border-white/10 text-slate-300"
            )}
          >
            <div className="flex items-center gap-2.5">
              {tp.signal_state === 'EXECUTE_BUY' ? (
                paper_ledger.entry_guard_blocked ? (
                  <ShieldAlert className="w-5 h-5 text-amber-400 shrink-0" />
                ) : (
                  <ShieldCheck className="w-5 h-5 text-emerald-400 shrink-0" />
                )
              ) : (
                <ShieldAlert className="w-5 h-5 text-indigo-400 shrink-0" />
              )}
              <div>
                <div className="text-[10px] font-mono uppercase tracking-wider opacity-80">
                  {tp.signal_state} {paper_ledger.entry_guard_blocked ? '(PAUSED)' : ''} • {et.trigger_type}
                </div>
                <div className="text-sm sm:text-base font-bold text-white">{formatOptionSymbolInText(tp.signal_headline)}</div>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {!paper_ledger.open_trade ? (
                (() => {
                  const isCleanSetup = rg.all_passed && tp.signal_state === 'EXECUTE_BUY' && !paper_ledger.entry_guard_blocked;
                  return (
                    <button
                      type="button"
                      onClick={handlePaperEnter}
                      className={cn(
                        "px-3 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1.5 shadow-sm transition-all",
                        isCleanSetup
                          ? "bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-900/30"
                          : "bg-amber-600/80 hover:bg-amber-500 text-white border border-amber-400/40"
                      )}
                      title={
                        isCleanSetup
                          ? "Enter Quant-Approved Paper Trade"
                          : paper_ledger.entry_guard_blocked
                          ? "Override Active Quant Guard (Manual Simulation Entry)"
                          : "Simulate / Force Paper Entry (Gates Blocked or After-Hours)"
                      }
                    >
                      {isCleanSetup ? (
                        <Play className="w-3.5 h-3.5" />
                      ) : (
                        <AlertTriangle className="w-3.5 h-3.5 text-amber-200" />
                      )}
                      <span>
                        {isCleanSetup
                          ? `Paper Buy (${sz.study_lots} Lot)`
                          : paper_ledger.entry_guard_blocked
                          ? `Manual Override Buy (${sz.study_lots} Lot)`
                          : `Force Paper Buy (${sz.study_lots} Lot)`}
                      </span>
                    </button>
                  );
                })()
              ) : (
                <button
                  type="button"
                  onClick={handlePaperClose}
                  className="px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-xs font-bold flex items-center gap-1.5 shadow-sm"
                >
                  <Square className="w-3.5 h-3.5" />
                  <span>Square-Off Open Paper Trade</span>
                </button>
              )}
            </div>
          </div>

          {/* Market Internals Micro-Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
            <div className="p-2 rounded-lg bg-dark-900/80 border border-white/5">
              <div className="text-[10px] text-slate-400">
                <span className="text-emerald-300 font-semibold">NIFTY Spot</span> vs{' '}
                <span className="text-amber-300 font-semibold">VWAP</span>
              </div>
              <div className="font-mono font-bold mt-0.5">
                <span className={ms.spot_ltp >= ms.futures_vwap ? 'text-emerald-300' : 'text-rose-300'}>
                  {ms.spot_ltp.toLocaleString('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
                </span>{' '}
                <span className="text-slate-500">/</span>{' '}
                <span className="text-amber-300">
                  {ms.futures_vwap.toLocaleString('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
                </span>
              </div>
            </div>
            <div className="p-2 rounded-lg bg-dark-900/80 border border-white/5">
              <div className="text-[10px] text-slate-400">
                <span className="text-cyan-300 font-semibold">5m</span> /{' '}
                <span className="text-purple-300 font-semibold">15m EMA(20)</span>
              </div>
              <div className="font-mono font-bold mt-0.5">
                <span className="text-cyan-300">
                  {ms.spot_ema20_5m.toLocaleString('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
                </span>{' '}
                <span className="text-slate-500">/</span>{' '}
                <span className="text-purple-300">
                  {ms.spot_ema20_15m.toLocaleString('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
                </span>
              </div>
            </div>
            <div className="p-2 rounded-lg bg-dark-900/80 border border-white/5">
              <div className="text-[10px] text-slate-400">
                <span className="text-cyan-300 font-semibold">ATM Straddle</span> vs{' '}
                <span className="text-amber-300 font-semibold">VWAP</span>
              </div>
              <div className="font-mono font-bold mt-0.5">
                <span className="text-cyan-300">₹{ms.atm_straddle_ltp.toFixed(1)}</span>{' '}
                <span className="text-slate-500">/</span>{' '}
                <span className="text-amber-300">₹{ms.atm_straddle_vwap.toFixed(1)}</span>
              </div>
            </div>
            <div className="p-2 rounded-lg bg-dark-900/80 border border-white/5">
              <div className="text-[10px] text-slate-400">
                <span className="text-amber-300 font-semibold">ADX(14)</span> •{' '}
                <span className="text-fuchsia-300 font-semibold">VIX</span> •{' '}
                <span className="text-emerald-300 font-semibold">Local PCR</span>
              </div>
              <div className="font-mono font-bold mt-0.5">
                <span
                  className={
                    ms.adx_5m >= 25
                      ? 'text-emerald-300'
                      : ms.adx_5m >= 18.5
                      ? 'text-amber-300'
                      : 'text-rose-400'
                  }
                >
                  {ms.adx_5m.toFixed(1)}
                </span>{' '}
                <span className="text-slate-500">•</span>{' '}
                <span className="text-fuchsia-300">{ms.india_vix.toFixed(1)}</span>{' '}
                <span className="text-slate-500">•</span>{' '}
                <span className={ms.local_5strike_pcr >= 1 ? 'text-emerald-400' : 'text-rose-400'}>
                  {ms.local_5strike_pcr.toFixed(2)}
                </span>
              </div>
            </div>
          </div>

          {/* Module 2: Selected Strike & Black-76 Greeks */}
          <div className="p-3 rounded-xl bg-dark-900/90 border border-cyan-500/25 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-500/30">
                  {sc.moneyness}
                </span>
                <span className="text-sm font-bold text-white font-mono tracking-wide">{formatOptionSymbol(sc.symbol)}</span>
              </div>
              <div className="flex items-center gap-3 text-xs font-mono">
                <span>
                  LTP: <strong className="text-emerald-300">₹{sc.ltp.toFixed(2)}</strong>
                </span>
                <span>
                  Δ: <strong className="text-cyan-300">{sc.delta.toFixed(2)}</strong>
                </span>
                <span>
                  IV: <strong className="text-purple-300">{sc.iv_pct.toFixed(1)}%</strong>
                </span>
                <span>
                  Θ/hr (est.): <strong className="text-rose-300">₹{sc.theta_hr_est.toFixed(2)}</strong>
                </span>
                <span>
                  Spread: <strong className="text-slate-200">{sc.spread_pct.toFixed(2)}%</strong>
                </span>
              </div>
            </div>
            <p className="text-[11px] text-slate-300 leading-relaxed">{highlightQuantText(sc.selection_reason)}</p>
            <p className="text-[11px] text-slate-200 leading-relaxed">
              <strong className="text-indigo-300">Trigger Diagnostic:</strong> {highlightQuantText(et.trigger_reason)}
            </p>
          </div>

          {/* Module 4: Exact Entry, Delta-Floor SL, Targets & Net PnL Projection */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            <div className="p-2.5 rounded-lg bg-dark-900 border border-white/10">
              <div className="text-[10px] uppercase text-slate-400 font-semibold">Entry Premium</div>
              <div className="text-base font-mono font-bold text-white mt-0.5">₹{tp.entry_premium.toFixed(2)}</div>
              <div className="text-[10px] text-slate-400 font-mono mt-0.5">
                Outlay: ₹{sz.capital_required_inr.toLocaleString('en-IN')} ({sz.study_lots}L)
              </div>
            </div>

            <div className="p-2.5 rounded-lg bg-rose-950/25 border border-rose-500/30">
              <div className="text-[10px] uppercase text-rose-300 font-semibold">
                Hard Stop-Loss (-{tp.sl_points.toFixed(1)} pts)
              </div>
              <div className="text-base font-mono font-bold text-rose-300 mt-0.5">₹{tp.sl_premium.toFixed(2)}</div>
              <div className="text-[10px] text-rose-300/80 font-mono mt-0.5">
                All-In Loss: -₹{sz.net_max_loss_inr.toLocaleString('en-IN')} ({sz.net_max_loss_pct_capital}%)
              </div>
            </div>

            <div className="p-2.5 rounded-lg bg-emerald-950/25 border border-emerald-500/30">
              <div className="text-[10px] uppercase text-emerald-300 font-semibold">
                Target 1 (+1.5R / +{tp.t1_points.toFixed(1)} pts)
              </div>
              <div className="text-base font-mono font-bold text-emerald-300 mt-0.5">₹{tp.t1_premium.toFixed(2)}</div>
              <div className="text-[10px] text-emerald-300/80 font-mono mt-0.5">
                Net Profit: +₹{sz.net_t1_profit_inr.toLocaleString('en-IN')} ({sz.net_rr_t1}R)
              </div>
            </div>

            <div className="p-2.5 rounded-lg bg-cyan-950/25 border border-cyan-500/30">
              <div className="text-[10px] uppercase text-cyan-300 font-semibold">
                Target 2 (+2.5R / +{tp.t2_points.toFixed(1)} pts)
              </div>
              <div className="text-base font-mono font-bold text-cyan-300 mt-0.5">₹{tp.t2_premium.toFixed(2)}</div>
              <div className="text-[10px] text-cyan-300/80 font-mono mt-0.5">
                Net Profit: +₹{sz.net_t2_profit_inr.toLocaleString('en-IN')} ({sz.net_rr_t2}R)
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-300 pt-1">
            <span className="flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5 text-amber-400" />
              <strong className="text-amber-300">Time-Stop Rule:</strong>{' '}
              {highlightQuantText(`${tp.time_stop_rule} • Trail SL at T1: ₹${tp.trail_sl_at_t1.toFixed(2)}`)}
            </span>
            <span className="font-mono text-slate-300">
              Est. Charges + Slippage ({sz.study_lots}L):{' '}
              <strong className="text-amber-300">
                ₹{Math.round(sz.estimated_charges_inr + sz.estimated_slippage_inr).toLocaleString('en-IN')}
              </strong>
            </span>
          </div>
        </div>
      </div>

      {/* ===================================================================== */}
      {/* 4. INTRADAY PAPER TRADING LEDGER & KILL-SWITCH MONITOR                */}
      {/* ===================================================================== */}
      <div className="rounded-xl bg-dark-850 border border-white/10 p-3.5 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Activity className="w-4 h-4 text-cyan-400" />
            <h3 className="text-xs font-bold uppercase tracking-wider text-white">
              Module 5: Intraday Paper Ledger, 20-Min Time-Stop &amp; Kill-Switch ({displayedLedger.session_date})
            </h3>
            <span
              className={cn(
                "px-2 py-0.5 rounded text-[10px] font-mono font-bold border",
                displayedLedger.kill_switch.kill_switch_engaged
                  ? "bg-rose-950/60 border-rose-500/40 text-rose-300"
                  : isHistoricalSelected
                  ? "bg-amber-950/50 border-amber-500/30 text-amber-300"
                  : "bg-emerald-950/50 border-emerald-500/30 text-emerald-300"
              )}
            >
              {displayedLedger.kill_switch.reason} ({displayedLedger.kill_switch.trades_taken_today}/
              {displayedLedger.kill_switch.max_trades_per_day} Trades)
            </span>

            {/* Historical & Live Session Selector Dropdown */}
            {ledgerSessions && ledgerSessions.sessions.length > 0 && (
              <div className="flex items-center gap-1.5">
                <select
                  aria-label="Select Paper Ledger Session Date"
                  value={selectedSessionDate || paper_ledger.session_date}
                  onChange={(e) => handleSelectSessionDate(e.target.value)}
                  className={cn(
                    "px-2 py-0.5 rounded text-[10px] font-mono font-bold border bg-dark-900 focus:outline-none cursor-pointer",
                    isHistoricalSelected
                      ? "border-amber-500/50 text-amber-300"
                      : "border-cyan-500/30 text-cyan-300"
                  )}
                >
                  {ledgerSessions.sessions.map((s) => {
                    const pnlSign = s.net_realized_pnl_inr >= 0 ? '+' : '';
                    const roiSign = s.roi_pct >= 0 ? '+' : '';
                    const labelPrefix = s.is_today
                      ? `📅 ${s.session_date} (Live Today)`
                      : `📜 ${s.session_date}`;
                    return (
                      <option key={s.session_date} value={s.session_date} className="bg-dark-900 text-slate-200">
                        {`${labelPrefix} • ${s.total_closed}T (${s.wins}W/${s.losses}L) • ${pnlSign}₹${Math.round(
                          s.net_realized_pnl_inr
                        ).toLocaleString('en-IN')} (${roiSign}${s.roi_pct.toFixed(2)}%)`}
                      </option>
                    );
                  })}
                </select>

                {/* Interactive Cumulative Scorecard Selector Pill (All 11D vs From YYYY-MM-DD) */}
                {activeCumulativeOption && (
                  <select
                    aria-label="Select Cumulative Scorecard Start Date"
                    value={effectiveCumulativeFromDate}
                    onChange={(e) => handleSelectCumulativeFromDate(e.target.value)}
                    title={`Cumulative Across ${activeCumulativeOption.days} Traded Sessions (${activeCumulativeOption.trades} Trades: ${activeCumulativeOption.wins}W / ${activeCumulativeOption.losses}L • ${activeCumulativeOption.wrPct}% WR • ${activeCumulativeOption.cumR >= 0 ? '+' : ''}${activeCumulativeOption.cumR.toFixed(2)}R)`}
                    className={cn(
                      "px-2 py-0.5 rounded text-[10px] font-mono font-bold border focus:outline-none cursor-pointer",
                      activeCumulativeOption.netPnl >= 0
                        ? "bg-emerald-950/50 border-emerald-500/40 text-emerald-300"
                        : "bg-rose-950/50 border-rose-500/40 text-rose-300"
                    )}
                  >
                    {cumulativeRangeOptions.map((opt) => (
                      <option
                        key={opt.key}
                        value={opt.key}
                        className="bg-dark-900 text-slate-200"
                      >
                        {opt.label}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3 text-xs font-mono">
            {loadingHistory && (
              <span className="text-[10px] text-amber-300 animate-pulse">Loading session...</span>
            )}
            <span>
              Closed: <strong>{displayedLedger.stats.total_closed}</strong> ({displayedLedger.stats.wins}W /{' '}
              {displayedLedger.stats.losses}L)
            </span>
            {displayedLedger.stats.auto_trades !== undefined && displayedLedger.stats.auto_trades > 0 && (
              <span className="text-emerald-300">
                🤖 Auto: <strong>{displayedLedger.stats.auto_trades}</strong> ({displayedLedger.stats.auto_win_rate_pct}% WR)
              </span>
            )}
            <span className="inline-flex items-center gap-1">
              <span>Net Realized:</span>
              <strong
                className={
                  displayedLedger.stats.net_realized_pnl_inr >= 0 ? 'text-emerald-400' : 'text-rose-400'
                }
              >
                {displayedLedger.stats.net_realized_pnl_inr >= 0 ? '+' : ''}₹
                {displayedLedger.stats.net_realized_pnl_inr.toLocaleString('en-IN')}
              </strong>
              <span
                title={`Return on Committed Trading Capital (₹${activeCapitalInr.toLocaleString('en-IN')})`}
                className={cn(
                  "px-1.5 py-0.5 rounded text-[10px] font-bold border",
                  displayedLedger.stats.net_realized_pnl_inr >= 0
                    ? "bg-emerald-950/60 border-emerald-500/30 text-emerald-300"
                    : "bg-rose-950/60 border-rose-500/30 text-rose-300"
                )}
              >
                ({netRealizedRoiPct >= 0 ? '+' : ''}
                {netRealizedRoiPct.toFixed(2)}%)
              </span>
            </span>

            {!isHistoricalSelected ? (
              <button
                type="button"
                onClick={handlePaperReset}
                className="px-2 py-1 rounded bg-dark-800 hover:bg-white/10 text-slate-300 border border-white/10 flex items-center gap-1 text-[10px]"
              >
                <RotateCcw className="w-3 h-3" />
                <span>Reset Ledger</span>
              </button>
            ) : (
              <div className="flex items-center gap-1.5">
                <span className="px-2 py-0.5 rounded bg-amber-500/15 border border-amber-500/40 text-amber-300 text-[10px] font-bold">
                  📜 ARCHIVE: {selectedSessionDate}
                </span>
                <button
                  type="button"
                  onClick={() => handleSelectSessionDate(paper_ledger.session_date)}
                  className="px-2 py-1 rounded bg-cyan-950/70 hover:bg-cyan-900/80 text-cyan-300 border border-cyan-500/40 flex items-center gap-1 text-[10px] font-bold"
                >
                  <span>🔙 Live Today</span>
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Active Open Paper Position */}
        {paper_ledger.open_trade && (
          <div className="p-3 rounded-xl bg-indigo-950/30 border border-indigo-500/40 flex flex-wrap items-center justify-between gap-3">
            <div className="space-y-0.5">
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/20 text-emerald-300 animate-pulse">
                  OPEN POSITION
                </span>
                {paper_ledger.open_trade.source === "AUTO_QUANT_SIGNAL" ? (
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                    🤖 AUTO (4 GATES)
                  </span>
                ) : (
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40">
                    ⚡ FORCE BUY
                  </span>
                )}
                <span className="text-sm font-bold text-white font-mono">
                  {formatOptionSymbol(paper_ledger.open_trade.symbol)} ({paper_ledger.open_trade.lots}L / {paper_ledger.open_trade.qty.toLocaleString('en-IN')} Qty
                  {paper_ledger.open_trade.is_iceberg && paper_ledger.open_trade.entry_slices
                    ? ` • 🧊 ${paper_ledger.open_trade.entry_legs} Legs [${paper_ledger.open_trade.entry_slices.join('+')}]`
                    : ''}
                  )
                </span>
                <span className="text-xs text-slate-400 font-mono">
                  Entered @ {paper_ledger.open_trade.entry_time_str || paper_ledger.open_trade.entry_time?.slice(11, 16) || '--:--'}
                </span>
              </div>
              <div className="text-xs text-slate-300 font-mono flex flex-wrap items-center gap-3">
                <span>Entry: ₹{paper_ledger.open_trade.entry_premium.toFixed(2)}</span>
                <span>Live LTP: ₹{paper_ledger.open_trade.current_ltp.toFixed(2)}</span>
                <span className="text-rose-300">
                  Active SL: ₹{paper_ledger.open_trade.current_sl_premium.toFixed(2)}
                </span>
                <span className="text-emerald-300">T1: ₹{paper_ledger.open_trade.t1_premium.toFixed(2)}</span>
                <span className="text-cyan-300">T2: ₹{paper_ledger.open_trade.t2_premium.toFixed(2)}</span>
                <span className="text-amber-300">
                  {!paper_ledger.open_trade.t1_booked ? (
                    `Hold: ${paper_ledger.open_trade.hold_minutes.toFixed(1)}m / ${
                      paper_ledger.open_trade.time_stop_minutes ?? 20
                    }m Time-Stop${
                      paper_ledger.open_trade.pre_t1_doorstep_active
                        ? ' (+1.35R T1 Doorstep Lock ⚡)'
                        : paper_ledger.open_trade.pre_t1_shield_active
                        ? ' (+1.20R Chandelier Shield 🛡️)'
                        : paper_ledger.open_trade.stage1b0_shield_active
                        ? ' (+1.00R Green Shield 🛡️)'
                        : ''
                    }`
                  ) : paper_ledger.open_trade.hold_minutes < (paper_ledger.open_trade.post_t1_stepup_minutes ?? 45) ? (
                    `Hold: ${paper_ledger.open_trade.hold_minutes.toFixed(1)}m / 45m Step-Up (T1 Booked ✅ • 60m Max)`
                  ) : (
                    `Hold: ${paper_ledger.open_trade.hold_minutes.toFixed(1)}m / 60m Hard Exit (45m +0.5R SL Active 🛡️)`
                  )}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <div className="text-right font-mono">
                <div
                  className={cn(
                    "text-sm font-bold",
                    paper_ledger.open_trade.net_pnl_inr >= 0 ? "text-emerald-400" : "text-rose-400"
                  )}
                >
                  {paper_ledger.open_trade.net_pnl_inr >= 0 ? '+' : ''}₹
                  {paper_ledger.open_trade.net_pnl_inr.toLocaleString('en-IN')} Net ({openTradeRoiPct >= 0 ? '+' : ''}
                  {openTradeRoiPct.toFixed(2)}%)
                </div>
                <div className="text-[10px] text-slate-400">
                  ({paper_ledger.open_trade.unrealized_r ?? 0}R • Gross{' '}
                  {formatInrSigned(paper_ledger.open_trade.gross_pnl_inr)})
                </div>
              </div>
              <button
                type="button"
                onClick={handlePaperClose}
                className="px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-xs font-bold"
              >
                Exit Now
              </button>
            </div>
          </div>
        )}

        {/* Closed Paper Trades Table */}
        {displayedLedger.closed_trades.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs font-mono">
              <thead>
                <tr className="border-b border-white/10 text-[10px] uppercase text-slate-400">
                  <th className="py-1.5 px-2">Time</th>
                  <th className="py-1.5 px-2">Origin</th>
                  <th className="py-1.5 px-2">Contract</th>
                  <th className="py-1.5 px-2">Setup</th>
                  <th className="py-1.5 px-2">Lots/Qty</th>
                  <th className="py-1.5 px-2">Entry → Exit</th>
                  <th className="py-1.5 px-2">Hold</th>
                  <th className="py-1.5 px-2">Gross PnL</th>
                  <th className="py-1.5 px-2">Charges+Slip</th>
                  <th className="py-1.5 px-2">Net PnL (R)</th>
                  <th className="py-1.5 px-2">Exit Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {displayedLedger.closed_trades.map((tr) => (
                  <tr key={tr.trade_id} className="hover:bg-white/5">
                    <td className="py-1.5 px-2 text-slate-300">
                      {(tr.entry_time_str?.slice(0, 5) || tr.entry_time?.slice(11, 16) || '--:--')} → {(tr.exit_time_str?.slice(0, 5) || tr.exit_time?.slice(11, 16) || '--:--')}
                    </td>
                    <td className="py-1.5 px-2">
                      {tr.source === "AUTO_QUANT_SIGNAL" ? (
                        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 whitespace-nowrap">
                          <span>🤖</span>
                          <span>AUTO</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-500/15 text-amber-400 border border-amber-500/30 whitespace-nowrap">
                          <span>⚡</span>
                          <span>FORCE</span>
                        </span>
                      )}
                    </td>
                    <td className="py-1.5 px-2">
                      <div className="font-bold text-white font-mono">{formatOptionSymbol(tr.symbol)}</div>
                      {tr.entry_spot && (
                        <div className="text-[10px] text-slate-400 font-mono">Spot: ₹{tr.entry_spot.toFixed(1)}</div>
                      )}
                    </td>
                    <td className="py-1.5 px-2">
                      {tr.trigger_type?.includes("PULLBACK") ? (
                        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-cyan-500/15 text-cyan-300 border border-cyan-500/30 whitespace-nowrap">
                          <span>🔄</span>
                          <span>PULLBACK</span>
                        </span>
                      ) : tr.trigger_type?.includes("BREAKOUT") || tr.trigger_type?.includes("BREAKDOWN") ? (
                        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-purple-500/15 text-purple-300 border border-purple-500/30 whitespace-nowrap">
                          <span>📦</span>
                          <span>BOX BO</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono text-slate-400 bg-white/5 border border-white/10 whitespace-nowrap">
                          {tr.trigger_type || "MANUAL"}
                        </span>
                      )}
                    </td>
                    <td className="py-1.5 px-2 text-slate-300">
                      {tr.lots}L ({tr.qty.toLocaleString('en-IN')}){tr.is_iceberg ? ` 🧊[${tr.entry_legs}L]` : ''}
                    </td>
                    <td className="py-1.5 px-2 text-slate-200">
                      ₹{tr.entry_premium.toFixed(2)} → ₹{(tr.exit_premium ?? tr.current_ltp).toFixed(2)}
                    </td>
                    <td className="py-1.5 px-2 text-slate-400">{tr.hold_minutes.toFixed(1)}m</td>
                    <td
                      className={cn(
                        'py-1.5 px-2 font-medium',
                        tr.gross_pnl_inr >= 0 ? 'text-emerald-300/90' : 'text-rose-300/90'
                      )}
                    >
                      {formatInrSigned(tr.gross_pnl_inr)}
                    </td>
                    <td className="py-1.5 px-2 text-amber-300">
                      -₹{Math.round((tr.charges_inr ?? 0) + (tr.slippage_inr ?? 0)).toLocaleString('en-IN')}
                    </td>
                    <td
                      className={cn(
                        'py-1.5 px-2 font-bold',
                        tr.net_pnl_inr >= 0 ? 'text-emerald-400' : 'text-rose-400'
                      )}
                    >
                      {formatInrSigned(tr.net_pnl_inr)} ({(tr.r_multiple ?? 0) >= 0 ? '+' : ''}
                      {tr.r_multiple ?? 0}R)
                    </td>
                    <td className="py-1.5 px-2 text-cyan-300">{highlightQuantText(tr.exit_reason)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-3 px-3 rounded-lg bg-white/[0.02] border border-white/5 text-center text-xs text-slate-400 font-mono">
            No closed paper trades recorded for session {displayedLedger.session_date}.
          </div>
        )}
      </div>

      {/* ===================================================================== */}
      {/* 5. LIVE NIFTY OPTION CHAIN WINDOW (ATM ± 250 WITH BLACK-76 GREEKS)    */}
      {/* ===================================================================== */}
      <div className="rounded-xl bg-dark-850 border border-white/10 p-3.5 space-y-2.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Layers className="w-4 h-4 text-purple-400" />
            <h3 className="text-xs font-bold uppercase tracking-wider text-white">
              Live NIFTY 50 Option Chain Window (ATM ± 250 • Exact Black-76 IV, Delta &amp; Theta/hr)
            </h3>
          </div>
          <span className="text-[11px] text-slate-400 font-mono">
            ATM Strike: <strong className="text-cyan-300">{ms.atm_strike}</strong> • Selected:{' '}
            <strong className="text-emerald-300">
              {sc.strike} {sc.opt_type}
            </strong>
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-center border-collapse text-xs font-mono">
            <thead>
              <tr className="border-b border-white/10 text-[10px] uppercase text-slate-400 bg-dark-900/60">
                <th className="py-2 px-2 text-emerald-300">CE OI (Chg)</th>
                <th className="py-2 px-2 text-emerald-300">CE IV%</th>
                <th className="py-2 px-2 text-emerald-300">CE Δ</th>
                <th className="py-2 px-2 text-emerald-300">CE Θ/hr</th>
                <th className="py-2 px-2 text-emerald-300">CE LTP</th>
                <th className="py-2 px-3 bg-dark-800 text-white font-bold">STRIKE</th>
                <th className="py-2 px-2 text-rose-300">PE LTP</th>
                <th className="py-2 px-2 text-rose-300">PE Θ/hr</th>
                <th className="py-2 px-2 text-rose-300">PE Δ</th>
                <th className="py-2 px-2 text-rose-300">PE IV%</th>
                <th className="py-2 px-2 text-rose-300">PE OI (Chg)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {quant_engine.option_chain_window.map((row) => {
                const isSelectedCE = sc.strike === row.strike && sc.opt_type === 'CE';
                const isSelectedPE = sc.strike === row.strike && sc.opt_type === 'PE';
                return (
                  <tr
                    key={row.strike}
                    className={cn(
                      "transition-colors hover:bg-white/5",
                      row.is_atm && "bg-cyan-950/25"
                    )}
                  >
                    {/* CE Columns (Left Half-Row Highlight if Selected) */}
                    <td
                      className={cn(
                        "py-1.5 px-2 text-slate-300 transition-colors",
                        isSelectedCE && "bg-emerald-950/40 border-y border-l border-emerald-500/40 rounded-l"
                      )}
                    >
                      {(row.ce_oi / 1000).toFixed(0)}k{' '}
                      <span className={row.ce_chg_oi >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                        ({row.ce_chg_oi >= 0 ? '+' : ''}
                        {(row.ce_chg_oi / 1000).toFixed(0)}k)
                      </span>
                    </td>
                    <td
                      className={cn(
                        "py-1.5 px-2 text-slate-400 transition-colors",
                        isSelectedCE && "bg-emerald-950/40 border-y border-emerald-500/40"
                      )}
                    >
                      {row.ce_iv.toFixed(1)}%
                    </td>
                    <td
                      className={cn(
                        "py-1.5 px-2 transition-colors",
                        row.ce_delta >= 0.5 && row.ce_delta <= 0.65
                          ? "text-cyan-300 font-bold"
                          : "text-slate-300",
                        isSelectedCE && "bg-emerald-950/40 border-y border-emerald-500/40"
                      )}
                    >
                      {row.ce_delta.toFixed(2)}
                    </td>
                    <td
                      className={cn(
                        "py-1.5 px-2 text-slate-400 transition-colors",
                        isSelectedCE && "bg-emerald-950/40 border-y border-emerald-500/40"
                      )}
                    >
                      {row.ce_theta_hr.toFixed(1)}
                    </td>
                    <td
                      className={cn(
                        "py-1.5 px-2 font-bold transition-all",
                        isSelectedCE
                          ? "bg-emerald-500/25 text-emerald-200 border-y border-r border-emerald-400/60 shadow-sm"
                          : "text-emerald-300"
                      )}
                    >
                      ₹{row.ce_ltp.toFixed(2)}
                    </td>

                    {/* Central Strike Column */}
                    <td
                      className={cn(
                        "py-1.5 px-3 font-bold bg-dark-900/90 transition-all",
                        row.is_atm ? "text-cyan-300 border-x border-cyan-500/40" : "text-white",
                        isSelectedCE && "border-l border-emerald-500/40 text-emerald-300",
                        isSelectedPE && "border-r border-rose-500/40 text-rose-300"
                      )}
                    >
                      {row.strike} {row.is_atm && <span className="text-[9px] text-cyan-400">ATM</span>}
                    </td>

                    {/* PE Columns (Right Half-Row Highlight if Selected) */}
                    <td
                      className={cn(
                        "py-1.5 px-2 font-bold transition-all",
                        isSelectedPE
                          ? "bg-rose-500/25 text-rose-200 border-y border-l border-rose-400/60 shadow-sm"
                          : "text-rose-300"
                      )}
                    >
                      ₹{row.pe_ltp.toFixed(2)}
                    </td>
                    <td
                      className={cn(
                        "py-1.5 px-2 text-slate-400 transition-colors",
                        isSelectedPE && "bg-rose-950/40 border-y border-rose-500/40"
                      )}
                    >
                      {row.pe_theta_hr.toFixed(1)}
                    </td>
                    <td
                      className={cn(
                        "py-1.5 px-2 transition-colors",
                        Math.abs(row.pe_delta) >= 0.5 && Math.abs(row.pe_delta) <= 0.65
                          ? "text-cyan-300 font-bold"
                          : "text-slate-300",
                        isSelectedPE && "bg-rose-950/40 border-y border-rose-500/40"
                      )}
                    >
                      {row.pe_delta.toFixed(2)}
                    </td>
                    <td
                      className={cn(
                        "py-1.5 px-2 text-slate-400 transition-colors",
                        isSelectedPE && "bg-rose-950/40 border-y border-rose-500/40"
                      )}
                    >
                      {row.pe_iv.toFixed(1)}%
                    </td>
                    <td
                      className={cn(
                        "py-1.5 px-2 text-slate-300 transition-colors",
                        isSelectedPE && "bg-rose-950/40 border-y border-r border-rose-500/40 rounded-r"
                      )}
                    >
                      {(row.pe_oi / 1000).toFixed(0)}k{' '}
                      <span className={row.pe_chg_oi >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                        ({row.pe_chg_oi >= 0 ? '+' : ''}
                        {(row.pe_chg_oi / 1000).toFixed(0)}k)
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
