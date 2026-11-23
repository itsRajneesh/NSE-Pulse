"""
V13 Live Movers: Dedicated 20-EMA High-Tight Flag & Breakdown Telegram Notification Bot.
Supports multi-recipient broadcast, strict session deduplication, and isolated queue dispatch.
"""
import json
import logging
import os
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import pytz

IST_TZ = pytz.timezone("Asia/Kolkata")
logger = logging.getLogger("v13_live_movers_telegram")

CACHE_DIR = os.path.join(os.path.dirname(__file__), "data", "telegram notification audit")
CACHE_FILE = os.path.join(CACHE_DIR, "sent_live_movers_alerts_cache.json")

# In-memory alert cache guarded by a lock
# Key: f"{symbol}_{direction}" -> {symbol, direction, score, price, timestamp, date}
_ALERT_LOCK = threading.Lock()
_SENT_ALERTS: Dict[str, Dict[str, Any]] = {}
_CACHE_LOADED = False


def _get_env_path() -> str:
    """Locate backend/.env safely."""
    backend_dir = os.path.dirname(os.path.dirname(__file__))
    env_path = os.path.join(backend_dir, ".env")
    if os.path.exists(env_path):
        return env_path
    root_dir = os.path.dirname(backend_dir)
    env_path = os.path.join(root_dir, ".env")
    if os.path.exists(env_path):
        return env_path
    return ".env"


def get_live_movers_telegram_config() -> Tuple[bool, str, List[str], float, float]:
    """
    Dynamically reloads .env on every call to support live threshold and chat ID changes
    without requiring a server restart.
    Returns: (enabled, bot_token, chat_ids, min_score, cooldown_minutes)
    """
    try:
        from dotenv import load_dotenv
        env_file = _get_env_path()
        if os.path.exists(env_file):
            load_dotenv(env_file, override=True)
        else:
            load_dotenv(override=True)
    except Exception as e:
        logger.debug(f"dotenv load notice in live movers telegram: {e}")

    enabled = os.getenv("TELEGRAM_LIVE_MOVERS_ENABLED", "true").lower() in ("true", "1", "yes")
    bot_token = os.getenv("TELEGRAM_LIVE_MOVERS_BOT_TOKEN", "").strip()

    raw_chat = os.getenv("TELEGRAM_LIVE_MOVERS_CHAT_ID", "").strip() or os.getenv("TELEGRAM_LIVE_MOVERS_CHAT_IDS", "").strip()
    chat_ids = [cid.strip() for cid in raw_chat.split(",") if cid.strip()]

    try:
        min_score = float(str(os.getenv("TELEGRAM_LIVE_MOVERS_MIN_SCORE", "65.0")).replace("%", "").strip())
    except (TypeError, ValueError):
        min_score = 65.0

    try:
        cooldown_min = float(str(os.getenv("TELEGRAM_LIVE_MOVERS_COOLDOWN_MINUTES", "90.0")).strip())
    except (TypeError, ValueError):
        cooldown_min = 90.0

    return enabled, bot_token, chat_ids, min_score, cooldown_min


def _load_sent_alerts_cache() -> Dict[str, Dict[str, Any]]:
    """Load sent alert records from JSON cache file."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        now = time.time()
        today_date = datetime.now(IST_TZ).strftime("%Y-%m-%d")
        valid: Dict[str, Dict[str, Any]] = {}
        for key, item in data.items():
            if not isinstance(item, dict):
                continue
            item_date = item.get("date")
            ts = float(item.get("timestamp", 0))
            # Keep records from today or within last 24h
            if item_date == today_date or (now - ts < 86400):
                valid[key] = item
        return valid
    except Exception as e:
        logger.warning(f"Failed to load live movers alert cache from disk: {e}")
        return {}


def _save_sent_alerts_cache(cache: Dict[str, Dict[str, Any]]) -> None:
    """Atomically save sent alerts cache to disk JSON file."""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp_file = f"{CACHE_FILE}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
        os.replace(tmp_file, CACHE_FILE)
    except Exception as e:
        logger.warning(f"Failed to persist live movers alert cache to disk: {e}")


def _ensure_cache_loaded():
    global _SENT_ALERTS, _CACHE_LOADED
    if not _CACHE_LOADED:
        with _ALERT_LOCK:
            if not _CACHE_LOADED:
                _SENT_ALERTS = _load_sent_alerts_cache()
                _CACHE_LOADED = True


def _escape_md(text: Any) -> str:
    """Escape Telegram legacy Markdown reserved characters."""
    if text is None:
        return ""
    s = str(text)
    for ch in ("_", "*", "`", "["):
        s = s.replace(ch, f"\\{ch}")
    return s


def _format_inr(val: Optional[float]) -> str:
    if val is None:
        return "₹—"
    return f"₹{val:,.2f}"


def format_live_mover_message(
    item: Dict[str, Any], 
    is_long: bool,
    market_context: Optional[Dict[str, Any]] = None,
    universe: Optional[List[Any]] = None,
) -> str:
    """
    Format an institutional Markdown card for Telegram alerts with a dynamic
    3-tier top directional/warning banner and real-time conviction scorecard.
    Mutates item['conviction_grade'] and item['conviction_score'] in-place.
    """
    sym = item.get("symbol", "UNKNOWN")
    name = _escape_md(item.get("name", sym))
    sector = _escape_md(item.get("sector", "NSE Equity"))
    rank = item.get("rank") or item.get("nse_rank") or "—"
    price = item.get("price") or 0.0
    change_pct = float(item.get("change_pct", 0.0))
    v13_score = float(item.get("v13_score", 0.0))
    rel_vol = float(item.get("rel_vol", 1.0))
    ema20 = item.get("ema20")
    vwap = item.get("vwap")
    turnover_cr = item.get("turnover_cr", 0.0)
    rsi14 = item.get("rsi14", 50.0)

    tp = item.get("trade_plan") or {}
    entry = tp.get("entry") or price
    sl = tp.get("stop_loss")
    t1 = tp.get("target_1")
    t2 = tp.get("target_2")
    risk_amt = tp.get("risk_amount")
    live_risk = tp.get("live_risk") or risk_amt

    now_str = datetime.now(IST_TZ).strftime("%I:%M:%S %p IST")

    # 1. Pre-evaluate 3-Pillar Conviction BEFORE building the top banner
    conv_block = ""
    grade = "GRADE_B"
    try:
        from .v13_conviction import evaluate_conviction, format_conviction_block, is_conviction_rating_enabled
        if is_conviction_rating_enabled():
            sig_dict = dict(item)
            sig_dict["direction"] = "BULLISH" if is_long else "BEARISH"
            sig_dict["score"] = v13_score
            conv_data = evaluate_conviction(sig_dict, market_context=market_context, universe=universe)
            grade = str(conv_data.get("grade") or "GRADE_B")
            conv_block = format_conviction_block(conv_data)
            item["conviction_grade"] = grade
            item["conviction_score"] = conv_data.get("total_score")
        else:
            item["conviction_grade"] = grade
    except Exception as e:
        logger.debug(f"Conviction evaluation in live movers skipped: {e}")
        item["conviction_grade"] = grade

    # 2. Dynamic 3-Tier Top Banner (Prevents impulsively trading Grade C trap setups)
    if grade == "GRADE_C":
        if is_long:
            top_badge = "🟢⚠️ 【 WATCH ONLY / DO NOT TRADE • TRAP RISK 】 ⚠️🟢"
            header = "⚠️ *[V13 CONFLUENCE: LOW CONVICTION LONG WATCH]*"
            rank_desc = f"#{rank} Top Gainer"
            plan_title = "📐 *REFERENCE LEVELS (DO NOT EXECUTE)*"
            sl_note = "20-EMA Structural Floor"
            trigger_desc = "Official NSE Top Gainer + V13 Score (⚠️ Blocked by Grade C Trap Filter)"
        else:
            top_badge = "🔴⚠️ 【 WATCH ONLY / DO NOT TRADE • TRAP RISK 】 ⚠️🔴"
            header = "⚠️ *[V13 CONFLUENCE: LOW CONVICTION SHORT WATCH]*"
            rank_desc = f"#{rank} Top Loser"
            plan_title = "📐 *REFERENCE LEVELS (DO NOT EXECUTE)*"
            sl_note = "20-EMA Structural Ceiling"
            trigger_desc = "Official NSE Top Loser + V13 Score (⚠️ Blocked by Grade C Trap Filter)"
    else:
        if is_long:
            top_badge = "🟢🔥 【 A+ HIGH CONVICTION • BUY / LONG 】 🔥🟢" if grade == "GRADE_A_PLUS" else "🟢 【 BUY / LONG SETUP 】 🟢"
            header = "🚀 *[V13 DUAL CONFLUENCE: 20-EMA LONG]*"
            rank_desc = f"#{rank} Top Gainer"
            plan_title = "🎯 *20-EMA HIGH-TIGHT FLAG EXECUTION PLAN*"
            sl_note = "20-EMA Structural Floor"
            trigger_desc = "Official NSE Top Gainer + V13 High Score + 20-EMA Flag"
        else:
            top_badge = "🔴🔥 【 A+ HIGH CONVICTION • SELL / SHORT 】 🔥🔴" if grade == "GRADE_A_PLUS" else "🔴 【 SELL / SHORT SETUP 】 🔴"
            header = "📉 *[V13 DUAL CONFLUENCE: 20-EMA SHORT]*"
            rank_desc = f"#{rank} Top Loser"
            plan_title = "🎯 *20-EMA BEAR BREAKDOWN EXECUTION PLAN*"
            sl_note = "20-EMA Structural Ceiling"
            trigger_desc = "Official NSE Top Loser + V13 High Score + 20-EMA Breakdown"

    lines = [
        top_badge,
        header,
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📌 *Stock*: `{sym}` ({name})",
        f"🏷️ *Sector*: {sector} • *NSE Rank*: {rank_desc}",
        f"⚡ *V13 Score*: *{v13_score:.1f}/100* (ACTIVE QUALIFIED)",
        f"💰 *Live Price*: *{_format_inr(price)}* ({change_pct:+.2f}%) • *RelVol*: `{rel_vol:.2f}x`",
        "",
        plan_title,
        f"  📍 *Entry Price*: `{_format_inr(entry)}`",
        f"  🛡️ *Stop Loss (SL)*: `{_format_inr(sl)}` ({sl_note} • Risk: {_format_inr(risk_amt)}/sh)",
        f"  🎯 *Target 1 (1:1.5 RR)*: `{_format_inr(t1)}`",
        f"  🎯 *Target 2 (1:2.5 RR)*: `{_format_inr(t2)}`",
        f"  📏 *Live Risk*: `{_format_inr(live_risk)}`",
        "",
        "📊 *CONFLUENCE METRICS*",
        f"  📈 *20-EMA*: `{_format_inr(ema20)}` | *VWAP*: `{_format_inr(vwap)}`",
        f"  ⚡ *RSI(14)*: `{rsi14:.1f}` | *Turnover*: `₹{turnover_cr:,.1f} Cr`",
    ]

    if conv_block:
        lines.append(conv_block)

    lines.extend([
        "",
        f"💡 *Trigger*: {trigger_desc}",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"⏰ {now_str} • NSE Live Movers",
    ])
    return "\n".join(lines)


LIVE_MOVERS_LEDGER_FILE = os.path.join(CACHE_DIR, "live_movers_session_ledger.json")
_LEDGER_LOCK = threading.Lock()
_EOD_AUDIT_SENT_DATE: Optional[str] = None


def record_live_mover_ledger_entry(
    item: Dict[str, Any],
    direction: str,
    grade: str,
) -> None:
    """
    Persist dispatched Live Movers alerts to an isolated session ledger for EOD auditability.
    Grade A+ and Grade B are logged as active tradeable setups ('OPEN');
    Grade C is logged as 'SKIPPED_GRADE_C' (is_tradeable=False) to prevent win-rate pollution.
    """
    tp = item.get("trade_plan") or {}
    if not tp:
        return

    today_str = datetime.now(IST_TZ).strftime("%Y-%m-%d")
    now_iso = datetime.now(IST_TZ).isoformat()
    sym = str(item.get("symbol", "")).strip().upper()
    record_key = f"{today_str}_{sym}_{direction}"

    entry_price = float(tp.get("entry") or item.get("price") or item.get("ltp") or 0.0)
    cur_ltp = float(item.get("price") or item.get("ltp") or entry_price)

    entry_record = {
        "symbol": sym,
        "direction": direction,
        "date": today_str,
        "alerted_at": now_iso,
        "v13_score": round(float(item.get("v13_score") or 0.0), 1),
        "conviction_grade": grade,
        "conviction_score": item.get("conviction_score"),
        "entry": round(entry_price, 2),
        "stop_loss": tp.get("stop_loss"),
        "target_1": tp.get("target_1"),
        "target_2": tp.get("target_2"),
        "risk_amount": tp.get("risk_amount"),
        "ltp": round(cur_ltp, 2),
        "max_ltp_since_alert": round(cur_ltp, 2),
        "min_ltp_since_alert": round(cur_ltp, 2),
        "t1_progress_pct": 0.0,
        "highest_progress_pct": 0.0,
        "t1_was_hit": False,
        "outcome": "SKIPPED_GRADE_C" if grade == "GRADE_C" else "OPEN",
        "outcome_time": None,
        "is_tradeable": grade in ("GRADE_A_PLUS", "GRADE_B"),
        "realized_r": 0.0,
    }

    with _LEDGER_LOCK:
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            ledger_data: Dict[str, Any] = {}
            if os.path.exists(LIVE_MOVERS_LEDGER_FILE):
                with open(LIVE_MOVERS_LEDGER_FILE, "r", encoding="utf-8") as f:
                    ledger_data = json.load(f)

            # Upsert if not present or if conviction upgraded from GRADE_C to tradeable (A+/B)
            existing = ledger_data.get(record_key)
            if not existing or (existing.get("outcome") == "SKIPPED_GRADE_C" and grade != "GRADE_C"):
                ledger_data[record_key] = entry_record
                tmp_path = f"{LIVE_MOVERS_LEDGER_FILE}.tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(ledger_data, f, indent=2)
                os.replace(tmp_path, LIVE_MOVERS_LEDGER_FILE)
        except Exception as e:
            logger.warning(f"Failed to record live mover ledger entry: {e}")


def update_live_movers_ledger_outcomes(
    universe: Optional[List[Any]] = None,
    live_movers_items: Optional[List[Dict[str, Any]]] = None,
    now_dt: Optional[datetime] = None,
) -> int:
    """
    Update outcomes for today's tradeable Live Movers alerts using strictly POST-ALERT live LTPs.
    - Trap #1 Guard: NEVER compares against full-session Day High/Low (`snap["high"]` / `snap["low"]`),
      which include pre-alert morning price action from 09:15 AM. Strictly uses post-alert `live_ltp`
      (and `max_ltp_since_alert` / `min_ltp_since_alert` updated only from post-alert live ticks).
    - Trap #2 Guard: Prioritizes real-time NSE Live Movers feed LTPs (`live_movers_items` and
      `NSELiveVariationsFetcher`) over 15m universe snapshot prices.
    """
    effective_now = now_dt or datetime.now(IST_TZ)
    today_str = effective_now.strftime("%Y-%m-%d")
    now_iso = effective_now.isoformat()
    is_eod_settlement = (effective_now.hour > 15) or (effective_now.hour == 15 and effective_now.minute >= 30)

    # Build multi-tier live LTP map (Priority #1: live_movers_items, Priority #2: NSELiveVariationsFetcher, Priority #3: universe)
    live_ltp_map: Dict[str, float] = {}

    # Tier 3 (Base fallback): 15m Universe snapshot price
    if universe:
        for u in universe:
            if isinstance(u, dict):
                usym = str(u.get("symbol") or "").replace(".NS", "").strip().upper()
                snap = u.get("snapshot") if isinstance(u.get("snapshot"), dict) else {}
                u_price = u.get("ltp") or u.get("price") or snap.get("price")
                if usym and u_price:
                    try:
                        val = float(u_price)
                        if val > 0:
                            live_ltp_map[usym] = val
                    except (ValueError, TypeError):
                        pass

    # Tier 2: NSELiveVariationsFetcher in-memory real-time cache (if available)
    try:
        from .nse_live_movers import GLOBAL_NSE_FETCHER
        with GLOBAL_NSE_FETCHER._lock:
            for item in (GLOBAL_NSE_FETCHER._gainers_cache or []) + (GLOBAL_NSE_FETCHER._losers_cache or []):
                if isinstance(item, dict):
                    nsym = str(item.get("symbol") or "").replace(".NS", "").strip().upper()
                    nprice = item.get("ltp") or item.get("price")
                    if nsym and nprice:
                        try:
                            val = float(nprice)
                            if val > 0:
                                live_ltp_map[nsym] = val
                        except (ValueError, TypeError):
                            pass
    except Exception:
        pass

    # Tier 1 (Highest Priority): Fresh real-time Live Movers items passed directly from the 60s loop
    if live_movers_items:
        for m in live_movers_items:
            if isinstance(m, dict):
                msym = str(m.get("symbol") or "").replace(".NS", "").strip().upper()
                mprice = m.get("price") or m.get("ltp")
                if msym and mprice:
                    try:
                        val = float(mprice)
                        if val > 0:
                            live_ltp_map[msym] = val
                    except (ValueError, TypeError):
                        pass

    if not live_ltp_map and not is_eod_settlement:
        return 0

    updated_count = 0
    with _LEDGER_LOCK:
        try:
            if not os.path.exists(LIVE_MOVERS_LEDGER_FILE):
                return 0
            with open(LIVE_MOVERS_LEDGER_FILE, "r", encoding="utf-8") as f:
                ledger_data = json.load(f)

            dirty = False
            for key, rec in ledger_data.items():
                if not isinstance(rec, dict) or key.startswith("_"):
                    continue
                if rec.get("date") != today_str:
                    continue
                if not rec.get("is_tradeable", False):
                    continue

                cur_outcome = str(rec.get("outcome") or "OPEN")
                # Terminal outcomes are already locked
                if cur_outcome in (
                    "T2_HIT",
                    "T1_WIN_BE_EXIT",
                    "SL_HIT",
                    "CLOSED_EOD_PROFIT",
                    "CLOSED_EOD_LOSS",
                    "CLOSED_EOD_FLAT",
                    "EOD_PARTIAL_WIN",
                    "SKIPPED_GRADE_C",
                ):
                    continue

                sym = str(rec.get("symbol") or "").strip().upper()
                direction = str(rec.get("direction") or "LONG").upper()
                entry = float(rec.get("entry") or 0.0)
                sl = float(rec.get("stop_loss") or 0.0)
                t1 = float(rec.get("target_1") or 0.0)
                t2 = float(rec.get("target_2") or 0.0)
                risk = float(rec.get("risk_amount") or abs(entry - sl) or 0.0)
                if entry <= 0 or risk <= 0:
                    continue

                cur_ltp = live_ltp_map.get(sym) or float(rec.get("ltp") or entry)
                if cur_ltp <= 0:
                    cur_ltp = entry

                prev_max = float(rec.get("max_ltp_since_alert") or entry)
                prev_min = float(rec.get("min_ltp_since_alert") or entry)
                post_max = max(prev_max, cur_ltp)
                post_min = min(prev_min, cur_ltp)

                rec["ltp"] = round(cur_ltp, 2)
                rec["max_ltp_since_alert"] = round(post_max, 2)
                rec["min_ltp_since_alert"] = round(post_min, 2)

                is_long = direction in ("LONG", "BULLISH")
                t1_dist = abs(t1 - entry) if t1 > 0 else risk * 1.5
                if t1_dist > 0:
                    if is_long:
                        cur_prog = ((cur_ltp - entry) / t1_dist) * 100.0
                        best_prog = ((post_max - entry) / t1_dist) * 100.0
                    else:
                        cur_prog = ((entry - cur_ltp) / t1_dist) * 100.0
                        best_prog = ((entry - post_min) / t1_dist) * 100.0
                    rec["t1_progress_pct"] = round(cur_prog, 1)
                    rec["highest_progress_pct"] = round(max(float(rec.get("highest_progress_pct") or 0.0), best_prog), 1)

                t1_was_hit = bool(rec.get("t1_was_hit") or cur_outcome == "T1_HIT_TRAILED")

                if is_long:
                    # 1. Check T2 Hit (post-alert max LTP >= T2)
                    if t2 > 0 and post_max >= t2:
                        rec["t1_was_hit"] = True
                        rec["outcome"] = "T2_HIT"
                        rec["realized_r"] = 2.0
                        rec["outcome_time"] = rec.get("outcome_time") or now_iso
                        dirty = True
                        updated_count += 1
                        continue

                    # 2. Check T1 Hit (post-alert max LTP >= T1)
                    if t1 > 0 and post_max >= t1 and not t1_was_hit:
                        t1_was_hit = True
                        rec["t1_was_hit"] = True
                        rec["outcome"] = "T1_HIT_TRAILED"
                        rec["realized_r"] = 0.75
                        rec["outcome_time"] = rec.get("outcome_time") or now_iso
                        dirty = True
                        updated_count += 1

                    # 3. If T1 was already hit, check if price pulled back to Breakeven (entry) on current tick
                    if t1_was_hit:
                        if cur_ltp <= entry:
                            rec["outcome"] = "T1_WIN_BE_EXIT"
                            rec["realized_r"] = 0.75
                            rec["outcome_time"] = now_iso
                            dirty = True
                            updated_count += 1
                            continue
                        if is_eod_settlement:
                            rem_r = (cur_ltp - entry) / risk
                            rec["outcome"] = "EOD_PARTIAL_WIN"
                            rec["realized_r"] = round(0.375 + 0.5 * rem_r, 2)
                            rec["outcome_time"] = now_iso
                            dirty = True
                            updated_count += 1
                            continue
                    else:
                        # 4. Check Stop Loss Hit (post-alert min LTP <= SL)
                        if sl > 0 and post_min <= sl:
                            rec["outcome"] = "SL_HIT"
                            rec["realized_r"] = -1.0
                            rec["outcome_time"] = rec.get("outcome_time") or now_iso
                            dirty = True
                            updated_count += 1
                            continue

                        # 5. EOD Auto-Settlement at >= 15:30 IST
                        if is_eod_settlement:
                            mtm_r = round((cur_ltp - entry) / risk, 2)
                            if abs(mtm_r) <= 0.05:
                                rec["outcome"] = "CLOSED_EOD_FLAT"
                                rec["realized_r"] = 0.0
                            elif mtm_r > 0:
                                rec["outcome"] = "CLOSED_EOD_PROFIT"
                                rec["realized_r"] = mtm_r
                            else:
                                rec["outcome"] = "CLOSED_EOD_LOSS"
                                rec["realized_r"] = max(-1.0, mtm_r)
                            rec["outcome_time"] = now_iso
                            dirty = True
                            updated_count += 1
                else:
                    # SHORT trade evaluation
                    # 1. Check T2 Hit (post-alert min LTP <= T2)
                    if t2 > 0 and post_min <= t2:
                        rec["t1_was_hit"] = True
                        rec["outcome"] = "T2_HIT"
                        rec["realized_r"] = 2.0
                        rec["outcome_time"] = rec.get("outcome_time") or now_iso
                        dirty = True
                        updated_count += 1
                        continue

                    # 2. Check T1 Hit (post-alert min LTP <= T1)
                    if t1 > 0 and post_min <= t1 and not t1_was_hit:
                        t1_was_hit = True
                        rec["t1_was_hit"] = True
                        rec["outcome"] = "T1_HIT_TRAILED"
                        rec["realized_r"] = 0.75
                        rec["outcome_time"] = rec.get("outcome_time") or now_iso
                        dirty = True
                        updated_count += 1

                    # 3. If T1 was already hit, check if price pulled back to Breakeven (entry)
                    if t1_was_hit:
                        if cur_ltp >= entry:
                            rec["outcome"] = "T1_WIN_BE_EXIT"
                            rec["realized_r"] = 0.75
                            rec["outcome_time"] = now_iso
                            dirty = True
                            updated_count += 1
                            continue
                        if is_eod_settlement:
                            rem_r = (entry - cur_ltp) / risk
                            rec["outcome"] = "EOD_PARTIAL_WIN"
                            rec["realized_r"] = round(0.375 + 0.5 * rem_r, 2)
                            rec["outcome_time"] = now_iso
                            dirty = True
                            updated_count += 1
                            continue
                    else:
                        # 4. Check Stop Loss Hit (post-alert max LTP >= SL)
                        if sl > 0 and post_max >= sl:
                            rec["outcome"] = "SL_HIT"
                            rec["realized_r"] = -1.0
                            rec["outcome_time"] = rec.get("outcome_time") or now_iso
                            dirty = True
                            updated_count += 1
                            continue

                        # 5. EOD Auto-Settlement at >= 15:30 IST
                        if is_eod_settlement:
                            mtm_r = round((entry - cur_ltp) / risk, 2)
                            if abs(mtm_r) <= 0.05:
                                rec["outcome"] = "CLOSED_EOD_FLAT"
                                rec["realized_r"] = 0.0
                            elif mtm_r > 0:
                                rec["outcome"] = "CLOSED_EOD_PROFIT"
                                rec["realized_r"] = mtm_r
                            else:
                                rec["outcome"] = "CLOSED_EOD_LOSS"
                                rec["realized_r"] = max(-1.0, mtm_r)
                            rec["outcome_time"] = now_iso
                            dirty = True
                            updated_count += 1

            if dirty:
                tmp_path = f"{LIVE_MOVERS_LEDGER_FILE}.tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(ledger_data, f, indent=2)
                os.replace(tmp_path, LIVE_MOVERS_LEDGER_FILE)
        except Exception as e:
            logger.warning(f"Failed to update live movers ledger outcomes: {e}")

    return updated_count


def _compute_tier_stats(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(records)
    t1_only = sum(
        1 for r in records if r.get("outcome") in ("T1_HIT_TRAILED", "T1_WIN_BE_EXIT", "EOD_PARTIAL_WIN")
    )
    t2_runners = sum(1 for r in records if r.get("outcome") == "T2_HIT")
    t1_wins = t1_only + t2_runners
    sl_losses = sum(1 for r in records if r.get("outcome") == "SL_HIT")
    eod_profits = sum(1 for r in records if r.get("outcome") == "CLOSED_EOD_PROFIT")
    eod_losses = sum(1 for r in records if r.get("outcome") == "CLOSED_EOD_LOSS")
    eod_flats = sum(1 for r in records if r.get("outcome") == "CLOSED_EOD_FLAT")
    eod_settled = eod_profits + eod_losses + eod_flats
    open_cnt = sum(1 for r in records if r.get("outcome") == "OPEN")
    net_r = round(sum(float(r.get("realized_r") or 0.0) for r in records), 2)

    def _pct(val: int) -> float:
        return round((val / total) * 100.0, 1) if total > 0 else 0.0

    return {
        "total": total,
        "t1_only": t1_only,
        "t1_only_pct": _pct(t1_only),
        "t2": t2_runners,
        "t2_pct": _pct(t2_runners),
        "t1_wins": t1_wins,
        "win_rate_pct": _pct(t1_wins),
        "sl": sl_losses,
        "sl_pct": _pct(sl_losses),
        "eod_settled": eod_settled,
        "eod_settled_pct": _pct(eod_settled),
        "eod_profits": eod_profits,
        "eod_losses": eod_losses,
        "eod_flats": eod_flats,
        "open": open_cnt,
        "open_pct": _pct(open_cnt),
        "net_realized_r": net_r,
    }


def get_live_movers_eod_metrics(session_date: Optional[str] = None) -> Dict[str, Any]:
    """Compute EOD performance metrics for NSE Live Movers alerts on the specified session date."""
    target_date = session_date or datetime.now(IST_TZ).strftime("%Y-%m-%d")
    records: List[Dict[str, Any]] = []
    with _LEDGER_LOCK:
        if os.path.exists(LIVE_MOVERS_LEDGER_FILE):
            try:
                with open(LIVE_MOVERS_LEDGER_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for k, v in raw.items():
                    if isinstance(v, dict) and not k.startswith("_") and v.get("date") == target_date:
                        records.append(v)
            except Exception as e:
                logger.warning(f"Failed to read live movers ledger for metrics: {e}")

    tradeable = [r for r in records if r.get("is_tradeable", False)]
    grade_a_plus = [r for r in tradeable if r.get("conviction_grade") == "GRADE_A_PLUS"]
    grade_b = [r for r in tradeable if r.get("conviction_grade") == "GRADE_B"]
    skipped_grade_c = [r for r in records if r.get("conviction_grade") == "GRADE_C" or r.get("outcome") == "SKIPPED_GRADE_C"]

    ov = _compute_tier_stats(tradeable)
    a_stats = _compute_tier_stats(grade_a_plus)
    b_stats = _compute_tier_stats(grade_b)

    # Top 3 winners sorted by realized_r descending, then highest_progress_pct descending
    winners = sorted(
        [r for r in tradeable if float(r.get("realized_r") or 0.0) > 0],
        key=lambda x: (float(x.get("realized_r") or 0.0), float(x.get("highest_progress_pct") or 0.0)),
        reverse=True,
    )[:3]

    return {
        "session_date": target_date,
        "total_dispatched": len(records),
        "tradeable_count": len(tradeable),
        "skipped_grade_c_count": len(skipped_grade_c),
        "overall": ov,
        "grade_a_plus": a_stats,
        "grade_b": b_stats,
        "top_winners": winners,
        "records": records,
    }


def format_live_movers_eod_report(
    session_date: Optional[str] = None,
    market_regime: str = "Neutral",
    now_dt: Optional[datetime] = None,
) -> str:
    """
    Format the official NSE Live Movers EOD Performance Audit report for the
    dedicated 'NSE Live - Live Mover VIP' Telegram channel.
    """
    effective_now = now_dt or datetime.now(IST_TZ)
    target_date = session_date or effective_now.strftime("%Y-%m-%d")
    metrics = get_live_movers_eod_metrics(target_date)
    ov = metrics["overall"]
    ga = metrics["grade_a_plus"]
    gb = metrics["grade_b"]
    c_skipped = metrics["skipped_grade_c_count"]

    try:
        dt_fmt = datetime.strptime(target_date, "%Y-%m-%d").strftime("%d %b %Y")
    except Exception:
        dt_fmt = target_date

    winners = metrics.get("top_winners") or []
    if winners:
        top_lines = []
        for idx, w in enumerate(winners, 1):
            sym = _escape_md(w.get("symbol", "UNKNOWN"))
            d_str = "LONG" if str(w.get("direction", "LONG")).upper() in ("LONG", "BULLISH") else "SHORT"
            r_val = float(w.get("realized_r") or 0.0)
            out_lbl = str(w.get("outcome", "PROFIT")).replace("_", " ")
            grade_lbl = "A+" if w.get("conviction_grade") == "GRADE_A_PLUS" else "B"
            top_lines.append(f"   {idx}. *{sym}* ({d_str} | Grade {grade_lbl}) — *{out_lbl}* (`{r_val:+.2f} R`)")
        top_str = "\n".join(top_lines)
    else:
        top_str = "   • No realized winners recorded today"

    total_tr = ov["total"]
    eod_prof_pct = round((ov["eod_profits"] / total_tr) * 100.0, 1) if total_tr > 0 else 0.0
    eod_loss_pct = round((ov["eod_losses"] / total_tr) * 100.0, 1) if total_tr > 0 else 0.0
    eod_flat_pct = round((ov["eod_flats"] / total_tr) * 100.0, 1) if total_tr > 0 else 0.0
    safe_regime = _escape_md(market_regime)

    report = (
        "=================================================\n"
        f"📊 *NSE LIVE MOVERS — EOD PERFORMANCE AUDIT*\n"
        f"📅 *Session Date:* {dt_fmt} | *Regime:* {safe_regime}\n"
        "🤖 *Channel:* NSE Live - Live Mover VIP (20-EMA)\n"
        "=================================================\n\n"
        "🔥 *1. GRADE A+ CONVICTION ALERTS (75-100):*\n"
        f"   • Triggered Setups : {ga['total']}\n"
        f"   • Target 1 Wins    : {ga['t1_only']} ({ga['t1_only_pct']}%)\n"
        f"   • Target 2 Runners : {ga['t2']} ({ga['t2_pct']}%)\n"
        f"   • Stop Loss Hit    : {ga['sl']} ({ga['sl_pct']}%)\n"
        f"   • EOD Auto-Settled : {ga['eod_settled']} ({ga['eod_settled_pct']}% — {ga['eod_profits']}W / {ga['eod_losses']}L / {ga['eod_flats']}F)\n"
        f"   • Net Realized R   : {ga['net_realized_r']:+.2f} R\n\n"
        "⚡ *2. GRADE B MODERATE CONVICTION (55-74):*\n"
        f"   • Triggered Setups : {gb['total']}\n"
        f"   • Target 1 Wins    : {gb['t1_only']} ({gb['t1_only_pct']}%)\n"
        f"   • Target 2 Runners : {gb['t2']} ({gb['t2_pct']}%)\n"
        f"   • Stop Loss Hit    : {gb['sl']} ({gb['sl_pct']}%)\n"
        f"   • EOD Auto-Settled : {gb['eod_settled']} ({gb['eod_settled_pct']}% — {gb['eod_profits']}W / {gb['eod_losses']}L / {gb['eod_flats']}F)\n"
        f"   • Net Realized R   : {gb['net_realized_r']:+.2f} R\n\n"
        "🛡️ *3. GRADE C FILTERED (CAPITAL PROTECTED):*\n"
        f"   • Skipped Low-Conviction Alerts : {c_skipped} (0.00 R Risked)\n\n"
        "=================================================\n"
        "🎯 *TOTAL LIVE MOVERS SESSION ACCURACY & METRICS:*\n"
        f"   • Total Tradeable Alerts  : {ov['total']} (100%)\n"
        f"   • Target 1 Only Wins      : {ov['t1_only']} ({ov['t1_only_pct']}% T1 Win Rate)\n"
        f"   • Target 2 Runners        : {ov['t2']} ({ov['t2_pct']}% Deep Trend Wins)\n"
        f"   • Total Target Wins       : {ov['t1_wins']} ({ov['win_rate_pct']}% Combined Win Rate)\n"
        f"   • Total Losses (SL Hit)   : {ov['sl']} ({ov['sl_pct']}% Loss Rate)\n"
        f"   • EOD Auto-Settled (MTM)  : {ov['eod_settled']} ({ov['eod_settled_pct']}% Settled at 15:30)\n"
        f"     ├─ 🟢 Closed in Profit  : {ov['eod_profits']} ({eod_prof_pct}%)\n"
        f"     ├─ 🔴 Closed in Loss    : {ov['eod_losses']} ({eod_loss_pct}%)\n"
        f"     └─ ⚪ Closed Flat (C2C) : {ov['eod_flats']} ({eod_flat_pct}%)\n"
        f"   • Open at EOD             : {ov['open']} ({ov['open_pct']}% Unrealized)\n"
        f"   • Net Realized R-Multiple : {ov['net_realized_r']:+.2f} R\n\n"
        "🚀 *TOP 3 LIVE MOVER WINNERS OF THE DAY:*\n"
        f"{top_str}\n"
        "================================================="
    )

    try:
        from .nse_calendar import format_holiday_telegram_notice
        holiday_notice = format_holiday_telegram_notice(effective_now)
        if holiday_notice:
            report += f"\n\n{holiday_notice}"
    except Exception:
        pass

    return report


def dispatch_live_movers_eod_audit(
    market_regime: str = "Neutral",
    universe: Optional[List[Any]] = None,
    now_dt: Optional[datetime] = None,
    force: bool = False,
) -> bool:
    """
    Thread-safe, idempotent EOD Performance Audit dispatcher for NSE Live Movers.
    Sends exclusively to the dedicated 'NSE Live - Live Mover VIP' Telegram bot
    (using TELEGRAM_LIVE_MOVERS_BOT_TOKEN and TELEGRAM_LIVE_MOVERS_CHAT_ID).
    """
    global _EOD_AUDIT_SENT_DATE
    effective_now = now_dt or datetime.now(IST_TZ)
    today_str = effective_now.strftime("%Y-%m-%d")

    if not force and _EOD_AUDIT_SENT_DATE == today_str:
        return False

    with _LEDGER_LOCK:
        ledger_data: Dict[str, Any] = {}
        if os.path.exists(LIVE_MOVERS_LEDGER_FILE):
            try:
                with open(LIVE_MOVERS_LEDGER_FILE, "r", encoding="utf-8") as f:
                    ledger_data = json.load(f)
            except Exception:
                ledger_data = {}

        meta = ledger_data.get("_meta") if isinstance(ledger_data.get("_meta"), dict) else {}
        already_sent_date = meta.get("eod_audit_sent_date") or _EOD_AUDIT_SENT_DATE

        if not force and already_sent_date == today_str:
            _EOD_AUDIT_SENT_DATE = today_str
            return False

        # Check if there were any Live Movers alerts today before sending
        has_today_records = any(
            isinstance(v, dict) and not k.startswith("_") and v.get("date") == today_str
            for k, v in ledger_data.items()
        )
        if not force and not has_today_records:
            return False

        # Lock today's date BEFORE network I/O to prevent concurrent duplicate dispatches
        prev_sent_date = already_sent_date
        _EOD_AUDIT_SENT_DATE = today_str
        meta["eod_audit_sent_date"] = today_str
        meta["eod_audit_sent_at"] = effective_now.isoformat()
        ledger_data["_meta"] = meta
        try:
            tmp_path = f"{LIVE_MOVERS_LEDGER_FILE}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(ledger_data, f, indent=2)
            os.replace(tmp_path, LIVE_MOVERS_LEDGER_FILE)
        except Exception:
            pass

    # Ensure all open tradeable alerts are settled at 15:30 MTM before formatting
    try:
        update_live_movers_ledger_outcomes(universe=universe, now_dt=effective_now)
    except Exception as e:
        logger.warning(f"Live Movers pre-EOD outcome settlement warning: {e}")

    # Persist daily Live Movers EOD archive snapshot
    try:
        history_dir = os.path.join(os.path.dirname(__file__), "data", "EOD performance history")
        os.makedirs(history_dir, exist_ok=True)
        metrics_snap = get_live_movers_eod_metrics(today_str)
        arch_path = os.path.join(history_dir, f"live_movers_ledger_{today_str}.json")
        with open(arch_path, "w", encoding="utf-8") as af:
            json.dump(metrics_snap, af, indent=2)
    except Exception as e:
        logger.debug(f"Live Movers EOD archive write notice: {e}")

    report_text = format_live_movers_eod_report(
        session_date=today_str,
        market_regime=market_regime,
        now_dt=effective_now,
    )
    sent = send_live_movers_broadcast(report_text, sync_send=True)
    if sent:
        logger.info(f"[LIVE MOVERS EOD AUDIT] Dispatched EOD Performance Audit to NSE Live Mover VIP bot for {today_str}")
    else:
        # Rollback lock ONLY if all chat IDs failed so the next watchdog tick can retry
        with _LEDGER_LOCK:
            _EOD_AUDIT_SENT_DATE = prev_sent_date
            try:
                if os.path.exists(LIVE_MOVERS_LEDGER_FILE):
                    with open(LIVE_MOVERS_LEDGER_FILE, "r", encoding="utf-8") as f:
                        ldata = json.load(f)
                    m = ldata.get("_meta") if isinstance(ldata.get("_meta"), dict) else {}
                    m["eod_audit_sent_date"] = prev_sent_date
                    ldata["_meta"] = m
                    tmp_path = f"{LIVE_MOVERS_LEDGER_FILE}.tmp"
                    with open(tmp_path, "w", encoding="utf-8") as f:
                        json.dump(ldata, f, indent=2)
                    os.replace(tmp_path, LIVE_MOVERS_LEDGER_FILE)
            except Exception:
                pass
    return sent


def _send_http(bot_token: str, chat_id: str, message: str) -> bool:
    """Send message via Telegram Bot API with fallback to plain text if Markdown fails."""
    import ssl
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    def _open_req(req_obj):
        try:
            return urllib.request.urlopen(req_obj, timeout=10)
        except urllib.error.URLError as ue:
            if "CERTIFICATE_VERIFY_FAILED" in str(ue) or isinstance(getattr(ue, "reason", None), ssl.SSLError):
                return urllib.request.urlopen(req_obj, timeout=10, context=ssl._create_unverified_context())
            raise

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _open_req(req) as resp:
            resp_body = resp.read().decode("utf-8")
            res = json.loads(resp_body)
            return bool(res.get("ok"))
    except urllib.error.HTTPError as http_err:
        if http_err.code == 400:
            logger.warning(f"Live Movers Telegram Markdown parse error 400 for chat {chat_id}, falling back to plain text")
            try:
                plain_payload = {
                    "chat_id": chat_id,
                    "text": message.replace("*", "").replace("`", "").replace("\\", ""),
                    "disable_web_page_preview": True,
                }
                plain_data = json.dumps(plain_payload).encode("utf-8")
                plain_req = urllib.request.Request(
                    url,
                    data=plain_data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with _open_req(plain_req) as resp:
                    resp_body = resp.read().decode("utf-8")
                    res = json.loads(resp_body)
                    return bool(res.get("ok"))
            except Exception as fb_err:
                logger.error(f"Live Movers Telegram plain text fallback failed: {fb_err}")
                return False
        logger.error(f"Live Movers Telegram HTTP error {http_err.code}: {http_err}")
        return False
    except Exception as e:
        logger.error(f"Live Movers Telegram network error: {e}")
        return False


# Rate-limited queue worker for Live Movers bot (max 1 msg/sec to prevent HTTP 429)
_ALERT_QUEUE: "queue.Queue[Optional[Tuple[str, str, str]]]" = queue.Queue()
_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_LOCK = threading.Lock()


def _queue_worker():
    while True:
        try:
            item = _ALERT_QUEUE.get()
            if item is None:
                break
            bot_token, chat_id, message = item
            _send_http(bot_token, chat_id, message)
            time.sleep(1.0)
            _ALERT_QUEUE.task_done()
        except Exception as e:
            logger.error(f"Live Movers Telegram queue worker exception: {e}")
            time.sleep(1.0)


def _ensure_worker_started():
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is None or not _WORKER_THREAD.is_alive():
            _WORKER_THREAD = threading.Thread(
                target=_queue_worker,
                name="v13-live-movers-tg-worker",
                daemon=True,
            )
            _WORKER_THREAD.start()


def send_live_movers_broadcast(message: str, sync_send: bool = False) -> bool:
    """
    Broadcasts message to all configured chat IDs.
    If sync_send is True, sends synchronously (useful for test pings).
    Otherwise enqueues via rate-limited queue worker.
    """
    enabled, bot_token, chat_ids, _, _ = get_live_movers_telegram_config()
    if not enabled or not bot_token or not chat_ids:
        logger.info("Live Movers Telegram alerts not configured or disabled.")
        return False

    any_success = False
    if sync_send:
        for cid in chat_ids:
            ok = _send_http(bot_token, cid, message)
            if ok:
                any_success = True
            time.sleep(0.05)  # Safe inter-message pacing
        return any_success
    else:
        _ensure_worker_started()
        for cid in chat_ids:
            _ALERT_QUEUE.put((bot_token, cid, message))
        return True


def send_live_movers_test_ping() -> Dict[str, Any]:
    """
    Send an immediate test verification ping to all configured chat IDs.
    Returns status dict with delivery breakdown per chat ID.
    """
    enabled, bot_token, chat_ids, min_score, cooldown_min = get_live_movers_telegram_config()
    if not bot_token:
        return {"status": "error", "message": "TELEGRAM_LIVE_MOVERS_BOT_TOKEN is missing in .env"}
    if not chat_ids:
        return {"status": "error", "message": "TELEGRAM_LIVE_MOVERS_CHAT_ID is missing in .env"}

    now_str = datetime.now(IST_TZ).strftime("%I:%M:%S %p IST")
    test_msg = (
        "🟢 *[NSE LIVE MOVERS BOT ACTIVE]*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ Dedicated 20-EMA High-Tight Flag & Breakdown Telegram bot is online!\n\n"
        f"🎯 *Active Score Filter*: ≥ *{min_score:.0f}*\n"
        f"⏳ *Anti-Spam Cooldown*: *{cooldown_min:.0f} mins*\n"
        f"👥 *Subscribers*: `{len(chat_ids)}` active recipients\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ {now_str} • NSE Live Movers Alert Bot"
    )

    results = {}
    for cid in chat_ids:
        ok = _send_http(bot_token, cid, test_msg)
        results[cid] = "Delivered" if ok else "Failed"
        time.sleep(0.05)

    all_ok = all(v == "Delivered" for v in results.values())
    return {
        "status": "success" if all_ok else "partial",
        "chat_ids": results,
        "bot_token_preview": f"{bot_token[:10]}...",
    }


def dispatch_live_movers_alerts(
    runners: List[Dict[str, Any]],
    short_runners: List[Dict[str, Any]],
    min_score: Optional[float] = None,
    market_context: Optional[Dict[str, Any]] = None,
    universe: Optional[List[Any]] = None,
) -> int:
    """
    Evaluates qualifying runners and short_runners from V13 Active Movers,
    pre-evaluates real-time Conviction Rating BEFORE cooldown inspection,
    applies strict anti-spam deduplication with Conviction Tier Upgrade bypass,
    and dispatches rich alerts to all configured Telegram chat IDs.

    Returns the count of new alerts dispatched.
    """
    enabled, bot_token, chat_ids, env_min_score, cooldown_min = get_live_movers_telegram_config()
    if not enabled or not bot_token or not chat_ids:
        return 0

    # Strict Market-Hours Gate: Live Mover trade alerts only fire Mon-Fri between 09:15 and 15:00 IST
    now_ist = datetime.now(IST_TZ)
    if now_ist.weekday() > 4:
        return 0
    t_now = now_ist.time()
    from datetime import time as dtime
    if not (dtime(9, 15) <= t_now <= dtime(15, 0)):
        return 0
    if dtime(9, 30, 0) <= t_now < dtime(9, 35, 15):
        return 0

    effective_min_score = min_score if min_score is not None else env_min_score
    cooldown_seconds = cooldown_min * 60.0

    _ensure_cache_loaded()
    now_ts = time.time()
    today_date = now_ist.strftime("%Y-%m-%d")

    dispatched_count = 0

    # Combine candidates to process
    items_to_check: List[Tuple[Dict[str, Any], bool, str]] = []
    for r in runners:
        items_to_check.append((r, True, "LONG"))
    for sr in short_runners:
        items_to_check.append((sr, False, "SHORT"))

    for item, is_long, direction in items_to_check:
        sym = str(item.get("symbol", "")).strip().upper()
        if not sym:
            continue

        v13_score = float(item.get("v13_score") or 0.0)
        # Must meet the minimum V13 Score threshold
        if v13_score < effective_min_score:
            continue

        cache_key = f"{sym}_{direction}"

        # 1. Pre-format message and evaluate live Conviction Grade BEFORE cooldown check
        # This populates item["conviction_grade"] and item["conviction_score"] in-place
        msg = format_live_mover_message(
            item,
            is_long=is_long,
            market_context=market_context,
            universe=universe,
        )
        cur_grade = str(item.get("conviction_grade") or "GRADE_B")

        # 2. Deduplication & Cooldown Check (with Conviction Tier Upgrade Bypass)
        with _ALERT_LOCK:
            existing = _SENT_ALERTS.get(cache_key)
            if existing:
                ex_date = existing.get("date")
                ex_ts = float(existing.get("timestamp", 0))
                ex_score = float(existing.get("score", 0))
                ex_grade = str(existing.get("conviction_grade") or "GRADE_C")
                time_elapsed = now_ts - ex_ts

                # Rank hierarchy for conviction tier upgrade detection
                rank_map = {"GRADE_C": 0, "GRADE_B": 1, "GRADE_A_PLUS": 2}
                is_conviction_upgraded = rank_map.get(cur_grade, 0) > rank_map.get(ex_grade, 0)

                if ex_date == today_date:
                    # Bypass cooldown if V13 score jumped by >= 5.0 pts OR conviction tier upgraded
                    if (
                        time_elapsed < cooldown_seconds
                        and (v13_score <= ex_score + 4.9)
                        and not is_conviction_upgraded
                    ):
                        continue

            _ensure_worker_started()
            for cid in chat_ids:
                _ALERT_QUEUE.put((bot_token, cid, msg))

            # Record in cache (persists conviction_grade for disk cache & restart recovery)
            _SENT_ALERTS[cache_key] = {
                "symbol": sym,
                "direction": direction,
                "score": round(v13_score, 1),
                "price": item.get("price"),
                "conviction_grade": cur_grade,
                "conviction_score": item.get("conviction_score"),
                "timestamp": now_ts,
                "date": today_date,
            }
            dispatched_count += 1

        # 3. Record in isolated Live Movers Session Ledger (outside _ALERT_LOCK to avoid lock nesting)
        record_live_mover_ledger_entry(item, direction=direction, grade=cur_grade)

    if dispatched_count > 0:
        with _ALERT_LOCK:
            _save_sent_alerts_cache(_SENT_ALERTS)
        logger.info(f"Dispatched {dispatched_count} live movers alerts to {len(chat_ids)} recipients")

    return dispatched_count
