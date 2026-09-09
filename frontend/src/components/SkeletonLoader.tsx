"use client";

import React from 'react';

export const SkeletonLoader: React.FC = () => {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {[1, 2, 3, 4, 5, 6].map((i) => (
        <div key={i} className="glass-panel rounded-xl p-4 border border-white/5 space-y-4 animate-pulse">
          <div className="flex justify-between items-start">
            <div className="space-y-2">
              <div className="h-5 w-24 bg-dark-750 rounded" />
              <div className="h-3 w-36 bg-dark-800 rounded" />
            </div>
            <div className="h-6 w-28 bg-dark-750 rounded-full" />
          </div>

          <div className="flex justify-between py-2 border-y border-white/5">
            <div className="h-8 w-28 bg-dark-750 rounded" />
            <div className="h-6 w-16 bg-dark-750 rounded" />
          </div>

          <div className="grid grid-cols-3 gap-2">
            <div className="h-10 bg-dark-800 rounded" />
            <div className="h-10 bg-dark-800 rounded" />
            <div className="h-10 bg-dark-800 rounded" />
          </div>

          <div className="h-20 bg-dark-800 rounded-lg" />

          <div className="flex justify-between items-center pt-2 border-t border-white/5">
            <div className="h-3 w-32 bg-dark-800 rounded" />
            <div className="h-8 w-24 bg-dark-750 rounded" />
          </div>
        </div>
      ))}
    </div>
  );
};
