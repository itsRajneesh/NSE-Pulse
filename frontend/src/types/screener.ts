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
  is_holiday?: boolean;
  holiday_name?: string | null;
  next_holiday_notice?: string | null;
  next_trading_session?: string | null;
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

export interface PaperTrade {
  signal_id: string;
  scan_time: string;
  signal_time: string;
  symbol: string;
  name: string;
  sector: string;
  direction: string;
  setup_type: string;
  score: number;
  ltp: number;
  entry_price: number;
  stop_loss: number;
  target_1: number;
  target_2: number;
  risk_amount: number;
  risk_reward_t1: string;
  risk_reward_t2: string;
  ema20: number;
  rsi14: number;
  rel_vol: number;
  vwap: number;
  atr14: number;
  opening_range_high: number;
  opening_range_low: number;
  previous_day_high: number;
  previous_day_low: number;
  reasons: string[];
  status: string;
  outcome: string;
  outcome_price: number | null;
  outcome_time: string | null;
  realized_r: number | null;
}

export interface PaperTradingResponse {
  mode: 'PAPER_TRADING';
  real_orders: false;
  total_trades: number;
  open_trades: number;
  closed_trades: number;
  wins: number;
  losses: number;
  total_realized_r: number;
  trades: PaperTrade[];
}

export type V13Direction = 'BULLISH' | 'BEARISH';
export type V13Stage = 'WATCH' | 'CONFIRMED' | 'TRADE_READY';
export type V13UniverseStatus = 'SIGNAL' | 'DIAGNOSTIC' | 'NO_SETUP' | 'INVALID' | 'ENGINE_ERROR';

export interface V13Risk {
  entry: number | null;
  stop_loss: number | null;
  target_1: number | null;
  target_2: number | null;
  risk_amount: number | null;
  risk_reward_t1: string | null;
  risk_reward_t2: string | null;
}

export interface V13Indicators {
  ema20: number | null;
  rsi14: number | null;
  rel_vol: number | null;
  vwap: number | null;
  atr14: number | null;
  true_velocity: number | null;
  breakout_distance_atr: number | null;
  breakout_candle_range: number | null;
}

export interface V13Confirmation {
  opening_range_high: number | null;
  opening_range_low: number | null;
  previous_day_high: number | null;
  previous_day_low: number | null;
  reasons: string[];
  penalties: string[];
}

export interface V13ScoreBreakdown {
  trend_structure?: number;
  ema_alignment?: number;
  vwap_alignment?: number;
  rsi_momentum?: number;
  volume?: number;
  opening_range?: number;
  previous_day_level?: number;
  candle_quality?: number;
  market_sector_alignment?: number;
  true_velocity?: number;
  extension_chase?: number;
  trade_risk_penalties?: number;
  [key: string]: number | undefined;
}

export interface V13Signal {
  symbol: string;
  name: string;
  sector: string;
  direction: V13Direction;
  setup: string;
  setup_type?: string;
  stage: V13Stage | 'BELOW_THRESHOLD' | 'EARLY_TRIGGER';
  score: number;
  score_classification?: 'BELOW THRESHOLD' | 'EARLY TRIGGER' | 'WATCH' | 'STRONG' | 'HIGH CONFIDENCE';
  t1_progress_pct?: number;
  execution_status?: string;
  signal_time: string;
  market: Record<string, unknown>;
  price: number | null;
  risk: V13Risk;
  indicators: V13Indicators;
  confirmation: V13Confirmation;
  score_breakdown?: V13ScoreBreakdown;
  conviction?: V13Conviction;
  is_nifty500?: boolean;
  market_cap_cr?: number;
}

export interface V13ConvictionPillar {
  points: number;
  icon: string;
  desc: string;
}

export interface V13Conviction {
  enabled: boolean;
  total_score: number;
  max_score: number;
  grade: 'GRADE_A_PLUS' | 'GRADE_B' | 'GRADE_C';
  badge_header: string;
  directive: string;
  pillar_1: V13ConvictionPillar;
  pillar_2: V13ConvictionPillar;
  pillar_3: V13ConvictionPillar;
}

export interface V13MarketContext {
  nifty_direction: V13Direction | 'NEUTRAL';
  nifty_close: number | null;
  nifty_atr_pct: number | null;
  nifty_bar_range_pct: number | null;
  nifty_range_expansion: number | null;
  nifty_slope5: number | null;
  nifty_slope12: number | null;
  nifty_extension_atr: number | null;
  signal_time: string | null;
  bars_used: number | null;
}

export interface V13StockSnapshot {
  price: number | null;
  ema20: number | null;
  rsi14: number | null;
  rel_vol: number | null;
  vwap: number | null;
  atr14: number | null;
  true_velocity: number | null;
  latest_session_change_pct: number | null;
  high?: number | null;
  low?: number | null;
  open?: number | null;
  volume?: number | null;
  opening_range_high?: number | null;
  opening_range_low?: number | null;
}

export interface V13UniverseStock {
  symbol: string;
  name: string;
  sector: string;
  status: V13UniverseStatus;
  signals: V13Signal[];
  snapshot: V13StockSnapshot;
  is_nifty500?: boolean;
  market_cap_cr?: number;
}

export type V13ChartTarget = V13Signal | V13UniverseStock;

export interface V13ScanResponse {
  market_status: 'LIVE' | 'CLOSED' | null;
  market_status_details?: MarketStatus | null;
  market_regime: string | null;
  generated_at: string;
  bullish: V13Signal[];
  bearish: V13Signal[];
  watchlist: V13Signal[];
  trade_ready: V13Signal[];
  diagnostic_signals?: V13Signal[];
  universe: V13UniverseStock[];
  is_scanning?: boolean;
}

export interface LiveMoverTradePlan {
  entry: number;
  stop_loss: number;
  target_1: number;
  target_2: number;
  risk_amount: number;
  risk_reward_t1: string;
  risk_reward_t2: string;
  plan_type: string;
  live_risk?: number;
}

export interface LiveMoverItem {
  symbol: string;
  name: string;
  sector: string;
  rank: number;
  nse_rank?: number;
  price: number;
  change_pct: number;
  volume: number;
  turnover_cr: number;
  rel_vol: number;
  ema20: number | null;
  vwap: number | null;
  atr14: number | null;
  rsi14?: number | null;
  bar_range?: number | null;
  dist_to_ema20?: number;
  archetype: 'RUNNER' | 'SHORT_RUNNER' | 'EXHAUSTION_WARNING' | 'OBSERVATION';
  status: string;
  reasons: string[];
  warning?: string | null;
  trade_plan?: LiveMoverTradePlan | null;
  is_nifty500?: boolean;
  is_fno?: boolean;
  index_tags?: string[];
  v13_score?: number | null;
  is_v13_active?: boolean;
  updated_at: string;
}

export interface LiveMoversResponse {
  category?: string;
  min_v13_score?: number;
  gainers: LiveMoverItem[];
  losers: LiveMoverItem[];
  runners: LiveMoverItem[];
  short_runners?: LiveMoverItem[];
  exhaustion: LiveMoverItem[];
  total_tracked: number;
  updated_at: string;
}

// =========================================================================
// V13 Market Pulse & Radar Types (Idea #1 & Idea #2)
// =========================================================================

export interface MarketPulseEfficiencyRatio {
  score: number;
  max_score: number;
  er_effective: number;
  er_session: number;
  er_impulse_6: number;
  mode: string;
  v_reversal_qualified: boolean;
  bars_count: number;
}

export interface MarketPulseVwapBreadth {
  score: number;
  max_score: number;
  vwap_breadth_pct: number;
  ema20_breadth_pct: number;
  advancers: number;
  decliners: number;
  adv_decline_ratio: number;
  total_stocks_evaluated: number;
  divergence_flag: string | null;
}

export interface MarketPulseWickRatio {
  score: number;
  max_score: number;
  wick_ratio_rw: number;
  wick_pct: number;
  quality: 'CLEAN_BODIES' | 'STOP_HUNT_WICKS' | 'NORMAL';
}

export interface MarketPulseRangeConsumed {
  score: number;
  max_score: number;
  tdrc_pct: number;
  intraday_true_range: number;
  status: 'HEALTHY' | 'EXHAUSTED' | 'COMPRESSED';
}

export interface MarketPulseIndiaVix {
  score: number;
  max_score: number;
  vix_level: number;
  vix_change_pct: number;
  state: 'FAVORABLE' | 'ELEVATED_RISK';
}

export interface SectorBreadthItem {
  sector: string;
  breadth_pct: number;
  avg_change_pct: number;
  stock_count: number;
}

export interface MarketPulseTradeability {
  score: number;
  raw_score?: number;
  cap_reason?: string | null;
  traffic_light: 'GREEN' | 'YELLOW' | 'RED';
  verdict: string;
  position_sizing: string;
  action_summary: string;
  opening_discovery: boolean;
  factors: {
    efficiency_ratio: MarketPulseEfficiencyRatio;
    vwap_breadth: MarketPulseVwapBreadth;
    wick_ratio: MarketPulseWickRatio;
    range_consumed: MarketPulseRangeConsumed;
    india_vix: MarketPulseIndiaVix;
  };
  leading_sectors: SectorBreadthItem[];
  lagging_sectors: SectorBreadthItem[];
}

export interface ConditionalZones {
  bullish_trigger: number;
  target_1: number;
  target_2: number;
  chop_zone_high: number;
  chop_zone_low: number;
  bearish_trigger: number;
  support_1: number;
  support_2: number;
}

export interface Stage1EodStructure {
  clv_pct: number;
  ref_high: number;
  ref_low: number;
  ref_close: number;
  ema20_daily: number;
  ema50_daily: number;
}

export interface Stage2GlobalMacro {
  macro_tailwind_score: number;
  sp500_chg_pct: number;
  nasdaq_chg_pct: number;
  dxy_chg_pct: number;
  crude_chg_pct: number;
}

export interface NextDayPillarScores {
  clv_momentum: number;
  ema_structure: number;
  universe_breadth: number;
  global_macro: number;
  vix_regime: number;
}

export interface MarketPulseRadar {
  stage_mode: string;
  structural_bias: string;
  next_day_direction?: 'BULLISH' | 'BEARISH' | 'SIDEWAYS';
  next_day_color?: 'GREEN' | 'RED' | 'YELLOW';
  next_day_score?: number;
  next_day_conviction_pct?: number;
  next_day_summary?: string;
  target_session_date?: string;
  target_session_prefix?: string;
  target_session_headline?: string;
  pillar_scores?: NextDayPillarScores;
  compression_tag: string;
  current_zone: string;
  zone_color: string;
  zone_guidance: string;
  gap_warning: string | null;
  anchored_reference_date: string;
  conditional_zones: ConditionalZones;
  stage_1_eod_structure: Stage1EodStructure;
  stage_2_global_macro: Stage2GlobalMacro;
}

export interface V13MarketPulseResponse {
  generated_at: string;
  market_status: 'LIVE' | 'CLOSED';
  session_date?: string;
  current_nifty_price: number;
  nifty_session_change_pts: number;
  nifty_session_change_pct: number;
  nifty_atr_14: number;
  tradeability: MarketPulseTradeability;
  radar: MarketPulseRadar;
}
