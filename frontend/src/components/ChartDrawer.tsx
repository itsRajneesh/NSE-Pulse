"use client";

import React, { useEffect, useRef, useState } from 'react';
import { 
  X, 
  Target, 
  Calculator, 
  Activity,
  Copy,
  Check,
  ShieldAlert,
  Zap,
  Clock,
  AlertTriangle,
  Receipt
} from 'lucide-react';
import { createChart, ColorType, IChartApi, ISeriesApi, LineStyle } from 'lightweight-charts';
import { V13Signal, V13UniverseStock, StockHistoryResponse } from '@/types/screener';
import { formatINR, cn } from '@/lib/utils';

const isV13Signal = (stock: V13Signal | V13UniverseStock): stock is V13Signal => {
  return 'risk' in stock;
};
interface ChartDrawerProps {
  stock: V13Signal | V13UniverseStock | null;
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
  const [customEntry, setCustomEntry] = useState<string>('');
  const [customTarget, setCustomTarget] = useState<string>('');

  // --- Persistent Risk & Position Sizing State (Zerodha 5x & SEBI Margin Aligned) ---
  const [accountCapital, setAccountCapital] = useState<number>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('intraday_account_capital');
      if (saved && !isNaN(Number(saved)) && Number(saved) > 0) return Number(saved);
    }
    return 50000;
  });

  const [riskMode, setRiskMode] = useState<'FIXED_INR' | 'PERCENT_CAPITAL'>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('intraday_risk_mode');
      if (saved === 'PERCENT_CAPITAL' || saved === 'FIXED_INR') return saved;
    }
    return 'FIXED_INR';
  });

  const [riskValue, setRiskValue] = useState<number>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('intraday_risk_val');
      if (saved && !isNaN(Number(saved)) && Number(saved) > 0) return Number(saved);
    }
    return 1000;
  });

  const [productType, setProductType] = useState<'MIS' | 'CNC'>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('intraday_product_type');
      if (saved === 'CNC' || saved === 'MIS') return saved;
    }
    return 'MIS';
  });

  const [pnlMode, setPnlMode] = useState<'GROSS' | 'NET'>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('intraday_pnl_mode');
      if (saved === 'NET' || saved === 'GROSS') return saved;
    }
    return 'GROSS';
  });

  const [copied, setCopied] = useState<boolean>(false);
  const [isMarginFlipped, setIsMarginFlipped] = useState<boolean>(false);

  const handleCapitalChange = (val: number) => {
    setAccountCapital(val);
    if (typeof window !== 'undefined' && val > 0) {
      localStorage.setItem('intraday_account_capital', val.toString());
    }
  };

  const handleRiskModeChange = (mode: 'FIXED_INR' | 'PERCENT_CAPITAL') => {
    setRiskMode(mode);
    if (typeof window !== 'undefined') localStorage.setItem('intraday_risk_mode', mode);
  };

  const handleRiskValueChange = (val: number) => {
    const clean = Math.max(0.1, val);
    setRiskValue(clean);
    if (typeof window !== 'undefined') localStorage.setItem('intraday_risk_val', clean.toString());
  };

  const handleProductTypeChange = (type: 'MIS' | 'CNC') => {
    setProductType(type);
    if (typeof window !== 'undefined') localStorage.setItem('intraday_product_type', type);
  };

  const handlePnlModeChange = (mode: 'GROSS' | 'NET') => {
    setPnlMode(mode);
    if (typeof window !== 'undefined') localStorage.setItem('intraday_pnl_mode', mode);
  };

  // Safely initialize / sync shareQty whenever a new stock is opened (Unconditionally top-level)
  useEffect(() => {
    if (!stock || !isOpen) return;
    const chartSignal = isV13Signal(stock) ? stock : stock.signals?.[0] ?? null;
    const tp = chartSignal?.risk ?? null;
    const isBull = chartSignal?.direction === 'BULLISH';
    const ltp = chartSignal?.price ?? (isV13Signal(stock) ? stock.price : stock.snapshot?.price) ?? 0;
    const entry = tp?.entry ?? ltp;
    const sl = tp?.stop_loss ?? (isBull ? entry * 0.985 : entry * 1.015);
    const rps = Math.max(0.10, Math.abs(entry - sl));
    const cap = Math.max(1, accountCapital || 50000);
    const pRisk = riskMode === 'PERCENT_CAPITAL'
      ? Math.round((cap * Math.max(0.1, riskValue)) / 100)
      : Math.round(Math.max(10, riskValue));
    const friction = pnlMode === 'NET' ? 50 : 0;
    const netBudget = pnlMode === 'NET' ? Math.max(50, pRisk - friction) : pRisk;
    const qr = Math.max(1, Math.floor(netBudget / rps));
    const lev = (!isBull || productType === 'MIS') ? 5 : 1;
    const qm = entry > 0 ? Math.max(1, Math.floor((cap * lev) / entry)) : 1;
    setShareQty(Math.max(1, Math.min(qr, qm)));
    setIsMarginFlipped(false);
  }, [stock?.symbol, isOpen, pnlMode]);

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

    // -------------------------------------------------------------
    // Session VWAP Line Overlay (Calculated from 15m Candles)
    // -------------------------------------------------------------
    let currentVwapDate = '';
    let cumulativePV = 0;
    let cumulativeVol = 0;
    const formattedVwap: { time: any; value: number }[] = [];

    historyData.candles.forEach((c, i) => {
      const parsed = Date.parse(c.timestamp);
      const t = isNaN(parsed) ? (1725500000 + i * 900) : Math.floor(parsed / 1000);
      const dateKey = c.timestamp ? (c.timestamp.split(' ')[0] || c.timestamp.split('T')[0]) : '';

      if (dateKey !== currentVwapDate) {
        currentVwapDate = dateKey;
        cumulativePV = 0;
        cumulativeVol = 0;
      }

      const typicalPrice = (c.high + c.low + c.close) / 3;
      cumulativePV += typicalPrice * c.volume;
      cumulativeVol += c.volume;

      const vwapVal = cumulativeVol > 0 ? cumulativePV / cumulativeVol : typicalPrice;
      formattedVwap.push({
        time: t as any,
        value: Math.round(vwapVal * 100) / 100,
      });
    });

    if (formattedVwap.length > 0) {
      const vwapLineSeries = mainChart.addLineSeries({
        color: '#06b6d4',
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        title: 'VWAP',
        priceLineVisible: false,
      });
      vwapLineSeries.setData(formattedVwap);
    }

    const chartSignal = stock ? (isV13Signal(stock) ? stock : stock.signals[0] ?? null) : null;
    const tp = chartSignal?.risk ?? null;
    if (tp) {
      if (tp.entry !== null) {
        candleSeries.createPriceLine({
          price: tp.entry,
          color: '#06b6d4',
          lineWidth: 2,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: true,
          title: 'ENTRY ₹' + tp.entry,
        });
      }

      if (tp.stop_loss !== null) {
        candleSeries.createPriceLine({
          price: tp.stop_loss,
          color: '#f43f5e',
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: 'SL ₹' + tp.stop_loss,
        });
      }

      if (tp.target_1 !== null) {
        candleSeries.createPriceLine({
          price: tp.target_1,
          color: '#10b981',
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: 'T1 ' + tp.target_1,
        });
      }

      if (tp.target_2 !== null) {
        candleSeries.createPriceLine({
          price: tp.target_2,
          color: '#22c55e',
          lineWidth: 2,
          lineStyle: LineStyle.Dotted,
          axisLabelVisible: true,
          title: 'T2 ' + tp.target_2,
        });
      }
    }

    // Dynamic Custom Target Price Line on Candlestick Chart
    const parsedCustom = parseFloat(customTarget);
    if (!isNaN(parsedCustom) && parsedCustom > 0) {
      candleSeries.createPriceLine({
        price: parsedCustom,
        color: '#a855f7',
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'CUSTOM ₹' + parsedCustom,
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
  }, [isOpen, historyData, stock, customTarget]);

  if (!isOpen || !stock) return null;

  const chartSignal = isV13Signal(stock) ? stock : stock.signals[0] ?? null;
  const isSignal = chartSignal !== null;
  const tp = chartSignal?.risk ?? null;
  const isBullish = chartSignal?.direction === 'BULLISH';
  const ind = chartSignal?.indicators ?? (isV13Signal(stock) ? stock.indicators : stock.snapshot);
  
  // Requirement: Anchor calculation on Breakout Entry level by default, or Custom Execution Entry Price if provided!
  const ltp = chartSignal?.price ?? (isV13Signal(stock) ? stock.price : stock.snapshot.price) ?? 0;
  const defaultEntryPrice = tp?.entry ?? ltp;
  const parsedCustomEntry = parseFloat(customEntry);
  const entryPrice = (!isNaN(parsedCustomEntry) && parsedCustomEntry > 0) ? parsedCustomEntry : defaultEntryPrice;

  const stopLossPrice = tp?.stop_loss ?? (isBullish ? defaultEntryPrice * 0.985 : defaultEntryPrice * 1.015);
  const target1Price = tp?.target_1 ?? (isBullish ? defaultEntryPrice * 1.02 : defaultEntryPrice * 0.98);
  const target2Price = tp?.target_2 ?? (isBullish ? defaultEntryPrice * 1.035 : defaultEntryPrice * 0.965);

  // --- Dual-Constraint Position Sizing & Margin Math Engine ---
  const effectiveCapital = Math.max(1, accountCapital || 0);
  const plannedRiskINR = riskMode === 'PERCENT_CAPITAL'
    ? Math.round((effectiveCapital * Math.max(0.1, riskValue)) / 100)
    : Math.round(Math.max(10, riskValue));

  const rawRiskPerShare = Math.abs(entryPrice - stopLossPrice);
  const riskPerShare = Math.max(0.10, rawRiskPerShare > 0 ? rawRiskPerShare : entryPrice * 0.015);

  // Dynamic Statutory Friction Buffer (0 for Gross Mode, ~₹50 for Net Mode)
  const isNetMode = pnlMode === 'NET';
  const frictionCushionINR = isNetMode ? 50 : 0;
  const netRiskBudget = isNetMode ? Math.max(50, plannedRiskINR - frictionCushionINR) : plannedRiskINR;

  // Constraint 1: Risk-based Quantity
  const qRisk = Math.max(1, Math.floor(netRiskBudget / riskPerShare));

  // Constraint 2: Margin-based Quantity (MIS 5x Leverage vs CNC 1x Cash)
  // Short selling in Cash equity is strictly Intraday MIS
  const effectiveProductType = !isBullish ? 'MIS' : productType;
  const leverageMultiplier = effectiveProductType === 'MIS' ? 5 : 1;
  const totalBuyingPower = effectiveCapital * leverageMultiplier;
  const qMargin = entryPrice > 0 ? Math.max(1, Math.floor(totalBuyingPower / entryPrice)) : 1;

  // Final Optimal Safe Quantity
  const suggestedSafeQty = Math.max(1, Math.min(qRisk, qMargin));
  const isMarginCappingActive = qRisk > qMargin;

  // Realized metrics based on active shareQty (FYERS RMS Aligned)
  const totalInvestment = shareQty * entryPrice;
  const isMis = effectiveProductType === 'MIS';
  const baseMargin = isMis ? Math.round((totalInvestment / 5) * 100) / 100 : Math.round(totalInvestment * 100) / 100;

  // FYERS Intraday Equity Brokerage: min(20.0, Turnover * 0.03%)
  // Equity Delivery (CNC): ₹0 Free
  const fyersBrokerage = isMis 
    ? Math.min(20.0, Math.round(totalInvestment * 0.0003 * 100) / 100) 
    : 0;

  // FYERS Upfront Required Margin (Blocks Base Margin + Brokerage to enter exchange queue)
  const marginRequired = Math.round((baseMargin + fyersBrokerage) * 100) / 100;
  const isMarginExceeded = marginRequired > accountCapital;

  // Detailed Statutory Levies Breakdown (Matching FYERS Electronic Contract Note on NSE)
  const exchTxnCharge = Math.round(totalInvestment * 0.0000307 * 100) / 100;
  const sebiFee = totalInvestment > 0 ? Math.max(0.01, Math.round(totalInvestment * 0.000001 * 100) / 100) : 0;
  const stampDuty = isBullish ? Math.max(0.01, Math.round(totalInvestment * 0.00003 * 100) / 100) : 0;
  const sttFee = !isBullish ? Math.round(totalInvestment * 0.00025 * 100) / 100 : 0;
  const gstTaxable = fyersBrokerage + exchTxnCharge + sebiFee;
  // Indian Statutory GST split: CGST (9%) + SGST (9%) rounded individually matching FYERS
  const cgstFee = Math.round(gstTaxable * 0.09 * 100) / 100;
  const sgstFee = Math.round(gstTaxable * 0.09 * 100) / 100;
  const gstFee = Math.round((cgstFee + sgstFee) * 100) / 100;
  const totalStatutoryCharges = Math.round((exchTxnCharge + sebiFee + stampDuty + sttFee + gstFee) * 100) / 100;
  const totalFyersCharges = Math.round((fyersBrokerage + totalStatutoryCharges) * 100) / 100;
  const totalEodDebit = Math.round((baseMargin + totalFyersCharges) * 100) / 100;

  const totalRiskINR = Math.round((shareQty * riskPerShare) + (shareQty > 0 ? frictionCushionINR : 0));
  const target1ProfitINR = Math.round((shareQty * Math.abs(target1Price - entryPrice)) - (shareQty > 0 ? frictionCushionINR : 0));
  const target2ProfitINR = Math.round((shareQty * Math.abs(target2Price - entryPrice)) - (shareQty > 0 ? frictionCushionINR : 0));

  const customTgtNum = parseFloat(customTarget);
  const hasCustomTarget = !isNaN(customTgtNum) && customTgtNum > 0;
  const customDiff = isBullish ? (customTgtNum - entryPrice) : (entryPrice - customTgtNum);
  const customProfitINR = hasCustomTarget ? Math.round((shareQty * customDiff) - (shareQty > 0 ? frictionCushionINR : 0)) : 0;
  const customReturnPct = hasCustomTarget && entryPrice > 0 ? (customDiff / entryPrice) * 100 : 0;
  const customRR = hasCustomTarget && riskPerShare > 0 ? (customDiff / riskPerShare).toFixed(2) : 'N/A';

  // --- Trailing Stop-Loss (TSL) 1.0x ATR Step Math (Snapped to ₹0.05 NSE Tick Size) ---
  const isTslEnabled = process.env.NEXT_PUBLIC_ENABLE_TRAILING_SL_GUIDE !== 'false';
  const roundToTick = (val: number, tick = 0.05): number => {
    return Math.max(tick, Math.round(val / tick) * tick);
  };
  const rawAtr = (ind as any)?.atr14 ?? (stock as any)?.snapshot?.atr14 ?? (stock as any)?.atr14 ?? (riskPerShare > 0 ? riskPerShare * 0.75 : 1.0);
  const effectiveAtr = typeof rawAtr === 'number' && rawAtr > 0 ? rawAtr : (riskPerShare > 0 ? riskPerShare * 0.75 : 1.0);
  // Upper Safety Guard: TSL Jump should never exceed initial risk per share
  const cappedTsl = riskPerShare > 0 ? Math.min(effectiveAtr, riskPerShare) : effectiveAtr;
  const tslStepValue = roundToTick(cappedTsl);

  const handleCopyOrder = () => {
    const action = isBullish ? 'BUY' : 'SELL (SHORT)';
    const tslChunk = isTslEnabled ? ` | TSL Step: ₹${tslStepValue.toFixed(2)} (1.0x ATR)` : '';
    const text = `${stock.symbol} | ${action} ${effectiveProductType} | Qty: ${shareQty} | Entry: ₹${entryPrice.toFixed(2)} | SL: ₹${stopLossPrice.toFixed(2)}${tslChunk} | T1: ₹${target1Price.toFixed(2)} | Margin Req: ₹${marginRequired.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  // Synchronized RSI: Aligns top pill with the exact last closed candle of the TradingView RSI chart
  const activeRsi = (historyData?.rsi_series && historyData.rsi_series.length > 0)
    ? (historyData.rsi_series[historyData.rsi_series.length - 1]?.value ?? chartSignal?.indicators?.rsi14 ?? 50.0)
    : (chartSignal?.indicators?.rsi14 ?? 50.0);

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
                {isSignal && (
                  <span className={cn(
                    "px-2 py-0.5 text-[11px] font-bold rounded-full border",
                    (chartSignal?.score ?? 0) < 72
                      ? "bg-slate-800 text-rose-300 border-rose-500/30"
                      : isBullish
                        ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                        : "bg-rose-500/20 text-rose-300 border-rose-500/40"
                  )}>
                    {(chartSignal?.score ?? 0) < 72
                      ? '📊 BELOW THRESHOLD (<72)'
                      : isBullish ? '🚀 BULLISH BREAKOUT' : '🔻 BEARISH BREAKDOWN'}
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-400">{stock.name} ? NSE 15-Minute Candlestick Chart</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="text-right hidden sm:block">
              <div className="text-lg font-mono font-bold text-white">{ltp > 0 ? formatINR(ltp) : 'N/A'}</div>
              <div className="text-xs font-mono font-semibold text-indigo-300">
                SCORE {chartSignal?.score ?? '—'}
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
              <span className="text-slate-400 block text-[10px]">
                {(chartSignal?.setup?.includes('EMA') || chartSignal?.setup_type?.includes('EMA')) ? '15m Bar Range' : 'Breakout Candle Range'}
              </span>
              <span className="font-bold font-mono text-cyan-300">
                {chartSignal?.indicators?.breakout_candle_range != null ? formatINR(chartSignal.indicators.breakout_candle_range) : 'N/A'}
              </span>
            </div>
            <div className="p-2.5 rounded-lg bg-dark-800/80 border border-white/5">
              <span className="text-slate-400 block text-[10px]">
                {(chartSignal?.setup?.includes('EMA') || chartSignal?.setup_type?.includes('EMA')) ? 'Distance to 20-EMA' : 'Breakout Distance from OR'}
              </span>
              <span className="font-bold font-mono text-cyan-300">
                {chartSignal?.indicators?.breakout_distance_atr != null ? `${chartSignal.indicators.breakout_distance_atr} ATR` : 'N/A'}
              </span>
            </div>
            <div className="p-2.5 rounded-lg bg-dark-800/80 border border-white/5">
              <span className="text-slate-400 block text-[10px]">RSI (14)</span>
              <span className={cn(
                "font-bold font-mono",
                activeRsi >= 75
                  ? "text-amber-400"
                  : activeRsi >= 60
                  ? "text-emerald-400"
                  : activeRsi <= 40
                  ? "text-rose-400"
                  : "text-indigo-300"
              )}>
                {Number(activeRsi).toFixed(1)}
              </span>
            </div>
            <div className="p-2.5 rounded-lg bg-dark-800/80 border border-white/5">
              <span className="text-slate-400 block text-[10px]">Relative Volume</span>
              <span className="font-bold font-mono text-amber-300">
                {chartSignal?.indicators?.rel_vol != null ? `${Number(chartSignal.indicators.rel_vol).toFixed(1)}x` : '—'}
              </span>
            </div>
          </div>

          <div className="rounded-xl bg-dark-900 border border-white/10 p-3 relative overflow-hidden">
            <div className="flex items-center justify-between mb-2 px-2">
              <div className="flex items-center gap-3 text-xs">
                <span className="font-semibold text-white flex items-center gap-1">
                  <Activity className="w-3.5 h-3.5 text-indigo-400" /> 15m Candles + Indicators
                </span>
                <span className="inline-flex items-center gap-1 text-[11px] text-amber-400 font-mono">
                  <span className="w-2 h-0.5 bg-amber-400 inline-block" /> EMA(20)
                </span>
                <span className="inline-flex items-center gap-1 text-[11px] text-cyan-400 font-mono">
                  <span className="w-2 h-0.5 bg-cyan-400 inline-block" /> VWAP
                </span>
                {hasCustomTarget && (
                  <span className="inline-flex items-center gap-1 text-[11px] text-purple-400 font-mono">
                    <span className="w-2 h-0.5 bg-purple-400 inline-block" /> Custom Tgt
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 text-[10px] text-slate-400 font-mono">
                <span className="text-cyan-400">● Entry</span>
                <span className="text-rose-400">● SL</span>
                <span className="text-emerald-400">● Targets</span>
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

              <div className={cn("grid grid-cols-2 gap-3", isTslEnabled ? "sm:grid-cols-5" : "sm:grid-cols-4")}>
                <div className="p-3 rounded-lg bg-dark-800 border border-cyan-500/30">
                  <span className="text-[11px] text-cyan-400 font-medium block">
                    {(chartSignal?.score ?? 0) >= 72 ? (isBullish ? 'Breakout Entry' : 'Breakdown Entry') : 'Evaluation Entry'}
                  </span>
                  <span className="text-lg font-mono font-bold text-cyan-200">{tp.entry ?? 'N/A'}</span>
                  <span className="text-[10px] text-slate-400 block mt-0.5">OR Boundary Level</span>
                </div>

                <div className="p-3 rounded-lg bg-dark-800 border border-rose-500/30">
                  <span className="text-[11px] text-rose-400 font-medium block">Stop Loss (SL)</span>
                  <span className="text-lg font-mono font-bold text-rose-200">{tp.stop_loss ?? 'N/A'}</span>
                  <span className="text-[10px] text-slate-400 block mt-0.5">Structural Support / Low</span>
                </div>

                <div className="p-3 rounded-lg bg-dark-800 border border-emerald-500/30">
                  <div className="flex justify-between items-center">
                    <span className="text-[11px] text-emerald-400 font-medium block">Target 1</span>
                    <span className="text-[9px] bg-emerald-900/60 px-1 rounded text-emerald-300">1:1.5 RR</span>
                  </div>
                  <span className="text-lg font-mono font-bold text-emerald-200">{tp.target_1 ?? 'N/A'}</span>
                  <span className="text-[10px] text-slate-400 block mt-0.5">+₹{tp.risk_amount !== null ? (tp.risk_amount * 1.5).toFixed(2) : 'N/A'} gain</span>
                </div>

                <div className="p-3 rounded-lg bg-dark-800 border border-emerald-500/30">
                  <div className="flex justify-between items-center">
                    <span className="text-[11px] text-emerald-400 font-medium block">Target 2</span>
                    <span className="text-[9px] bg-emerald-900/60 px-1 rounded text-emerald-300">1:2.5 RR</span>
                  </div>
                  <span className="text-lg font-mono font-bold text-emerald-200">{tp.target_2 ?? 'N/A'}</span>
                  <span className="text-[10px] text-slate-400 block mt-0.5">+₹{tp.risk_amount !== null ? (tp.risk_amount * 2.5).toFixed(2) : 'N/A'} gain</span>
                </div>

                {isTslEnabled && (
                  <div className="p-3 rounded-lg bg-dark-800 border border-indigo-500/30">
                    <div className="flex justify-between items-center">
                      <span className="text-[11px] text-indigo-400 font-medium block">TSL Step (Jump)</span>
                      <span className="text-[9px] bg-indigo-900/60 px-1 rounded text-indigo-300 font-mono">1.0x ATR</span>
                    </div>
                    <span className="text-lg font-mono font-bold text-indigo-200">
                      ₹{tslStepValue.toFixed(2)}
                    </span>
                    <span className="text-[10px] text-slate-400 block mt-0.5 truncate" title="Fyers / Zerodha Order Jump • Lock Cost at T1">
                      Fyers Jump • Lock @ T1
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="glass-panel p-4 sm:p-5 rounded-xl space-y-4 border border-amber-500/20 bg-dark-850/90 shadow-xl">
            {/* Calculator Header & Fast Actions */}
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/5 pb-3">
              <div className="flex items-center gap-2">
                <span className="p-1.5 rounded-lg bg-amber-500/20 text-amber-400 border border-amber-500/30">
                  <Calculator className="w-4 h-4" />
                </span>
                <div>
                  <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    <span>Intraday Risk & Position Sizing Calculator</span>
                    <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/20">
                      Zerodha 5x & SEBI Margin Aligned
                    </span>
                  </h3>
                  <p className="text-[11px] text-slate-400">
                    Dual-Constraint Math: Risk Limit ({formatINR(plannedRiskINR)}) + 5x Leverage Capacity
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                {/* P&L Mode Toggle: Gross (Pure R:R) vs Net (Taxes/Brokerage) */}
                <div className="flex items-center bg-dark-900 rounded-lg p-0.5 border border-white/10 text-[11px] font-semibold">
                  <button
                    type="button"
                    onClick={() => handlePnlModeChange('GROSS')}
                    className={cn(
                      "px-2.5 py-1 rounded-md transition-all flex items-center gap-1",
                      pnlMode === 'GROSS'
                        ? "bg-amber-500 text-dark-950 font-bold shadow-sm"
                        : "text-slate-400 hover:text-white"
                    )}
                    title="Real price-level Risk-Reward without tax deductions"
                  >
                    <span>📊 Gross (Pure R:R)</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => handlePnlModeChange('NET')}
                    className={cn(
                      "px-2.5 py-1 rounded-md transition-all flex items-center gap-1",
                      pnlMode === 'NET'
                        ? "bg-amber-500 text-dark-950 font-bold shadow-sm"
                        : "text-slate-400 hover:text-white"
                    )}
                    title="Estimated Net P&L after ₹50 Brokerage, STT, and GST buffer"
                  >
                    <span>🧾 Net (-₹50 Tax)</span>
                  </button>
                </div>

                <button
                  type="button"
                  onClick={handleCopyOrder}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-300 border border-indigo-500/30 text-xs font-semibold transition-all shadow-sm active:scale-95"
                  title="Copy formatted order instructions for Zerodha / Groww / Dhan"
                >
                  {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  <span>{copied ? 'Order Copied! ✅' : 'Copy Order'}</span>
                </button>
              </div>
            </div>

            {/* Account Capital, Risk Appetite, Product Mode Controls */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {/* Account Capital Card (Fully Dynamic) */}
              <div className="p-3 rounded-lg bg-dark-800 border border-white/5 space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-[11px] text-slate-300 font-medium">
                    Trading Capital (₹):
                  </label>
                  <span className="text-[10px] font-mono text-cyan-300">
                    Buying Power: {formatINR(totalBuyingPower)}
                  </span>
                </div>
                <div className="relative">
                  <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500 font-mono text-xs">
                    ₹
                  </span>
                  <input
                    type="number"
                    min="1"
                    placeholder="Enter Capital e.g. 50000"
                    value={accountCapital > 0 ? accountCapital : ''}
                    onChange={(e) => handleCapitalChange(Number(e.target.value))}
                    className="w-full pl-6 pr-2.5 py-1.5 bg-dark-900 border border-white/10 rounded-lg text-white font-mono text-sm focus:outline-none focus:border-cyan-500 placeholder-slate-600"
                  />
                </div>
                <div className="flex items-center justify-between text-[10px] font-mono text-slate-400 pt-0.5">
                  <span className="text-slate-500">Live Power:</span>
                  <span className="text-cyan-400 font-semibold">
                    {effectiveProductType === 'MIS' ? '5x Margin (~20% Block)' : '1x Delivery (100% Cash)'}
                  </span>
                </div>
              </div>

              {/* Risk Tolerance Card */}
              <div className="p-3 rounded-lg bg-dark-800 border border-white/5 space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-[11px] text-slate-300 font-medium">
                    Risk Appetite:
                  </label>
                  <div className="flex items-center bg-dark-900 rounded p-0.5 border border-white/10 text-[10px]">
                    <button
                      type="button"
                      onClick={() => handleRiskModeChange('FIXED_INR')}
                      className={cn(
                        "px-1.5 py-0.5 rounded transition-colors",
                        riskMode === 'FIXED_INR' ? "bg-amber-500 text-dark-950 font-bold" : "text-slate-400 hover:text-white"
                      )}
                    >
                      Fixed ₹
                    </button>
                    <button
                      type="button"
                      onClick={() => handleRiskModeChange('PERCENT_CAPITAL')}
                      className={cn(
                        "px-1.5 py-0.5 rounded transition-colors",
                        riskMode === 'PERCENT_CAPITAL' ? "bg-amber-500 text-dark-950 font-bold" : "text-slate-400 hover:text-white"
                      )}
                    >
                      % Cap
                    </button>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min={riskMode === 'PERCENT_CAPITAL' ? "0.1" : "100"}
                    step={riskMode === 'PERCENT_CAPITAL' ? "0.5" : "250"}
                    value={riskValue}
                    onChange={(e) => handleRiskValueChange(Number(e.target.value))}
                    className="w-full px-2.5 py-1.5 bg-dark-900 border border-white/10 rounded-lg text-amber-300 font-mono text-sm focus:outline-none focus:border-amber-500"
                  />
                  <span className="text-xs font-mono text-slate-400 shrink-0">
                    {riskMode === 'PERCENT_CAPITAL' ? `% (= ₹${plannedRiskINR})` : `₹`}
                  </span>
                </div>

                <div className="flex items-center gap-1 text-[10px] font-mono">
                  <span className="text-slate-500">Presets:</span>
                  {riskMode === 'FIXED_INR'
                    ? [500, 1000, 2000, 5000].map((r) => (
                        <button
                          key={r}
                          type="button"
                          onClick={() => handleRiskValueChange(r)}
                          className={cn(
                            "px-1.5 py-0.5 rounded transition-colors",
                            riskValue === r
                              ? "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                              : "bg-dark-750 text-slate-400 hover:text-white"
                          )}
                        >
                          ₹{r >= 1000 ? `${r / 1000}k` : r}
                        </button>
                      ))
                    : [0.5, 1.0, 1.5, 2.0].map((p) => (
                        <button
                          key={p}
                          type="button"
                          onClick={() => handleRiskValueChange(p)}
                          className={cn(
                            "px-1.5 py-0.5 rounded transition-colors",
                            riskValue === p
                              ? "bg-amber-500/20 text-amber-300 border border-amber-500/40"
                              : "bg-dark-750 text-slate-400 hover:text-white"
                          )}
                        >
                          {p}%
                        </button>
                      ))}
                </div>
              </div>

              {/* Product Mode Card */}
              <div className="p-3 rounded-lg bg-dark-800 border border-white/5 space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-[11px] text-slate-300 font-medium">
                    Product / Order Type:
                  </label>
                  <span className="text-[10px] font-mono text-indigo-300">
                    {effectiveProductType === 'MIS' ? '5x Leverage' : '1x Cash'}
                  </span>
                </div>

                {isBullish ? (
                  <div className="grid grid-cols-2 gap-1.5 bg-dark-900 p-1 rounded-lg border border-white/10 text-xs font-semibold">
                    <button
                      type="button"
                      onClick={() => handleProductTypeChange('MIS')}
                      className={cn(
                        "py-1.5 rounded-md transition-all text-center",
                        effectiveProductType === 'MIS'
                          ? "bg-indigo-600 text-white shadow-sm"
                          : "text-slate-400 hover:text-white"
                      )}
                    >
                      ⚡ MIS (5x Intraday)
                    </button>
                    <button
                      type="button"
                      onClick={() => handleProductTypeChange('CNC')}
                      className={cn(
                        "py-1.5 rounded-md transition-all text-center",
                        effectiveProductType === 'CNC'
                          ? "bg-emerald-600 text-white shadow-sm"
                          : "text-slate-400 hover:text-white"
                      )}
                    >
                      📦 CNC (1x Cash)
                    </button>
                  </div>
                ) : (
                  <div className="p-2 rounded-lg bg-rose-950/40 border border-rose-500/30 text-[11px] text-rose-300 flex items-center gap-1.5">
                    <ShieldAlert className="w-4 h-4 shrink-0 text-rose-400" />
                    <span>Short Selling is strictly <strong>MIS (Intraday)</strong>. Delivery not allowed.</span>
                  </div>
                )}

                <div className="flex items-center justify-between text-[10px] text-slate-400">
                  <span>Margin Deposit: {effectiveProductType === 'MIS' ? '20% (5x)' : '100% (1x)'}</span>
                  <span className="text-amber-400">3:15 PM Cutoff</span>
                </div>
              </div>
            </div>

            {/* Smart Safe Quantity Sizing Banner */}
            <div className="p-3 rounded-xl bg-gradient-to-r from-dark-800 via-dark-800 to-indigo-950/40 border border-indigo-500/30 flex flex-wrap items-center justify-between gap-3 text-xs">
              <div className="flex items-center gap-2.5">
                <span className="p-1.5 rounded-lg bg-indigo-500/20 text-indigo-400 border border-indigo-500/30">
                  <Zap className="w-4 h-4 text-amber-400" />
                </span>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-white font-bold">
                      Recommended Safe Quantity:
                    </span>
                    <span className="font-mono font-black text-amber-300 text-sm px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/30">
                      {suggestedSafeQty} Shares
                    </span>
                  </div>
                  <span className="text-[11px] text-slate-400">
                    {isMarginCappingActive
                      ? `⚠️ Capped by 5x Margin (Risk budget allows ${qRisk} qty, capped to ${qMargin} by capital)`
                      : `✅ Exact Risk Fit (${qRisk} shares keeps Max Loss capped at planned ~${formatINR(plannedRiskINR)})`}
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setShareQty(suggestedSafeQty)}
                  className={cn(
                    "px-3 py-1.5 rounded-lg text-xs font-mono font-bold transition-all flex items-center gap-1.5 active:scale-95",
                    shareQty === suggestedSafeQty
                      ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                      : "bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-600/30"
                  )}
                >
                  <Zap className="w-3.5 h-3.5 text-amber-300" />
                  <span>{shareQty === suggestedSafeQty ? 'Applied (Auto-Sized)' : `Apply Safe Qty (${suggestedSafeQty})`}</span>
                </button>
              </div>
            </div>

            {/* Execution Parameter Inputs */}
            <div className="grid grid-cols-1 sm:grid-cols-12 gap-3">
              <div className="sm:col-span-4 space-y-1">
                <div className="flex items-center justify-between">
                  <label className="text-xs text-cyan-300 font-medium block">
                    Execution Entry (₹):
                  </label>
                  <div className="flex items-center gap-1.5 text-[10px]">
                    <button
                      type="button"
                      onClick={() => setCustomEntry(defaultEntryPrice > 0 ? defaultEntryPrice.toString() : '')}
                      className="text-slate-400 hover:text-cyan-300 transition-colors font-mono"
                      title="Reset to Breakout Level"
                    >
                      [ Breakout ]
                    </button>
                    <button
                      type="button"
                      onClick={() => setCustomEntry(ltp > 0 ? ltp.toString() : '')}
                      className="text-slate-400 hover:text-amber-300 transition-colors font-mono"
                      title="Set to Current Live LTP"
                    >
                      [ Live LTP ]
                    </button>
                  </div>
                </div>
                <input
                  type="number"
                  step="0.05"
                  placeholder={`Default: ₹${defaultEntryPrice.toFixed(2)}`}
                  value={customEntry}
                  onChange={(e) => setCustomEntry(e.target.value)}
                  className="w-full px-3 py-1.5 bg-dark-800 border border-cyan-500/30 rounded-lg text-cyan-200 font-mono text-sm focus:outline-none focus:border-cyan-500 placeholder-slate-500"
                />
              </div>

              <div className="sm:col-span-4 space-y-1">
                <div className="flex items-center justify-between">
                  <label className="text-xs text-slate-300 font-medium block">
                    Active Order Quantity:
                  </label>
                  <span className="text-[10px] text-slate-400 font-mono">
                    Per Share Risk: ₹{riskPerShare.toFixed(2)}
                  </span>
                </div>
                <input
                  type="number"
                  min="1"
                  step="5"
                  value={shareQty}
                  onChange={(e) => setShareQty(Math.max(1, Number(e.target.value)))}
                  className="w-full px-3 py-1.5 bg-dark-800 border border-white/10 rounded-lg text-white font-mono text-sm focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="sm:col-span-4 space-y-1">
                <div className="flex items-center justify-between">
                  <label className="text-xs text-purple-300 font-medium block">
                    Custom Target Price (₹):
                  </label>
                  <div className="flex items-center gap-1.5 text-[10px] font-mono">
                    <button
                      type="button"
                      onClick={() => setCustomTarget(target1Price.toString())}
                      className="text-slate-400 hover:text-emerald-300 transition-colors"
                      title="Fill with Target 1 Level"
                    >
                      [ T1 ]
                    </button>
                    <button
                      type="button"
                      onClick={() => setCustomTarget(target2Price.toString())}
                      className="text-slate-400 hover:text-emerald-300 transition-colors"
                      title="Fill with Target 2 Level"
                    >
                      [ T2 ]
                    </button>
                  </div>
                </div>
                <input
                  type="number"
                  step="0.05"
                  placeholder={`e.g. ${(target1Price || entryPrice * 1.02).toFixed(2)}`}
                  value={customTarget}
                  onChange={(e) => setCustomTarget(e.target.value)}
                  className="w-full px-3 py-1.5 bg-dark-800 border border-purple-500/30 rounded-lg text-purple-200 font-mono text-sm focus:outline-none focus:border-purple-500 placeholder-slate-600"
                />
              </div>
            </div>

            {/* 4 Standard Scenario Tiles (Margin Health, Max Risk, T1, T2) */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center text-xs">
              {/* Tile 1: Required Margin (Deposit) with FYERS RMS & Flip Breakdown */}
              <div 
                onClick={() => setIsMarginFlipped(!isMarginFlipped)}
                className={cn(
                  "p-3 rounded-lg border transition-all cursor-pointer group relative overflow-hidden select-none text-left",
                  isMarginFlipped && "ring-2 ring-indigo-500/50 shadow-lg shadow-indigo-500/10",
                  isMarginExceeded 
                    ? "bg-rose-950/30 border-rose-500/40 hover:border-rose-400" 
                    : "bg-dark-800 border-indigo-500/20 hover:border-indigo-500/40 hover:bg-dark-750"
                )}
                title="Click to view detailed FYERS Charges & Margin Breakdown"
              >
                <div className="flex items-center justify-between gap-1 mb-0.5">
                  <span className="text-[10px] text-slate-400 font-medium truncate">
                    {effectiveProductType === 'MIS' ? 'Required Margin (5x)' : 'Required Capital (1x)'}
                  </span>
                  <span className="text-[8.5px] px-1 py-0.2 rounded bg-indigo-500/20 text-indigo-300 font-bold border border-indigo-500/30">
                    {isMarginFlipped ? 'FLIPPED ↩️' : 'FYERS ⚡'}
                  </span>
                </div>

                <span className={cn(
                  "font-bold font-mono text-base block mt-0.5",
                  isMarginExceeded ? "text-rose-300" : "text-indigo-200"
                )}>
                  ₹{marginRequired.toFixed(2)}
                </span>

                <span className={cn(
                  "text-[9px] font-mono block mt-1 truncate",
                  isMarginExceeded ? "text-rose-400 font-bold" : "text-slate-400"
                )}>
                  {isMarginExceeded 
                    ? `⚠️ Exceeds by ${formatINR(marginRequired - accountCapital)}` 
                    : `Base ₹${baseMargin.toFixed(0)} + Brok ₹${fyersBrokerage.toFixed(2)}`}
                </span>

                <div className="flex items-center justify-between text-[8px] text-indigo-300/80 mt-1 pt-1 border-t border-white/5">
                  <span>Exposure: ₹{totalInvestment.toLocaleString('en-IN')}</span>
                  <span className="text-cyan-400 font-semibold group-hover:underline">
                    {isMarginFlipped ? 'Hide ✕' : 'Charges 🔍'}
                  </span>
                </div>
              </div>

              {/* Tile 2: Max Risk (SL) */}
              <div className="p-3 rounded-lg bg-dark-800 border border-rose-500/20">
                <span className="text-[10px] text-rose-400 block font-medium">
                  {isNetMode ? 'Net Max Loss at SL' : 'Max Loss at SL (1.0R)'}
                </span>
                <span className="font-bold font-mono text-rose-300 text-base block mt-0.5">
                  -{formatINR(totalRiskINR)}
                </span>
                <span className="text-[9px] text-rose-400/80 block mt-1 font-mono">
                  SL: ₹{stopLossPrice.toFixed(2)}
                </span>
                <span className="text-[8px] text-slate-500 block">
                  {isNetMode ? 'Incl. ~₹50 Friction Cushion' : 'Pure 1.0R Risk (No Taxes)'}
                </span>
              </div>

              {/* Tile 3: Profit at Target 1 */}
              <div className="p-3 rounded-lg bg-dark-800 border border-emerald-500/20">
                <span className="text-[10px] text-emerald-400 block font-medium">
                  {isNetMode ? 'Net Profit at T1 (1.5 RR)' : 'Profit at Target 1 (1.5 RR)'}
                </span>
                <span className="font-bold font-mono text-emerald-300 text-base block mt-0.5">
                  +{formatINR(target1ProfitINR)}
                </span>
                <span className="text-[9px] text-emerald-400/80 block mt-1 font-mono">
                  T1: ₹{target1Price.toFixed(2)}
                </span>
                <span className="text-[8px] text-slate-500 block">
                  {isNetMode ? 'Net of statutory costs (-₹50)' : 'Pure 1.5R Gain'}
                </span>
              </div>

              {/* Tile 4: Profit at Target 2 */}
              <div className="p-3 rounded-lg bg-dark-800 border border-emerald-500/30">
                <span className="text-[10px] text-emerald-400 block font-medium">
                  {isNetMode ? 'Net Profit at T2 (2.5 RR)' : 'Profit at Target 2 (2.5 RR)'}
                </span>
                <span className="font-bold font-mono text-emerald-300 text-base block mt-0.5">
                  +{formatINR(target2ProfitINR)}
                </span>
                <span className="text-[9px] text-emerald-400/80 block mt-1 font-mono">
                  T2: ₹{target2Price.toFixed(2)}
                </span>
                <span className="text-[8px] text-slate-500 block">
                  {isNetMode ? 'Net of statutory costs (-₹50)' : 'Pure 2.5R Gain'}
                </span>
              </div>
            </div>

            {/* Interactive FYERS Charges & Margin Breakdown Panel (Smooth Expand on Flip) */}
            {isMarginFlipped && (
              <div className="p-4 bg-dark-900/90 border border-indigo-500/30 rounded-xl space-y-3 animate-fade-in shadow-xl">
                <div className="flex items-center justify-between border-b border-white/10 pb-2">
                  <div className="flex items-center gap-2">
                    <span className="p-1 rounded bg-indigo-500/20 text-indigo-400">
                      <Receipt className="w-3.5 h-3.5" />
                    </span>
                    <div>
                      <h4 className="text-xs font-bold text-white flex items-center gap-2">
                        <span>FYERS Order Margin & Charges Breakdown</span>
                        <span className="text-[9.5px] px-1.5 py-0.2 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 font-mono font-bold">
                          {stock.symbol} ({shareQty} Qty @ ₹{entryPrice.toFixed(2)})
                        </span>
                      </h4>
                      <p className="text-[10px] text-slate-400">Exact calculation matching FYERS Live RMS & Contract Note</p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setIsMarginFlipped(false)}
                    className="text-[10px] px-2 py-0.5 rounded bg-dark-750 hover:bg-dark-700 text-slate-400 hover:text-white border border-white/10 transition-colors cursor-pointer"
                  >
                    Close ✕
                  </button>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                  {/* Left Column: Upfront Required Margin (Order Placement) */}
                  <div className="p-3 rounded-lg bg-dark-800/80 border border-white/5 space-y-2">
                    <span className="text-[10px] font-bold text-indigo-300 uppercase tracking-wider block">
                      1. Upfront Required Margin (Order Box)
                    </span>
                    <div className="space-y-1.5 text-[11px] font-mono">
                      <div className="flex justify-between items-center text-slate-300">
                        <span>Total Trade Turnover:</span>
                        <span className="text-white font-semibold">₹{totalInvestment.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                      </div>
                      <div className="flex justify-between items-center text-slate-300">
                        <span>Pure 5x Margin ({effectiveProductType === 'MIS' ? '20%' : '100%'}):</span>
                        <span className="text-white font-semibold">₹{baseMargin.toFixed(2)}</span>
                      </div>
                      <div className="flex justify-between items-center text-slate-300">
                        <span>Fyers Brokerage ({isMis ? '0.03% max ₹20' : 'Free CNC'}):</span>
                        <span className="text-amber-300 font-semibold">+₹{fyersBrokerage.toFixed(2)}</span>
                      </div>
                      <div className="pt-1.5 border-t border-white/10 flex justify-between items-center text-indigo-200 font-bold">
                        <span>Req Margin Blocked:</span>
                        <span className="text-sm text-indigo-300 font-bold">₹{marginRequired.toFixed(2)}</span>
                      </div>
                    </div>
                    <p className="text-[9px] text-slate-400 italic">
                      *FYERS blocks pure margin + brokerage upfront to prevent negative ledger balance upon execution.
                    </p>
                  </div>

                  {/* Right Column: Other Statutory Levies & EOD Settlement */}
                  <div className="p-3 rounded-lg bg-dark-800/80 border border-white/5 space-y-2">
                    <div className="flex justify-between items-center">
                      <span className="text-[10px] font-bold text-cyan-300 uppercase tracking-wider block">
                        2. Other Charges (EOD Contract Note)
                      </span>
                      <span className="text-[10px] font-mono text-cyan-400 font-bold">
                        ₹{totalStatutoryCharges.toFixed(2)}
                      </span>
                    </div>
                    <div className="space-y-1 text-[10.5px] font-mono">
                      <div className="flex justify-between items-center text-slate-400">
                        <span>NSE Exchange & Clearing (0.00307%):</span>
                        <span className="text-slate-200">₹{exchTxnCharge.toFixed(2)}</span>
                      </div>
                      <div className="flex justify-between items-center text-slate-400">
                        <span>CTT / STT (0% on Intraday Buy):</span>
                        <span className="text-slate-200">₹{sttFee.toFixed(2)}</span>
                      </div>
                      <div className="flex justify-between items-center text-slate-400">
                        <span>GST (18% on Brokerage & Exch):</span>
                        <span className="text-slate-200">₹{gstFee.toFixed(2)}</span>
                      </div>
                      <div className="flex justify-between items-center text-slate-400">
                        <span>Stamp Duty (0.003% on Buy):</span>
                        <span className="text-slate-200">₹{stampDuty.toFixed(2)}</span>
                      </div>
                      <div className="flex justify-between items-center text-slate-400">
                        <span>SEBI Turnover Fee (₹10/Cr):</span>
                        <span className="text-slate-200">₹{sebiFee.toFixed(2)}</span>
                      </div>
                      <div className="pt-1 border-t border-white/10 flex justify-between items-center text-emerald-300 font-bold">
                        <span>Total Transaction Charges:</span>
                        <span>₹{totalFyersCharges.toFixed(2)}</span>
                      </div>
                      <div className="flex justify-between items-center text-slate-300 font-semibold text-[10px] pt-0.5">
                        <span>Total EOD Debit (Margin + Charges):</span>
                        <span className="text-white font-bold">₹{totalEodDebit.toFixed(2)}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Custom Target Reactive Calculation Tile */}
            {hasCustomTarget && (
              <div className="p-3 bg-purple-950/30 border border-purple-500/40 rounded-xl flex flex-wrap items-center justify-between gap-3 text-xs animate-fade-in shadow-lg">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded bg-purple-500/30 text-purple-200 font-bold text-xs font-mono border border-purple-500/50">
                    🎯 CUSTOM TARGET: ₹{customTgtNum}
                  </span>
                  <span className="text-slate-400">
                    Distance from Entry: <span className="font-mono text-purple-200 font-bold">{customDiff >= 0 ? `+₹${customDiff.toFixed(2)}` : `-₹${Math.abs(customDiff).toFixed(2)}`}</span>
                  </span>
                </div>

                <div className="flex items-center gap-4 font-mono">
                  <div>
                    <span className="text-slate-400 text-[10px] block">
                      {isNetMode ? 'Net Profit at Custom Target:' : 'Gross Profit at Custom Target:'}
                    </span>
                    <span className={cn("font-bold text-sm", customProfitINR >= 0 ? "text-emerald-400" : "text-rose-400")}>
                      {customProfitINR >= 0 ? `+${formatINR(customProfitINR)}` : `-${formatINR(Math.abs(customProfitINR))}`}
                      <span className="text-xs ml-1 font-semibold text-slate-300">({customReturnPct >= 0 ? `+${customReturnPct.toFixed(2)}%` : `${customReturnPct.toFixed(2)}%`})</span>
                    </span>
                  </div>

                  <div className="border-l border-white/10 pl-3">
                    <span className="text-slate-400 text-[10px] block">Risk-Reward Ratio:</span>
                    <span className="font-bold text-sm text-cyan-300">
                      1:{customRR} RR
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Direction & Intraday 3:15 PM Square-off Safety Banner */}
            <div className={cn(
              "p-2.5 rounded-lg border text-xs flex items-center justify-between gap-3",
              isBullish 
                ? "bg-dark-800/80 border-emerald-500/20 text-slate-300"
                : "bg-rose-950/30 border-rose-500/30 text-rose-200"
            )}>
              <div className="flex items-center gap-2">
                <Clock className={cn("w-4 h-4 shrink-0", isBullish ? "text-amber-400" : "text-rose-400")} />
                <span>
                  {isBullish ? (
                    <><strong>Long Trade (Buy MIS):</strong> Zerodha Intraday orders auto-square off around 3:15 PM. Close trade manually before cutoff to avoid ₹50+GST broker penalty.</>
                  ) : (
                    <><strong>Short Sell (Sell MIS):</strong> Shares borrowed for intraday breakdown. Must be squared-off before 3:15 PM. Overnight holding is strictly disabled in Cash equity.</>
                  )}
                </span>
              </div>
              <span className="shrink-0 font-mono text-[10px] text-slate-400 hidden sm:inline">
                SEBI Intraday Rules
              </span>
            </div>
          </div>

        </div>

      </div>
    </div>
  );
};
