"use client";

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Navbar, NiftySpotSnapshot } from '@/components/Navbar';
import { CandleSyncBar } from '@/components/CandleSyncBar';
import { HolidayAlertBanner } from '@/components/HolidayAlertBanner';
import { OverviewStats } from '@/components/OverviewStats';
import { 
  FilterControls, 
  SignalFilterType, 
  SortOptionType, 
  RefreshIntervalType 
} from '@/components/FilterControls';
import { SignalCard } from '@/components/SignalCard';
import { ChartDrawer } from '@/components/ChartDrawer';
import { SkeletonLoader } from '@/components/SkeletonLoader';
import { EmptyState } from '@/components/EmptyState';
import { ToastContainer } from '@/components/ToastNotification';
import { Pagination } from '@/components/Pagination';
import { LiveMoversPanel } from '@/components/LiveMoversPanel';
import { MarketPulsePanel } from '@/components/MarketPulsePanel';
import { NiftyOptionsPanel } from '@/components/NiftyOptionsPanel';
import { Zap, Target, Compass, Crosshair } from 'lucide-react';
import { V13ScanResponse, V13Signal, V13ChartTarget, MarketStatus, V13MarketPulseResponse } from '@/types/screener';
import { playSignalSound, speakSignalAlert, cn } from '@/lib/utils';
import { normalizeV13Response } from '@/lib/v13Adapter';

export default function ScreenerDashboard() {
  const [mainTab, setMainTab] = useState<'V13_UNIVERSE' | 'LIVE_MOVERS' | 'MARKET_PULSE' | 'NIFTY_OPTIONS'>('V13_UNIVERSE');
  const [marketPulseData, setMarketPulseData] = useState<V13MarketPulseResponse | null>(null);
  const [niftySpotData, setNiftySpotData] = useState<NiftySpotSnapshot | null>(null);
  const [data, setData] = useState<V13ScanResponse | null>(null);
  const [marketStatusDetails, setMarketStatusDetails] = useState<MarketStatus | null>(null);
  const [sectors, setSectors] = useState<string[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // User Filter & Sort States
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedSector, setSelectedSector] = useState<string>('ALL');
  
  // Requirement: Default tab behavior set to 'Active Signals'
  const [signalFilter, setSignalFilter] = useState<SignalFilterType>('ACTIVE_ONLY');
  const [sortBy, setSortBy] = useState<SortOptionType>('REL_VOL_DESC');
  
  // Pagination States
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(24);

  // Helper to read saved refreshInterval from localStorage synchronously
  const getInitialRefreshInterval = (): RefreshIntervalType => {
    if (typeof window !== 'undefined') {
      try {
        const saved = localStorage.getItem('v13_refresh_interval');
        if (saved !== null) {
          const val = Number(saved);
          if ([0, 30, 45, 60, 180, 300].includes(val)) {
            return val as RefreshIntervalType;
          }
        }
      } catch {
        // Fallback
      }
    }
    return 60;
  };

  // Refresh & Mode States with LocalStorage Persistence
  const [mode, setMode] = useState<'live' | 'simulation' | 'auto'>('live');
  const [refreshInterval, setRefreshIntervalState] = useState<RefreshIntervalType>(getInitialRefreshInterval);
  const [countdown, setCountdown] = useState<number>(getInitialRefreshInterval);

  const nextRefreshTargetRef = useRef<number>(0);
  const refreshIntervalRef = useRef<RefreshIntervalType>(60);

  // Sync initial state on client mount
  useEffect(() => {
    const initial = getInitialRefreshInterval();
    setRefreshIntervalState(initial);
    refreshIntervalRef.current = initial;
    if (initial > 0) {
      setCountdown(initial);
      nextRefreshTargetRef.current = Date.now() + initial * 1000;
    } else {
      setCountdown(0);
      nextRefreshTargetRef.current = 0;
    }
  }, []);

  const handleRefreshIntervalChange = useCallback((newInterval: RefreshIntervalType) => {
    setRefreshIntervalState(newInterval);
    refreshIntervalRef.current = newInterval;
    if (newInterval > 0) {
      nextRefreshTargetRef.current = Date.now() + newInterval * 1000;
      setCountdown(newInterval);
    } else {
      nextRefreshTargetRef.current = 0;
      setCountdown(0);
    }
    if (typeof window !== 'undefined') {
      try {
        localStorage.setItem('v13_refresh_interval', String(newInterval));
      } catch {
        // Ignore storage access errors
      }
    }
  }, []);

  // Prevent overlapping V13 scan requests.
  const fetchInFlightRef = useRef<boolean>(false);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refreshPollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refreshStartedAtRef = useRef<string>("");
  const latestGeneratedAtRef = useRef<string>("");
  const manualPollAttemptsRef = useRef<number>(0);

  // Audio & Alerts
  const [audioEnabled, setAudioEnabled] = useState<boolean>(true);
  const [toastSignals, setToastSignals] = useState<V13Signal[]>([]);
  const previousSignalSymbolsRef = useRef<Set<string>>(new Set());
  const isFirstLoadRef = useRef<boolean>(true);

  // Interactive Chart Drawer State
  const [selectedStockForChart, setSelectedStockForChart] = useState<V13ChartTarget | null>(null);
  const [isChartOpen, setIsChartOpen] = useState<boolean>(false);

  // Reset pagination on filter or search changes
  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, selectedSector, signalFilter, sortBy]);

    // Market Pulse 90s Background Poller
  useEffect(() => {
    let isMounted = true;
    const fetchPulse = async () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
      try {
        const res = await fetch('/api/v13/market-pulse');
        if (res.ok && isMounted) {
          const json = await res.json();
          setMarketPulseData(json);
        }
      } catch {
        // Silent background fallback
      }
    };

    fetchPulse();
    const interval = setInterval(fetchPulse, 90000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  // Fetch Sectors and Market Status on Mount
  useEffect(() => {
    fetch('/api/sectors')
      .then((res) => res.json())
      .then((secData) => {
        if (Array.isArray(secData)) setSectors(secData);
      })
      .catch((e) => console.log('Notice fetching sectors:', e));

    fetch('/api/market-status')
      .then((res) => res.json())
      .then((ms) => {
        if (ms) setMarketStatusDetails(ms);
      })
      .catch((e) => console.log('Notice fetching market status:', e));
  }, []);

  // Fetch V13 Scan Data Function
  const fetchScreenerData = useCallback(async (isManual: boolean = false, isPolling: boolean = false) => {
    if (fetchInFlightRef.current) return;

    fetchInFlightRef.current = true;

    if (isManual) {
      setIsRefreshing(true);
      if (!isPolling && !refreshStartedAtRef.current) {
        refreshStartedAtRef.current = latestGeneratedAtRef.current;
      }
    }

    try {
      // Only send force=1 on initial manual click; status polls must NOT re-trigger force=1
      const url = isManual && !isPolling ? "/api/v13/scan?force=1" : "/api/v13/scan";
      const res = await fetch(url);

      if (res.status === 503) {
        setError(null);

        if (retryTimerRef.current === null) {
          retryTimerRef.current = setTimeout(() => {
            retryTimerRef.current = null;
            void fetchScreenerData(false);
          }, 5000);
        }

        return;
      }

      if (!res.ok) {
        throw new Error("V13 scan API error! status: " + res.status);
      }

      const raw = await res.json();
      const json: V13ScanResponse = normalizeV13Response(raw);

      const newActive = json.watchlist;
      const newTriggered: V13Signal[] = [];

      newActive.forEach((signal) => {
        if (!previousSignalSymbolsRef.current.has(signal.symbol)) {
          newTriggered.push(signal);
        }
      });

      previousSignalSymbolsRef.current = new Set(
        newActive.map((signal) => signal.symbol)
      );

      // Only trigger toast notifications, audio chime & speech synthesis on subsequent real-time refreshes!
      if (isFirstLoadRef.current) {
        // Initial load: prime the cache without blasting chimes or voice alerts
        isFirstLoadRef.current = false;
      } else if (newTriggered.length > 0) {
        setToastSignals((prev) => [
          ...newTriggered.slice(0, 3),
          ...prev,
        ].slice(0, 4));

        if (audioEnabled) {
          playSignalSound(
            newTriggered[0].direction === "BULLISH"
              ? "BULLISH"
              : "BEARISH"
          );

          // 🚀 Speech Synthesis Voice Alert for 85+ High Confidence Signals
          const highConfSignal = newTriggered.find((s) => s.score >= 85);
          if (highConfSignal) {
            const dir = highConfSignal.direction === 'BULLISH' ? 'Bullish' : 'Bearish';
            const priceText = highConfSignal.price ? `${Math.round(highConfSignal.price)} Rupees` : '';
            setTimeout(() => {
              speakSignalAlert(
                `High Confidence ${dir} Breakout on ${highConfSignal.symbol} at ${priceText}`
              );
            }, 600);
          }
        }
      }

      latestGeneratedAtRef.current = json.generated_at ?? "";
      setData(json);
      if (json.market_status_details) {
        setMarketStatusDetails(json.market_status_details);
      }
      setError(null);

      if (isManual) {
        const isScanCompleted = !json.is_scanning;
        const isFreshDataDelivered = Boolean(
          json.generated_at &&
          refreshStartedAtRef.current &&
          json.generated_at !== refreshStartedAtRef.current
        );

        if (isScanCompleted || isFreshDataDelivered || manualPollAttemptsRef.current >= 45) {
          refreshStartedAtRef.current = "";
          manualPollAttemptsRef.current = 0;
          if (refreshPollTimerRef.current) {
            clearTimeout(refreshPollTimerRef.current);
            refreshPollTimerRef.current = null;
          }
          setIsRefreshing(false);
        } else if (refreshPollTimerRef.current === null) {
          manualPollAttemptsRef.current += 1;
          refreshPollTimerRef.current = setTimeout(() => {
            refreshPollTimerRef.current = null;
            void fetchScreenerData(true, true);
          }, 2000);
        }
      }
    } catch (err: any) {
      console.error("Error fetching V13 scan:", err);
      setError(err.message || "Failed to connect to V13 Scan API");
      manualPollAttemptsRef.current = 0;
      refreshStartedAtRef.current = "";
      if (refreshPollTimerRef.current) {
        clearTimeout(refreshPollTimerRef.current);
        refreshPollTimerRef.current = null;
      }
      setIsRefreshing(false);
    } finally {
      fetchInFlightRef.current = false;
      setLoading(false);
      // Ensure target timer is set if not active
      if (refreshIntervalRef.current > 0) {
        if (nextRefreshTargetRef.current <= Date.now()) {
          nextRefreshTargetRef.current = Date.now() + refreshIntervalRef.current * 1000;
          setCountdown(refreshIntervalRef.current);
        }
      } else {
        setCountdown(0);
      }
    }
  }, [refreshInterval, audioEnabled]);

  useEffect(() => {
    void fetchScreenerData();
    return () => {
      if (refreshPollTimerRef.current) {
        clearTimeout(refreshPollTimerRef.current);
        refreshPollTimerRef.current = null;
      }
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
    };
  }, []);

  // Native visibilitychange listener: syncs smoothly when returning to tab without resetting countdown
  useEffect(() => {
    if (typeof window === 'undefined') return;

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible' && refreshIntervalRef.current > 0) {
        const now = Date.now();
        const target = nextRefreshTargetRef.current;
        if (target > 0 && now >= target) {
          // Timer expired while user was in background: fetch immediately and reset target
          nextRefreshTargetRef.current = now + refreshIntervalRef.current * 1000;
          setCountdown(refreshIntervalRef.current);
          void fetchScreenerData(false);
        } else if (target > 0) {
          // Timer is still running: update remaining countdown seamlessly without resetting
          const remainingSecs = Math.max(1, Math.ceil((target - now) / 1000));
          setCountdown(remainingSecs);
        }
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [fetchScreenerData]);

  // Dedicated Web Worker Timer: bypasses browser background tab throttling so countdown & refreshes run continuously
  useEffect(() => {
    if (refreshInterval === 0 || typeof window === 'undefined') return;

    const workerScript = `
      let timer = null;
      self.onmessage = function(e) {
        if (e.data === 'start') {
          if (timer) clearInterval(timer);
          timer = setInterval(function() {
            self.postMessage('tick');
          }, 1000);
        } else if (e.data === 'stop') {
          if (timer) clearInterval(timer);
          timer = null;
        }
      };
    `;

    let worker: Worker | null = null;
    let fallbackTimer: NodeJS.Timeout | null = null;

    const onTick = () => {
      if (refreshIntervalRef.current === 0) return;
      const now = Date.now();
      let target = nextRefreshTargetRef.current;

      if (target <= 0) {
        target = now + refreshIntervalRef.current * 1000;
        nextRefreshTargetRef.current = target;
        setCountdown(refreshIntervalRef.current);
        return;
      }

      const remainingMs = target - now;
      if (remainingMs <= 500) {
        // Interval completed: trigger fetch and advance target
        nextRefreshTargetRef.current = now + refreshIntervalRef.current * 1000;
        setCountdown(refreshIntervalRef.current);
        void fetchScreenerData(false);
      } else {
        setCountdown(Math.ceil(remainingMs / 1000));
      }
    };

    try {
      const blob = new Blob([workerScript], { type: 'application/javascript' });
      const workerUrl = URL.createObjectURL(blob);
      worker = new Worker(workerUrl);
      worker.onmessage = (e) => {
        if (e.data === 'tick') {
          onTick();
        }
      };
      worker.postMessage('start');
    } catch {
      // Fallback to standard setInterval if Web Worker is restricted
      fallbackTimer = setInterval(onTick, 1000);
    }

    return () => {
      if (worker) {
        worker.postMessage('stop');
        worker.terminate();
      }
      if (fallbackTimer) {
        clearInterval(fallbackTimer);
      }
    };
  }, [refreshInterval, fetchScreenerData]);

  const handleOpenChart = (stock: V13ChartTarget) => {
    setSelectedStockForChart(stock);
    setIsChartOpen(true);
  };

  const handleCloseChart = () => {
    setIsChartOpen(false);
  };

  const handleDismissToast = (symbol: string) => {
    setToastSignals((prev) => prev.filter((s) => s.symbol !== symbol));
  };

  const handleResetFilters = () => {
    setSearchQuery('');
    setSelectedSector('ALL');
    setSignalFilter('ACTIVE_ONLY');
    setSortBy('REL_VOL_DESC');
    setCurrentPage(1);
  };

  // Unified stock universe with mapped signals (both >=72 active and <72 diagnostics)
  const universeWithSignals = useMemo(() => {
    if (!data?.universe) return [];

    const activeMap = new Map<string, V13Signal[]>();
    (data.watchlist ?? []).forEach((sig) => {
      const existing = activeMap.get(sig.symbol) ?? [];
      existing.push(sig);
      activeMap.set(sig.symbol, existing);
    });

    const diagMap = new Map<string, V13Signal[]>();
    (data.diagnostic_signals ?? []).forEach((diag) => {
      const existing = diagMap.get(diag.symbol) ?? [];
      existing.push(diag);
      diagMap.set(diag.symbol, existing);
    });

    return data.universe.map((stock) => {
      const candidateList = [
        ...(activeMap.get(stock.symbol) ?? []),
        ...(stock.signals ?? []),
        ...(diagMap.get(stock.symbol) ?? []),
      ];

      // Deduplicate by direction, keeping the highest score
      const dirMap = new Map<string, V13Signal>();
      candidateList.forEach((s) => {
        const dir = s.direction ?? 'BULLISH';
        const curr = dirMap.get(dir);
        if (!curr || (s.score ?? 0) > (curr.score ?? 0)) {
          dirMap.set(dir, s);
        }
      });

      const sortedSignals = Array.from(dirMap.values()).sort(
        (a, b) => (b.score ?? 0) - (a.score ?? 0)
      );

      if (sortedSignals.length > 0) {
        return {
          ...stock,
          status: sortedSignals[0].score >= 72 ? ('SIGNAL' as const) : ('DIAGNOSTIC' as const),
          signals: sortedSignals,
        };
      }
      return stock;
    });
  }, [data]);

  // Filtered & Sorted V13 Universe List
  const filteredStocks = useMemo(() => {
    if (!universeWithSignals.length) return [];

    let list = [...universeWithSignals];

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      list = list.filter(
        (stock) =>
          stock.symbol.toLowerCase().includes(q) ||
          stock.name.toLowerCase().includes(q) ||
          stock.sector.toLowerCase().includes(q)
      );
    }

    if (selectedSector !== 'ALL') {
      list = list.filter(
        (stock) =>
          stock.sector.toLowerCase() === selectedSector.toLowerCase()
      );
    }

    if (signalFilter === 'ACTIVE_ONLY') {
      list = list.filter((stock) => stock.signals.some((s) => s.score >= 72));
    } else if (signalFilter === 'BELOW_THRESHOLD') {
      list = list.filter((stock) => stock.signals.length > 0 && stock.signals.every((s) => s.score < 72));
    } else if (signalFilter === 'NO_SETUP') {
      list = list.filter((stock) => stock.signals.length === 0);
    } else if (signalFilter === 'WATCH') {
      list = list.filter((stock) => stock.signals.some((s) => s.score >= 72 && s.score < 80));
    } else if (signalFilter === 'STRONG') {
      list = list.filter((stock) => stock.signals.some((s) => s.score >= 80 && s.score < 85));
    } else if (signalFilter === 'HIGH_CONFIDENCE') {
      list = list.filter((stock) => stock.signals.some((s) => s.score >= 85));
    } else if (signalFilter === 'BULLISH') {
      list = list
        .filter((stock) =>
          stock.signals.some((signal) => signal.score >= 72 && signal.direction === 'BULLISH')
        )
        .map((stock) => {
          const bul = stock.signals.find((s) => s.direction === 'BULLISH');
          return bul ? { ...stock, signals: [bul, ...stock.signals.filter((s) => s !== bul)] } : stock;
        });
    } else if (signalFilter === 'BEARISH') {
      list = list
        .filter((stock) =>
          stock.signals.some((signal) => signal.score >= 72 && signal.direction === 'BEARISH')
        )
        .map((stock) => {
          const bea = stock.signals.find((s) => s.direction === 'BEARISH');
          return bea ? { ...stock, signals: [bea, ...stock.signals.filter((s) => s !== bea)] } : stock;
        });
    }

    switch (sortBy) {
      case 'SCORE_DESC_T1_ASC':
        list.sort((a, b) => {
          const aSig = a.signals[0];
          const bSig = b.signals[0];
          const aScore = aSig?.score ?? 0;
          const bScore = bSig?.score ?? 0;

          const getTierWeight = (score: number) => {
            if (score >= 85) return 3; // High Confidence
            if (score >= 80) return 2; // Strong
            if (score >= 72) return 1; // Watchlist
            return 0;
          };

          const aTier = getTierWeight(aScore);
          const bTier = getTierWeight(bScore);

          // 1. Higher Quality Tier first (High Confidence > Strong > Watchlist)
          if (bTier !== aTier) {
            return bTier - aTier;
          }

          // 2. Within the same Tier, Lowest T1 Progress first (Fresh Base Entry)
          const aProg = aSig?.t1_progress_pct ?? 0;
          const bProg = bSig?.t1_progress_pct ?? 0;
          if (Math.abs(aProg - bProg) > 0.01) {
            return aProg - bProg;
          }

          // 3. Tie-breaker: Higher Score first
          return bScore - aScore;
        });
        break;

      case 'SCORE_DESC':
        list.sort((a, b) => {
          const aScore = a.signals[0]?.score ?? 0;
          const bScore = b.signals[0]?.score ?? 0;
          return bScore - aScore;
        });
        break;

      case 'SCORE_ASC':
        list.sort((a, b) => {
          const aScore = a.signals[0]?.score ?? 0;
          const bScore = b.signals[0]?.score ?? 0;
          return aScore - bScore;
        });
        break;

      case 'REL_VOL_DESC':
        list.sort((a, b) => {
          const aRelVol = a.signals[0]?.indicators.rel_vol ?? a.snapshot.rel_vol ?? -Infinity;
          const bRelVol = b.signals[0]?.indicators.rel_vol ?? b.snapshot.rel_vol ?? -Infinity;
          return bRelVol - aRelVol;
        });
        break;

      case 'T1_PROGRESS_ASC':
        list.sort((a, b) => {
          const aProg = a.signals[0]?.t1_progress_pct ?? 0;
          const bProg = b.signals[0]?.t1_progress_pct ?? 0;
          return aProg - bProg;
        });
        break;

      case 'T1_PROGRESS_DESC':
        list.sort((a, b) => {
          const aProg = a.signals[0]?.t1_progress_pct ?? 0;
          const bProg = b.signals[0]?.t1_progress_pct ?? 0;
          return bProg - aProg;
        });
        break;

      case 'NIFTY500_FIRST':
        list.sort((a, b) => {
          const aN500 = (a.is_nifty500 ?? a.signals[0]?.is_nifty500) ? 1 : 0;
          const bN500 = (b.is_nifty500 ?? b.signals[0]?.is_nifty500) ? 1 : 0;
          if (bN500 !== aN500) return bN500 - aN500;
          const aScore = a.signals[0]?.score ?? 0;
          const bScore = b.signals[0]?.score ?? 0;
          return bScore - aScore;
        });
        break;

      case 'MCAP_DESC':
        list.sort((a, b) => {
          const aMcap = a.market_cap_cr ?? a.signals[0]?.market_cap_cr ?? 0;
          const bMcap = b.market_cap_cr ?? b.signals[0]?.market_cap_cr ?? 0;
          return bMcap - aMcap;
        });
        break;

      case 'RR_DESC':
        list.sort((a, b) => {
          const parseRR = (value: string | null | undefined): number => {
            if (!value) return -Infinity;
            const match = value.match(/([0-9]+(?:\.[0-9]+)?)/);
            return match ? Number(match[1]) : -Infinity;
          };

          const aRR = parseRR(a.signals[0]?.risk.risk_reward_t1);
          const bRR = parseRR(b.signals[0]?.risk.risk_reward_t1);
          return bRR - aRR;
        });
        break;

      case 'SYMBOL_ASC':
        list.sort((a, b) => a.symbol.localeCompare(b.symbol));
        break;

      case 'CHANGE_DESC':
        list.sort((a, b) => {
          const aChange = a.snapshot.latest_session_change_pct ?? -Infinity;
          const bChange = b.snapshot.latest_session_change_pct ?? -Infinity;
          return bChange - aChange;
        });
        break;

      case 'CHANGE_ASC':
        list.sort((a, b) => {
          const aChange = a.snapshot.latest_session_change_pct ?? Infinity;
          const bChange = b.snapshot.latest_session_change_pct ?? Infinity;
          return aChange - bChange;
        });
        break;
    }

    return list;
  }, [universeWithSignals, searchQuery, selectedSector, signalFilter, sortBy]);

  const belowThresholdCount = useMemo(() => {
    return universeWithSignals.filter((stock) => stock.signals.length > 0 && stock.signals.every((s) => s.score < 72)).length;
  }, [universeWithSignals]);

  const noSetupCount = useMemo(() => {
    return universeWithSignals.filter((stock) => stock.signals.length === 0).length;
  }, [universeWithSignals]);

  const bullishCount = useMemo(() => {
    return universeWithSignals.filter((stock) => stock.signals.some((s) => s.score >= 72 && s.direction === 'BULLISH')).length;
  }, [universeWithSignals]);

  const bearishCount = useMemo(() => {
    return universeWithSignals.filter((stock) => stock.signals.some((s) => s.score >= 72 && s.direction === 'BEARISH')).length;
  }, [universeWithSignals]);

  const watchCount = useMemo(() => {
    return (data?.watchlist ?? []).filter((s) => s.score >= 72 && s.score < 80).length;
  }, [data]);

  const strongCount = useMemo(() => {
    return (data?.watchlist ?? []).filter((s) => s.score >= 80 && s.score < 85).length;
  }, [data]);

  const highConfidenceCount = useMemo(() => {
    return (data?.watchlist ?? []).filter((s) => s.score >= 85).length;
  }, [data]);

  // Pagination slicing
  const totalPages = Math.max(1, Math.ceil(filteredStocks.length / pageSize));
  const paginatedStocks = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredStocks.slice(start, start + pageSize);
  }, [filteredStocks, currentPage, pageSize]);

  return (
    <div className="min-h-screen bg-dark-900 text-slate-100 flex flex-col font-sans">
      <Navbar
        marketStatus={marketStatusDetails || data?.market_status || null}
        mode={mode}
        onModeChange={(m) => setMode(m)}
        audioEnabled={audioEnabled}
        onToggleAudio={() => setAudioEnabled((prev) => !prev)}
        onRefresh={() => fetchScreenerData(true)}
        isRefreshing={isRefreshing}
        lastRefreshedTime={data?.generated_at ?? ''}
        activeTab={mainTab}
        onTabChange={setMainTab}
        niftySpot={niftySpotData}
        onSelectNiftyOptions={() => setMainTab('NIFTY_OPTIONS')}
      />

      <CandleSyncBar 
        generatedAt={data?.generated_at} 
        marketStatus={data?.market_status} 
      />

      <HolidayAlertBanner 
        marketStatus={marketStatusDetails} 
      />

      {/* Ultra-Slim, Non-Sticky Primary Navigation Switcher Strip */}
      <nav aria-label="Main navigation modules" className="w-full bg-dark-900 border-b border-white/5 py-1.5 px-4">
        <div className="max-w-[1440px] mx-auto flex items-center justify-between gap-3">
          <div className="flex items-center gap-1.5 p-0.5 bg-dark-800/90 rounded-lg border border-white/10 shadow-inner">
            <button
              onClick={() => setMainTab('V13_UNIVERSE')}
              className={cn(
                "px-3 py-1 rounded-md text-xs font-bold transition-all flex items-center gap-1.5 select-none",
                mainTab === 'V13_UNIVERSE'
                  ? "bg-indigo-600 text-white shadow-sm shadow-indigo-500/20"
                  : "text-slate-400 hover:text-white hover:bg-white/5"
              )}
            >
              <Target className="w-3.5 h-3.5 text-indigo-300" />
              <span>V13 Universe</span>
              <span className="text-[10px] font-mono px-1.5 py-0.2 rounded-full bg-black/40 text-indigo-200">
                1,468 Stocks
              </span>
            </button>

            <button
              onClick={() => setMainTab('LIVE_MOVERS')}
              className={cn(
                "px-3 py-1 rounded-md text-xs font-bold transition-all flex items-center gap-1.5 select-none",
                mainTab === 'LIVE_MOVERS'
                  ? "bg-emerald-600 text-white shadow-sm shadow-emerald-500/20"
                  : "text-slate-400 hover:text-white hover:bg-white/5"
              )}
            >
              <Zap className="w-3.5 h-3.5 text-amber-300" />
              <span>⚡ NSE Live Movers</span>
              <span className="px-1.5 py-0.2 rounded-full text-[9px] font-bold bg-black/40 text-emerald-300 border border-emerald-400/30 animate-pulse">
                LIVE
              </span>
            </button>

            <button
              onClick={() => setMainTab('MARKET_PULSE')}
              className={cn(
                "px-3 py-1 rounded-md text-xs font-bold transition-all flex items-center gap-1.5 select-none",
                mainTab === 'MARKET_PULSE'
                  ? "bg-purple-600 text-white shadow-sm shadow-purple-500/20"
                  : "text-slate-400 hover:text-white hover:bg-white/5"
              )}
            >
              <Compass className="w-3.5 h-3.5 text-purple-300" />
              <span>🧭 Market Pulse & Radar</span>
            </button>

            <button
              onClick={() => setMainTab('NIFTY_OPTIONS')}
              className={cn(
                "px-3 py-1 rounded-md text-xs font-bold transition-all flex items-center gap-1.5 select-none",
                mainTab === 'NIFTY_OPTIONS'
                  ? "bg-cyan-600 text-white shadow-sm shadow-cyan-500/20"
                  : "text-slate-400 hover:text-white hover:bg-white/5"
              )}
            >
              <Crosshair className="w-3.5 h-3.5 text-cyan-300" />
              <span>⚡ Alpha</span>
              <span className="px-1.5 py-0.2 rounded-full text-[9px] font-mono font-bold bg-black/40 text-cyan-200 border border-cyan-400/30">
                NIFTY OPTIONS
              </span>
            </button>
          </div>

          {/* Always-Visible Live Tradeability Filter Traffic Light Pill */}
          <button
            onClick={() => setMainTab('MARKET_PULSE')}
            className={cn(
              "flex items-center gap-2 px-2.5 py-1 rounded-lg border text-xs font-mono font-semibold transition-all shadow-sm hover:scale-[1.02] active:scale-[0.98]",
              marketPulseData?.tradeability.traffic_light === 'GREEN'
                ? "bg-emerald-950/40 border-emerald-500/40 text-emerald-300 hover:bg-emerald-950/60 shadow-emerald-950/20"
                : marketPulseData?.tradeability.traffic_light === 'YELLOW'
                ? "bg-amber-950/40 border-amber-500/40 text-amber-300 hover:bg-amber-950/60 shadow-amber-950/20"
                : marketPulseData?.tradeability.traffic_light === 'RED'
                ? "bg-rose-950/40 border-rose-500/40 text-rose-300 hover:bg-rose-950/60 shadow-rose-950/20"
                : "bg-dark-800 border-white/10 text-slate-400"
            )}
            title="Click to open Market Pulse & Strategic Radar"
          >
            <span className={cn(
              "w-2 h-2 rounded-full",
              marketPulseData?.tradeability.traffic_light === 'GREEN'
                ? "bg-emerald-400 animate-pulse shadow-[0_0_8px_rgba(52,211,153,0.8)]"
                : marketPulseData?.tradeability.traffic_light === 'YELLOW'
                ? "bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.8)]"
                : marketPulseData?.tradeability.traffic_light === 'RED'
                ? "bg-rose-400 animate-pulse shadow-[0_0_8px_rgba(244,63,94,0.8)]"
                : "bg-slate-500"
            )} />
            {marketPulseData ? (
              <span className="flex items-center gap-1.5 font-sans">
                <span className="font-bold">
                  {marketPulseData.tradeability.traffic_light === 'GREEN' ? 'GO' :
                   marketPulseData.tradeability.traffic_light === 'YELLOW' ? 'SELECTIVE' : 'SIT ON CASH'}
                </span>
                <span className="font-mono text-[11px] opacity-80">
                  ({marketPulseData.tradeability.score}/100)
                </span>
                <span className="hidden md:inline font-mono text-[10px] px-1 rounded bg-black/40">
                  {marketPulseData.tradeability.position_sizing.split(' ')[0]}
                </span>
              </span>
            ) : (
              <span className="font-sans text-[11px]">🧭 Pulse Radar</span>
            )}
          </button>
        </div>
      </nav>

      <main className="flex-1 max-w-[1440px] w-full mx-auto px-3.5 sm:px-6 lg:px-8 py-5 space-y-5">
        {/* V13 Universe Panel */}
        <div className={mainTab === 'V13_UNIVERSE' ? 'space-y-5' : 'hidden'}>
          <OverviewStats data={data} marketPulse={marketPulseData} loading={loading} />

          <FilterControls
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            selectedSector={selectedSector}
            onSectorChange={setSelectedSector}
            sectors={sectors}
            signalFilter={signalFilter}
            onSignalFilterChange={setSignalFilter}
            sortBy={sortBy}
            onSortChange={setSortBy}
            refreshInterval={refreshInterval}
            onRefreshIntervalChange={handleRefreshIntervalChange}
            countdown={countdown}
            totalCount={data?.universe.length ?? 0}
            activeCount={data?.watchlist.length ?? 0}
            bullishCount={bullishCount}
            bearishCount={bearishCount}
            belowThresholdCount={belowThresholdCount}
            noSetupCount={noSetupCount}
            watchCount={watchCount}
            strongCount={strongCount}
            highConfidenceCount={highConfidenceCount}
          />

          {loading && !data ? (
            <SkeletonLoader />
          ) : filteredStocks.length === 0 ? (
            <EmptyState onReset={handleResetFilters} />
          ) : (
            <div className="space-y-4">
              {/* Top Pagination Control */}
              {filteredStocks.length > pageSize && (
                <Pagination
                  currentPage={currentPage}
                  totalPages={totalPages}
                  onPageChange={setCurrentPage}
                  pageSize={pageSize}
                  onPageSizeChange={setPageSize}
                  totalItems={filteredStocks.length}
                />
              )}

              {/* Grid of Stock Signal Cards (4-Card Density on XL Screens) */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3.5">
                {paginatedStocks.map((stock) => (
                  <SignalCard
                    key={stock.symbol}
                    stock={stock}
                    onOpenChart={handleOpenChart}
                  />
                ))}
              </div>

              {/* Bottom Pagination Control */}
              <Pagination
                currentPage={currentPage}
                totalPages={totalPages}
                onPageChange={setCurrentPage}
                pageSize={pageSize}
                onPageSizeChange={setPageSize}
                totalItems={filteredStocks.length}
              />
            </div>
          )}
        </div>

        {/* Live Movers Panel */}
        <div className={mainTab === 'LIVE_MOVERS' ? 'block' : 'hidden'}>
          <LiveMoversPanel onOpenChart={handleOpenChart} />
        </div>

        {/* Market Pulse & Strategic Radar Panel */}
        <div className={mainTab === 'MARKET_PULSE' ? 'block' : 'hidden'}>
          <MarketPulsePanel onOpenChart={handleOpenChart} initialData={marketPulseData} onDataUpdate={setMarketPulseData} />
        </div>

        {/* Isolated 4th Tab: ALPHA — NIFTY 50 Intraday Options Buying Quant Engine */}
        <div className={mainTab === 'NIFTY_OPTIONS' ? 'block' : 'hidden'}>
          <NiftyOptionsPanel
            isActive={mainTab === 'NIFTY_OPTIONS'}
            onSwitchToAlphaTab={() => setMainTab('NIFTY_OPTIONS')}
            onSpotUpdate={setNiftySpotData}
          />
        </div>
      </main>

      <ChartDrawer
        stock={selectedStockForChart}
        isOpen={isChartOpen}
        onClose={handleCloseChart}
      />

      <ToastContainer
        signals={toastSignals}
        onDismiss={handleDismissToast}
        onView={(stock) => {
          handleDismissToast(stock.symbol);
          handleOpenChart(stock);
        }}
      />

      <footer className="border-t border-white/5 py-4 bg-dark-900 text-center text-xs text-slate-500">
        <p>NSE Quantitative Intraday Screener • 1,468 Equities (Market Cap ≥ ₹1,000 Cr) • 15m Momentum + 20 EMA + RSI(14) + RelVol Breakout Strategy</p>
        <p className="text-[11px] text-slate-600 mt-0.5">Designed for Indian Stock Markets (NSE Nifty 500 & Expanded Universe). Past performance does not guarantee future results.</p>
      </footer>
    </div>
  );
}








