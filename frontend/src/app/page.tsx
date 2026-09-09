"use client";

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Navbar } from '@/components/Navbar';
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
import { ScreenerResponse, StockSignal } from '@/types/screener';
import { playSignalSound } from '@/lib/utils';

export default function ScreenerDashboard() {
  const [data, setData] = useState<ScreenerResponse | null>(null);
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

  // Refresh & Mode States
  const [mode, setMode] = useState<'live' | 'simulation' | 'auto'>('live');
  const [refreshInterval, setRefreshInterval] = useState<RefreshIntervalType>(60);
  const [countdown, setCountdown] = useState<number>(60);

  // Audio & Alerts
  const [audioEnabled, setAudioEnabled] = useState<boolean>(true);
  const [toastSignals, setToastSignals] = useState<StockSignal[]>([]);
  const previousSignalSymbolsRef = useRef<Set<string>>(new Set());

  // Interactive Chart Drawer State
  const [selectedStockForChart, setSelectedStockForChart] = useState<StockSignal | null>(null);
  const [isChartOpen, setIsChartOpen] = useState<boolean>(false);

  // Reset pagination on filter or search changes
  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, selectedSector, signalFilter, sortBy]);

  // Fetch Sectors on Mount
  useEffect(() => {
    fetch('/api/sectors')
      .then((res) => res.json())
      .then((secData) => {
        if (Array.isArray(secData)) setSectors(secData);
      })
      .catch((e) => console.log('Notice fetching sectors:', e));
  }, []);

  // Fetch Screener Data Function
  const fetchScreenerData = useCallback(async (isManual: boolean = false) => {
    if (isManual) setIsRefreshing(true);
    try {
      const queryParams = new URLSearchParams();
      if (mode) queryParams.set('mode', mode);
      if (isManual) queryParams.set('force_refresh', 'true');

      const url = '/api/screener?' + queryParams.toString();
      const res = await fetch(url);
      if (!res.ok) throw new Error('HTTP error! status: ' + res.status);
      const json: ScreenerResponse = await res.json();
      
      const newActive = json.stocks.filter((s) => s.is_active_signal);
      const newTriggered: StockSignal[] = [];

      newActive.forEach((s) => {
        if (!previousSignalSymbolsRef.current.has(s.symbol)) {
          newTriggered.push(s);
        }
      });

      previousSignalSymbolsRef.current = new Set(newActive.map((s) => s.symbol));

      if (newTriggered.length > 0) {
        setToastSignals((prev) => [...newTriggered.slice(0, 3), ...prev].slice(0, 4));
        if (audioEnabled) {
          playSignalSound(newTriggered[0].signal_type === 'BULLISH' ? 'BULLISH' : 'BEARISH');
        }
      }

      setData(json);
      setError(null);
    } catch (err: any) {
      console.error('Error fetching screener:', err);
      setError(err.message || 'Failed to connect to Screener API');
    } finally {
      setLoading(false);
      setIsRefreshing(false);
      setCountdown(refreshInterval);
    }
  }, [mode, refreshInterval, audioEnabled]);

  useEffect(() => {
    fetchScreenerData();
  }, [fetchScreenerData]);

  useEffect(() => {
    if (refreshInterval === 0) return;

    const timer = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          fetchScreenerData();
          return refreshInterval;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [refreshInterval, fetchScreenerData]);

  const handleOpenChart = (stock: StockSignal) => {
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

  // Filtered & Sorted Stock List
  const filteredStocks = useMemo(() => {
    if (!data?.stocks) return [];

    let list = [...data.stocks];

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      list = list.filter(
        (s) =>
          s.symbol.toLowerCase().includes(q) ||
          s.name.toLowerCase().includes(q) ||
          s.sector.toLowerCase().includes(q)
      );
    }

    if (selectedSector !== 'ALL') {
      list = list.filter((s) => s.sector.toLowerCase() === selectedSector.toLowerCase());
    }

    if (signalFilter === 'ACTIVE_ONLY') {
      list = list.filter((s) => s.is_active_signal);
    } else if (signalFilter === 'BULLISH') {
      list = list.filter((s) => s.signal_type === 'BULLISH' && s.is_active_signal);
    } else if (signalFilter === 'BEARISH') {
      list = list.filter((s) => s.signal_type === 'BEARISH' && s.is_active_signal);
    }

    // Client-side sort override if user selects non-default
    switch (sortBy) {
      case 'REL_VOL_DESC':
        list.sort((a, b) => {
          // Primary: active signals first
          if (a.is_active_signal !== b.is_active_signal) {
            return a.is_active_signal ? -1 : 1;
          }
          return b.rel_vol - a.rel_vol;
        });
        break;
      case 'CHANGE_DESC':
        list.sort((a, b) => b.price_change_pct - a.price_change_pct);
        break;
      case 'CHANGE_ASC':
        list.sort((a, b) => a.price_change_pct - b.price_change_pct);
        break;
      case 'RR_DESC':
        list.sort((a, b) => {
          const aRisk = a.trade_params?.risk_amount ?? 1;
          const bRisk = b.trade_params?.risk_amount ?? 1;
          return bRisk - aRisk;
        });
        break;
      case 'SYMBOL_ASC':
        list.sort((a, b) => a.symbol.localeCompare(b.symbol));
        break;
    }

    return list;
  }, [data, searchQuery, selectedSector, signalFilter, sortBy]);

  // Pagination slicing
  const totalPages = Math.max(1, Math.ceil(filteredStocks.length / pageSize));
  const paginatedStocks = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredStocks.slice(start, start + pageSize);
  }, [filteredStocks, currentPage, pageSize]);

  return (
    <div className="min-h-screen bg-dark-900 text-slate-100 flex flex-col font-sans">
      <Navbar
        marketStatus={data?.market_status ?? null}
        mode={mode}
        onModeChange={(m) => setMode(m)}
        audioEnabled={audioEnabled}
        onToggleAudio={() => setAudioEnabled((prev) => !prev)}
        onRefresh={() => fetchScreenerData(true)}
        isRefreshing={isRefreshing}
        lastRefreshedTime={data?.last_refreshed ?? ''}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        <OverviewStats data={data} loading={loading} />

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
          onRefreshIntervalChange={setRefreshInterval}
          countdown={countdown}
          totalCount={data?.total_scanned ?? 0}
          activeCount={data?.active_signals_count ?? 0}
          bullishCount={data?.bullish_count ?? 0}
          bearishCount={data?.bearish_count ?? 0}
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

            {/* Grid of Stock Signal Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
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
        <p>NSE Quantitative Intraday Screener ? Nifty 500 constituents ? 15m Momentum + 20 EMA + RSI(14) + RelVol Breakout Strategy</p>
        <p className="text-[11px] text-slate-600 mt-0.5">Designed for Indian Stock Markets (NSE Nifty 500). Past performance does not guarantee future results.</p>
      </footer>
    </div>
  );
}
