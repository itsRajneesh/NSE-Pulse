export type SignalType = 'BULLISH' | 'BEARISH' | 'NEUTRAL';

export interface Candle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TechnicalIndicators {
  ema20: number;
  rsi14: number;
  rel_vol: number;
  current_vol: number;
  avg_vol_10d: number;
  price_change_pct: number;
  day_high: number;
  day_low: number;
  last_candle_high: number;
  last_candle_low: number;
}

export interface TradeParameters {
  entry_price: number;
  stop_loss: number;
  risk_amount: number;
  target_1: number;
  target_2: number;
  risk_reward_ratio_t1: string;
  risk_reward_ratio_t2: string;
}

export interface StockSignal {
  symbol: string;
  name: string;
  sector: string;
  ltp: number;
  price_change_pct: number;
  signal_type: SignalType;
  signal_reason: string[];
  is_active_signal: boolean;
  rel_vol: number;
  trade_params: TradeParameters | null;
  indicators: TechnicalIndicators;
  last_updated: string;
}

export interface MarketStatus {
  is_open: boolean;
  session_message: string;
  market_time_ist: string;
  mode: 'live' | 'simulation';
}

export interface ScreenerResponse {
  total_scanned: number;
  active_signals_count: number;
  bullish_count: number;
  bearish_count: number;
  neutral_count: number;
  bullish_ratio: number;
  market_sentiment: string;
  market_status: MarketStatus;
  last_refreshed: string;
  stocks: StockSignal[];
}

export interface LinePoint {
  time: string;
  value: number;
}

export interface StockHistoryResponse {
  symbol: string;
  name: string;
  sector: string;
  timeframe: string;
  candles: Candle[];
  ema20_series: LinePoint[];
  rsi_series: LinePoint[];
  trade_params: TradeParameters | null;
  signal_type: SignalType;
}
