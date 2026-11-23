export interface NiftyOptionsFyersStatus {
  connected: boolean;
  feed_mode: 'FULL' | 'DEGRADED';
  app_id_configured: boolean;
  app_id_masked: string;
  app_id: string;
  secret_configured: boolean;
  redirect_uri: string;
  token_date: string;
  user_name: string;
  login_url: string;
}

export interface NiftyOptionsSizingPreferences {
  capital_inr: number;
  risk_mode: 'PERCENT' | 'FIXED_INR';
  risk_value: number;
  lot_size: number;
}

export interface NiftyOptionsRegimeGate {
  id: string;
  name: string;
  passed: boolean;
  status: 'PASS' | 'BLOCKED' | 'AFTER_HOURS';
  detail: string;
}

export interface NiftyOptionsSelectedContract {
  strike: number;
  opt_type: 'CE' | 'PE';
  moneyness: string;
  symbol: string;
  expiry: string;
  dte_days: number;
  ltp: number;
  bid: number;
  ask: number;
  spread_pts: number;
  spread_pct: number;
  iv_pct: number;
  delta: number;
  abs_delta: number;
  gamma: number;
  theta_hr_est: number;
  oi: number;
  chg_oi: number;
  volume: number;
  selection_reason: string;
}

export interface NiftyOptionsPositionSizing {
  capital_inr: number;
  risk_mode: 'PERCENT' | 'FIXED_INR';
  risk_value: number;
  effective_risk_pct: number;
  risk_budget_inr: number;
  lot_size: number;
  allowed_lots: number;
  allowed_qty: number;
  study_lots: number;
  study_qty: number;
  is_iceberg?: boolean;
  entry_slices?: number[];
  entry_legs?: number;
  t1_lots?: number;
  runner_lots?: number;
  t1_slices?: number[];
  runner_slices?: number[];
  max_freeze_qty?: number;
  max_freeze_lots?: number;
  max_system_lots_cap?: number;
  weighted_entry_premium?: number;
  sizing_sl_pts_floor?: number;
  capital_per_lot_inr: number;
  capital_required_inr: number;
  capital_utilization_pct: number;
  raw_sl_loss_per_lot_inr: number;
  all_in_risk_per_lot_inr: number;
  estimated_charges_inr: number;
  estimated_slippage_inr: number;
  breakeven_points: number;
  net_max_loss_inr: number;
  net_max_loss_pct_capital: number;
  net_t1_profit_inr: number;
  net_t2_profit_inr: number;
  net_rr_t1: number;
  net_rr_t2: number;
  min_risk_for_1_lot_inr: number;
  min_capital_for_1_lot_inr: number;
  sizing_status: 'OPTIMAL' | 'AUTO_SLICED_ICEBERG' | 'CAPPED_BY_OUTLAY_LIMIT' | 'CAPPED_BY_CAPITAL' | 'INSUFFICIENT_RISK_BUDGET' | 'INSUFFICIENT_BUYING_POWER';
  sizing_note: string;
  charges_breakdown: {
    qty: number;
    buy_turnover: number;
    sell_turnover: number;
    brokerage: number;
    stt: number;
    exchange_txn: number;
    gst: number;
    stamp_and_sebi: number;
    total_charges: number;
    charges_per_lot: number;
    breakeven_pts: number;
  };
}

export interface NiftyOptionChainStrikeRow {
  strike: number;
  is_atm: boolean;
  ce_ltp: number;
  ce_bid: number;
  ce_ask: number;
  ce_oi: number;
  ce_chg_oi: number;
  ce_volume: number;
  ce_symbol: string;
  ce_iv: number;
  ce_delta: number;
  ce_gamma: number;
  ce_theta_hr: number;
  ce_spread_pct: number;
  pe_ltp: number;
  pe_bid: number;
  pe_ask: number;
  pe_oi: number;
  pe_chg_oi: number;
  pe_volume: number;
  pe_symbol: string;
  pe_iv: number;
  pe_delta: number;
  pe_gamma: number;
  pe_theta_hr: number;
  pe_spread_pct: number;
}

export interface NiftyOptionsPaperTrade {
  trade_id: string;
  source: string;
  entry_time: string;
  entry_time_str: string;
  exit_time?: string;
  exit_time_str?: string;
  symbol: string;
  strike: number;
  opt_type: 'CE' | 'PE';
  moneyness: string;
  lots: number;
  lot_size: number;
  qty: number;
  is_iceberg?: boolean;
  entry_slices?: number[];
  entry_legs?: number;
  t1_lots?: number;
  runner_lots?: number;
  t1_slices?: number[];
  runner_slices?: number[];
  t1_legs?: number;
  runner_legs?: number;
  final_exit_legs?: number;
  total_executed_legs?: number;
  sizing_status: string;
  entry_spot: number;
  current_spot?: number;
  exit_spot?: number;
  best_spot?: number;
  entry_premium: number;
  current_ltp: number;
  exit_premium?: number;
  high_watermark: number;
  initial_sl_premium: number;
  current_sl_premium: number;
  sl_points: number;
  t1_premium: number;
  t2_premium: number;
  t1_booked: boolean;
  t2_reached?: boolean;
  stage0a_shield_active?: boolean;
  stage0b_shield_active?: boolean;
  stage1b0_shield_active?: boolean;
  pre_t1_shield_active?: boolean;
  pre_t1_doorstep_active?: boolean;
  stage2_notified?: boolean;
  doorstep_notified?: boolean;
  sl_45m_tightened?: boolean;
  coiling_extension_active?: boolean;
  hold_minutes: number;
  time_stop_minutes: number;
  post_t1_stepup_minutes?: number;
  post_t1_max_hold_minutes?: number;
  post_t1_lock_r?: number;
  unrealized_pts?: number;
  unrealized_r?: number;
  realized_pts?: number;
  r_multiple?: number;
  gross_pnl_inr: number;
  est_charges_inr?: number;
  charges_inr?: number;
  est_slippage_inr?: number;
  slippage_inr?: number;
  net_pnl_inr: number;
  delta_at_entry: number;
  iv_at_entry: number;
  trigger_type: string;
  exit_reason?: string;
}

export interface NiftyOptionsDashboardResponse {
  status: string;
  fyers_status: NiftyOptionsFyersStatus;
  sizing_preferences: NiftyOptionsSizingPreferences;
  quant_engine: {
    generated_at: string;
    ist_time_str: string;
    feed_mode: 'FULL' | 'DEGRADED';
    feed_badge: string;
    degraded_bypassed_checks: string[];
    market_snapshot: {
      spot_ltp: number;
      spot_change?: number;
      spot_change_pct?: number;
      futures_ltp: number;
      forward_source: string;
      spot_vwap: number;
      futures_vwap: number;
      vwap_source: string;
      spot_ema20_5m: number;
      spot_ema20_15m: number;
      spot_rsi_5m: number;
      adx_5m: number;
      adx_prev_5m: number;
      plus_di_5m: number;
      minus_di_5m: number;
      atr_5m: number;
      india_vix: number;
      atm_strike: number;
      atm_straddle_ltp: number;
      atm_straddle_vwap: number;
      straddle_source: string;
      local_5strike_pcr: number;
      local_ce_oi: number;
      local_pe_oi: number;
      local_ce_chg_oi: number;
      local_pe_chg_oi: number;
      banknifty_ltp: number;
      banknifty_status: string;
      expiry_str: string;
      dte_days: number;
      seconds_to_expiry: number;
    };
    regime_gates: {
      all_passed: boolean;
      core_passed: boolean;
      directional_bias: 'BULLISH_CE' | 'BEARISH_PE';
      gates: NiftyOptionsRegimeGate[];
    };
    selected_contract: NiftyOptionsSelectedContract;
    entry_trigger: {
      trigger_fired: boolean;
      trigger_type: string;
      trigger_reason: string;
      spot_swing_stop: number;
      sl_spot_pts: number;
    };
    trade_plan: {
      signal_state: 'EXECUTE_BUY' | 'READY_AFTER_HOURS_STUDY' | 'ARMED_WAITING_TRIGGER' | 'NO_TRADE_REGIME_BLOCKED';
      signal_headline: string;
      symbol: string;
      strike: number;
      opt_type: 'CE' | 'PE';
      moneyness: string;
      entry_premium: number;
      sl_premium: number;
      sl_points: number;
      t1_premium: number;
      t1_points: number;
      t2_premium: number;
      t2_points: number;
      trail_sl_at_t1: number;
      time_stop_minutes: number;
      time_stop_rule: string;
      hard_eod_squareoff: string;
    };
    position_sizing: NiftyOptionsPositionSizing;
    option_chain_window: NiftyOptionChainStrikeRow[];
  };
  paper_ledger: NiftyOptionsPaperLedger;
}

export interface NiftyOptionsPaperLedger {
  session_date: string;
  auto_trade_enabled: boolean;
  kill_switch: {
    kill_switch_engaged: boolean;
    reason: string;
    trades_taken_today: number;
    max_trades_per_day: number;
    consecutive_losses: number;
    max_consecutive_losses: number;
    realized_net_pnl_inr?: number;
  };
  open_trade: NiftyOptionsPaperTrade | null;
  closed_trades: NiftyOptionsPaperTrade[];
  entry_guard_blocked?: boolean;
  entry_guard_reason?: string | null;
  stats: {
    total_closed: number;
    wins: number;
    losses: number;
    win_rate_pct: number;
    auto_trades?: number;
    force_trades?: number;
    auto_win_rate_pct?: number;
    gross_realized_pnl_inr: number;
    total_charges_and_slippage_inr: number;
    net_realized_pnl_inr: number;
    unrealized_net_pnl_inr: number;
    combined_net_pnl_inr: number;
    cum_r_multiple: number;
  };
}

export interface NiftyOptionsSessionSummaryItem {
  session_date: string;
  is_today: boolean;
  total_closed: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  auto_trades: number;
  gross_realized_pnl_inr: number;
  total_charges_and_slippage_inr: number;
  net_realized_pnl_inr: number;
  roi_pct: number;
  cum_r_multiple: number;
}

export interface NiftyOptionsCumulativeSummary {
  from_date?: string | null;
  total_sessions: number;
  total_trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number;
  gross_realized_pnl_inr: number;
  total_charges_and_slippage_inr: number;
  net_realized_pnl_inr: number;
  cumulative_roi_pct: number;
  cum_r_multiple: number;
}

export interface NiftyOptionsLedgerSessionsResponse {
  status: string;
  live_session_date: string;
  capital_inr: number;
  sessions: NiftyOptionsSessionSummaryItem[];
  cumulative: NiftyOptionsCumulativeSummary;
}
