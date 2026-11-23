import {
  V13Confirmation,
  V13Indicators,
  V13Risk,
  V13ScanResponse,
  V13Signal,
  V13UniverseStock,
} from '@/types/screener';

type V13ApiSignal = {
  symbol: string;
  name: string;
  sector: string;
  signal_type: string;
  setup_type: string;
  action: string;
  grade?: string | null;
  score: number;
  ltp: number | null;
  entry_price: number | null;
  stop_loss: number | null;
  target_1: number | null;
  target_2: number | null;
  risk_amount: number | null;
  risk_reward_t1: string | null;
  risk_reward_t2: string | null;
  ema20: number | null;
  rsi14: number | null;
  rel_vol: number | null;
  vwap: number | null;
  atr14: number | null;
  true_velocity: number | null;
  opening_range_high: number | null;
  opening_range_low: number | null;
  previous_day_high: number | null;
  previous_day_low: number | null;
  breakout_distance_atr: number | null;
  breakout_candle_range: number | null;
  reasons: string[];
  penalties: string[];
  score_breakdown?: V13Signal['score_breakdown'];
  conviction?: V13Signal['conviction'];
  t1_progress_pct?: number;
  execution_status?: string;
  signal_time: string;
  is_nifty500?: boolean;
  market_cap_cr?: number;
};

type V13ApiUniverseStock = {
  symbol: string;
  name: string;
  sector: string;
  status: string;
  signals: V13ApiSignal[];
  snapshot: V13UniverseStock['snapshot'];
  is_nifty500?: boolean;
  market_cap_cr?: number;
};

type V13ApiResponse = {
  market_status: V13ScanResponse['market_status'];
  market_status_details?: V13ScanResponse['market_status_details'];
  market_regime: V13ScanResponse['market_regime'];
  generated_at: string;
  bullish: V13ApiSignal[];
  bearish: V13ApiSignal[];
  watchlist: V13ApiSignal[];
  trade_ready: V13ApiSignal[];
  diagnostic_signals?: V13ApiSignal[];
  universe: V13ApiUniverseStock[];
  is_scanning?: boolean;
};

const normalizeStage = (action: string): V13Signal['stage'] => {
  const value = action.toUpperCase();

  if (value === 'TRADE_READY' || value === 'TRADE-READY') {
    return 'TRADE_READY';
  }

  if (value === 'CONFIRMED') {
    return 'CONFIRMED';
  }

  if (value === 'EARLY_TRIGGER') {
    return 'EARLY_TRIGGER';
  }

  if (value === 'BELOW_THRESHOLD' || value === 'BELOW-THRESHOLD') {
    return 'BELOW_THRESHOLD';
  }

  return 'WATCH';
};

const getClassification = (score: number, exec_status?: string): V13Signal['score_classification'] => {
  if (score < 72) return 'BELOW THRESHOLD';
  if (exec_status === 'EARLY_TRIGGER') return 'EARLY TRIGGER';
  if (score >= 85) return 'HIGH CONFIDENCE';
  if (score >= 80) return 'STRONG';
  return 'WATCH';
};

export const normalizeV13Signal = (raw: V13ApiSignal): V13Signal => {
  const risk: V13Risk = {
    entry: raw.entry_price,
    stop_loss: raw.stop_loss,
    target_1: raw.target_1,
    target_2: raw.target_2,
    risk_amount: raw.risk_amount,
    risk_reward_t1: raw.risk_reward_t1,
    risk_reward_t2: raw.risk_reward_t2,
  };

  const indicators: V13Indicators = {
    ema20: raw.ema20,
    rsi14: raw.rsi14,
    rel_vol: raw.rel_vol,
    vwap: raw.vwap,
    atr14: raw.atr14,
    true_velocity: raw.true_velocity,
    breakout_distance_atr: raw.breakout_distance_atr,
    breakout_candle_range: raw.breakout_candle_range,
  };

  const confirmation: V13Confirmation = {
    opening_range_high: raw.opening_range_high,
    opening_range_low: raw.opening_range_low,
    previous_day_high: raw.previous_day_high,
    previous_day_low: raw.previous_day_low,
    reasons: raw.reasons ?? [],
    penalties: raw.penalties ?? [],
  };

  return {
    symbol: raw.symbol,
    name: raw.name,
    sector: raw.sector,
    direction: raw.signal_type.toUpperCase() as V13Signal['direction'],
    setup: raw.setup_type,
    stage: normalizeStage(raw.action),
    score: raw.score,
    score_classification: getClassification(raw.score, raw.execution_status),
    t1_progress_pct: raw.t1_progress_pct ?? 0,
    execution_status: raw.execution_status ?? 'FRESH_ENTRY',
    signal_time: raw.signal_time,
    market: {},
    price: raw.ltp,
    risk,
    indicators,
    confirmation,
    score_breakdown: raw.score_breakdown,
    conviction: raw.conviction,
    is_nifty500: raw.is_nifty500,
    market_cap_cr: raw.market_cap_cr,
  };
};

const normalizeUniverseStatus = (
  status: string,
): V13UniverseStock['status'] => {
  return status as V13UniverseStock['status'];
};

export const normalizeV13Response = (
  raw: V13ApiResponse,
): V13ScanResponse => ({
  market_status: raw.market_status,
  market_status_details: raw.market_status_details ?? null,
  market_regime: raw.market_regime,
  generated_at: raw.generated_at,
  bullish: raw.bullish.map(normalizeV13Signal),
  bearish: raw.bearish.map(normalizeV13Signal),
  watchlist: raw.watchlist.map(normalizeV13Signal),
  trade_ready: raw.trade_ready.map(normalizeV13Signal),
  diagnostic_signals: (raw.diagnostic_signals ?? []).map(normalizeV13Signal),
  universe: raw.universe.map((stock) => ({
    symbol: stock.symbol,
    name: stock.name,
    sector: stock.sector,
    status: normalizeUniverseStatus(stock.status),
    signals: stock.signals.map(normalizeV13Signal),
    snapshot: stock.snapshot,
    is_nifty500: stock.is_nifty500,
    market_cap_cr: stock.market_cap_cr,
  })),
  is_scanning: Boolean(raw.is_scanning),
});
