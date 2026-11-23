"use client";

import React from "react";
import {
  TrendingUp,
  TrendingDown,
  Target,
  ShieldAlert,
  Clock3,
  BarChart3,
} from "lucide-react";
import { PaperTradingResponse, PaperTrade } from "@/types/screener";
import { cn } from "@/lib/utils";

interface PaperTradingPanelProps {
  data: PaperTradingResponse | null;
  loading?: boolean;
}

const formatPrice = (value: number | null | undefined) => {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }

  return `₹${value.toFixed(2)}`;
};

const formatR = (value: number) => {
  if (value > 0) return `+${value.toFixed(2)}R`;
  return `${value.toFixed(2)}R`;
};

const formatSignalTime = (value: string) => {
  if (!value) return "-";

  return value
    .replace(" IST", "")
    .replace(", ", " • ");
};

const TradeRow: React.FC<{ trade: PaperTrade }> = ({ trade }) => {
  const isBullish = trade.direction === "BULLISH";
  const isOpen = trade.status === "OPEN";
  const isWin =
    trade.outcome === "T1_FIRST" || trade.outcome === "T2_FIRST";
  const isLoss = trade.outcome === "SL_FIRST";

  return (
    <div className="rounded-xl border border-white/5 bg-dark-850/70 p-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        {/* Stock */}
        <div className="min-w-0 lg:w-[180px]">
          <div className="flex items-center gap-2">
            {isBullish ? (
              <TrendingUp className="h-4 w-4 text-emerald-400" />
            ) : (
              <TrendingDown className="h-4 w-4 text-rose-400" />
            )}

            <span className="font-bold text-white">{trade.symbol}</span>

            <span
              className={cn(
                "rounded px-1.5 py-0.5 text-[9px] font-bold",
                isBullish
                  ? "bg-emerald-500/10 text-emerald-300"
                  : "bg-rose-500/10 text-rose-300"
              )}
            >
              {trade.direction}
            </span>
          </div>

          <div className="mt-1 truncate text-[10px] text-slate-500">
            {trade.name}
          </div>
        </div>

        {/* Score */}
        <div className="lg:w-[90px]">
          <div className="text-[9px] uppercase tracking-wide text-slate-500">
            Setup Score
          </div>
          <div
            className={cn(
              "font-mono text-lg font-black",
              trade.score >= 70
                ? "text-emerald-300"
                : "text-slate-300"
            )}
          >
            {trade.score.toFixed(0)}
          </div>
        </div>

        {/* Volume */}
        <div className="lg:w-[90px]">
          <div className="text-[9px] uppercase tracking-wide text-slate-500">
            RelVol
          </div>
          <div className="font-mono text-sm font-bold text-amber-300">
            {trade.rel_vol.toFixed(2)}x
          </div>
        </div>

        {/* Entry / SL */}
        <div className="grid grid-cols-2 gap-3 lg:w-[190px]">
          <div>
            <div className="text-[9px] uppercase tracking-wide text-slate-500">
              Entry
            </div>
            <div className="font-mono text-sm font-bold text-cyan-300">
              {formatPrice(trade.entry_price)}
            </div>
          </div>

          <div>
            <div className="text-[9px] uppercase tracking-wide text-slate-500">
              Stop Loss
            </div>
            <div className="font-mono text-sm font-bold text-rose-300">
              {formatPrice(trade.stop_loss)}
            </div>
          </div>
        </div>

        {/* Targets */}
        <div className="grid grid-cols-2 gap-3 lg:w-[190px]">
          <div>
            <div className="flex items-center gap-1 text-[9px] uppercase tracking-wide text-slate-500">
              <Target className="h-3 w-3 text-emerald-400" />
              T1
            </div>
            <div className="font-mono text-sm font-bold text-emerald-300">
              {formatPrice(trade.target_1)}
            </div>
          </div>

          <div>
            <div className="flex items-center gap-1 text-[9px] uppercase tracking-wide text-slate-500">
              <Target className="h-3 w-3 text-emerald-400" />
              T2
            </div>
            <div className="font-mono text-sm font-bold text-emerald-300">
              {formatPrice(trade.target_2)}
            </div>
          </div>
        </div>

        {/* Status */}
        <div className="lg:w-[120px]">
          <div className="text-[9px] uppercase tracking-wide text-slate-500">
            Status
          </div>

          <span
            className={cn(
              "mt-1 inline-flex rounded-full border px-2 py-1 text-[9px] font-bold",
              isOpen &&
                "border-amber-500/30 bg-amber-500/10 text-amber-300",
              isWin &&
                "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
              isLoss &&
                "border-rose-500/30 bg-rose-500/10 text-rose-300",
              !isOpen &&
                !isWin &&
                !isLoss &&
                "border-white/10 bg-dark-700 text-slate-400"
            )}
          >
            {isOpen
              ? "OPEN"
              : isWin
              ? trade.outcome === "T2_FIRST"
                ? "T2 HIT"
                : "T1 HIT"
              : isLoss
              ? "STOP LOSS"
              : trade.outcome || trade.status}
          </span>
        </div>

        {/* Result */}
        <div className="text-left lg:w-[90px] lg:text-right">
          <div className="text-[9px] uppercase tracking-wide text-slate-500">
            Result
          </div>

          <div
            className={cn(
              "font-mono text-sm font-black",
              trade.outcome === "T1_FIRST" ||
                trade.outcome === "T2_FIRST"
                ? "text-emerald-300"
                : trade.outcome === "SL_FIRST"
                ? "text-rose-300"
                : "text-slate-500"
            )}
          >
            {isOpen || trade.realized_r === null
              ? "-"
              : formatR(trade.realized_r)}
          </div>
        </div>
      </div>

      {/* Signal metadata */}
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-white/5 pt-2 text-[9px] text-slate-500">
        <span className="flex items-center gap-1">
          <Clock3 className="h-3 w-3" />
          {formatSignalTime(trade.signal_time)}
        </span>

        <span>{trade.setup_type}</span>

        <span>VWAP {formatPrice(trade.vwap)}</span>

        <span>RSI {trade.rsi14.toFixed(1)}</span>

        <span>ATR {formatPrice(trade.atr14)}</span>
      </div>
    </div>
  );
};

export const PaperTradingPanel: React.FC<PaperTradingPanelProps> = ({
  data,
  loading = false,
}) => {
  if (loading && !data) {
    return (
      <section className="glass-panel rounded-2xl border border-white/5 p-5">
        <div className="animate-pulse space-y-4">
          <div className="h-6 w-56 rounded bg-dark-700" />
          <div className="h-20 rounded-xl bg-dark-800" />
          <div className="h-16 rounded-xl bg-dark-800" />
        </div>
      </section>
    );
  }

  if (!data) {
    return null;
  }

  return (
    <section className="glass-panel rounded-2xl border border-indigo-500/20 p-5">
      {/* Header */}
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5 text-indigo-400" />

            <h2 className="text-lg font-black text-white">
              V12 Paper Trading
            </h2>

            <span className="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2 py-0.5 text-[9px] font-bold text-indigo-300">
              SHADOW MODE
            </span>
          </div>

          <p className="mt-1 text-xs text-slate-500">
            V12 candidate: Bullish developing breakout • Score 70–74 •
            12:00–14:00
          </p>
        </div>

        <div className="flex items-center gap-2 text-[10px] text-slate-500">
          <ShieldAlert className="h-3.5 w-3.5 text-amber-400" />
          No real orders
        </div>
      </div>

      {/* Stats */}
      <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <div className="rounded-xl border border-white/5 bg-dark-850/70 p-3">
          <div className="text-[9px] uppercase text-slate-500">
            Total Signals
          </div>
          <div className="mt-1 font-mono text-xl font-black text-white">
            {data.total_trades}
          </div>
        </div>

        <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-3">
          <div className="text-[9px] uppercase text-slate-500">
            Open
          </div>
          <div className="mt-1 font-mono text-xl font-black text-amber-300">
            {data.open_trades}
          </div>
        </div>

        <div className="rounded-xl border border-white/5 bg-dark-850/70 p-3">
          <div className="text-[9px] uppercase text-slate-500">
            Closed
          </div>
          <div className="mt-1 font-mono text-xl font-black text-slate-200">
            {data.closed_trades}
          </div>
        </div>

        <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3">
          <div className="text-[9px] uppercase text-slate-500">
            Wins
          </div>
          <div className="mt-1 font-mono text-xl font-black text-emerald-300">
            {data.wins}
          </div>
        </div>

        <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-3">
          <div className="text-[9px] uppercase text-slate-500">
            Losses
          </div>
          <div className="mt-1 font-mono text-xl font-black text-rose-300">
            {data.losses}
          </div>
        </div>

        <div
          className={cn(
            "rounded-xl border p-3",
            data.total_realized_r >= 0
              ? "border-emerald-500/20 bg-emerald-500/5"
              : "border-rose-500/20 bg-rose-500/5"
          )}
        >
          <div className="text-[9px] uppercase text-slate-500">
            Realized R
          </div>
          <div
            className={cn(
              "mt-1 font-mono text-xl font-black",
              data.total_realized_r >= 0
                ? "text-emerald-300"
                : "text-rose-300"
            )}
          >
            {formatR(data.total_realized_r)}
          </div>
        </div>
      </div>

      {/* Empty state */}
      {data.trades.length === 0 ? (
        <div className="mt-5 rounded-xl border border-dashed border-white/10 bg-dark-850/50 px-5 py-8 text-center">
          <BarChart3 className="mx-auto h-8 w-8 text-slate-600" />

          <div className="mt-3 text-sm font-semibold text-slate-300">
            No V12 paper signals yet
          </div>

          <p className="mt-1 text-xs text-slate-500">
            Qualifying signals will appear automatically when the V12
            conditions are met.
          </p>
        </div>
      ) : (
        <div className="mt-5 space-y-2">
          {data.trades.map((trade) => (
            <TradeRow key={trade.signal_id} trade={trade} />
          ))}
        </div>
      )}
    </section>
  );
};