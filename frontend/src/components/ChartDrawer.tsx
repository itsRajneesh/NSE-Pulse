"use client";

import React, { useEffect, useRef, useState } from 'react';
import { 
  X, 
  Target, 
  Calculator, 
  Activity 
} from 'lucide-react';
import { createChart, ColorType, IChartApi, ISeriesApi, LineStyle } from 'lightweight-charts';
import { StockSignal, StockHistoryResponse } from '@/types/screener';
import { formatINR, cn } from '@/lib/utils';

interface ChartDrawerProps {
  stock: StockSignal | null;
  isOpen: boolean;
  onClose: () => void;
}

export const ChartDrawer: React.FC<ChartDrawerProps> = ({ stock, isOpen, onClose }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const rsiContainerRef = useRef<HTMLDivElement>(null);
  
  const [historyData, setHistoryData] = useState<StockHistoryResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [shareQty, setShareQty] = useState<number>(100);

  useEffect(() => {
    if (!stock || !isOpen) return;

    let isMounted = true;
    setLoading(true);
    setError(null);

    const fetchHistory = async () => {
      try {
        const url = '/api/stocks/' + encodeURIComponent(stock.symbol) + '/history';
        const res = await fetch(url);
        if (!res.ok) throw new Error('Failed to fetch stock history data');
        const data: StockHistoryResponse = await res.json();
        if (isMounted) {
          setHistoryData(data);
          setLoading(false);
        }
      } catch (err: any) {
        if (isMounted) {
          setError(err.message || 'Error loading chart data');
          setLoading(false);
        }
      }
    };

    fetchHistory();

    return () => {
      isMounted = false;
    };
  }, [stock, isOpen]);

  useEffect(() => {
    if (!isOpen || !historyData || !chartContainerRef.current) return;

    chartContainerRef.current.innerHTML = '';
    if (rsiContainerRef.current) rsiContainerRef.current.innerHTML = '';

    const mainChart: IChartApi = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: 380,
      layout: {
        background: { type: ColorType.Solid, color: '#0b0f17' },
        textColor: '#94a3b8',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.04)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.04)' },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: 'rgba(255, 255, 255, 0.1)',
      },
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.1)',
      },
      crosshair: {
        vertLine: { color: '#6366f1', width: 1, style: LineStyle.Dashed },
        horzLine: { color: '#6366f1', width: 1, style: LineStyle.Dashed },
      },
    });

    const candleSeries: ISeriesApi<'Candlestick'> = mainChart.addCandlestickSeries({
      upColor: '#10b981',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    });

    const formattedCandles = historyData.candles.map((c, i) => {
      const parsed = Date.parse(c.timestamp);
      const t = isNaN(parsed) ? (1725500000 + i * 900) : Math.floor(parsed / 1000);
      return {
        time: t as any,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      };
    });

    candleSeries.setData(formattedCandles);

    const volumeSeries = mainChart.addHistogramSeries({
      color: '#26a69a',
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: {
        top: 0.8,
        bottom: 0,
      },
    });

    const formattedVolumes = historyData.candles.map((c, i) => {
      const parsed = Date.parse(c.timestamp);
      const t = isNaN(parsed) ? (1725500000 + i * 900) : Math.floor(parsed / 1000);
      return {
        time: t as any,
        value: c.volume,
        color: c.close >= c.open ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)',
      };
    });
    volumeSeries.setData(formattedVolumes);

    if (historyData.ema20_series && historyData.ema20_series.length > 0) {
      const emaLineSeries = mainChart.addLineSeries({
        color: '#f59e0b',
        lineWidth: 2,
        title: '20 EMA',
        priceLineVisible: false,
      });

      const formattedEma = historyData.ema20_series.map((pt, i) => {
        const parsed = Date.parse(pt.time);
        const t = isNaN(parsed) ? (1725500000 + i * 900) : Math.floor(parsed / 1000);
        return {
          time: t as any,
          value: pt.value,
        };
      });
      emaLineSeries.setData(formattedEma);
    }

    const tp = historyData.trade_params || stock?.trade_params;
    if (tp) {
      candleSeries.createPriceLine({
        price: tp.entry_price,
        color: '#06b6d4',
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: 'ENTRY ?' + tp.entry_price,
      });

      candleSeries.createPriceLine({
        price: tp.stop_loss,
        color: '#f43f5e',
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'SL ?' + tp.stop_loss,
      });

      candleSeries.createPriceLine({
        price: tp.target_1,
        color: '#10b981',
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'T1 (1:1.5) ?' + tp.target_1,
      });

      candleSeries.createPriceLine({
        price: tp.target_2,
        color: '#22c55e',
        lineWidth: 2,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: 'T2 (1:2.0) ?' + tp.target_2,
      });
    }

    let rsiChart: IChartApi | null = null;
    if (rsiContainerRef.current && historyData.rsi_series && historyData.rsi_series.length > 0) {
      rsiChart = createChart(rsiContainerRef.current, {
        width: rsiContainerRef.current.clientWidth,
        height: 120,
        layout: {
          background: { type: ColorType.Solid, color: '#0b0f17' },
          textColor: '#94a3b8',
          fontSize: 10,
        },
        grid: {
          vertLines: { color: 'rgba(255, 255, 255, 0.02)' },
          horzLines: { color: 'rgba(255, 255, 255, 0.02)' },
        },
        timeScale: {
          timeVisible: true,
          borderColor: 'rgba(255, 255, 255, 0.1)',
        },
        rightPriceScale: {
          borderColor: 'rgba(255, 255, 255, 0.1)',
          scaleMargins: { top: 0.1, bottom: 0.1 },
        },
      });

      const rsiLineSeries = rsiChart.addLineSeries({
        color: '#818cf8',
        lineWidth: 2,
        title: 'RSI(14)',
      });

      const formattedRsi = historyData.rsi_series.map((pt, i) => {
        const parsed = Date.parse(pt.time);
        const t = isNaN(parsed) ? (1725500000 + i * 900) : Math.floor(parsed / 1000);
        return {
          time: t as any,
          value: pt.value,
        };
      });
      rsiLineSeries.setData(formattedRsi);

      rsiLineSeries.createPriceLine({
        price: 70,
        color: '#ef4444',
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: false,
        title: '70',
      });

      rsiLineSeries.createPriceLine({
        price: 50,
        color: '#e2e8f0',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: '50 CENTER',
      });

      rsiLineSeries.createPriceLine({
        price: 30,
        color: '#10b981',
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: false,
        title: '30',
      });

      mainChart.timeScale().subscribeVisibleTimeRangeChange((timeRange) => {
        if (timeRange && rsiChart) {
          rsiChart.timeScale().setVisibleRange(timeRange);
        }
      });
    }

    mainChart.timeScale().fitContent();

    const handleResize = () => {
      if (chartContainerRef.current) {
        mainChart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
      if (rsiContainerRef.current && rsiChart) {
        rsiChart.applyOptions({ width: rsiContainerRef.current.clientWidth });
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      mainChart.remove();
      if (rsiChart) rsiChart.remove();
    };
  }, [isOpen, historyData, stock]);

  if (!isOpen || !stock) return null;

  const tp = stock.trade_params;
  const isBullish = stock.signal_type === 'BULLISH';

  const totalInvestment = shareQty * stock.ltp;
  const totalRiskINR = tp ? shareQty * tp.risk_amount : 0;
  const target1ProfitINR = tp ? shareQty * (tp.risk_amount * 1.5) : 0;
  const target2ProfitINR = tp ? shareQty * (tp.risk_amount * 2.0) : 0;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/70 backdrop-blur-sm flex justify-end animate-in fade-in duration-200">
      <div className="w-full max-w-4xl bg-dark-900 border-l border-white/10 h-full flex flex-col shadow-2xl overflow-y-auto">
        
        <div className="p-4 border-b border-white/10 bg-dark-850 flex items-center justify-between sticky top-0 z-20">
          <div className="flex items-center gap-3">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-black text-white">{stock.symbol}</h2>
                <span className="px-2 py-0.5 text-xs font-semibold bg-dark-750 text-indigo-300 rounded border border-white/10">
                  {stock.sector}
                </span>
                {stock.is_active_signal && (
                  <span className={cn(
                    "px-2 py-0.5 text-[11px] font-bold rounded-full border",
                    isBullish ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40" : "bg-rose-500/20 text-rose-300 border-rose-500/40"
                  )}>
                    {isBullish ? 'BULLISH BREAKOUT' : 'BEARISH BREAKDOWN'}
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-400">{stock.name} ? NSE 15-Minute Candlestick Chart</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="text-right hidden sm:block">
              <div className="text-lg font-mono font-bold text-white">{formatINR(stock.ltp)}</div>
              <div className={cn("text-xs font-mono font-semibold", stock.price_change_pct >= 0 ? "text-emerald-400" : "text-rose-400")}>
                {stock.price_change_pct >= 0 ? '+' : ''}{stock.price_change_pct}%
              </div>
            </div>

            <button
              onClick={onClose}
              className="p-2 rounded-xl bg-dark-750 hover:bg-dark-700 text-slate-400 hover:text-white border border-white/10 transition-all"
              title="Close Chart (Esc)"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        <div className="p-4 sm:p-6 space-y-6 flex-1">
          
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
            <div className="p-2.5 rounded-lg bg-dark-800/80 border border-white/5">
              <span className="text-slate-400 block text-[10px]">20 EMA (Trend Line)</span>
              <span className="font-bold font-mono text-amber-400">?{stock.indicators.ema20}</span>
            </div>
            <div className="p-2.5 rounded-lg bg-dark-800/80 border border-white/5">
              <span className="text-slate-400 block text-[10px]">RSI (14) Momentum</span>
              <span className="font-bold font-mono text-indigo-300">{stock.indicators.rsi14}</span>
            </div>
            <div className="p-2.5 rounded-lg bg-dark-800/80 border border-white/5">
              <span className="text-slate-400 block text-[10px]">Relative Volume (10d)</span>
              <span className="font-bold font-mono text-amber-400">{stock.rel_vol}x Volume</span>
            </div>
            <div className="p-2.5 rounded-lg bg-dark-800/80 border border-white/5">
              <span className="text-slate-400 block text-[10px]">Breakout Candle Range</span>
              <span className="font-bold font-mono text-cyan-300">
                ?{stock.indicators.last_candle_low} - ?{stock.indicators.last_candle_high}
              </span>
            </div>
          </div>

          <div className="rounded-xl bg-dark-900 border border-white/10 p-3 relative overflow-hidden">
            <div className="flex items-center justify-between mb-2 px-2">
              <div className="flex items-center gap-3 text-xs">
                <span className="font-semibold text-white flex items-center gap-1">
                  <Activity className="w-3.5 h-3.5 text-indigo-400" /> 15m Candles + 20 EMA Overlay
                </span>
                <span className="inline-flex items-center gap-1 text-[11px] text-amber-400 font-mono">
                  <span className="w-2 h-0.5 bg-amber-400 inline-block" /> EMA(20)
                </span>
              </div>
              <div className="flex items-center gap-2 text-[10px] text-slate-400 font-mono">
                <span className="text-cyan-400">? Entry</span>
                <span className="text-rose-400">? SL</span>
                <span className="text-emerald-400">? Targets</span>
              </div>
            </div>

            {loading && (
              <div className="h-[380px] flex items-center justify-center text-slate-400 text-sm">
                <div className="flex items-center gap-2">
                  <div className="w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
                  <span>Loading TradingView Chart Engine...</span>
                </div>
              </div>
            )}

            {error && (
              <div className="h-[380px] flex items-center justify-center text-rose-400 text-sm">
                {error}
              </div>
            )}

            <div ref={chartContainerRef} className={loading ? 'hidden' : 'w-full'} />

            <div className="mt-3 pt-3 border-t border-white/5">
              <div className="flex items-center justify-between text-xs px-2 mb-1">
                <span className="font-semibold text-slate-300">RSI (14) Oscillator</span>
                <span className="text-[10px] text-slate-400">Confirmation Threshold: 50.0</span>
              </div>
              <div ref={rsiContainerRef} className={loading ? 'hidden' : 'w-full'} />
            </div>
          </div>

          {tp && (
            <div className="glass-panel p-4 rounded-xl space-y-3">
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <Target className="w-4 h-4 text-indigo-400" />
                Dynamic Trade Execution Parameters (Feature B)
              </h3>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="p-3 rounded-lg bg-dark-800 border border-cyan-500/30">
                  <span className="text-[11px] text-cyan-400 font-medium block">Breakout Entry</span>
                  <span className="text-lg font-mono font-bold text-cyan-200">?{tp.entry_price}</span>
                  <span className="text-[10px] text-slate-400 block mt-0.5">Last Candle High</span>
                </div>

                <div className="p-3 rounded-lg bg-dark-800 border border-rose-500/30">
                  <span className="text-[11px] text-rose-400 font-medium block">Stop Loss (SL)</span>
                  <span className="text-lg font-mono font-bold text-rose-200">?{tp.stop_loss}</span>
                  <span className="text-[10px] text-slate-400 block mt-0.5">Last Candle Low</span>
                </div>

                <div className="p-3 rounded-lg bg-dark-800 border border-emerald-500/30">
                  <div className="flex justify-between items-center">
                    <span className="text-[11px] text-emerald-400 font-medium block">Target 1</span>
                    <span className="text-[9px] bg-emerald-900/60 px-1 rounded text-emerald-300">1:1.5 RR</span>
                  </div>
                  <span className="text-lg font-mono font-bold text-emerald-200">?{tp.target_1}</span>
                  <span className="text-[10px] text-slate-400 block mt-0.5">+?{(tp.risk_amount * 1.5).toFixed(2)} gain</span>
                </div>

                <div className="p-3 rounded-lg bg-dark-800 border border-emerald-500/30">
                  <div className="flex justify-between items-center">
                    <span className="text-[11px] text-emerald-400 font-medium block">Target 2</span>
                    <span className="text-[9px] bg-emerald-900/60 px-1 rounded text-emerald-300">1:2.0 RR</span>
                  </div>
                  <span className="text-lg font-mono font-bold text-emerald-200">?{tp.target_2}</span>
                  <span className="text-[10px] text-slate-400 block mt-0.5">+?{(tp.risk_amount * 2.0).toFixed(2)} gain</span>
                </div>
              </div>
            </div>
          )}

          <div className="glass-panel p-4 rounded-xl space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <Calculator className="w-4 h-4 text-amber-400" />
                Intraday Risk & Position Sizing Calculator
              </h3>
              <span className="text-xs text-slate-400">Instant P&L Scenario Planning</span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-12 gap-4 items-center">
              <div className="sm:col-span-4 space-y-1.5">
                <label className="text-xs text-slate-300 font-medium block">
                  Order Quantity (Shares):
                </label>
                <input
                  type="number"
                  min="1"
                  step="10"
                  value={shareQty}
                  onChange={(e) => setShareQty(Math.max(1, Number(e.target.value)))}
                  className="w-full px-3 py-2 bg-dark-800 border border-white/10 rounded-lg text-white font-mono text-sm focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="sm:col-span-8 grid grid-cols-3 gap-2 text-center text-xs">
                <div className="p-2.5 rounded-lg bg-dark-800 border border-white/5">
                  <span className="text-[10px] text-slate-400 block">Total Capital</span>
                  <span className="font-bold font-mono text-slate-200 text-sm">
                    {formatINR(totalInvestment)}
                  </span>
                </div>

                <div className="p-2.5 rounded-lg bg-dark-800 border border-rose-500/20">
                  <span className="text-[10px] text-rose-400 block">Max Risk (SL Hit)</span>
                  <span className="font-bold font-mono text-rose-300 text-sm">
                    -{formatINR(totalRiskINR)}
                  </span>
                </div>

                <div className="p-2.5 rounded-lg bg-dark-800 border border-emerald-500/20">
                  <span className="text-[10px] text-emerald-400 block">Profit at Target 1</span>
                  <span className="font-bold font-mono text-emerald-300 text-sm">
                    +{formatINR(target1ProfitINR)}
                  </span>
                </div>

                <div className="p-2.5 rounded-lg bg-dark-800 border border-emerald-500/20">
                  <span className="text-[10px] text-emerald-400 block">Profit at Target 2</span>
                  <span className="font-bold font-mono text-emerald-300 text-sm">
                    +{formatINR(target2ProfitINR)}
                  </span>
                </div>
              </div>
            </div>
          </div>

        </div>

      </div>
    </div>
  );
};
