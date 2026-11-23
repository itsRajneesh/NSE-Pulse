"use client";

import React, { useState, useRef, useEffect } from "react";
import { Info, X } from "lucide-react";
import { cn } from "@/lib/utils";

export interface MarketPulseTooltipProps {
  title: string;
  meaning: string;
  rule?: string;
  formula?: string;
  align?: "left" | "right" | "center";
  className?: string;
}

export const MarketPulseTooltip: React.FC<MarketPulseTooltipProps> = ({
  title,
  meaning,
  rule,
  formula,
  align = "left",
  className,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close on click outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    }
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen]);

  // Position alignment styling
  const alignClasses = {
    left: "left-0",
    right: "right-0",
    center: "left-1/2 -translate-x-1/2",
  }[align];

  return (
    <div
      ref={containerRef}
      className={cn("relative inline-flex items-center", className)}
      onMouseEnter={() => setIsOpen(true)}
      onMouseLeave={() => setIsOpen(false)}
    >
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setIsOpen((prev) => !prev);
        }}
        aria-label={`Info: ${title}`}
        className="p-0.5 rounded text-slate-400 hover:text-cyan-400 hover:bg-cyan-950/40 focus:outline-none focus:ring-1 focus:ring-cyan-500/40 transition-colors"
      >
        <Info className="w-3.5 h-3.5" />
      </button>

      {/* Floating Tooltip Card */}
      {isOpen && (
        <div
          className={cn(
            "absolute top-full mt-1.5 z-[60] w-72 sm:w-80 p-3 rounded-xl",
            "bg-dark-900/98 backdrop-blur-md border border-cyan-500/30 shadow-[0_10px_30px_rgba(0,0,0,0.8)]",
            "text-xs space-y-2 pointer-events-auto animate-in fade-in zoom-in-95 duration-150 select-text",
            alignClasses
          )}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-start justify-between gap-2 pb-1.5 border-b border-white/10">
            <span className="font-bold text-white tracking-tight flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 shrink-0" />
              {title}
            </span>
            <button
              type="button"
              onClick={() => setIsOpen(false)}
              className="sm:hidden text-slate-400 hover:text-white p-0.5"
            >
              <X className="w-3 h-3" />
            </button>
          </div>

          {/* Formula badge if provided */}
          {formula && (
            <div className="font-mono text-[10px] text-cyan-300 bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-500/20 w-fit">
              {formula}
            </div>
          )}

          {/* Hinglish Meaning */}
          <p className="text-slate-300 text-[11px] leading-relaxed">
            <strong className="text-cyan-300 font-semibold">Matlab: </strong>
            {meaning}
          </p>

          {/* Trading Rule if provided */}
          {rule && (
            <div className="p-2 rounded-lg bg-black/50 border border-amber-500/20 text-[10.5px] text-amber-200/95 leading-snug">
              <strong className="text-amber-400 font-semibold block mb-0.5">
                Trading Rule (Kab kya karein):
              </strong>
              {rule}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
