import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatINR(val: number): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  }).format(val);
}

export function formatNumber(val: number): string {
  return new Intl.NumberFormat('en-IN', {
    maximumFractionDigits: 2,
  }).format(val);
}

export function formatOptionSymbol(symbol?: string): string {
  if (!symbol) return '';
  const clean = symbol.replace(/^NSE:/i, '').trim();
  const match = clean.match(/^([A-Z]+)(\d{2}[A-Z0-9]{3})(\d{4,5})(CE|PE)$/i);
  if (match) {
    const [, index, expiry, strike, optType] = match;
    return `${index} ${expiry} ${strike} ${optType.toUpperCase()}`;
  }
  return clean;
}

export function formatOptionSymbolInText(text?: string): string {
  if (!text) return '';
  return text.replace(/(?:NSE:)?([A-Z]+)(\d{2}[A-Z0-9]{3})(\d{4,5})(CE|PE)/gi, (_m, index, expiry, strike, opt) => {
    return `${index} ${expiry} ${strike} ${opt.toUpperCase()}`;
  });
}

let sharedAudioCtx: AudioContext | null = null;

function getSharedAudioContext(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  if (!AudioCtx) return null;
  if (!sharedAudioCtx || sharedAudioCtx.state === 'closed') {
    sharedAudioCtx = new AudioCtx();
  }
  if (sharedAudioCtx.state === 'suspended') {
    sharedAudioCtx.resume().catch(() => {});
  }
  return sharedAudioCtx;
}

export function playSignalSound(type: 'BULLISH' | 'BEARISH') {
  try {
    const ctx = getSharedAudioContext();
    if (!ctx) return;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);

    if (type === 'BULLISH') {
      // Ascending chime
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(587.33, ctx.currentTime); // D5
      osc.frequency.exponentialRampToValueAtTime(880, ctx.currentTime + 0.15); // A5
      gain.gain.setValueAtTime(0.2, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
      osc.start();
      osc.stop(ctx.currentTime + 0.45);
    } else {
      // Descending warning chime
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(659.25, ctx.currentTime); // E5
      osc.frequency.exponentialRampToValueAtTime(440, ctx.currentTime + 0.2); // A4
      gain.gain.setValueAtTime(0.2, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
      osc.start();
      osc.stop(ctx.currentTime + 0.45);
    }
  } catch (e) {
    // AudioContext blocked by browser policy until user gesture
  }
}

export function speakSignalAlert(text: string) {
  try {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1.0;
      utterance.pitch = 1.0;
      utterance.volume = 1.0;
      utterance.lang = 'en-IN';
      window.speechSynthesis.speak(utterance);
    }
  } catch (e) {
    console.warn('Speech synthesis alert failed:', e);
  }
}

export function playAlphaSound(type: 'ENTRY' | 'T1_WIN' | 'SHIELD' | 'EXIT_WIN' | 'EXIT_LOSS') {
  try {
    const ctx = getSharedAudioContext();
    if (!ctx) return;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    const now = ctx.currentTime;

    if (type === 'ENTRY') {
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(698.46, now); // F5
      osc.frequency.exponentialRampToValueAtTime(1046.50, now + 0.18); // C6
      gain.gain.setValueAtTime(0.22, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.45);
      osc.start(now);
      osc.stop(now + 0.48);
    } else if (type === 'T1_WIN' || type === 'EXIT_WIN') {
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(523.25, now); // C5
      osc.frequency.setValueAtTime(659.25, now + 0.12); // E5
      osc.frequency.exponentialRampToValueAtTime(1046.50, now + 0.28); // C6
      gain.gain.setValueAtTime(0.24, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.55);
      osc.start(now);
      osc.stop(now + 0.58);
    } else if (type === 'SHIELD') {
      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, now); // A5
      gain.gain.setValueAtTime(0.18, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
      osc.start(now);
      osc.stop(now + 0.38);
    } else {
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(587.33, now); // D5
      osc.frequency.exponentialRampToValueAtTime(392.00, now + 0.22); // G4
      gain.gain.setValueAtTime(0.18, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.42);
      osc.start(now);
      osc.stop(now + 0.45);
    }
  } catch {
    // Ignore autoplay restrictions before first user gesture
  }
}

export function speakAlphaAlert(text: string) {
  try {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel(); // Bug #4 Fix: Always clear stuck queue first!
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1.02;
      utterance.pitch = 1.0;
      utterance.volume = 1.0;
      utterance.lang = 'en-IN';
      window.speechSynthesis.speak(utterance);
    }
  } catch {
    // Ignore speech synthesis errors
  }
}
