"""
Telegram Live Alerts Bot for NSE-PULSE V13.
100% Free, instant phone push notifications for 72+, 80+, 85+ breakout signals.
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
from typing import Any, Dict, List, Optional

from .config import (
    IST_TZ,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_CHAT_IDS,
    TELEGRAM_ENABLED,
    TELEGRAM_MIN_SCORE,
    TELEGRAM_MAX_T1_PROGRESS,
)

logger = logging.getLogger("telegram_bot")

CACHE_DIR = os.path.join(os.path.dirname(__file__), "data", "telegram notification audit")
CACHE_FILE = os.path.join(CACHE_DIR, "sent_alerts_cache.json")
HISTORY_DIR = os.path.join(os.path.dirname(__file__), "data", "telegram notification history")


def _load_sent_alerts_cache() -> Dict[str, Dict[str, Any]]:
    """Load sent alerts cache from disk JSON file to survive reloads/restarts."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        now = time.time()
        today_date = datetime.now(IST_TZ).strftime("%Y-%m-%d")
        valid: Dict[str, Dict[str, Any]] = {}
        for sym, item in data.items():
            if not isinstance(item, dict):
                continue
            item_date = item.get("date")
            ts = float(item.get("timestamp", 0))
            if (item_date == today_date) or (now - ts < 86400):
                valid[sym] = item
        logger.info(f"Loaded {len(valid)} active alert records from {CACHE_FILE}")
        return valid
    except Exception as e:
        logger.warning(f"Failed to load sent alerts cache from disk: {e}")
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
        logger.warning(f"Failed to persist sent alerts cache to disk: {e}")


def clear_sent_alerts_cache() -> None:
    """Clear both in-memory and disk alert cache (for session reset or testing)."""
    global _SENT_ALERTS
    with _ALERT_LOCK:
        _SENT_ALERTS = {}
        try:
            if os.path.exists(CACHE_FILE):
                os.remove(CACHE_FILE)
        except Exception as e:
            logger.warning(f"Failed to remove {CACHE_FILE}: {e}")


# Disk-backed alert cache to prevent duplicate notification spam across reloads/restarts
# Key: symbol -> {"score": float, "direction": str, "timestamp": float, "tier": str, "date": str}
_SENT_ALERTS: Dict[str, Dict[str, Any]] = _load_sent_alerts_cache()
_ALERT_LOCK = threading.Lock()


def archive_session_telegram_alerts(
    session_date: str,
    ledger_records: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Archive Telegram alerts dispatched for a specific session date into
    backend/app/data/telegram notification history/telegram_alerts_YYYY-MM-DD.json.

    Enriches alert metadata with full trade outcomes from SessionTradeLedger:
    score, human-readable trigger timestamp (IST), direction, tier, entry_price,
    stop_loss, target_1, target_2, risk_amount, highest_progress_pct, outcome, realized_r, outcome_time.
    """
    try:
        # 1. Grab alerts for the target session date from sent cache
        with _ALERT_LOCK:
            target_alerts = {
                sym: dict(info)
                for sym, info in _SENT_ALERTS.items()
                if isinstance(info, dict) and info.get("date") == session_date
            }

        # If cache in memory had 0 for that date, also inspect raw disk file
        if not target_alerts and os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    disk_cache = json.load(f)
                for sym, info in disk_cache.items():
                    if isinstance(info, dict) and info.get("date") == session_date:
                        target_alerts[sym] = dict(info)
            except Exception:
                pass

        if not target_alerts:
            logger.info(f"No Telegram alerts found to archive for session {session_date}")
            return None

        # 2. Reconcile with ledger records (live or historical)
        if ledger_records is None:
            try:
                from .v13_ledger import GLOBAL_SESSION_LEDGER, LEDGER_HISTORY_DIR
                if GLOBAL_SESSION_LEDGER.date_str == session_date and GLOBAL_SESSION_LEDGER.records:
                    ledger_records = dict(GLOBAL_SESSION_LEDGER.records)
                else:
                    hist_path = os.path.join(LEDGER_HISTORY_DIR, f"ledger_{session_date}.json")
                    if os.path.exists(hist_path):
                        with open(hist_path, "r", encoding="utf-8") as f:
                            h_data = json.load(f)
                        ledger_records = h_data.get("records", {})
            except Exception as e:
                logger.warning(f"Could not load ledger records for telegram archiving of {session_date}: {e}")
                ledger_records = {}

        ledger_records = ledger_records or {}

        def _get_field(rec_obj: Any, attr: str, default: Any = None) -> Any:
            if rec_obj is None:
                return default
            if isinstance(rec_obj, dict):
                return rec_obj.get(attr, default)
            return getattr(rec_obj, attr, default)

        enriched_alerts = []
        for sym, item in target_alerts.items():
            clean_sym = item.get("symbol") or (
                sym.rsplit("_", 1)[0]
                if sym.endswith(("_BULLISH", "_BEARISH", "_LONG", "_SHORT"))
                else sym
            )
            direction = str(item.get("direction") or "BULLISH").upper()
            lookup_key = f"{clean_sym}_{direction}"
            rec = ledger_records.get(lookup_key) or ledger_records.get(clean_sym)

            ts = float(item.get("timestamp") or 0.0)
            if ts > 0:
                time_of_trigger = datetime.fromtimestamp(ts, tz=IST_TZ).strftime("%I:%M:%S %p IST")
            else:
                time_of_trigger = "—"

            enriched = {
                "symbol": clean_sym,
                "name": _get_field(rec, "name", clean_sym),
                "sector": _get_field(rec, "sector", "NSE Equity"),
                "score": float(item.get("score") or _get_field(rec, "peak_score", 0.0) or 0.0),
                "direction": direction,
                "tier": str(item.get("tier") or _get_field(rec, "peak_tier", "WATCH")),
                "time_of_trigger": time_of_trigger,
                "timestamp": ts,
                "date": session_date,
                "entry_price": _get_field(rec, "entry_price"),
                "stop_loss": _get_field(rec, "stop_loss"),
                "target_1": _get_field(rec, "target_1"),
                "target_2": _get_field(rec, "target_2"),
                "risk_amount": _get_field(rec, "risk_amount"),
                "highest_progress_pct": round(float(_get_field(rec, "highest_progress_pct", 0.0) or 0.0), 1),
                "outcome": _get_field(rec, "outcome", "OPEN"),
                "realized_r": round(float(_get_field(rec, "realized_r", 0.0) or 0.0), 2),
                "outcome_time": _get_field(rec, "outcome_time"),
            }
            enriched_alerts.append(enriched)

        # Sort chronologically by timestamp
        enriched_alerts.sort(key=lambda x: x.get("timestamp", 0))

        # 3. Save atomically into HISTORY_DIR
        os.makedirs(HISTORY_DIR, exist_ok=True)
        dest_file = os.path.join(HISTORY_DIR, f"telegram_alerts_{session_date}.json")
        payload = {
            "date": session_date,
            "archived_at": datetime.now(IST_TZ).isoformat(),
            "total_alerts": len(enriched_alerts),
            "alerts": enriched_alerts,
        }
        tmp_file = f"{dest_file}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, dest_file)
        logger.info(f"Successfully archived {len(enriched_alerts)} telegram alerts to {dest_file}")
        return dest_file
    except Exception as e:
        logger.error(f"Error archiving telegram alerts for {session_date}: {e}")
        return None


def rollover_sent_alerts_cache(new_session_date: str, old_session_date: Optional[str] = None) -> None:
    """
    Rollover sent alerts cache at .env EOD_RESET_TIME:
    1. Archives all un-archived alerts for previous session dates into HISTORY_DIR.
    2. Resets active cache so it only contains alerts for the new session date.
    """
    global _SENT_ALERTS
    with _ALERT_LOCK:
        # Collect distinct dates present in cache
        distinct_dates = set()
        for item in _SENT_ALERTS.values():
            if isinstance(item, dict) and item.get("date"):
                distinct_dates.add(item["date"])
        if old_session_date:
            distinct_dates.add(old_session_date)

    # Archive older dates outside lock to prevent lock contention
    for past_date in distinct_dates:
        if past_date and past_date != new_session_date:
            try:
                archive_session_telegram_alerts(past_date)
            except Exception as e:
                logger.error(f"Failed to archive past telegram alerts for {past_date}: {e}")

    # Prune active cache
    with _ALERT_LOCK:
        new_cache = {
            sym: item for sym, item in _SENT_ALERTS.items()
            if isinstance(item, dict) and item.get("date") == new_session_date
        }
        _SENT_ALERTS = new_cache
        _save_sent_alerts_cache(_SENT_ALERTS)
        logger.info(f"Rolled over sent alerts cache for new session date: {new_session_date} ({len(_SENT_ALERTS)} active)")


def get_archived_telegram_alerts(session_date: str) -> List[Dict[str, Any]]:
    """Retrieve archived Telegram alerts for a specific session date."""
    archive_path = os.path.join(HISTORY_DIR, f"telegram_alerts_{session_date}.json")
    if os.path.exists(archive_path):
        try:
            with open(archive_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("alerts", [])
        except Exception as e:
            logger.warning(f"Error reading telegram archive {archive_path}: {e}")
    return []

# Sequential rate-limited queue worker (adheres to Telegram's 1 msg/sec limit per chat)
_ALERT_QUEUE: "queue.Queue[tuple[str, str, str]]" = queue.Queue()
_QUEUE_WORKER_THREAD: Optional[threading.Thread] = None
_QUEUE_WORKER_LOCK = threading.Lock()


def _format_inr(val: Optional[float]) -> str:
    if val is None:
        return "₹—"
    return f"₹{val:,.2f}"


def _escape_md(text: Any) -> str:
    """Escape Telegram legacy Markdown reserved characters to prevent 400 Bad Request."""
    if text is None:
        return ""
    s = str(text)
    for ch in ("_", "*", "`", "["):
        s = s.replace(ch, f"\\{ch}")
    return s


def format_telegram_message(signal: Dict[str, Any]) -> str:
    """Format an attractive, clean Markdown message for Telegram."""
    raw_sym = signal.get("symbol", "UNKNOWN")
    raw_name = signal.get("name", raw_sym)
    raw_sec = signal.get("sector", "NSE Equity")

    sym = _escape_md(raw_sym)
    name = _escape_md(raw_name)
    sector = _escape_md(raw_sec)

    direction = str(signal.get("direction") or signal.get("signal_type") or "BULLISH").upper()
    score = float(signal.get("score") or 0.0)
    ltp = signal.get("ltp") or signal.get("price")

    tp = signal.get("risk") or signal.get("trade_params") or {}
    entry = tp.get("entry") or signal.get("entry_price") or ltp
    sl = tp.get("stop_loss") or signal.get("stop_loss")
    t1 = tp.get("target_1") or signal.get("target_1")
    t2 = tp.get("target_2") or signal.get("target_2")
    risk_amt = tp.get("risk_amount") or signal.get("risk_amount")
    if risk_amt is None and entry and sl:
        risk_amt = abs(entry - sl)

    ind = signal.get("indicators") or {}
    rel_vol = ind.get("rel_vol") or signal.get("rel_vol")
    ema20 = ind.get("ema20") or signal.get("ema20")
    vwap = ind.get("vwap") or signal.get("vwap")
    rsi = ind.get("rsi14") or signal.get("rsi14")

    # Header Emoji and Tier Classification
    exec_status = str(signal.get("execution_status") or "").upper()
    t1_prog = float(signal.get("t1_progress_pct") or 0.0)

    if exec_status == "EARLY_TRIGGER" or (65.0 <= score < 72.0 and t1_prog < 50.0):
        header_badge = "⚡ *EARLY ALERT: SETUP FORMING NEAR ENTRY*"
        tier = "EARLY TRIGGER"
    elif score >= 85.0:
        header_badge = "🚀 *HIGH CONFIDENCE BREAKOUT (85+)*"
        tier = "HIGH CONFIDENCE"
    elif score >= 80.0:
        header_badge = "⚡ *STRONG BREAKOUT (80-84)*"
        tier = "STRONG"
    elif score >= 72.0:
        header_badge = "👀 *WATCHLIST BREAKOUT (72-79)*"
        tier = "WATCH"
    else:
        header_badge = "📊 *BELOW THRESHOLD SETUP (<72)*"
        tier = "BELOW THRESHOLD"

    dir_icon = "🟢 BULLISH LONG" if direction == "BULLISH" else "🔴 BEARISH SHORT"
    entry_label = "Breakout Entry" if direction == "BULLISH" else "Breakdown Entry"

    now_str = datetime.now(IST_TZ).strftime("%d %b %Y, %I:%M %p IST")

    # Reasons & confirmations
    conf = signal.get("confirmation") or {}
    reasons = conf.get("reasons") or signal.get("reasons") or []
    top_reasons = _escape_md(", ".join(reasons[:2]) if reasons else "OR Breakout confirmed")

    # Determine Universe Category (NIFTY 500 vs >=1000 CR)
    is_n500 = signal.get("is_nifty500")
    if is_n500 is None:
        try:
            from .config import NIFTY_500_SYMBOLS
            is_n500 = raw_sym in NIFTY_500_SYMBOLS
        except Exception:
            is_n500 = False
    
    category_label = "NIFTY 500" if is_n500 else ">=1000 CR"

    lines = [
        header_badge,
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"🏢 *{sym}* — {name}",
        f"🏛️ *Universe*: `{category_label}`",
        f"📂 *Sector*: {sector}",
        f"🎯 *Score*: *{score:.1f}/100* ({tier})",
        f"📈 *Direction*: {dir_icon}",
        f"💰 *Current Price (LTP)*: *{_format_inr(ltp)}*",
        f"📏 *T1 Progress*: `{t1_prog:.1f}%`",
        "",
        "🎯 *TRADE EXECUTION PLAN*",
        f"  📍 *{entry_label}*: `{_format_inr(entry)}`",
        f"  🛡️ *Stop Loss (SL)*: `{_format_inr(sl)}` (Risk: {_format_inr(risk_amt)}/sh)",
        f"  🎯 *Target 1 (1:1.5 RR)*: `{_format_inr(t1)}`",
        f"  🎯 *Target 2 (1:2.5 RR)*: `{_format_inr(t2)}`",
        "",
        "📊 *QUANTITATIVE METRICS*",
        f"  🔥 *RelVol*: `{f'{rel_vol:.2f}x' if rel_vol else '—'}`",
        f"  📈 *20 EMA*: `{_format_inr(ema20)}` | *VWAP*: `{_format_inr(vwap)}`",
        f"  ⚡ *RSI(14)*: `{f'{rsi:.1f}' if rsi else '—'}`",
        f"  💡 *Key Driver*: {top_reasons}",
    ]

    # Append Conviction Rating Stamp if enabled (Toggleable via ENABLE_CONVICTION_RATING)
    try:
        from .v13_conviction import evaluate_conviction, format_conviction_block, is_conviction_rating_enabled
        if is_conviction_rating_enabled():
            conv_data = signal.get("conviction")
            if not conv_data or not isinstance(conv_data, dict) or not conv_data.get("enabled"):
                m_ctx = signal.get("_market_context")
                u_list = signal.get("_universe")
                conv_data = evaluate_conviction(signal, market_context=m_ctx, universe=u_list)
            conv_block = format_conviction_block(conv_data)
            if conv_block:
                lines.append(conv_block)
                signal["conviction_grade"] = conv_data.get("grade")
                signal["conviction_score"] = conv_data.get("total_score")
    except Exception as e:
        logger.debug(f"Conviction evaluation skipped: {e}")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"⏰ {now_str} • NSE-PULSE V13",
    ])

    return "\n".join(lines)


def _send_telegram_http(bot_token: str, chat_id: str, message: str) -> bool:
    """
    Send message via official Telegram Bot API using urllib.
    Includes auto-fallback to plain text if Markdown entity parsing fails (HTTP 400).
    """
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
            result = json.loads(resp_body)
            return bool(result.get("ok"))
    except urllib.error.HTTPError as http_err:
        # If Markdown entity parsing failed (400 Bad Request), fallback to plain text so alert is never lost
        if http_err.code == 400:
            logger.warning(f"Telegram Markdown parse failed (400) for chat {chat_id}, retrying as plain text...")
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
                    result = json.loads(resp_body)
                    return bool(result.get("ok"))
            except Exception as fb_err:
                logger.error(f"Telegram plain-text fallback failed: {fb_err}")
                return False
        logger.error(f"Telegram API HTTP error {http_err.code}: {http_err}")
        return False
    except Exception as e:
        logger.error(f"Telegram API request failed: {e}")
        return False


def _telegram_queue_worker():
    """Sequential rate-limited worker thread ensuring max 1 msg/sec per chat ID to prevent HTTP 429."""
    while True:
        try:
            item = _ALERT_QUEUE.get()
            if item is None:
                break
            bot_token, chat_id, message = item
            _send_telegram_http(bot_token, chat_id, message)
            time.sleep(1.0)  # Complies with Telegram's strict 1 msg/sec limit
            _ALERT_QUEUE.task_done()
        except Exception as e:
            logger.error(f"Telegram queue dispatcher error: {e}")
            time.sleep(1.0)


def _ensure_queue_worker_started():
    global _QUEUE_WORKER_THREAD
    with _QUEUE_WORKER_LOCK:
        if _QUEUE_WORKER_THREAD is None or not _QUEUE_WORKER_THREAD.is_alive():
            _QUEUE_WORKER_THREAD = threading.Thread(
                target=_telegram_queue_worker,
                name="tg-rate-limit-dispatcher",
                daemon=True,
            )
            _QUEUE_WORKER_THREAD.start()


def get_telegram_config() -> tuple[bool, str, List[str], float]:
    """Dynamically reload .env and return current Telegram settings with multi-chat ID support."""
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path, override=True)
        else:
            load_dotenv(override=True)
    except Exception:
        pass

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or TELEGRAM_BOT_TOKEN

    raw_chat = os.getenv("TELEGRAM_CHAT_IDS", "").strip() or os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not raw_chat and TELEGRAM_CHAT_IDS:
        chat_ids = TELEGRAM_CHAT_IDS
    elif raw_chat:
        chat_ids = [cid.strip() for cid in raw_chat.split(",") if cid.strip()]
    else:
        chat_ids = [TELEGRAM_CHAT_ID] if TELEGRAM_CHAT_ID else []

    try:
        min_score = float(str(os.getenv("TELEGRAM_MIN_SCORE", str(TELEGRAM_MIN_SCORE))).replace("%", "").strip())
    except (TypeError, ValueError):
        min_score = 75.0

    enabled = os.getenv("TELEGRAM_ENABLED", "true").lower() in ("true", "1", "yes")

    return enabled, bot_token, chat_ids, min_score


def get_telegram_max_prog() -> float:
    """Return maximum allowed Target 1 progress % (default 25.0%) for live entry alerts."""
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path, override=True)
    except Exception:
        pass
    try:
        return float(str(os.getenv("TELEGRAM_MAX_T1_PROGRESS", str(TELEGRAM_MAX_T1_PROGRESS))).replace("%", "").strip())
    except (TypeError, ValueError):
        return 25.0


def _get_score_tier(score: float, exec_status: str = "") -> str:
    """Return the score classification tier name for deduplication boundary checks."""
    if exec_status == "EARLY_TRIGGER":
        return "EARLY TRIGGER"
    elif score >= 85.0:
        return "HIGH CONFIDENCE"
    elif score >= 80.0:
        return "STRONG"
    elif score >= 72.0:
        return "WATCH"
    return "BELOW THRESHOLD"


def send_telegram_alert_async(signal: Dict[str, Any]) -> None:
    """Queue Telegram alert for sequential rate-limited background delivery to all chat IDs."""
    enabled, bot_token, chat_ids, _ = get_telegram_config()
    if not enabled or not bot_token or not chat_ids:
        return

    sym = signal.get("symbol", "")
    score = float(signal.get("score") or 0.0)
    exec_status = str(signal.get("execution_status") or "").upper()
    t1_prog = float(signal.get("t1_progress_pct") or 0.0)

    # STRICT EARLY ENTRY GUARD: Block late, running, or expired setups
    # Ensures trader gets alerts ONLY when pristine Risk:Reward is intact (Base / Early Entry).
    max_prog = get_telegram_max_prog()
    if exec_status in ("TARGET_HIT", "TARGET_NEAR", "EXPIRED_T1_NEAR") or t1_prog > max_prog:
        logger.info(
            f"Telegram alert blocked for {sym}: Target 1 progress ({t1_prog:.1f}%) > {max_prog:.1f}% "
            f"or status={exec_status} (Strict <={max_prog:.0f}% Early Entry Guard)"
        )
        return

    # BLOCK STALE DATE SIGNALS: Only block during LIVE market hours on weekdays
    # Outside active market hours (e.g. weekend testing or post-market reviews), allow alerts through.
    try:
        from .data_fetcher import get_market_status
        is_market_open = get_market_status().is_open
    except Exception:
        is_market_open = False

    sig_time_str = str(signal.get("signal_time") or "")
    if is_market_open and sig_time_str and "T" in sig_time_str:
        try:
            sig_date = sig_time_str.split("T")[0]
            today_date = datetime.now(IST_TZ).strftime("%Y-%m-%d")
            if sig_date != today_date:
                logger.info(
                    f"Telegram alert blocked for {sym}: Stale signal date ({sig_date}) != today ({today_date}) during live market"
                )
                return
        except Exception:
            pass

    # STRICT 15:00 IST LATE-SESSION CUTOFF FOR LIVE NOTIFICATIONS:
    # During live market hours, do not push new trade alerts to phone after 15:00 IST.
    # Protects trader from intraday broker auto-square-off (15:15-15:20) and end-of-day volatility.
    now_ist = datetime.now(IST_TZ)
    if is_market_open and now_ist.hour >= 15:
        logger.info(
            f"Telegram live alert blocked for {sym}: Trigger time ({now_ist.strftime('%H:%M:%S')}) is at or after 15:00 IST cutoff"
        )
        return

    # TIER-AWARE DEDUPLICATION RULE: Prevent repeat notifications for 90 minutes UNLESS:
    # 1. Score classification tier changes (e.g. WATCH -> STRONG, STRONG -> HIGH CONFIDENCE)
    # 2. Score changes by >= +5.0 or <= -5.0 points
    # Keyed by f"{sym}_{direction}" so a valid intraday reversal in the opposite direction is never blocked.
    now = time.time()
    direction = str(signal.get("direction") or signal.get("signal_type") or "BULLISH").upper()
    current_tier = _get_score_tier(score, exec_status)
    alert_key = f"{sym}_{direction}"

    with _ALERT_LOCK:
        last_alert = _SENT_ALERTS.get(alert_key)
        if last_alert is None and sym in _SENT_ALERTS:
            legacy_alert = _SENT_ALERTS.get(sym)
            if isinstance(legacy_alert, dict) and str(legacy_alert.get("direction") or "BULLISH").upper() == direction:
                last_alert = legacy_alert

        if last_alert is not None:
            last_time = float(last_alert.get("timestamp", 0))
            last_score = float(last_alert.get("score", 0.0))
            last_tier = str(last_alert.get("tier") or _get_score_tier(last_score))
            score_diff = score - last_score

            # Suppress duplicate ONLY IF:
            # - Sent within 90 minutes (5400s) AND
            # - Score change is strictly less than 5.0 points AND
            # - Classification Tier has NOT changed (e.g. still WATCH -> WATCH)
            if (now - last_time < 5400) and (abs(score_diff) < 5.0) and (current_tier == last_tier):
                logger.info(
                    f"Telegram alert suppressed for {alert_key}: Sent {int(now - last_time)}s ago, "
                    f"Score diff ({score_diff:+.1f} pts) < 5.0 threshold, Tier unchanged ({current_tier})"
                )
                return

        # Update cache with current alert state including symbol, classification tier and date
        today_date = datetime.now(IST_TZ).strftime("%Y-%m-%d")
        _SENT_ALERTS[alert_key] = {
            "symbol": sym,
            "score": score,
            "direction": direction,
            "timestamp": now,
            "tier": current_tier,
            "date": today_date,
        }
        _save_sent_alerts_cache(_SENT_ALERTS)

    # Immediately lock the active trade into the ledger's telegram_alerted_trades
    try:
        from .v13_ledger import GLOBAL_SESSION_LEDGER
        GLOBAL_SESSION_LEDGER.record_telegram_alert(signal)
    except Exception as _le:
        logger.debug(f"Failed to record telegram alert in ledger: {_le}")

    message = format_telegram_message(signal)
    _ensure_queue_worker_started()

    for cid in chat_ids:
        _ALERT_QUEUE.put((bot_token, cid, message))


def dispatch_telegram_alerts(
    candidates: List[Any],
    max_batch_alerts: int = 25,
    market_context: Optional[Dict[str, Any]] = None,
    universe: Optional[List[Any]] = None,
) -> int:
    """
    Examine scan candidates and queue Telegram alerts for setups >= TELEGRAM_MIN_SCORE.
    Sorts by score descending to prioritize highest confidence setups.
    Rate limits to max_batch_alerts per cycle (default 25) to avoid flooding chat.
    """
    enabled, bot_token, chat_ids, min_score = get_telegram_config()
    if not enabled or not bot_token or not chat_ids:
        return 0

    valid_candidates = []
    seen_keys = set()
    max_prog = get_telegram_max_prog()

    for cand in candidates:
        if isinstance(cand, dict):
            score = float(cand.get("score") or 0.0)
            sym = cand.get("symbol")
            direction = str(cand.get("direction") or cand.get("signal_type") or "BULLISH").upper()
            t1_prog = float(cand.get("t1_progress_pct") or 0.0)
            exec_status = str(cand.get("execution_status") or "").upper()
            sig_dict = dict(cand)
        else:
            score = float(getattr(cand, "score", 0.0) or 0.0)
            sym = getattr(cand, "symbol", "")
            direction = str(getattr(cand, "direction", "") or getattr(cand, "signal_type", "") or "BULLISH").upper()
            t1_prog = float(getattr(cand, "t1_progress_pct", 0.0) or 0.0)
            exec_status = str(getattr(cand, "execution_status", "") or "").upper()
            sig_dict = dict(cand.__dict__) if hasattr(cand, "__dict__") else {}

        if market_context is not None:
            sig_dict["_market_context"] = market_context
        if universe is not None:
            sig_dict["_universe"] = universe

        # Strict Early Entry Guard: Skip setups already past max progress or expired
        if exec_status in ("TARGET_HIT", "TARGET_NEAR", "EXPIRED_T1_NEAR") or t1_prog > max_prog:
            continue

        dedup_key = f"{sym}_{direction}"
        if sym and dedup_key not in seen_keys and score >= min_score:
            seen_keys.add(dedup_key)
            valid_candidates.append((score, sig_dict))

    # Highest scores first
    valid_candidates.sort(key=lambda x: x[0], reverse=True)

    sent = 0
    for score, sig_dict in valid_candidates:
        send_telegram_alert_async(sig_dict)
        sent += 1
        if sent >= max_batch_alerts:
            break

    return sent


def send_telegram_text(message: str, sync_send: bool = False) -> bool:
    """
    Queue a custom text or markdown report to all configured Telegram chats.
    If sync_send is True, sends synchronously via HTTP and returns True only if delivered to all chats.
    This guarantees that critical audits (EOD reports) are never lost during process reload.
    """
    enabled, bot_token, chat_ids, _ = get_telegram_config()
    if not enabled or not bot_token or not chat_ids:
        logger.info("Telegram not configured or disabled; text message not sent.")
        return False

    if sync_send:
        any_ok = False
        for cid in chat_ids:
            try:
                ok = _send_telegram_http(bot_token, cid, message)
                if ok:
                    any_ok = True
            except Exception as e:
                logger.error(f"Synchronous telegram send failed for {cid}: {e}")
            time.sleep(0.5)
        return any_ok

    _ensure_queue_worker_started()
    for cid in chat_ids:
        _ALERT_QUEUE.put((bot_token, cid, message))
    return True


def send_telegram_document(file_path: str, caption: str = "") -> bool:
    """
    Send document (PDF, CSV, etc.) directly to all configured Telegram chats.
    Uses requests for reliable multipart/form-data upload.
    Returns True if successfully delivered to all chat IDs.
    """
    enabled, bot_token, chat_ids, _ = get_telegram_config()
    if not enabled or not bot_token or not chat_ids:
        logger.info("Telegram not configured or disabled; document not sent.")
        return False

    if not os.path.exists(file_path):
        logger.error(f"Cannot send document: File not found at {file_path}")
        return False

    import requests

    success = True
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    filename = os.path.basename(file_path)

    for cid in chat_ids:
        try:
            with open(file_path, "rb") as f:
                resp = requests.post(
                    url,
                    data={"chat_id": cid, "caption": caption, "parse_mode": "Markdown"},
                    files={"document": (filename, f, "application/pdf")},
                    timeout=35,
                )
            if resp.status_code == 200 and resp.json().get("ok"):
                logger.info(f"Successfully delivered document {filename} to chat {cid}")
            else:
                logger.warning(f"Failed to send document to {cid} with markdown caption ({resp.status_code}): {resp.text}, retrying with plain text caption...")
                clean_caption = caption.replace("*", "").replace("`", "").replace("_", "")
                with open(file_path, "rb") as f:
                    resp_retry = requests.post(
                        url,
                        data={"chat_id": cid, "caption": clean_caption},
                        files={"document": (filename, f, "application/pdf")},
                        timeout=35,
                    )
                if resp_retry.status_code == 200 and resp_retry.json().get("ok"):
                    logger.info(f"Delivered document {filename} to chat {cid} via plain-text fallback")
                else:
                    logger.error(f"Document delivery failed for chat {cid}: {resp_retry.status_code} - {resp_retry.text}")
                    success = False
            time.sleep(1.0)
        except Exception as e:
            logger.error(f"Error sending document to {cid}: {e}")
            success = False

    return success


