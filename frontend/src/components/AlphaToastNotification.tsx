"use client";

import React from "react";
import { createPortal } from "react-dom";

export type AlphaToastKind =
  | "ENTRY"
  | "SHIELD"
  | "T1"
  | "STAGE2"
  | "45M"
  | "EXIT_WIN"
  | "EXIT_LOSS"
  | "TEST";

export interface AlphaToastItem {
  id: string;
  kind: AlphaToastKind;
  title: string;
  contract: string;
  subtitle: string;
  metricsLine: string;
  timestamp: string;
}

interface AlphaToastNotificationProps {
  toasts: AlphaToastItem[];
  onDismiss: (id: string) => void;
  onSwitchToAlphaTab?: () => void;
  isAlphaTabActive?: boolean;
}

export default function AlphaToastNotification({
  toasts,
  onDismiss,
  onSwitchToAlphaTab,
  isAlphaTabActive = true,
}: AlphaToastNotificationProps) {
  if (typeof document === "undefined") return null;
  if (!toasts || toasts.length === 0) return null;

  const getBadgeStyles = (kind: AlphaToastKind) => {
    switch (kind) {
      case "ENTRY":
        return {
          border: "border-cyan-500/70",
          bg: "from-slate-950/95 via-cyan-950/90 to-slate-900/95",
          pill: "bg-cyan-500/20 text-cyan-300 border-cyan-500/40",
          icon: "⚡",
        };
      case "T1":
      case "EXIT_WIN":
        return {
          border: "border-emerald-500/70",
          bg: "from-slate-950/95 via-emerald-950/90 to-slate-900/95",
          pill: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
          icon: "🎯",
        };
      case "SHIELD":
      case "STAGE2":
      case "45M":
        return {
          border: "border-amber-500/70",
          bg: "from-slate-950/95 via-amber-950/90 to-slate-900/95",
          pill: "bg-amber-500/20 text-amber-300 border-amber-500/40",
          icon: "🛡️",
        };
      case "EXIT_LOSS":
        return {
          border: "border-rose-500/70",
          bg: "from-slate-950/95 via-rose-950/90 to-slate-900/95",
          pill: "bg-rose-500/20 text-rose-300 border-rose-500/40",
          icon: "🛑",
        };
      default:
        return {
          border: "border-indigo-500/70",
          bg: "from-slate-950/95 via-indigo-950/90 to-slate-900/95",
          pill: "bg-indigo-500/20 text-indigo-300 border-indigo-500/40",
          icon: "🔔",
        };
    }
  };

  return createPortal(
    <div className="fixed top-20 right-5 z-[100] flex flex-col gap-3 max-w-md w-full pointer-events-none">
      {toasts.map((t) => {
        const st = getBadgeStyles(t.kind);
        return (
          <div
            key={t.id}
            className={`pointer-events-auto rounded-xl border ${st.border} bg-gradient-to-br ${st.bg} p-4 shadow-2xl backdrop-blur-md transition-all duration-300`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="text-lg">{st.icon}</span>
                <span
                  className={`text-[11px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border ${st.pill}`}
                >
                  {t.title}
                </span>
                <span className="text-[11px] text-slate-400 font-mono">{t.timestamp}</span>
              </div>
              <button
                onClick={() => onDismiss(t.id)}
                className="text-slate-400 hover:text-white text-xs px-1.5 py-0.5 rounded hover:bg-slate-800/60"
                title="Dismiss Alert"
              >
                ✕
              </button>
            </div>

            <div className="mt-2">
              <div className="text-sm font-bold text-white font-mono">{t.contract}</div>
              <div className="text-xs text-slate-200 mt-0.5">{t.subtitle}</div>
              <div className="text-xs font-mono text-cyan-300 mt-1.5 bg-slate-900/70 px-2.5 py-1.5 rounded border border-slate-800">
                {t.metricsLine}
              </div>
            </div>

            {!isAlphaTabActive && onSwitchToAlphaTab && (
              <div className="mt-2.5 flex justify-end">
                <button
                  onClick={() => {
                    onSwitchToAlphaTab();
                    onDismiss(t.id);
                  }}
                  className="text-xs font-semibold text-cyan-300 hover:text-cyan-200 bg-cyan-950/60 hover:bg-cyan-900/70 border border-cyan-500/40 px-2.5 py-1 rounded transition-colors"
                >
                  Open ⚡ Alpha Terminal →
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>,
    document.body
  );
}
