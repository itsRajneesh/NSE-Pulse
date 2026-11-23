"""
NSE-PULSE V13: Weekly EOD Performance Audit Engine.

Aggregates Monday–Friday trading session ledgers and Telegram notification archives
into the official quantitative Weekly EOD Performance Audit report conforming strictly
to the system audit template.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .config import IST_TZ

logger = logging.getLogger("v13_weekly_audit")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LEDGER_HISTORY_DIR = os.path.join(DATA_DIR, "EOD performance history")
LEDGER_ACTIVE_PATH = os.path.join(DATA_DIR, "active performance live eod", "session_trade_ledger.json")
TG_HISTORY_DIR = os.path.join(DATA_DIR, "telegram notification history")
TG_CACHE_PATH = os.path.join(DATA_DIR, "telegram notification audit", "sent_alerts_cache.json")
WEEKLY_HISTORY_DIR = os.path.join(DATA_DIR, "weekly performance history")

# V14 Outcome Categories (Synchronized with v13_ledger.py Dual-Tranche Engine)
V14_T1_WIN_OUTCOMES = ("T1_HIT", "T2_HIT", "T1_HIT_TRAILED", "T1_WIN_BE_EXIT", "EOD_PARTIAL_WIN")
V14_WIN_OUTCOMES = ("T1_HIT", "T2_HIT", "T1_HIT_TRAILED", "T1_WIN_BE_EXIT", "EOD_PARTIAL_WIN", "CLOSED_EOD_PROFIT")
V14_EOD_PROFIT_OUTCOMES = ("CLOSED_EOD_PROFIT", "EOD_PARTIAL_WIN")
V14_OPEN_OUTCOMES = ("OPEN", "T1_HIT_TRAILED")


def get_week_dates(target_dt: Optional[datetime] = None) -> Tuple[datetime, datetime, List[str]]:
    """
    Given a target datetime in IST, returns:
    (monday_dt, friday_dt, [mon_str, tue_str, wed_str, thu_str, fri_str])
    where date strings are in 'YYYY-MM-DD' format.
    """
    dt = target_dt or datetime.now(IST_TZ)
    monday = dt - timedelta(days=dt.weekday())
    friday = monday + timedelta(days=4)

    week_days = [
        (monday + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(5)
    ]
    return monday, friday, week_days


def _load_day_ledger(day_str: str) -> Dict[str, Any]:
    """Load ledger records for a given date from active or historical file."""
    # Check active ledger first if date matches
    if os.path.exists(LEDGER_ACTIVE_PATH):
        try:
            with open(LEDGER_ACTIVE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") == day_str and data.get("records"):
                return data.get("records", {})
        except Exception:
            pass

    # Check history folder
    hist_file = os.path.join(LEDGER_HISTORY_DIR, f"ledger_{day_str}.json")
    if os.path.exists(hist_file):
        try:
            with open(hist_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("records", {})
        except Exception as e:
            logger.warning(f"Error loading {hist_file}: {e}")

    return {}


def _load_day_telegram_alerts(day_str: str) -> List[Dict[str, Any]]:
    """Load telegram alerts for a given date from history or active cache."""
    # Check history first
    hist_file = os.path.join(TG_HISTORY_DIR, f"telegram_alerts_{day_str}.json")
    if os.path.exists(hist_file):
        try:
            with open(hist_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            alerts = data.get("alerts", [])
            if alerts:
                return alerts
        except Exception:
            pass

    # Fallback to active cache
    if os.path.exists(TG_CACHE_PATH):
        try:
            with open(TG_CACHE_PATH, "r", encoding="utf-8") as f:
                cache = json.load(f)
            matched = []
            for sym, item in cache.items():
                if isinstance(item, dict) and item.get("date") == day_str:
                    clean_item = dict(item)
                    clean_sym = item.get("symbol") or (
                        sym.rsplit("_", 1)[0]
                        if sym.endswith(("_BULLISH", "_BEARISH", "_LONG", "_SHORT"))
                        else sym
                    )
                    clean_item["symbol"] = str(clean_sym).replace(".NS", "").strip().upper()
                    matched.append(clean_item)
            return matched
        except Exception:
            pass

    return []


def generate_weekly_eod_report(
    target_dt: Optional[datetime] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Generate the official Quantitative Weekly EOD Performance Audit.
    Returns (report_markdown_text, metrics_dictionary).
    """
    now = target_dt or datetime.now(IST_TZ)
    monday_dt, friday_dt, week_days = get_week_dates(now)

    start_date_str = week_days[0]
    end_date_str = week_days[-1]
    week_str = f"{start_date_str}_to_{end_date_str}"

    day_labels = ["MON", "TUE", "WED", "THU", "FRI"]
    daily_stats: Dict[str, Dict[str, Any]] = {}

    all_setups: List[Dict[str, Any]] = []
    all_tg_alerts: List[Dict[str, Any]] = []

    # 1. Load data for each day
    for day_str, label in zip(week_days, day_labels):
        records = _load_day_ledger(day_str)
        tg_alerts = _load_day_telegram_alerts(day_str)

        day_setups = list(records.values())
        if day_setups:
            all_setups.extend(day_setups)
        if tg_alerts:
            all_tg_alerts.extend(tg_alerts)

        # Day-level metrics
        day_total = len(day_setups)
        day_wins = sum(1 for s in day_setups if s.get("outcome") in V14_T1_WIN_OUTCOMES)
        day_sl = sum(1 for s in day_setups if s.get("outcome") == "SL_HIT")
        day_mtm = sum(1 for s in day_setups if str(s.get("outcome", "")).startswith("CLOSED_EOD"))
        day_net_r = sum(float(s.get("realized_r", 0.0) or 0.0) for s in day_setups)
        day_early = sum(1 for s in day_setups if s.get("first_detection_stage") == "EARLY_TRIGGER")

        daily_stats[day_str] = {
            "label": label,
            "date": day_str,
            "has_data": day_total > 0,
            "total_signals": day_total,
            "wins": day_wins,
            "sl": day_sl,
            "mtm": day_mtm,
            "net_r": round(day_net_r, 2),
            "early_count": day_early,
            "early_pct": round((day_early / day_total * 100), 1) if day_total > 0 else 0.0,
            "win_rate_pct": round((day_wins / day_total * 100), 1) if day_total > 0 else 0.0,
        }

    # Active session days
    active_days = [d for d in daily_stats.values() if d["has_data"]]
    n_sessions = len(active_days)
    total_signals = len(all_setups)

    if n_sessions == 0 or total_signals == 0:
        empty_report = (
            "=================================================\n"
            "📊 *NSE-PULSE V13: WEEKLY EOD PERFORMANCE AUDIT*\n"
            f"📅 Week: {start_date_str} → {end_date_str} | Sessions: 0 | Overall Bias: NEUTRAL\n"
            "=================================================\n\n"
            "No trading sessions with recorded setups found for this week."
        )
        return empty_report, {"total_signals": 0, "sessions": 0}

    # Overall bias calculation
    bullish_wins = sum(1 for s in all_setups if s.get("direction") == "BULLISH" and s.get("outcome") in V14_T1_WIN_OUTCOMES)
    bearish_wins = sum(1 for s in all_setups if s.get("direction") == "BEARISH" and s.get("outcome") in V14_T1_WIN_OUTCOMES)
    if bullish_wins > bearish_wins * 1.2:
        overall_bias = "BULLISH"
    elif bearish_wins > bullish_wins * 1.2:
        overall_bias = "BEARISH"
    else:
        overall_bias = "NEUTRAL"

    # Signals / Day & Extremes
    avg_signals_day = round(total_signals / n_sessions, 1)
    best_sig_day_stat = max(active_days, key=lambda x: x["total_signals"])
    lowest_sig_day_stat = min(active_days, key=lambda x: x["total_signals"])

    def _fmt_dd_mmm(iso_date: str) -> str:
        try:
            return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d-%b")
        except Exception:
            return iso_date

    best_sig_day_str = f"{_fmt_dd_mmm(best_sig_day_stat['date'])} ({best_sig_day_stat['total_signals']} Signals)"
    lowest_sig_day_str = f"{_fmt_dd_mmm(lowest_sig_day_stat['date'])} ({lowest_sig_day_stat['total_signals']} Signals)"

    # Net R Metrics
    weekly_net_r = round(sum(float(s.get("realized_r", 0.0) or 0.0) for s in all_setups), 2)
    avg_r_day = round(weekly_net_r / n_sessions, 2)
    avg_r_sig = round(weekly_net_r / total_signals, 2)

    # 2. Execution Lifecycle Breakdown
    early_count = sum(1 for s in all_setups if s.get("first_detection_stage") == "EARLY_TRIGGER")
    actionable_count = sum(1 for s in all_setups if s.get("first_detection_stage") == "ACTIONABLE")
    near_target_count = sum(1 for s in all_setups if s.get("first_detection_stage") == "TARGET_NEAR")
    target_hit_count = sum(1 for s in all_setups if s.get("first_detection_stage") == "TARGET_HIT")

    early_pct = round((early_count / total_signals) * 100, 1)
    actionable_pct = round((actionable_count / total_signals) * 100, 1)
    near_target_pct = round((near_target_count / total_signals) * 100, 1)
    target_hit_pct = round((target_hit_count / total_signals) * 100, 1)

    best_early_stat = max(active_days, key=lambda x: x["early_pct"])
    best_early_day_str = f"{_fmt_dd_mmm(best_early_stat['date'])} ({best_early_stat['early_pct']}%)"

    best_t1_stat = max(active_days, key=lambda x: x["win_rate_pct"])
    best_t1_day_str = f"{_fmt_dd_mmm(best_t1_stat['date'])} ({best_t1_stat['win_rate_pct']}%)"

    best_exec_stat = max(active_days, key=lambda x: x["net_r"])
    best_exec_day_str = _fmt_dd_mmm(best_exec_stat["date"])

    # 3. Telegram Live Alerts Scorecard
    tg_total = len(all_tg_alerts)
    if tg_total > 0:
        tg_t1_total = sum(1 for a in all_tg_alerts if a.get("outcome") in V14_T1_WIN_OUTCOMES)
        tg_t2_runners = sum(1 for a in all_tg_alerts if a.get("outcome") == "T2_HIT")
        tg_t1_only = tg_t1_total - tg_t2_runners
        tg_sl_losses = sum(1 for a in all_tg_alerts if a.get("outcome") == "SL_HIT")
        tg_eod_p = sum(1 for a in all_tg_alerts if a.get("outcome") in V14_EOD_PROFIT_OUTCOMES)
        tg_eod_l = sum(1 for a in all_tg_alerts if a.get("outcome") == "CLOSED_EOD_LOSS")
        tg_eod_f = sum(1 for a in all_tg_alerts if a.get("outcome") == "CLOSED_EOD_FLAT")
        tg_eod_settled = tg_eod_p + tg_eod_l + tg_eod_f
        tg_open = sum(1 for a in all_tg_alerts if a.get("outcome") in V14_OPEN_OUTCOMES)
        tg_net_r = round(sum(float(a.get("realized_r", 0.0) or 0.0) for a in all_tg_alerts), 2)
        tg_avg_r = round(tg_net_r / tg_total, 2)

        tg_metrics = {
            "total_dispatched": tg_total,
            "t1_only": tg_t1_only,
            "t1_only_pct": round((tg_t1_only / tg_total) * 100, 1),
            "t2_runners": tg_t2_runners,
            "t2_rate_pct": round((tg_t2_runners / tg_total) * 100, 1),
            "total_target_wins": tg_t1_total,
            "win_rate_pct": round((tg_t1_total / tg_total) * 100, 1),
            "sl_losses": tg_sl_losses,
            "sl_loss_pct": round((tg_sl_losses / tg_total) * 100, 1),
            "eod_settled": tg_eod_settled,
            "eod_settled_pct": round((tg_eod_settled / tg_total) * 100, 1),
            "eod_p": tg_eod_p,
            "eod_p_pct": round((tg_eod_p / tg_total) * 100, 1),
            "eod_l": tg_eod_l,
            "eod_l_pct": round((tg_eod_l / tg_total) * 100, 1),
            "eod_f": tg_eod_f,
            "eod_f_pct": round((tg_eod_f / tg_total) * 100, 1),
            "open": tg_open,
            "open_pct": round((tg_open / tg_total) * 100, 1),
            "net_realized_r": tg_net_r,
            "avg_realized_r": tg_avg_r,
        }
    else:
        tg_metrics = {
            "total_dispatched": 0, "t1_only": 0, "t1_only_pct": 0.0,
            "t2_runners": 0, "t2_rate_pct": 0.0, "total_target_wins": 0,
            "win_rate_pct": 0.0, "sl_losses": 0, "sl_loss_pct": 0.0,
            "eod_settled": 0, "eod_settled_pct": 0.0, "eod_p": 0, "eod_p_pct": 0.0,
            "eod_l": 0, "eod_l_pct": 0.0, "eod_f": 0, "eod_f_pct": 0.0,
            "open": 0, "open_pct": 0.0, "net_realized_r": 0.0, "avg_realized_r": 0.0,
        }

    # 4. Quality Tier Breakdown
    def _calc_tier_stats(tier_name: str) -> Dict[str, Any]:
        setups = [s for s in all_setups if s.get("peak_tier") == tier_name]
        c = len(setups)
        if c == 0:
            return {
                "total": 0, "pct_weekly": 0.0, "early_caught": 0, "early_pct": 0.0,
                "t1_hit": 0, "t1_pct": 0.0, "t1_only": 0, "t1_only_pct": 0.0,
                "t2_hit": 0, "t2_pct": 0.0, "sl_hit": 0, "sl_pct": 0.0,
                "eod_settled": 0, "eod_settled_pct": 0.0,
                "eod_p": 0, "eod_p_pct": 0.0, "eod_l": 0, "eod_l_pct": 0.0,
                "eod_f": 0, "eod_f_pct": 0.0, "open": 0, "open_pct": 0.0,
                "net_r": 0.0,
            }
        early = sum(1 for s in setups if s.get("first_detection_stage") == "EARLY_TRIGGER")
        t1_total = sum(1 for s in setups if s.get("outcome") in V14_T1_WIN_OUTCOMES)
        t2 = sum(1 for s in setups if s.get("outcome") == "T2_HIT")
        t1_only = t1_total - t2
        sl = sum(1 for s in setups if s.get("outcome") == "SL_HIT")
        eod_p = sum(1 for s in setups if s.get("outcome") in V14_EOD_PROFIT_OUTCOMES)
        eod_l = sum(1 for s in setups if s.get("outcome") == "CLOSED_EOD_LOSS")
        eod_f = sum(1 for s in setups if s.get("outcome") == "CLOSED_EOD_FLAT")
        eod_set = eod_p + eod_l + eod_f
        op = sum(1 for s in setups if s.get("outcome") in V14_OPEN_OUTCOMES)
        net_r = round(sum(float(s.get("realized_r", 0.0) or 0.0) for s in setups), 2)

        return {
            "total": c,
            "pct_weekly": round((c / total_signals) * 100, 1),
            "early_caught": early,
            "early_pct": round((early / c) * 100, 1),
            "t1_hit": t1_total,
            "t1_pct": round((t1_total / c) * 100, 1),
            "t1_only": t1_only,
            "t1_only_pct": round((t1_only / c) * 100, 1),
            "t2_hit": t2,
            "t2_pct": round((t2 / c) * 100, 1),
            "sl_hit": sl,
            "sl_pct": round((sl / c) * 100, 1),
            "eod_settled": eod_set,
            "eod_settled_pct": round((eod_set / c) * 100, 1),
            "eod_p": eod_p,
            "eod_p_pct": round((eod_p / c) * 100, 1),
            "eod_l": eod_l,
            "eod_l_pct": round((eod_l / c) * 100, 1),
            "eod_f": eod_f,
            "eod_f_pct": round((eod_f / c) * 100, 1),
            "open": op,
            "open_pct": round((op / c) * 100, 1),
            "net_r": net_r,
        }

    hc = _calc_tier_stats("HIGH_CONFIDENCE")
    st = _calc_tier_stats("STRONG")
    wl = _calc_tier_stats("WATCHLIST")

    # 5. Total Weekly Accuracy
    t1_total_hits = sum(1 for s in all_setups if s.get("outcome") in V14_T1_WIN_OUTCOMES)
    t2_runners = sum(1 for s in all_setups if s.get("outcome") == "T2_HIT")
    t1_only = t1_total_hits - t2_runners
    sl_losses = sum(1 for s in all_setups if s.get("outcome") == "SL_HIT")
    eod_profits = sum(1 for s in all_setups if s.get("outcome") in V14_EOD_PROFIT_OUTCOMES)
    eod_losses = sum(1 for s in all_setups if s.get("outcome") == "CLOSED_EOD_LOSS")
    eod_flats = sum(1 for s in all_setups if s.get("outcome") == "CLOSED_EOD_FLAT")
    eod_settled = eod_profits + eod_losses + eod_flats
    open_eod = sum(1 for s in all_setups if s.get("outcome") in V14_OPEN_OUTCOMES)

    t1_only_pct = round((t1_only / total_signals) * 100, 1)
    t2_rate_pct = round((t2_runners / total_signals) * 100, 1)
    win_rate_pct = round((t1_total_hits / total_signals) * 100, 1)
    sl_loss_pct = round((sl_losses / total_signals) * 100, 1)
    eod_settled_pct = round((eod_settled / total_signals) * 100, 1)
    eod_profit_pct = round((eod_profits / total_signals) * 100, 1)
    eod_loss_pct = round((eod_losses / total_signals) * 100, 1)
    eod_flat_pct = round((eod_flats / total_signals) * 100, 1)
    open_pct = round((open_eod / total_signals) * 100, 1)

    # Profit Factor & Drawdown
    pos_r = sum(float(s.get("realized_r", 0.0) or 0.0) for s in all_setups if float(s.get("realized_r", 0.0) or 0.0) > 0)
    neg_r = sum(abs(float(s.get("realized_r", 0.0) or 0.0)) for s in all_setups if float(s.get("realized_r", 0.0) or 0.0) < 0)
    profit_factor = round(pos_r / neg_r, 2) if neg_r > 0 else (99.0 if pos_r > 0 else 1.0)

    daily_r_list = [d["net_r"] for d in active_days]
    best_daily_r = max(daily_r_list) if daily_r_list else 0.0
    worst_daily_r = min(daily_r_list) if daily_r_list else 0.0
    max_daily_dd = min(0.0, worst_daily_r)

    # Max Weekly Drawdown (cumulative peak to trough)
    cum_r = 0.0
    peak_cum = 0.0
    max_dd = 0.0
    for r_val in daily_r_list:
        cum_r += r_val
        if cum_r > peak_cum:
            peak_cum = cum_r
        dd = cum_r - peak_cum
        if dd < max_dd:
            max_dd = dd
    max_weekly_dd = round(max_dd, 2)

    # Volatility of daily R
    if len(daily_r_list) > 1:
        mean_r = sum(daily_r_list) / len(daily_r_list)
        var_r = sum((x - mean_r) ** 2 for x in daily_r_list) / (len(daily_r_list) - 1)
        weekly_vol = round(math.sqrt(var_r), 2)
    else:
        weekly_vol = 0.0

    # Risk & Consistency counts
    pos_days = sum(1 for d in active_days if d["net_r"] > 0)
    neg_days = sum(1 for d in active_days if d["net_r"] < 0)
    flat_days = sum(1 for d in active_days if d["net_r"] == 0)

    # Consecutive days
    consec_pos = 0
    max_consec_pos = 0
    consec_neg = 0
    max_consec_neg = 0
    for d in active_days:
        if d["net_r"] > 0:
            consec_pos += 1
            consec_neg = 0
            if consec_pos > max_consec_pos:
                max_consec_pos = consec_pos
        elif d["net_r"] < 0:
            consec_neg += 1
            consec_pos = 0
            if consec_neg > max_consec_neg:
                max_consec_neg = consec_neg
        else:
            consec_pos = 0
            consec_neg = 0

    # Quality Tier Rankings
    tier_perf = [
        ("High Confidence", hc["win_rate_pct"] if "win_rate_pct" in hc else hc["t1_pct"], hc["t2_pct"], hc["sl_pct"]),
        ("Strong Setups", st["t1_pct"], st["t2_pct"], st["sl_pct"]),
        ("Watchlist", wl["t1_pct"], wl["t2_pct"], wl["sl_pct"]),
    ]
    best_tier = max(tier_perf, key=lambda x: x[1])[0]
    highest_t2_tier = max(tier_perf, key=lambda x: x[2])[0]
    lowest_sl_tier = min(tier_perf, key=lambda x: x[3])[0]

    # 6. Top 10 Winners of the Week (Enhanced with Real % Price Gain Sort)
    valid_winners = []
    for s in all_setups:
        r_val = float(s.get("realized_r", 0.0) or 0.0)
        out = s.get("outcome")
        if out not in V14_WIN_OUTCOMES and r_val <= 0:
            continue
        entry = float(s.get("entry_price") or 0.0)
        sl = float(s.get("stop_loss") or 0.0)
        risk = float(s.get("risk_amount") or abs(entry - sl))
        # Exclude zero risk / corrupt glitch setups
        if entry <= 0 or risk < 0.10 or abs(entry - sl) < 0.10:
            continue
        ltp = float(s.get("ltp") or entry)
        direction = str(s.get("direction", "BULLISH")).upper()
        if direction == "BULLISH":
            gain_pct = ((ltp - entry) / entry) * 100.0
        else:
            gain_pct = ((entry - ltp) / entry) * 100.0

        # Cap highest_progress_pct to avoid 15000% division-by-zero glitches
        prog = float(s.get("highest_progress_pct") or 0.0)
        capped_prog = min(prog, 500.0)

        s_copy = dict(s)
        s_copy["gain_pct"] = round(gain_pct, 2)
        s_copy["highest_progress_pct"] = round(capped_prog, 1)
        valid_winners.append(s_copy)

    # Sort primarily by realized_r (descending) and secondarily by actual % price gain (descending)
    valid_winners.sort(key=lambda s: (float(s.get("realized_r", 0.0)), s.get("gain_pct", 0.0)), reverse=True)

    seen_win_syms = set()
    unique_winners = []
    for s in valid_winners:
        sym = s.get("symbol")
        if sym and sym not in seen_win_syms:
            seen_win_syms.add(sym)
            unique_winners.append(s)
            if len(unique_winners) >= 10:
                break

    top_10_lines = []
    for idx, s in enumerate(unique_winners, 1):
        r_val = float(s.get("realized_r", 0.0) or 0.0)
        g_val = float(s.get("gain_pct", 0.0) or 0.0)
        top_10_lines.append(f"{idx}. **{s.get('symbol')}** (+{r_val:.2f}R | +{g_val:.2f}% Real Move)")
    top_10_str = "\n".join(top_10_lines) if top_10_lines else "• None (No winning trades recorded this week)"

    # Addition 1: Weekly Sector Performance Heatmap (Heroes vs Zeroes)
    sector_stats: Dict[str, Dict[str, Any]] = {}
    for s in all_setups:
        sec = s.get("sector") or "Diversified"
        if not sec or sec.strip().lower() in ("none", "unknown", "nse equity", "equity"):
            sec = "Diversified"
        if sec not in sector_stats:
            sector_stats[sec] = {"sector": sec, "total": 0, "wins": 0, "losses": 0, "net_r": 0.0}
        sector_stats[sec]["total"] += 1
        r = float(s.get("realized_r", 0.0) or 0.0)
        sector_stats[sec]["net_r"] += r
        if s.get("outcome") in V14_T1_WIN_OUTCOMES or r > 0:
            sector_stats[sec]["wins"] += 1
        elif s.get("outcome") == "SL_HIT" or r < 0:
            sector_stats[sec]["losses"] += 1

    ranked_sectors = []
    for sec, s_item in sector_stats.items():
        if s_item["total"] >= 5:
            wr = round((s_item["wins"] / s_item["total"]) * 100.0, 1)
            ranked_sectors.append({
                "sector": sec,
                "total": s_item["total"],
                "wins": s_item["wins"],
                "losses": s_item["losses"],
                "win_rate_pct": wr,
                "net_r": round(s_item["net_r"], 2),
            })
    ranked_sectors.sort(key=lambda x: (x["win_rate_pct"], x["net_r"]), reverse=True)
    sector_heroes = ranked_sectors[:5]
    sector_zeroes = ranked_sectors[-5:] if len(ranked_sectors) >= 10 else ranked_sectors[5:]

    # Addition 2: 15-Minute Time-of-Day Execution Window (09:15 to 15:30)
    import datetime as dt_mod
    all_intervals = []
    start_t_obj = dt_mod.time(9, 15)
    cur_t_obj = dt_mod.datetime.combine(dt_mod.date.today(), start_t_obj)
    end_t_obj = dt_mod.datetime.combine(dt_mod.date.today(), dt_mod.time(15, 30))
    time_buckets: Dict[str, Dict[str, Any]] = {}
    while cur_t_obj < end_t_obj:
        next_t_obj = cur_t_obj + dt_mod.timedelta(minutes=15)
        label = f"{cur_t_obj.strftime('%H:%M')}-{next_t_obj.strftime('%H:%M')}"
        all_intervals.append((cur_t_obj.time(), next_t_obj.time(), label))
        time_buckets[label] = {"window": label, "signals": 0, "wins": 0, "losses": 0, "net_r": 0.0}
        cur_t_obj = next_t_obj

    for s in all_setups:
        reg_str = str(s.get("registered_at") or "")
        if len(reg_str) >= 19:
            try:
                t_part = reg_str[11:19]
                stock_t = dt_mod.datetime.strptime(t_part, "%H:%M:%S").time()
                for start_t, end_t, label in all_intervals:
                    if start_t <= stock_t < end_t:
                        time_buckets[label]["signals"] += 1
                        r = float(s.get("realized_r", 0.0) or 0.0)
                        time_buckets[label]["net_r"] += r
                        if s.get("outcome") in V14_T1_WIN_OUTCOMES or r > 0:
                            time_buckets[label]["wins"] += 1
                        elif s.get("outcome") == "SL_HIT" or r < 0:
                            time_buckets[label]["losses"] += 1
                        break
            except Exception:
                pass

    time_window_stats = []
    for label, tb_item in time_buckets.items():
        if tb_item["signals"] > 0:
            wr = round((tb_item["wins"] / tb_item["signals"]) * 100.0, 1)
            nr = round(tb_item["net_r"], 2)
            time_window_stats.append({
                "window": label,
                "signals": tb_item["signals"],
                "wins": tb_item["wins"],
                "losses": tb_item["losses"],
                "win_rate_pct": wr,
                "net_r": nr,
            })

    # Addition 4: Bullish vs Bearish Market Regime Scorecard
    bull_setups = [s for s in all_setups if str(s.get("direction", "BULLISH")).upper() == "BULLISH"]
    bear_setups = [s for s in all_setups if str(s.get("direction", "BULLISH")).upper() == "BEARISH"]

    def _calc_regime(setups, name):
        tot = len(setups)
        if tot == 0:
            return {"name": name, "total": 0, "wins": 0, "sl": 0, "mtm": 0, "win_rate_pct": 0.0, "sl_rate_pct": 0.0, "net_r": 0.0, "profit_factor": 0.0}
        wins = sum(1 for s in setups if s.get("outcome") in V14_T1_WIN_OUTCOMES or float(s.get("realized_r", 0.0) or 0.0) > 0)
        sl = sum(1 for s in setups if s.get("outcome") == "SL_HIT" or float(s.get("realized_r", 0.0) or 0.0) <= -1.0)
        mtm = sum(1 for s in setups if str(s.get("outcome", "")).startswith("CLOSED_EOD"))
        net_r = sum(float(s.get("realized_r", 0.0) or 0.0) for s in setups)
        gross_pos = sum(float(s.get("realized_r", 0.0) or 0.0) for s in setups if float(s.get("realized_r", 0.0) or 0.0) > 0)
        gross_neg = sum(abs(float(s.get("realized_r", 0.0) or 0.0)) for s in setups if float(s.get("realized_r", 0.0) or 0.0) < 0)
        pf = round(gross_pos / gross_neg, 2) if gross_neg > 0 else 99.0
        return {
            "name": name,
            "total": tot,
            "wins": wins,
            "sl": sl,
            "mtm": mtm,
            "win_rate_pct": round((wins / tot) * 100.0, 1),
            "sl_rate_pct": round((sl / tot) * 100.0, 1),
            "net_r": round(net_r, 2),
            "profit_factor": pf,
        }

    regime_scorecard = {
        "bullish": _calc_regime(bull_setups, "BULLISH LONG SETUPS"),
        "bearish": _calc_regime(bear_setups, "BEARISH SHORT SETUPS"),
    }

    # 7. Top 5 Loss / Failure Patterns
    loss_setups = [
        s for s in all_setups
        if (s.get("outcome") in ("SL_HIT", "CLOSED_EOD_LOSS") or float(s.get("realized_r", 0.0) or 0.0) < 0)
    ]
    loss_setups.sort(key=lambda s: float(s.get("realized_r", 0.0) or 0.0))
    # Deduplicate by symbol keeping worst loss
    seen_loss_syms = set()
    unique_losses = []
    for s in loss_setups:
        sym = s.get("symbol")
        if sym and sym not in seen_loss_syms:
            seen_loss_syms.add(sym)
            unique_losses.append(s)
            if len(unique_losses) >= 5:
                break

    def _determine_failure_reason(s: Dict[str, Any]) -> str:
        outcome = s.get("outcome")
        prog = float(s.get("highest_progress_pct", 0.0) or 0.0)
        if outcome == "SL_HIT":
            if prog < 15.0:
                return "SL Breached (-1.00R) — Immediate reversal / false breakout post-entry"
            elif prog >= 50.0:
                return "SL Breached (-1.00R) — Deep mid-move retracement after reaching trailing zone"
            return "SL Breached (-1.00R) — Failed breakout retest"
        elif outcome == "CLOSED_EOD_LOSS":
            r_val = float(s.get("realized_r", 0.0) or 0.0)
            return f"MTM Settlement Loss ({r_val:+.2f}R) — Range-bound intraday consolidation / chop"
        r_val = float(s.get("realized_r", 0.0) or 0.0)
        return f"Consolidation Drag ({r_val:+.2f}R)"

    top_5_loss_lines = []
    for idx, s in enumerate(unique_losses, 1):
        r_val = float(s.get("realized_r", 0.0) or 0.0)
        reason = _determine_failure_reason(s)
        top_5_loss_lines.append(f"{idx}. {s.get('symbol')} — {r_val:+.2f}R — [{reason}]")
    top_5_loss_str = "\n".join(top_5_loss_lines) if top_5_loss_lines else "• None (Zero losses recorded this week)"

    # 8. Day-by-day table lines
    day_by_day_lines = []
    for day_str, label in zip(week_days, day_labels):
        st_day = daily_stats[day_str]
        if st_day["has_data"]:
            day_by_day_lines.append(
                f"{label} | Signals: {st_day['total_signals']:3d} | Wins: {st_day['wins']:3d} | "
                f"SL: {st_day['sl']:2d} | MTM: {st_day['mtm']:2d} | Net: {st_day['net_r']:+6.2f} R"
            )
        else:
            day_by_day_lines.append(f"{label} | No Session / Market Closed")
    day_by_day_str = "\n".join(day_by_day_lines)

    # 9. Qualitative observations
    exec_strength_obs = (
        f"Exceptional Early Entry capture at {early_pct}% with {win_rate_pct}% combined win rate, "
        f"anchoring {weekly_net_r:+.2f}R net realization across {n_sessions} trading sessions."
    )
    main_leakage_obs = (
        f"Intraday stop-outs accounted for {sl_loss_pct}% loss rate; "
        f"{eod_settled_pct}% trades required MTM auto-settlement at market close."
    )
    tier_obs = (
        f"{best_tier} delivered highest accuracy ({tier_perf[0][1]}% conversion), "
        f"while {highest_t2_tier} offered maximum deep trend runner expansion ({tier_perf[0][2]}% T2 rate)."
    )
    timing_obs = (
        f"Best overall execution achieved on {best_exec_day_str}; "
        f"Early trigger capture peaked on {best_early_day_str}."
    )
    risk_obs = (
        f"Profit factor of {profit_factor:.2f} with {pos_days}/{n_sessions} positive trading days. "
        f"Max daily drawdown held tightly at {max_daily_dd:+.2f}R."
    )

    # Audit status
    if weekly_net_r > 0 and profit_factor >= 2.0:
        audit_status = "STABLE"
    elif weekly_net_r > 0:
        audit_status = "REVIEW"
    else:
        audit_status = "ACTION REQUIRED"

    # Next audit date (following Friday)
    next_audit_dt = friday_dt + timedelta(days=7)
    next_audit_str = next_audit_dt.strftime("%d-%m-%Y")

    # 10. Assemble complete Markdown text adhering strictly to template
    report = (
        "=================================================\n"
        "📊 **NSE-PULSE V13: WEEKLY EOD PERFORMANCE AUDIT**\n"
        f"📅 Week: {start_date_str} → {end_date_str} | Sessions: {n_sessions} | Overall Bias: {overall_bias}\n"
        "======================================================================\n\n"
        "📆 **WEEKLY SESSION COVERAGE:**\n"
        f"• Trading Sessions Audited : {n_sessions}\n"
        f"• Active Trading Days      : {n_sessions}\n"
        f"• Signals Triggered        : {total_signals}\n"
        f"• Avg Signals / Day        : {avg_signals_day:.1f}\n"
        f"• Best Signal Day          : {best_sig_day_str}\n"
        f"• Lowest Signal Day        : {lowest_sig_day_str}\n"
        f"• Weekly Net R-Multiple    : {weekly_net_r:+.2f} R\n"
        f"• Avg R / Trading Day      : {avg_r_day:+.2f} R\n\n"
        "-------------------------------------------------\n"
        "⚡ **EXECUTION LIFECYCLE BREAKDOWN (Weekly Timing Accuracy):**\n"
        "-------------------------------------------------\n"
        f"• ⚡ Early Triggers (0–25% Prog)    : {early_count} ({early_pct}% - Golden Entry)\n"
        f"• 🎯 Actionable Plays (25–75% Prog) : {actionable_count} ({actionable_pct}% - Continuation)\n"
        f"• ⏳ Near Target (75–99% Prog)      : {near_target_count} ({near_target_pct}% - Trailing Zone)\n"
        f"• 🏆 Target 1 Hit (≥ 100% Prog)     : {target_hit_count} ({target_hit_pct}% - Accomplished)\n\n"
        f"• Best Early-Catch Day             : {best_early_day_str}\n"
        f"• Best T1 Conversion Day           : {best_t1_day_str}\n"
        f"• Best Overall Execution Day       : {best_exec_day_str}\n\n"
        "-------------------------------------------------\n"
        "📱 **TELEGRAM LIVE ALERTS SCORECARD (Weekly Real-World Traded):**\n"
        "⚙️ Active Alerts Triggered on Phone During Week\n"
        "-------------------------------------------------\n"
        f"• Total Dispatched Alerts : {tg_metrics['total_dispatched']} (100%)\n"
        f"• Target 1 Only Wins      : {tg_metrics['t1_only']} ({tg_metrics['t1_only_pct']}%)\n"
        f"• Target 2 Runners        : {tg_metrics['t2_runners']} ({tg_metrics['t2_rate_pct']}% Deep Trend)\n"
        f"• Total Target Wins       : {tg_metrics['total_target_wins']} ({tg_metrics['win_rate_pct']}% Win Rate)\n"
        f"• Stop Loss (SL Hit)      : {tg_metrics['sl_losses']} ({tg_metrics['sl_loss_pct']}% Loss Rate)\n"
        f"• EOD Auto-Settled (MTM)  : {tg_metrics['eod_settled']} ({tg_metrics['eod_settled_pct']}%)\n"
        f"├─ 🟢 Closed in Profit  : {tg_metrics['eod_p']} ({tg_metrics['eod_p_pct']}%)\n"
        f"├─ 🔴 Closed in Loss    : {tg_metrics['eod_l']} ({tg_metrics['eod_l_pct']}%)\n"
        f"└─ ⚪ Closed Flat (C2C) : {tg_metrics['eod_f']} ({tg_metrics['eod_f_pct']}%)\n"
        f"• Open at Week End        : {tg_metrics['open']} ({tg_metrics['open_pct']}%)\n"
        f"• Net Realized R-Multiple : {tg_metrics['net_realized_r']:+.2f} R\n"
        f"• Avg Realized R / Alert  : {tg_metrics['avg_realized_r']:+.2f} R\n\n"
        "-------------------------------------------------\n"
        "🏆 **QUALITY TIER BREAKDOWN (Weekly Peak Score):**\n"
        "-------------------------------------------------\n\n"
        "🥇 **HIGH CONFIDENCE (Peak Score ≥ 85):**\n"
        f"• Total Setups         : {hc['total']}\n"
        f"• % of Weekly Setups   : {hc['pct_weekly']}%\n"
        f"• Early Caught         : {hc['early_caught']} ({hc['early_pct']}% Caught at Base)\n"
        f"• Target 1 (Only)      : {hc['t1_only']} ({hc['t1_only_pct']}% T1 Win)\n"
        f"• Target 2 Runners     : {hc['t2_hit']} ({hc['t2_pct']}% T2 Runner Rate)\n"
        f"• Stop Loss (SL)       : {hc['sl_hit']} ({hc['sl_pct']}% SL Loss Rate)\n"
        f"• EOD Auto-Settled      : {hc['eod_settled']} ({hc['eod_settled_pct']}% MTM Settled)\n"
        f"├─ 🟢 Closed in Profit : {hc['eod_p']} ({hc['eod_p_pct']}%)\n"
        f"├─ 🔴 Closed in Loss   : {hc['eod_l']} ({hc['eod_l_pct']}%)\n"
        f"└─ ⚪ Closed Flat (C2C): {hc['eod_f']} ({hc['eod_f_pct']}%)\n"
        f"• Open at Week End      : {hc['open']} ({hc['open_pct']}%)\n\n"
        "🥈 **STRONG SETUPS (Peak Score 80–84.9):**\n"
        f"• Total Setups         : {st['total']}\n"
        f"• % of Weekly Setups   : {st['pct_weekly']}%\n"
        f"• Early Caught         : {st['early_caught']} ({st['early_pct']}% Caught at Base)\n"
        f"• Target 1 (Only)      : {st['t1_only']} ({st['t1_only_pct']}% T1 Win)\n"
        f"• Target 2 Runners     : {st['t2_hit']} ({st['t2_pct']}% T2 Runner Rate)\n"
        f"• Stop Loss (SL)       : {st['sl_hit']} ({st['sl_pct']}% SL Loss Rate)\n"
        f"• EOD Auto-Settled      : {st['eod_settled']} ({st['eod_settled_pct']}% MTM Settled)\n"
        f"├─ 🟢 Closed in Profit : {st['eod_p']} ({st['eod_p_pct']}%)\n"
        f"├─ 🔴 Closed in Loss   : {st['eod_l']} ({st['eod_l_pct']}%)\n"
        f"└─ ⚪ Closed Flat (C2C): {st['eod_f']} ({st['eod_f_pct']}%)\n"
        f"• Open at Week End      : {st['open']} ({st['open_pct']}%)\n\n"
        "🥉 **WATCHLIST (Peak Score 72–79.9):**\n"
        f"• Total Setups         : {wl['total']}\n"
        f"• % of Weekly Setups   : {wl['pct_weekly']}%\n"
        f"• Early Caught         : {wl['early_caught']} ({wl['early_pct']}% Caught at Base)\n"
        f"• Target 1 (Only)      : {wl['t1_only']} ({wl['t1_only_pct']}% T1 Win)\n"
        f"• Target 2 Runners     : {wl['t2_hit']} ({wl['t2_pct']}% T2 Runner Rate)\n"
        f"• Stop Loss (SL)       : {wl['sl_hit']} ({wl['sl_pct']}% SL Loss Rate)\n"
        f"• EOD Auto-Settled      : {wl['eod_settled']} ({wl['eod_settled_pct']}% MTM Settled)\n"
        f"├─ 🟢 Closed in Profit : {wl['eod_p']} ({wl['eod_p_pct']}%)\n"
        f"├─ 🔴 Closed in Loss   : {wl['eod_l']} ({wl['eod_l_pct']}%)\n"
        f"└─ ⚪ Closed Flat (C2C): {wl['eod_f']} ({wl['eod_f_pct']}%)\n"
        f"• Open at Week End      : {wl['open']} ({wl['open_pct']}%)\n\n"
        "=================================================\n"
        "🎯 **TOTAL WEEKLY ACCURACY & PERFORMANCE METRICS:**\n"
        f"• Total Signals Triggered : {total_signals} (100%)\n"
        f"• Target 1 Only Wins      : {t1_only} ({t1_only_pct}% T1 Win Rate)\n"
        f"• Target 2 Runners        : {t2_runners} ({t2_rate_pct}% Deep Trend Wins)\n"
        f"• Total Target Wins       : {t1_total_hits} ({win_rate_pct}% Combined Win Rate)\n"
        f"• Total Losses (SL Hit)   : {sl_losses} ({sl_loss_pct}% Loss Rate)\n"
        f"• EOD Auto-Settled (MTM)  : {eod_settled} ({eod_settled_pct}%)\n"
        f"├─ 🟢 Closed in Profit  : {eod_profits} ({eod_profit_pct}%)\n"
        f"├─ 🔴 Closed in Loss    : {eod_losses} ({eod_loss_pct}%)\n"
        f"└─ ⚪ Closed Flat (C2C) : {eod_flats} ({eod_flat_pct}%)\n"
        f"• Open at Week End        : {open_eod} ({open_pct}% Unrealized)\n"
        f"• Net Realized R-Multiple : {weekly_net_r:+.2f} R\n"
        f"• Avg R / Trading Day     : {avg_r_day:+.2f} R\n"
        f"• Avg R / Signal          : {avg_r_sig:+.2f} R\n"
        f"• Profit Factor           : {profit_factor:.2f}\n"
        f"• Max Daily Drawdown      : {max_daily_dd:+.2f} R\n"
        f"• Best Daily Result       : {best_daily_r:+.2f} R\n"
        f"• Worst Daily Result      : {worst_daily_r:+.2f} R\n\n"
        "-------------------------------------------------\n"
        "📅 **DAY-BY-DAY PERFORMANCE:**\n"
        "-------------------------------------------------\n"
        f"{day_by_day_str}\n\n"
        "-------------------------------------------------\n"
        "🔍 **WEEKLY AUDIT — SIGNAL QUALITY:**\n"
        "-------------------------------------------------\n"
        f"• High Confidence Conversion : {hc['t1_pct']}%\n"
        f"• Strong Setup Conversion    : {st['t1_pct']}%\n"
        f"• Watchlist Conversion       : {wl['t1_pct']}%\n"
        f"• Early Entry Capture Rate   : {early_pct}%\n"
        f"• T1 Conversion Rate         : {win_rate_pct}%\n"
        f"• T2 Runner Rate             : {t2_rate_pct}%\n"
        f"• SL Rate                    : {sl_loss_pct}%\n"
        f"• MTM Settlement Rate        : {eod_settled_pct}%\n"
        f"• Flat/C2C Rate              : {eod_flat_pct}%\n\n"
        f"📌 **Best Performing Quality Tier:** {best_tier}\n"
        f"📌 **Highest T2 Conversion Tier:** {highest_t2_tier}\n"
        f"📌 **Lowest SL Rate Tier:** {lowest_sl_tier}\n\n"
        "-------------------------------------------------\n"
        "📈 **WEEKLY RISK & CONSISTENCY AUDIT:**\n"
        "-------------------------------------------------\n"
        f"• Positive Days              : {pos_days} / {n_sessions} ({round(pos_days/n_sessions*100, 1)}%)\n"
        f"• Negative Days              : {neg_days} / {n_sessions} ({round(neg_days/n_sessions*100, 1)}%)\n"
        f"• Flat Days                  : {flat_days} / {n_sessions} ({round(flat_days/n_sessions*100, 1)}%)\n"
        f"• Consecutive Positive Days  : {max_consec_pos}\n"
        f"• Consecutive Negative Days  : {max_consec_neg}\n"
        f"• Max Daily Drawdown         : {max_daily_dd:+.2f} R\n"
        f"• Max Weekly Drawdown        : {max_weekly_dd:+.2f} R\n"
        f"• Weekly R Volatility        : {weekly_vol:.2f} R\n"
        f"• R-Multiple Range           : {worst_daily_r:+.2f} R → {best_daily_r:+.2f} R\n\n"
        "-------------------------------------------------\n"
        "🚀 **TOP 10 WINNERS OF THE WEEK:**\n"
        "-------------------------------------------------\n\n"
        f"{top_10_str}\n\n"
        "-------------------------------------------------\n"
        "⚠️ **TOP 5 LOSS / FAILURE PATTERNS:**\n"
        "-------------------------------------------------\n\n"
        f"{top_5_loss_str}\n\n"
        "-------------------------------------------------\n"
        "🧠 **WEEKLY AUDIT SUMMARY:**\n"
        "-------------------------------------------------\n"
        f"• Total Setups             : {total_signals}\n"
        f"• Total Target Wins        : {t1_total_hits} ({win_rate_pct}%)\n"
        f"• Total SL Losses          : {sl_losses} ({sl_loss_pct}%)\n"
        f"• MTM Settlements          : {eod_settled} ({eod_settled_pct}%)\n"
        f"• Net Realized R           : {weekly_net_r:+.2f} R\n"
        f"• Avg R / Day              : {avg_r_day:+.2f} R\n"
        f"• Avg R / Signal           : {avg_r_sig:+.2f} R\n\n"
        f"🔹 **Execution Strength:** {exec_strength_obs}\n"
        f"🔹 **Main Leakage:** {main_leakage_obs}\n"
        f"🔹 **Quality Tier Observation:** {tier_obs}\n"
        f"🔹 **Timing Observation:** {timing_obs}\n"
        f"🔹 **Risk Observation:** {risk_obs}\n\n"
        "=================================================\n"
        f"📌 **WEEKLY AUDIT STATUS:** [{audit_status}]\n"
        f"📅 Next Audit: {next_audit_str}\n"
        "================================================="
    )

    summary_data = {
        "week_range": f"{start_date_str} to {end_date_str}",
        "week_str": week_str,
        "sessions": n_sessions,
        "overall_bias": overall_bias,
        "total_signals": total_signals,
        "weekly_net_r": weekly_net_r,
        "profit_factor": profit_factor,
        "win_rate_pct": win_rate_pct,
        "telegram_scorecard": tg_metrics,
        "daily_breakdown": daily_stats,
        "top_10_winners": [
            {
                "symbol": s.get("symbol"),
                "direction": s.get("direction"),
                "entry_price": s.get("entry_price"),
                "ltp": s.get("ltp"),
                "gain_pct": s.get("gain_pct"),
                "realized_r": s.get("realized_r"),
                "highest_progress_pct": s.get("highest_progress_pct"),
            }
            for s in unique_winners
        ],
        "top_5_losses": [
            {
                "symbol": s.get("symbol"),
                "direction": s.get("direction"),
                "realized_r": s.get("realized_r"),
                "reason": _determine_failure_reason(s),
            }
            for s in unique_losses
        ],
        "sector_performance": {
            "heroes": sector_heroes,
            "zeroes": sector_zeroes,
        },
        "time_window_stats": time_window_stats,
        "regime_scorecard": regime_scorecard,
        "audit_status": audit_status,
        "next_audit": next_audit_str,
        "generated_at": datetime.now(IST_TZ).isoformat(),
    }

    return report, summary_data


def save_weekly_audit(week_str: str, report_text: str, data: Dict[str, Any]) -> str:
    """Save weekly audit to backend/app/data/weekly performance history/."""
    os.makedirs(WEEKLY_HISTORY_DIR, exist_ok=True)
    json_path = os.path.join(WEEKLY_HISTORY_DIR, f"weekly_audit_{week_str}.json")
    md_path = os.path.join(WEEKLY_HISTORY_DIR, f"weekly_audit_{week_str}.md")

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(report_text)
        logger.info(f"Saved weekly audit to {json_path} and {md_path}")
        return json_path
    except Exception as e:
        logger.error(f"Failed to save weekly audit: {e}")
        return ""


def dispatch_weekly_audit_to_telegram(target_dt: Optional[datetime] = None) -> bool:
    """
    Generate weekly performance audit, save Markdown/JSON to history,
    generate institutional-grade PDF, and dispatch PDF report to Telegram.
    """
    from .telegram_bot import send_telegram_document
    from .v13_weekly_pdf import generate_weekly_pdf

    report_text, summary_data = generate_weekly_eod_report(target_dt)
    if not summary_data.get("total_signals"):
        logger.info("Weekly audit skipped: 0 signals recorded this week.")
        return False

    week_str = summary_data.get("week_str", "current_week")
    save_weekly_audit(week_str, report_text, summary_data)

    # 1. Generate PDF in WEEKLY_HISTORY_DIR
    pdf_path = os.path.join(WEEKLY_HISTORY_DIR, f"weekly_audit_{week_str}.pdf")
    try:
        generate_weekly_pdf(summary_data, pdf_path)
    except Exception as pe:
        logger.error(f"Failed to generate weekly PDF audit: {pe}")
        return False

    # 2. Executive Telegram Caption
    tg_sc = summary_data.get("telegram_scorecard", {})
    caption = (
        "📊 *NSE-PULSE V13: WEEKLY PERFORMANCE AUDIT*\n"
        f"📅 *Week:* {summary_data.get('week_range')} | *Bias:* {summary_data.get('overall_bias')}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *Engine Signals:* {summary_data.get('total_signals'):,} | *Win Rate:* {summary_data.get('win_rate_pct')}%\n"
        f"💰 *Net Realized R:* +{summary_data.get('weekly_net_r'):,.2f} R | *Profit Factor:* {summary_data.get('profit_factor')}\n"
        f"📱 *Telegram Live Alerts:* {tg_sc.get('total_dispatched')} alerts (+{tg_sc.get('net_realized_r'):+.2f} R)\n"
        f"📌 *Weekly Audit Status:* [{summary_data.get('audit_status')}]\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📄 *Complete Institutional Audit PDF attached below:*"
    )

    return send_telegram_document(pdf_path, caption=caption)

