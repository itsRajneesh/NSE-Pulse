"""
v13_alpha_telegram.py
-------------------------------------------------------------------------------
Dedicated Multi-Recipient Institutional Telegram Bot for ALPHA (NIFTY 50 Options).
- 100% Isolated from V13 Equity and Live Movers Telegram bots.
- Non-blocking background daemon queue for zero latency on live option ticks.
- Per-recipient deduplication & isolated try/except per chat_id.
- Dynamic lot-split formatting (handles 1-Lot, 2-Lot, 3-Lot, and Iceberg >27-Lot trades).
-------------------------------------------------------------------------------
"""

from __future__ import annotations

import json
import logging
import math
import os
import queue
import ssl
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .v13_nifty_options_engine import IST, round_to_nse_tick

logger = logging.getLogger("v13_alpha_telegram")

CACHE_DIR = os.path.join(os.path.dirname(__file__), "data", "telegram notification audit")
CACHE_FILE = os.path.join(CACHE_DIR, "sent_alpha_alerts_cache.json")

_ALERT_LOCK = threading.Lock()
_SENT_ALERTS: Dict[str, Dict[str, Any]] = {}
_CACHE_LOADED = False
_LAST_ENV_MTIME: float = 0.0

_DISPATCH_QUEUE: "queue.Queue[Dict[str, Any]]" = queue.Queue()
_WORKER_STARTED = False
_WORKER_LOCK = threading.Lock()


def _get_env_path() -> str:
    backend_dir = os.path.dirname(os.path.dirname(__file__))
    env_path = os.path.join(backend_dir, ".env")
    if os.path.exists(env_path):
        return env_path
    root_dir = os.path.dirname(backend_dir)
    env_path = os.path.join(root_dir, ".env")
    return env_path if os.path.exists(env_path) else ".env"


def get_alpha_telegram_config() -> Dict[str, Any]:
    """
    Dynamically reload .env when modified on disk so token/chat_id edits apply without server restart,
    while respecting ALPHA_TEST_MODE == '1' so unit test environment variable mocks are never overridden.
    """
    global _LAST_ENV_MTIME
    if os.getenv("ALPHA_TEST_MODE") != "1":
        try:
            from dotenv import load_dotenv
            env_file = _get_env_path()
            if os.path.exists(env_file):
                current_mtime = os.path.getmtime(env_file)
                if current_mtime != _LAST_ENV_MTIME:
                    load_dotenv(env_file, override=True)
                    _LAST_ENV_MTIME = current_mtime
        except Exception:
            pass

    enabled = os.getenv("TELEGRAM_ALPHA_ENABLED", "true").lower() in ("true", "1", "yes")
    bot_token = os.getenv("TELEGRAM_ALPHA_BOT_TOKEN", "").strip()
    raw_chat = (
        os.getenv("TELEGRAM_ALPHA_CHAT_ID", "").strip()
        or os.getenv("TELEGRAM_ALPHA_CHAT_IDS", "").strip()
    )
    chat_ids = [cid.strip() for cid in raw_chat.split(",") if cid.strip()]

    return {
        "enabled": enabled,
        "bot_token": bot_token,
        "chat_ids": chat_ids,
        "notify_entries": os.getenv("TELEGRAM_ALPHA_NOTIFY_ENTRIES", "true").lower() in ("true", "1", "yes"),
        "notify_exits": os.getenv("TELEGRAM_ALPHA_NOTIFY_EXITS", "true").lower() in ("true", "1", "yes"),
        "notify_milestones": os.getenv("TELEGRAM_ALPHA_NOTIFY_MILESTONES", "true").lower() in ("true", "1", "yes"),
        "notify_killswitch": os.getenv("TELEGRAM_ALPHA_NOTIFY_KILLSWITCH", "true").lower() in ("true", "1", "yes"),
    }


def _ensure_cache_loaded() -> None:
    global _CACHE_LOADED, _SENT_ALERTS
    if _CACHE_LOADED:
        return
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            now_ts = time.time()
            today_str = datetime.now(IST).strftime("%Y-%m-%d")
            _SENT_ALERTS = {
                k: v for k, v in data.items()
                if isinstance(v, dict) and (v.get("date") == today_str or (now_ts - float(v.get("timestamp", 0)) < 86400))
            }
        except Exception as e:
            logger.warning("Failed loading Alpha Telegram cache: %s", e)
            _SENT_ALERTS = {}
    _CACHE_LOADED = True


def _save_cache() -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = f"{CACHE_FILE}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_SENT_ALERTS, f, indent=2)
        os.replace(tmp, CACHE_FILE)
    except Exception as e:
        logger.warning("Failed saving Alpha Telegram cache: %s", e)


RETRY_BACKOFF_SECONDS: Tuple[float, ...] = (0.8, 1.6, 3.0)


def _send_telegram_http(bot_token: str, chat_id: str, message: str) -> Tuple[bool, str]:
    """
    Send Telegram message to a single chat_id with:
    1. SSL fallback for local certificate issues.
    2. Automatic 3x retry with backoff (0.8s -> 1.6s -> 3.0s) on network/timeout/5xx/429/10054 errors.
    3. Immediate Markdown -> Plaintext fallback on HTTP 400 entity parse errors (also protected by retry).
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    def _open_req(req_obj: urllib.request.Request):
        try:
            return urllib.request.urlopen(req_obj, timeout=10)
        except urllib.error.URLError as ue:
            if "CERTIFICATE_VERIFY_FAILED" in str(ue) or isinstance(getattr(ue, "reason", None), ssl.SSLError):
                return urllib.request.urlopen(req_obj, timeout=10, context=ssl._create_unverified_context())
            raise

    def _post_with_retries(req_payload: Dict[str, Any], label: str) -> Tuple[bool, str, int]:
        max_attempts = 1 + len(RETRY_BACKOFF_SECONDS)
        last_err = ""
        for attempt in range(max_attempts):
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(req_payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with _open_req(req) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    if bool(res.get("ok")):
                        return True, label if attempt == 0 else f"{label}_RETRY_{attempt}", 200
                    last_err = f"API_NOT_OK: {res}"
            except urllib.error.HTTPError as he:
                err_body = ""
                try:
                    err_body = he.read().decode("utf-8")
                except Exception:
                    pass
                # Non-retryable client error (e.g., HTTP 400 entity parse error or 401/403)
                if he.code == 400 and "can't parse entities" in err_body.lower():
                    return False, f"HTTP_400_ENTITY: {err_body}", 400
                if 400 <= he.code < 500 and he.code != 429:
                    return False, f"HTTP_{he.code}: {err_body or he.reason}", he.code
                last_err = f"HTTP_{he.code}: {err_body or he.reason}"
            except Exception as e:
                last_err = str(e)

            if attempt < len(RETRY_BACKOFF_SECONDS):
                delay = RETRY_BACKOFF_SECONDS[attempt]
                logger.warning(
                    "[ALPHA TELEGRAM] Transient error on %s for chat_id %s (attempt %d/%d): %s — retrying in %.1fs",
                    label,
                    chat_id,
                    attempt + 1,
                    max_attempts,
                    last_err,
                    delay,
                )
                time.sleep(delay)

        return False, last_err, 0

    ok, detail, code = _post_with_retries(payload, "OK")
    if ok:
        return True, detail

    if code == 400 and "HTTP_400_ENTITY" in detail:
        plain_payload = {
            "chat_id": chat_id,
            "text": message.replace("*", "").replace("`", "").replace("_", ""),
            "disable_web_page_preview": True,
        }
        ok2, detail2, _ = _post_with_retries(plain_payload, "OK_PLAINTEXT")
        if ok2:
            return True, detail2
        return False, f"HTTP_400_RETRY_FAILED: {detail2}"

    return False, detail


def _broadcast_event(event_id: str, message: str, bypass_dedup: bool = False) -> Dict[str, Any]:
    """
    Bug #3 Fix: Broadcasts message to all configured chat_ids with:
    1. Per-recipient dedup key: f"{event_id}_{chat_id}"
    2. Isolated try/except per chat_id so one failed chat never blocks the other!
    """
    cfg = get_alpha_telegram_config()
    if not cfg["enabled"] or not cfg["bot_token"] or not cfg["chat_ids"]:
        return {"status": "skipped", "reason": "Telegram Alpha bot disabled or token/chat_ids empty"}

    sent_to: List[str] = []
    skipped_dedup: List[str] = []
    failed_chats: Dict[str, str] = {}

    with _ALERT_LOCK:
        _ensure_cache_loaded()

    for chat_id in cfg["chat_ids"]:
        per_chat_key = f"{event_id}_{chat_id}"
        if not bypass_dedup:
            with _ALERT_LOCK:
                if per_chat_key in _SENT_ALERTS:
                    skipped_dedup.append(chat_id)
                    continue

        try:
            ok, detail = _send_telegram_http(cfg["bot_token"], chat_id, message)
            if ok:
                sent_to.append(chat_id)
                if not bypass_dedup:
                    with _ALERT_LOCK:
                        _SENT_ALERTS[per_chat_key] = {
                            "event_id": event_id,
                            "chat_id": chat_id,
                            "timestamp": time.time(),
                            "date": datetime.now(IST).strftime("%Y-%m-%d"),
                        }
                        _save_cache()
            else:
                failed_chats[chat_id] = detail
                logger.warning("[ALPHA TELEGRAM] Delivery failed for chat_id %s: %s", chat_id, detail)
        except Exception as e:
            failed_chats[chat_id] = str(e)
            logger.warning("[ALPHA TELEGRAM] Unexpected error for chat_id %s: %s", chat_id, e)

    return {
        "status": "ok" if sent_to else ("dedup_skipped" if skipped_dedup and not failed_chats else "failed"),
        "sent_to": sent_to,
        "skipped_dedup": skipped_dedup,
        "failed_chats": failed_chats,
    }


def _worker_loop() -> None:
    while True:
        item = _DISPATCH_QUEUE.get()
        try:
            _broadcast_event(
                event_id=item["event_id"],
                message=item["message"],
                bypass_dedup=bool(item.get("bypass_dedup", False)),
            )
        except Exception as e:
            logger.error("[ALPHA TELEGRAM WORKER] Error: %s", e)
        finally:
            _DISPATCH_QUEUE.task_done()


def _enqueue_alert(event_id: str, message: str, bypass_dedup: bool = False) -> None:
    global _WORKER_STARTED
    with _WORKER_LOCK:
        if not _WORKER_STARTED:
            t = threading.Thread(target=_worker_loop, name="AlphaTelegramWorker", daemon=True)
            t.start()
            _WORKER_STARTED = True
    _DISPATCH_QUEUE.put({"event_id": event_id, "message": message, "bypass_dedup": bypass_dedup})


def _compute_split_lots(trade: Dict[str, Any]) -> Tuple[int, int, int, int]:
    """
    Bug #2 Fix: Exact 1-Lot & Multi-Lot dynamic split matching v13_nifty_options_ledger.py.
    Returns (lots, lot_size, t1_lots, runner_lots).
    """
    lots = max(1, int(trade.get("lots", 1)))
    lot_size = int(trade.get("lot_size", 65))
    raw_t1 = trade.get("t1_lots")
    raw_runner = trade.get("runner_lots")
    if raw_t1 is not None and raw_runner is not None:
        t1_lots = int(raw_t1)
        runner_lots = int(raw_runner)
    else:
        t1_lots = 0 if lots == 1 else math.ceil(lots / 2)
        runner_lots = lots - t1_lots
    return lots, lot_size, t1_lots, runner_lots


def format_alpha_entry_message(open_trade: Dict[str, Any], eval_result: Optional[Dict[str, Any]] = None) -> str:
    lots, lot_size, t1_lots, runner_lots = _compute_split_lots(open_trade)
    qty = int(open_trade.get("qty", lots * lot_size))
    opt_type = str(open_trade.get("opt_type") or open_trade.get("option_type") or "CE")
    strike = int(open_trade.get("strike", 0))
    contract = str(open_trade.get("symbol") or open_trade.get("contract_symbol") or f"NIFTY {strike} {opt_type}")
    setup = str(open_trade.get("trigger_type") or open_trade.get("trigger_setup") or "QUANT_BREAKOUT")
    entry_time = str(open_trade.get("entry_time_str") or open_trade.get("entry_time_ist") or datetime.now(IST).strftime("%H:%M:%S IST"))
    entry_prem = float(open_trade.get("entry_premium", 0.0))
    sl_prem = float(open_trade.get("initial_sl_premium", open_trade.get("current_sl_premium", 0.0)))
    sl_pts = float(open_trade.get("sl_points") or open_trade.get("sl_pts") or max(entry_prem - sl_prem, 1.0))
    t1_prem = float(open_trade.get("t1_premium", round_to_nse_tick(entry_prem + 1.5 * sl_pts)))
    t2_prem = float(open_trade.get("t2_premium", round_to_nse_tick(entry_prem + 2.5 * sl_pts)))
    spot_entry = float(open_trade.get("entry_spot") or open_trade.get("entry_spot_ltp") or 0.0)
    capital_deployed = float(open_trade.get("capital_deployed_inr", round(entry_prem * qty, 2)))
    max_risk = float(open_trade.get("max_loss_inr", round(sl_pts * qty, 2)))

    num_slices = int(open_trade.get("entry_legs") or open_trade.get("num_slices") or 1)
    slice_lots = open_trade.get("entry_slices") or open_trade.get("slice_lots") or [lots]
    slice_str = f" • 🧊 `{num_slices} Legs {slice_lots}`" if num_slices > 1 else ""

    if lots == 1:
        t1_desc = f"₹{t1_prem:.2f} (+1.5R • Trails 1L SL to Entry + ₹2.0)"
    else:
        t1_desc = f"₹{t1_prem:.2f} (+1.5R • Books {t1_lots}L / Trails {runner_lots}L Runner)"

    gates_info = ""
    if eval_result and isinstance(eval_result.get("module3_signal"), dict):
        m3 = eval_result["module3_signal"]
        passed = m3.get("gates_passed", 7)
        total = m3.get("gates_total", 7)
        gates_info = f"\n✅ *Quant Gates:* `{passed}/{total} Passed`"

    dir_emoji = "🟢" if opt_type == "CE" else "🔴"
    return (
        f"⚡ *ALPHA QUANT — AUTO TRADE ENTRY* {dir_emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *Contract:* `{contract}` ({strike} {opt_type})\n"
        f"📐 *Setup:* `{setup}`\n"
        f"⏰ *Time (IST):* `{entry_time}` | *Spot:* `₹{spot_entry:,.2f}`\n"
        f"📦 *Position:* `{lots} Lots ({qty} Qty)`{slice_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Entry Premium:* `₹{entry_prem:.2f}`\n"
        f"🛑 *Initial Stop-Loss:* `₹{sl_prem:.2f}` (`-{sl_pts:.2f} pts`)\n"
        f"🎯 *Target 1 (T1):* `{t1_desc}`\n"
        f"🚀 *Target 2 (T2):* `₹{t2_prem:.2f}` (`+2.5R Velocity Runner`)\n"
        f"💼 *Outlay:* `₹{capital_deployed:,.0f}` | *1R Risk:* `₹{max_risk:,.0f}`"
        f"{gates_info}"
    )


def format_alpha_milestone_message(open_trade: Dict[str, Any], milestone_type: str) -> str:
    lots, lot_size, t1_lots, runner_lots = _compute_split_lots(open_trade)
    opt_type = str(open_trade.get("opt_type") or open_trade.get("option_type") or "CE")
    strike = int(open_trade.get("strike", 0))
    contract = str(open_trade.get("symbol") or open_trade.get("contract_symbol") or f"NIFTY {strike} {opt_type}")
    entry_prem = float(open_trade.get("entry_premium", 0.0))
    cur_prem = float(open_trade.get("current_ltp") or open_trade.get("current_premium") or entry_prem)
    cur_sl = float(open_trade.get("current_sl_premium", 0.0))
    peak_prem = float(open_trade.get("high_watermark") or open_trade.get("peak_premium") or cur_prem)
    r_mult = float(open_trade.get("unrealized_r") or open_trade.get("current_r_multiple") or 0.0)

    if milestone_type == "STAGE_0A_UTURN_SHIELD":
        return (
            f"🛡️ *ALPHA — STAGE 0A (+0.45R) U-TURN SHIELD*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Contract:* `{contract}` ({strike} {opt_type})\n"
            f"📈 *Peak Reached:* `₹{peak_prem:.2f}` (`>= +0.45R`)\n"
            f"🔒 *Tightened SL:* `₹{cur_sl:.2f}` (`-0.45R Half-Loss Cap`)\n"
            f"💡 *Status:* Pre-T1 U-turn protection active! Maximum downside risk cut by 55%."
        )
    elif milestone_type == "STAGE_0B_UTURN_SHIELD":
        sl_pts = max(float(open_trade.get("sl_points", 1.0)), 1.0)
        peak_r = ((peak_prem - entry_prem) / sl_pts) if entry_prem > 0 else 0.80
        is_be_locked = cur_sl >= entry_prem and entry_prem > 0
        lock_desc = "Cost-Plus Breakeven Lock (Entry + ₹1.50)" if is_be_locked else "-0.25R Near-Breakeven Cap"
        header = (
            "🛡️ *ALPHA — STAGE 0B (+0.80R) NEAR-BE SHIELD*\n"
            if peak_r >= 0.80
            else "🛡️ *ALPHA — STAGE 0B (+0.75R) BREAKEVEN SHIELD*\n"
        )
        return (
            f"{header}"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Contract:* `{contract}` ({strike} {opt_type})\n"
            f"📈 *Peak Reached:* `₹{peak_prem:.2f}` (`>= +0.75R Halfway-to-T1`)\n"
            f"🔒 *Tightened SL:* `₹{cur_sl:.2f}` (`{lock_desc}`)\n"
            f"💡 *Status:* Pre-T1 Breakeven/Near-BE shield locked! Downside risk eliminated before T1."
        )
    elif milestone_type == "STAGE_1B0_GREEN_SHIELD":
        sl_pts = max(float(open_trade.get("sl_points", 1.0)), 1.0)
        locked_r = round((cur_sl - entry_prem) / sl_pts, 2)
        return (
            f"🛡️ *ALPHA — STAGE 1B-0 (+1.00R) GREEN SHIELD*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Contract:* `{contract}` ({strike} {opt_type})\n"
            f"📈 *Peak Reached:* `₹{peak_prem:.2f}` (`>= +1.00R`)\n"
            f"🔒 *Locked Green SL:* `₹{cur_sl:.2f}` (`+{locked_r:.2f}R Profit Floor`)\n"
            f"💡 *Status:* Red trade risk 100% eliminated! Guaranteed green floor locked before T1."
        )
    elif milestone_type == "PRE_T1_SHIELD":
        sl_pts = max(float(open_trade.get("sl_points", 1.0)), 1.0)
        locked_r = round((cur_sl - entry_prem) / sl_pts, 2)
        return (
            f"🛡️ *ALPHA — STAGE 1B-1 (+1.20R) CHANDELIER SHIELD*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Contract:* `{contract}` ({strike} {opt_type})\n"
            f"📈 *Peak Reached:* `₹{peak_prem:.2f}` (`>= +1.20R`)\n"
            f"🔒 *New Locked SL:* `₹{cur_sl:.2f}` (`+{locked_r:.2f}R Progressive Lock`)\n"
            f"💡 *Status:* Progressive Chandelier Shield active! Trailing peak with 8.5pt+ breathing floor."
        )
    elif milestone_type == "PRE_T1_DOORSTEP_135":
        sl_pts = max(float(open_trade.get("sl_points", 1.0)), 1.0)
        locked_r = round((cur_sl - entry_prem) / sl_pts, 2)
        return (
            f"⚡ *ALPHA — STAGE 1C (+1.35R) T1 DOORSTEP LOCK* 🔥\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Contract:* `{contract}` ({strike} {opt_type})\n"
            f"📈 *Peak Reached:* `₹{peak_prem:.2f}` (`>= +1.35R T1 Doorstep`)\n"
            f"🔒 *Doorstep SL:* `₹{cur_sl:.2f}` (`+{locked_r:.2f}R Locked on 100% Lots`)\n"
            f"🛡️ *Status:* T1 doorstep secured! Zero major profit give-back if wave reverses before T1."
        )
    elif milestone_type == "T1_BOOKED":
        t1_fill = float(open_trade.get("t1_exit_price") or open_trade.get("t1_premium") or cur_prem)
        if lots == 1 or t1_lots == 0:
            split_line = (
                f"🏃 *1-Lot Single Runner Mode:* 0 Lots exited at T1; full `1 Lot ({lot_size} Qty)` "
                f"riding for T2 (+2.5R) with SL locked at `₹{cur_sl:.2f}` (`Entry + ₹2.0`)!"
            )
        else:
            split_line = (
                f"💰 *Partial Booked:* `{t1_lots} Lots ({t1_lots * lot_size} Qty)` locked @ `₹{t1_fill:.2f}` (+1.5R)\n"
                f"🏃 *Runner Active:* `{runner_lots} Lots ({runner_lots * lot_size} Qty)` trailing with SL @ `₹{cur_sl:.2f}` (`Entry + ₹2.0`)"
            )
        return (
            f"🎯 *ALPHA — TARGET 1 (+1.5R) HIT!* 🔥\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Contract:* `{contract}` ({strike} {opt_type})\n"
            f"💵 *Entry:* `₹{entry_prem:.2f}` ➔ *T1 Fill:* `₹{t1_fill:.2f}`\n"
            f"{split_line}"
        )
    elif milestone_type == "STAGE_2_TRAIL":
        return (
            f"🚀 *ALPHA — STAGE 2 (+2.0R) STEP-TRAIL LOCKED*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Contract:* `{contract}` ({strike} {opt_type})\n"
            f"📈 *Peak Premium:* `₹{peak_prem:.2f}` (`{r_mult:+.2f}R`)\n"
            f"🔒 *Runner SL Trailed To:* `₹{cur_sl:.2f}` (`+1.0R+ Locked on Runner`)"
        )
    elif milestone_type == "DOORSTEP_220_TRAIL":
        return (
            f"⚡ *ALPHA — +2.20R DOORSTEP TRAIL LOCKED* 🔥\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Contract:* `{contract}` ({strike} {opt_type})\n"
            f"📈 *Peak Premium:* `₹{peak_prem:.2f}` (`{r_mult:+.2f}R Doorstep`)\n"
            f"🔒 *Runner SL Trailed To:* `₹{cur_sl:.2f}` (`+1.60R Locked Above T1`)\n"
            f"🛡️ *Status:* T2 target doorstep secured! Zero profit give-back on pullback."
        )
    elif milestone_type == "STAGE_4_T2_VELOCITY":
        t2_prem = float(open_trade.get("t2_premium", cur_prem))
        return (
            f"🔥 *ALPHA — TARGET 2 (+2.50R) REACHED • VELOCITY TRAIL ARMED!* 🚀\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Contract:* `{contract}` ({strike} {opt_type})\n"
            f"📈 *T2 Milestone:* `₹{t2_prem:.2f}` ➔ *Peak:* `₹{peak_prem:.2f}`\n"
            f"🔒 *Runner Floor SL:* `₹{cur_sl:.2f}` (`max(T2 - ₹1.50, HWM - 0.20R)`)\n"
            f"🏃 *Status:* Uncapped Parabolic Runner active! T2 profit floor locked while riding upside."
        )
    elif milestone_type == "COILING_30M_EXTENSION":
        sl_mode = (
            "Breakeven Lock (Entry + ₹1.50)"
            if cur_sl >= entry_prem
            else "Tight Coiling Cap (-0.35R)"
        )
        return (
            f"⏳ *ALPHA — 20M->30M COILING EXTENSION ARMED*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Contract:* `{contract}` ({strike} {opt_type})\n"
            f"📈 *20m Peak:* `₹{peak_prem:.2f}` | *Live LTP:* `₹{cur_prem:.2f}` (`{r_mult:+.2f}R`)\n"
            f"🔒 *Tightened SL:* `₹{cur_sl:.2f}` (`{sl_mode}`)\n"
            f"💡 *Status:* Spot in favor with strong initial impulse! Time-stop extended to 30.0m."
        )
    else:  # STAGE_3_45M_LOCK
        return (
            f"⏱️ *ALPHA — 45-MIN RUNNER SL STEP-UP*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *Contract:* `{contract}` ({strike} {opt_type})\n"
            f"🔒 *Tightened Runner SL:* `₹{cur_sl:.2f}`\n"
            f"💡 *Status:* Post-T1 45m theta protection lock engaged."
        )


def format_alpha_exit_message(closed_trade: Dict[str, Any], session_stats: Optional[Dict[str, Any]] = None) -> str:
    lots, lot_size, t1_lots, runner_lots = _compute_split_lots(closed_trade)
    qty = int(closed_trade.get("qty", lots * lot_size))
    opt_type = str(closed_trade.get("opt_type") or closed_trade.get("option_type") or "CE")
    strike = int(closed_trade.get("strike", 0))
    contract = str(closed_trade.get("symbol") or closed_trade.get("contract_symbol") or f"NIFTY {strike} {opt_type}")
    entry_prem = float(closed_trade.get("entry_premium", 0.0))
    exit_prem = float(closed_trade.get("exit_premium", 0.0))
    net_pnl = float(closed_trade.get("net_pnl_inr", 0.0))
    gross_pnl = float(closed_trade.get("gross_pnl_inr", 0.0))
    charges = float(closed_trade.get("charges_inr", 0.0)) + float(closed_trade.get("slippage_inr", 0.0))
    r_mult = float(
        closed_trade.get("r_multiple")
        if closed_trade.get("r_multiple") is not None
        else closed_trade.get("realized_r_multiple", 0.0)
    )
    hold_mins = float(closed_trade.get("hold_minutes", 0.0))
    exit_reason = str(closed_trade.get("exit_reason", "CLOSED"))
    t1_booked = bool(closed_trade.get("t1_booked", False))

    # Bug #2 Fix: Show ({t1_lots}:{runner_lots} Blended) ONLY when t1_booked and both t1_lots > 0 and runner_lots > 0
    blend_suffix = f" `({t1_lots}:{runner_lots} Blended)`" if (t1_booked and t1_lots > 0 and runner_lots > 0) else ""

    header_emoji = "✅" if net_pnl >= 0 else "🛑"
    pnl_sign = "+" if net_pnl >= 0 else ""

    session_footer = ""
    if session_stats:
        s_closed = int(session_stats.get("total_closed", 0))
        s_wins = int(session_stats.get("wins", 0))
        s_losses = int(session_stats.get("losses", 0))
        s_wr = float(session_stats.get("win_rate_pct", 0.0))
        s_net = float(session_stats.get("net_realized_pnl_inr", 0.0))
        s_sign = "+" if s_net >= 0 else ""
        session_footer = (
            f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Session Ledger:* `{s_closed} Trades ({s_wins}W / {s_losses}L • {s_wr:.1f}% WR)`\n"
            f"🏦 *Session Net Realized:* `{s_sign}₹{s_net:,.2f}`"
        )

    return (
        f"{header_emoji} *ALPHA QUANT — TRADE CLOSED*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *Contract:* `{contract}` ({strike} {opt_type})\n"
        f"📦 *Size:* `{lots} Lots ({qty} Qty)`\n"
        f"💵 *Entry ➔ Exit:* `₹{entry_prem:.2f}` ➔ `₹{exit_prem:.2f}`{blend_suffix}\n"
        f"⏱️ *Hold Time:* `{hold_mins:.1f} min`\n"
        f"📌 *Exit Reason:* `{exit_reason}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Net Realized PnL:* `{pnl_sign}₹{net_pnl:,.2f}` (`{r_mult:+.2f}R`)\n"
        f"🧾 *Gross:* `₹{gross_pnl:,.2f}` | *Charges+Slip:* `-₹{charges:,.2f}`"
        f"{session_footer}"
    )


def dispatch_alpha_entry_alert(open_trade: Dict[str, Any], eval_result: Optional[Dict[str, Any]] = None) -> None:
    cfg = get_alpha_telegram_config()
    if not cfg["enabled"] or not cfg["notify_entries"]:
        return
    trade_id = str(open_trade.get("trade_id", "UNKNOWN"))
    event_id = f"{trade_id}_ENTRY"
    msg = format_alpha_entry_message(open_trade, eval_result)
    _enqueue_alert(event_id, msg, bypass_dedup=False)


def dispatch_alpha_milestone_alert(open_trade: Dict[str, Any], milestone_type: str) -> None:
    cfg = get_alpha_telegram_config()
    if not cfg["enabled"] or not cfg["notify_milestones"]:
        return
    trade_id = str(open_trade.get("trade_id", "UNKNOWN"))
    event_id = f"{trade_id}_{milestone_type}"
    msg = format_alpha_milestone_message(open_trade, milestone_type)
    _enqueue_alert(event_id, msg, bypass_dedup=False)


def dispatch_alpha_exit_alert(closed_trade: Dict[str, Any], session_stats: Optional[Dict[str, Any]] = None) -> None:
    cfg = get_alpha_telegram_config()
    if not cfg["enabled"] or not cfg["notify_exits"]:
        return
    trade_id = str(closed_trade.get("trade_id", "UNKNOWN"))
    event_id = f"{trade_id}_EXIT"
    msg = format_alpha_exit_message(closed_trade, session_stats)
    _enqueue_alert(event_id, msg, bypass_dedup=False)


def dispatch_alpha_test_alert() -> Dict[str, Any]:
    """Synchronously broadcast a diagnostic test alert to all configured Alpha Telegram recipients."""
    now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    cfg = get_alpha_telegram_config()
    msg = (
        f"🔔 *ALPHA QUANT — DIAGNOSTIC TEST ALERT* ⚡\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *Bot Status:* Online & Authenticated\n"
        f"👥 *Configured Recipients:* `{len(cfg['chat_ids'])}` (`{', '.join(cfg['chat_ids'])}`)\n"
        f"🛡️ *Active Guards:* v4.1 Anti-Whipsaw + v3.1 Auto-Slice Iceberg\n"
        f"⏰ *Timestamp:* `{now_ist}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🚀 *Live Entries, +0.5R Shield, T1 (+1.5R), Stage 2 (+2.0R), 45m Lock & Exits are armed!*"
    )
    return _broadcast_event(f"TEST_ALERT_{int(time.time())}", msg, bypass_dedup=True)
