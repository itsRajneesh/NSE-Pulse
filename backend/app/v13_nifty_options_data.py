"""
v13_nifty_options_data.py
-------------------------------------------------------------------------------
Isolated Data & Broker Connectivity Layer for NIFTY 50 Intraday Options (v2.3)
- Supports FULL Mode via Fyers API v3 Non-Trading App ("NSE Paper Trade Lab"):
  * 1-Click OAuth Login URL generator + Auth-Code / Redirect-URL token exchange
  * SHA-256 appIdHash computation (Pure Python stdlib + requests/urllib, zero bloat)
  * 0.15s Rate-Limit Guard across Fyers v3 Option Chain & 5-minute History calls
- Supports Automatic DEGRADED Mode Fallback (when Fyers token is not active):
  * Uses cached Yahoo Finance 5m candles (^NSEI, ^INDIAVIX, ^NSEBANK)
  * Uses NSE Option Chain API with automatic Black-76 mathematical fallback
    after-hours so the 4th Tab never crashes 24x7.
-------------------------------------------------------------------------------
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import ssl
import threading
import time
import urllib.request
from datetime import datetime, date, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse, quote, urlencode

try:
    import requests  # type: ignore
except ImportError:
    requests = None  # type: ignore

try:
    import yfinance as yf  # type: ignore
except ImportError:
    yf = None  # type: ignore

from .v13_nifty_options_engine import (
    IST,
    RISK_FREE_RATE,
    SECONDS_PER_YEAR,
    black76_price,
    compute_seconds_to_expiry,
    round_to_nse_tick,
    _normalize_candles,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data" / "nifty_options_quant"
DATA_DIR.mkdir(parents=True, exist_ok=True)
FYERS_CONFIG_FILE = DATA_DIR / "fyers_config.json"

FYERS_AUTH_URL_BASE = "https://api-t1.fyers.in/api/v3/generate-authcode"
FYERS_VALIDATE_URL = "https://api-t1.fyers.in/api/v3/validate-authcode"
FYERS_PROFILE_URL = "https://api-t1.fyers.in/api/v3/profile"
FYERS_HISTORY_URL = "https://api-t1.fyers.in/data/history"
FYERS_OPTIONCHAIN_URL = "https://api-t1.fyers.in/data/options-chain-v3"
FYERS_QUOTES_URL = "https://api-t1.fyers.in/data/quotes"


def _http_json_request(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    timeout: int = 10,
) -> Tuple[int, Dict[str, Any]]:
    """
    Universal HTTPS JSON helper that uses `requests` when available and falls back
    to `urllib.request` (with SSL fallback) when running in minimal environments.
    """
    hdrs = dict(headers or {})
    if params:
        qs = urlencode({k: v for k, v in params.items() if v is not None})
        if qs:
            url = f"{url}{'&' if '?' in url else '?'}{qs}"

    if requests is not None:
        try:
            if method.upper() == "POST":
                r = requests.post(url, headers=hdrs, json=json_body, timeout=timeout)
            else:
                r = requests.get(url, headers=hdrs, timeout=timeout)
            data = r.json() if r.content else {}
            return r.status_code, data if isinstance(data, dict) else {}
        except Exception as e:
            logger.debug(f"requests {method} {url} error: {e}")

    try:
        body_bytes = None
        if json_body is not None:
            body_bytes = json.dumps(json_body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=body_bytes, headers=hdrs, method=method.upper())
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(raw) if raw else {}
    except Exception as e:
        logger.debug(f"urllib {method} {url} error: {e}")
        return 0, {"message": str(e)}


class NiftyOptionsDataManager:
    """
    Thread-safe data manager for NIFTY 50 Options Quant Engine.
    Seamlessly switches between FULL Mode (Fyers v3) and DEGRADED Mode (Free Fallback).
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._fyers_rate_lock = threading.Lock()
        self._last_fyers_call_ts: float = 0.0

        self._config: Dict[str, Any] = self._load_config()
        self._bundle_cache: Optional[Dict[str, Any]] = None
        self._bundle_cache_at: float = 0.0
        self._cache_ttl_seconds: float = 2.0

        # Tiered 5m historical candle cache (45s TTL to allow 2.0s fast option chain polling)
        self._candle_cache: Dict[str, Any] = {}
        self._candle_cache_at: float = 0.0
        self._candle_cache_ttl: float = 45.0

        # Last-Known-Good FULL bundle cache (60s grace period on transient broker hiccup)
        self._last_valid_full_bundle: Optional[Dict[str, Any]] = None
        self._last_full_bundle_ts: float = 0.0
        self._last_known_expiry_dt: Optional[datetime] = None
        self._last_known_expiry_str: Optional[str] = None

        self._straddle_session_date: Optional[str] = None
        self._straddle_samples: List[float] = []

        self._nse_session: Any = None
        self._nse_cookies_at: float = 0.0

    # ==========================================================================
    # FYERS CREDENTIALS & 1-CLICK DAILY TOKEN EXCHANGE
    # ==========================================================================

    def _load_config(self) -> Dict[str, Any]:
        cfg: Dict[str, Any] = {
            "app_id": os.getenv("FYERS_APP_ID", "").strip(),
            "secret_id": os.getenv("FYERS_SECRET_ID", "").strip(),
            "redirect_uri": os.getenv("FYERS_REDIRECT_URI", "https://127.0.0.1").strip() or "https://127.0.0.1",
            "access_token": os.getenv("FYERS_ACCESS_TOKEN", "").strip(),
            "token_date": "",
            "user_name": "",
            "capital_inr": 100000.0,
            "risk_mode": "PERCENT",
            "risk_value": 2.0,
            "lot_size": 75,
        }
        if FYERS_CONFIG_FILE.exists():
            try:
                saved = json.loads(FYERS_CONFIG_FILE.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    for k, v in saved.items():
                        if v not in (None, ""):
                            cfg[k] = v
            except Exception as e:
                logger.warning(f"Could not read fyers_config.json: {e}")
        return cfg

    def _save_config(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            tmp = FYERS_CONFIG_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._config, indent=2), encoding="utf-8")
            tmp.replace(FYERS_CONFIG_FILE)
        except Exception as e:
            logger.warning(f"Could not save fyers_config.json: {e}")

    def update_sizing_preferences(
        self,
        capital_inr: Optional[float] = None,
        risk_mode: Optional[str] = None,
        risk_value: Optional[float] = None,
        lot_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            if capital_inr is not None and capital_inr >= 1000:
                self._config["capital_inr"] = round(float(capital_inr), 2)
            if risk_mode is not None and str(risk_mode).upper() in ("PERCENT", "FIXED_INR"):
                self._config["risk_mode"] = str(risk_mode).upper()
            if risk_value is not None and risk_value > 0:
                self._config["risk_value"] = round(float(risk_value), 2)
            if lot_size is not None and int(lot_size) >= 1:
                self._config["lot_size"] = int(lot_size)
            self._save_config()
            self._bundle_cache_at = 0.0
            return self.get_sizing_preferences()

    def get_sizing_preferences(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "capital_inr": float(self._config.get("capital_inr", 100000.0)),
                "risk_mode": str(self._config.get("risk_mode", "PERCENT")),
                "risk_value": float(self._config.get("risk_value", 2.0)),
                "lot_size": int(self._config.get("lot_size", 75)),
            }

    @staticmethod
    def _normalize_app_id(app_id: str) -> str:
        clean = (app_id or "").strip()
        if clean and "-" not in clean and len(clean) == 10:
            return f"{clean}-100"
        return clean

    def get_fyers_status(self) -> Dict[str, Any]:
        with self._lock:
            app_id = self._normalize_app_id(self._config.get("app_id", ""))
            has_secret = bool(self._config.get("secret_id", ""))
            token = self._config.get("access_token", "")
            redirect_uri = self._config.get("redirect_uri", "https://127.0.0.1") or "https://127.0.0.1"
            today_str = datetime.now(IST).strftime("%Y-%m-%d")
            token_valid_today = bool(token) and (self._config.get("token_date") == today_str)

            login_url = ""
            if app_id:
                login_url = (
                    f"{FYERS_AUTH_URL_BASE}?client_id={quote(app_id)}"
                    f"&redirect_uri={quote(redirect_uri)}&response_type=code&state=nifty_quant"
                )

            return {
                "connected": token_valid_today,
                "feed_mode": "FULL" if token_valid_today else "DEGRADED",
                "app_id_configured": bool(app_id),
                "app_id_masked": (app_id[:4] + "****" + app_id[-4:]) if len(app_id) >= 8 else app_id,
                "app_id": app_id,
                "secret_configured": has_secret,
                "redirect_uri": redirect_uri,
                "token_date": self._config.get("token_date", ""),
                "user_name": self._config.get("user_name", ""),
                "login_url": login_url,
            }

    def configure_fyers_And_exchange_token(
        self,
        app_id: Optional[str] = None,
        secret_id: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        auth_code_or_url: Optional[str] = None,
        direct_access_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            if app_id is not None and app_id.strip():
                self._config["app_id"] = self._normalize_app_id(app_id.strip())
            if secret_id is not None and secret_id.strip():
                self._config["secret_id"] = secret_id.strip()
            if redirect_uri is not None and redirect_uri.strip():
                clean_uri = redirect_uri.strip()
                if "?" in clean_uri:
                    clean_uri = clean_uri.split("?", 1)[0]
                self._config["redirect_uri"] = clean_uri
            self._save_config()

            eff_app_id = self._normalize_app_id(self._config.get("app_id", ""))
            eff_secret = self._config.get("secret_id", "").strip()

            if direct_access_token and direct_access_token.strip():
                tok = direct_access_token.strip()
                if ":" in tok and tok.startswith(eff_app_id):
                    tok = tok.split(":", 1)[1]
                self._config["access_token"] = tok
                self._config["token_date"] = datetime.now(IST).strftime("%Y-%m-%d")
                self._save_config()
                self._bundle_cache_at = 0.0
                return {
                    "status": "success",
                    "message": "Direct Fyers access_token saved for today.",
                    "fyers_status": self.get_fyers_status(),
                }

            if auth_code_or_url and auth_code_or_url.strip():
                raw = auth_code_or_url.strip()
                auth_code = raw
                if "auth_code=" in raw:
                    try:
                        parsed = urlparse(raw)
                        qs = parse_qs(parsed.query)
                        if "auth_code" in qs and qs["auth_code"]:
                            auth_code = qs["auth_code"][0].strip()
                    except Exception:
                        pass

                if not eff_app_id or not eff_secret:
                    return {
                        "status": "error",
                        "message": "Please provide both Fyers App ID and Secret ID before exchanging auth_code.",
                        "fyers_status": self.get_fyers_status(),
                    }

                app_id_hash = hashlib.sha256(f"{eff_app_id}:{eff_secret}".encode("utf-8")).hexdigest()
                payload = {
                    "grant_type": "authorization_code",
                    "appIdHash": app_id_hash,
                    "code": auth_code,
                }
                status_code, data = _http_json_request(
                    FYERS_VALIDATE_URL,
                    method="POST",
                    json_body=payload,
                    timeout=12,
                )
                if status_code == 200 and data.get("s") == "ok" and data.get("access_token"):
                    self._config["access_token"] = data["access_token"]
                    self._config["token_date"] = datetime.now(IST).strftime("%Y-%m-%d")
                    prof = self._fyers_get(FYERS_PROFILE_URL)
                    if prof and prof.get("s") == "ok":
                        self._config["user_name"] = (prof.get("data") or {}).get("name", "Fyers Connected")
                    self._save_config()
                    self._bundle_cache_at = 0.0
                    return {
                        "status": "success",
                        "message": "Fyers Daily Access Token activated! Engine switched to FULL Mode.",
                        "fyers_status": self.get_fyers_status(),
                    }
                else:
                    err_msg = data.get("message") or f"HTTP {status_code}"
                    return {
                        "status": "error",
                        "message": f"Fyers Token Exchange Failed: {err_msg}",
                        "fyers_status": self.get_fyers_status(),
                    }

            return {
                "status": "success",
                "message": "Fyers App credentials saved. Click 'Open Fyers Login' to generate today's auth_code.",
                "fyers_status": self.get_fyers_status(),
            }

    # ==========================================================================
    # FYERS v3 RATE-LIMITED HTTP CLIENT (MAX ~6.5 REQ/SEC, WELL BELOW 10 REQ/SEC)
    # ==========================================================================

    def _fyers_headers(self) -> Dict[str, str]:
        app_id = self._normalize_app_id(self._config.get("app_id", ""))
        token = self._config.get("access_token", "")
        return {
            "Authorization": f"{app_id}:{token}",
            "Content-Type": "application/json",
            "User-Agent": "NiftyPulseQuant/2.3",
        }

    def _fyers_get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        with self._fyers_rate_lock:
            elapsed = time.monotonic() - self._last_fyers_call_ts
            if elapsed < 0.15:
                time.sleep(0.15 - elapsed)
            self._last_fyers_call_ts = time.monotonic()

        status_code, data = _http_json_request(
            url,
            method="GET",
            headers=self._fyers_headers(),
            params=params,
            timeout=10,
        )
        if status_code == 200 and data.get("s") == "ok":
            return data
        if status_code in (401, 403) or data.get("code") in (-16, -17, -15, 401, 403):
            self._config["token_date"] = ""
        return None

    def _fetch_fyers_5m_candles(self, symbol: str, days_back: int = 5) -> List[Dict[str, Any]]:
        now_ist = datetime.now(IST)
        range_from = (now_ist - timedelta(days=days_back)).strftime("%Y-%m-%d")
        range_to = now_ist.strftime("%Y-%m-%d")
        params = {
            "symbol": symbol,
            "resolution": "5",
            "date_format": "1",
            "range_from": range_from,
            "range_to": range_to,
            "cont_flag": "1",
        }
        res = self._fyers_get(FYERS_HISTORY_URL, params=params)
        candles = (res or {}).get("candles") or []
        out: List[Dict[str, Any]] = []
        for c in candles:
            if len(c) >= 6:
                out.append({
                    "timestamp": datetime.fromtimestamp(int(c[0]), tz=IST),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                })
        return out

    # ==========================================================================
    # FULL MODE vs DEGRADED MODE BUNDLE FETCHER
    # ==========================================================================

    def get_market_bundle(self, force_refresh: bool = False) -> Dict[str, Any]:
        now_mono = time.monotonic()
        with self._lock:
            if (
                not force_refresh
                and self._bundle_cache is not None
                and (now_mono - self._bundle_cache_at) < self._cache_ttl_seconds
            ):
                return self._bundle_cache

        fyers_status = self.get_fyers_status()
        bundle: Optional[Dict[str, Any]] = None

        if fyers_status["connected"]:
            bundle = self._build_full_fyers_bundle()
            if bundle is not None:
                with self._lock:
                    self._last_valid_full_bundle = bundle
                    self._last_full_bundle_ts = now_mono
            elif self._last_valid_full_bundle is not None and (now_mono - self._last_full_bundle_ts) < 60.0:
                logger.info(
                    "[NIFTY QUANT DATA] Serving last-known-good FULL bundle (age: %.1fs) during momentary Fyers latency.",
                    now_mono - self._last_full_bundle_ts,
                )
                bundle = self._last_valid_full_bundle

        if bundle is None:
            bundle = self._build_degraded_free_bundle()

        with self._lock:
            self._bundle_cache = bundle
            self._bundle_cache_at = time.monotonic()
        return bundle

    def _build_full_fyers_bundle(self) -> Optional[Dict[str, Any]]:
        oc_res = self._fyers_get(
            FYERS_OPTIONCHAIN_URL,
            params={"symbol": "NSE:NIFTY50-INDEX", "strikecount": 8},
        )
        if not oc_res or "data" not in oc_res:
            return None

        oc_data = oc_res["data"]
        india_vix = float((oc_data.get("indiavixData") or {}).get("ltp", 14.0) or 14.0)
        expiry_list = oc_data.get("expiryData") or []
        raw_chain = oc_data.get("optionsChain") or []

        spot_ltp = 0.0
        futures_ltp = 0.0
        futures_symbol = ""
        by_strike: Dict[int, Dict[str, Any]] = {}

        for item in raw_chain:
            opt_type = str(item.get("option_type", "")).upper()
            strike_val = int(round(float(item.get("strike_price", -1) or -1)))
            sym = str(item.get("symbol", ""))
            ltp = float(item.get("ltp", 0.0) or 0.0)

            if strike_val == -1 or opt_type == "":
                if "INDEX" in sym and ltp > 0:
                    spot_ltp = ltp
                elif "FUT" in sym and ltp > 0:
                    futures_ltp = ltp
                    futures_symbol = sym
                continue

            if strike_val not in by_strike:
                by_strike[strike_val] = {
                    "strike": strike_val,
                    "ce_ltp": 0.0,
                    "ce_bid": 0.0,
                    "ce_ask": 0.0,
                    "ce_oi": 0,
                    "ce_chg_oi": 0,
                    "ce_volume": 0,
                    "ce_symbol": "",
                    "pe_ltp": 0.0,
                    "pe_bid": 0.0,
                    "pe_ask": 0.0,
                    "pe_oi": 0,
                    "pe_chg_oi": 0,
                    "pe_volume": 0,
                    "pe_symbol": "",
                }
            row = by_strike[strike_val]
            prefix = "ce_" if opt_type == "CE" else "pe_"
            row[f"{prefix}ltp"] = ltp
            row[f"{prefix}bid"] = float(item.get("bid", ltp) or ltp)
            row[f"{prefix}ask"] = float(item.get("ask", ltp) or ltp)
            row[f"{prefix}oi"] = int(item.get("oi", 0) or 0)
            row[f"{prefix}chg_oi"] = int(item.get("oich", 0) or 0)
            row[f"{prefix}volume"] = int(item.get("volume", 0) or 0)
            row[f"{prefix}symbol"] = sym

        now_mono = time.monotonic()
        use_candle_cache = (
            bool(self._candle_cache)
            and (now_mono - self._candle_cache_at) < self._candle_cache_ttl
        )

        if use_candle_cache:
            spot_5m = [dict(c) for c in self._candle_cache.get("spot_5m", [])]
            futures_5m = [dict(c) for c in self._candle_cache.get("futures_5m", [])]
            banknifty_5m = [dict(c) for c in self._candle_cache.get("banknifty_5m", [])]
            banknifty_ltp = float(self._candle_cache.get("banknifty_ltp", 0.0))
            option_candles_5m = dict(self._candle_cache.get("option_candles_5m", {}))

            # Update latest bar with live tick prices
            if spot_5m and spot_ltp > 0:
                spot_5m[-1]["close"] = spot_ltp
                spot_5m[-1]["high"] = max(spot_5m[-1]["high"], spot_ltp)
                spot_5m[-1]["low"] = min(spot_5m[-1]["low"], spot_ltp)
            if futures_5m and futures_ltp > 0:
                futures_5m[-1]["close"] = futures_ltp
                futures_5m[-1]["high"] = max(futures_5m[-1]["high"], futures_ltp)
                futures_5m[-1]["low"] = min(futures_5m[-1]["low"], futures_ltp)
        else:
            spot_5m = self._fetch_fyers_5m_candles("NSE:NIFTY50-INDEX", days_back=5)
            if spot_ltp <= 0 and spot_5m:
                spot_ltp = float(spot_5m[-1]["close"])

            futures_5m = self._fetch_fyers_5m_candles(futures_symbol, days_back=5) if futures_symbol else []
            banknifty_5m = self._fetch_fyers_5m_candles("NSE:NIFTYBANK-INDEX", days_back=5)
            banknifty_ltp = float(banknifty_5m[-1]["close"]) if banknifty_5m else 0.0

            atm_strike = int(round(spot_ltp / 50.0) * 50) if spot_ltp > 0 else 25000
            option_candles_5m: Dict[str, List[Dict[str, Any]]] = {}
            for k, side in [(atm_strike, "CE"), (atm_strike, "PE"), (atm_strike - 50, "CE"), (atm_strike + 50, "PE")]:
                r = by_strike.get(k)
                if not r:
                    continue
                opt_sym = r.get("ce_symbol" if side == "CE" else "pe_symbol", "")
                if opt_sym:
                    df_opt = self._fetch_fyers_5m_candles(opt_sym, days_back=2)
                    if df_opt:
                        option_candles_5m[f"{k}_{side}"] = df_opt

            with self._lock:
                self._candle_cache = {
                    "spot_5m": spot_5m,
                    "futures_5m": futures_5m,
                    "banknifty_5m": banknifty_5m,
                    "banknifty_ltp": banknifty_ltp,
                    "option_candles_5m": option_candles_5m,
                }
                self._candle_cache_at = now_mono

        expiry_dt, expiry_str = self._parse_expiry_info(expiry_list)
        if expiry_dt and expiry_str:
            with self._lock:
                self._last_known_expiry_dt = expiry_dt
                self._last_known_expiry_str = expiry_str
        chain_rows = sorted(by_strike.values(), key=lambda x: x["strike"])

        return {
            "feed_mode": "FULL",
            "spot_ltp": spot_ltp,
            "futures_ltp": futures_ltp,
            "india_vix": india_vix,
            "banknifty_ltp": banknifty_ltp,
            "spot_5m": spot_5m,
            "futures_5m": futures_5m,
            "banknifty_5m": banknifty_5m,
            "option_chain": chain_rows,
            "option_candles_5m": option_candles_5m,
            "expiry_dt": expiry_dt,
            "expiry_str": expiry_str,
            "straddle_session_vwap": self._update_straddle_tracker(spot_ltp, chain_rows),
        }

    # ==========================================================================
    # DEGRADED FREE FALLBACK MODE (YAHOO 5M + NSE OPTION CHAIN / SYNTHETIC B76)
    # ==========================================================================

    def _build_degraded_free_bundle(self) -> Dict[str, Any]:
        spot_5m = self._fetch_yf_5m("^NSEI", default_base=24860.0)
        banknifty_5m = self._fetch_yf_5m("^NSEBANK", default_base=53200.0)
        vix_5m = self._fetch_yf_5m("^INDIAVIX", default_base=14.15)

        spot_ltp = float(spot_5m[-1]["close"]) if spot_5m else 24860.0
        banknifty_ltp = float(banknifty_5m[-1]["close"]) if banknifty_5m else 53200.0
        india_vix = float(vix_5m[-1]["close"]) if vix_5m else 14.15

        chain_rows, expiry_dt, expiry_str, nse_spot = self._fetch_nse_or_synthetic_option_chain(
            spot_ltp=spot_ltp,
            india_vix=india_vix,
        )
        if nse_spot > 0:
            spot_ltp = nse_spot

        straddle_vwap = self._update_straddle_tracker(spot_ltp, chain_rows)

        return {
            "feed_mode": "DEGRADED",
            "spot_ltp": spot_ltp,
            "futures_ltp": 0.0,
            "india_vix": india_vix,
            "banknifty_ltp": banknifty_ltp,
            "spot_5m": spot_5m,
            "futures_5m": [],
            "banknifty_5m": banknifty_5m,
            "option_chain": chain_rows,
            "option_candles_5m": {},
            "expiry_dt": expiry_dt,
            "expiry_str": expiry_str,
            "straddle_session_vwap": straddle_vwap,
        }

    @staticmethod
    def _fetch_yf_5m(ticker: str, default_base: float = 24860.0) -> List[Dict[str, Any]]:
        if yf is not None:
            try:
                raw = yf.download(
                    ticker,
                    period="5d",
                    interval="5m",
                    progress=False,
                    threads=False,
                    timeout=8,
                )
                if raw is not None and not raw.empty:
                    if hasattr(raw.columns, "levels"):
                        raw.columns = [c[0].lower() for c in raw.columns]
                    else:
                        raw.columns = [str(c).lower() for c in raw.columns]
                    return _normalize_candles(raw)
            except Exception as e:
                logger.debug(f"yfinance 5m download failed for {ticker}: {e}")

        # Try Yahoo v8 chart JSON API directly via HTTPS
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker)}?interval=5m&range=5d"
            status_code, data = _http_json_request(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=6,
            )
            if status_code == 200:
                res = ((data.get("chart") or {}).get("result") or [None])[0] or {}
                timestamps = res.get("timestamp") or []
                q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
                opens = q.get("open") or []
                highs = q.get("high") or []
                lows = q.get("low") or []
                closes = q.get("close") or []
                vols = q.get("volume") or []
                bars: List[Dict[str, Any]] = []
                for i, ts in enumerate(timestamps):
                    c_val = closes[i] if i < len(closes) else None
                    if c_val is None:
                        continue
                    bars.append({
                        "timestamp": datetime.fromtimestamp(int(ts), tz=IST),
                        "open": float(opens[i] or c_val),
                        "high": float(highs[i] or c_val),
                        "low": float(lows[i] or c_val),
                        "close": float(c_val),
                        "volume": float(vols[i] or 0.0) if i < len(vols) else 0.0,
                    })
                if bars:
                    return bars
        except Exception:
            pass

        # Offline / Sandbox fallback synthetic 5m bars so tests & offline UI never crash
        now_ist = datetime.now(IST)
        bars_fb: List[Dict[str, Any]] = []
        price = default_base - (35.0 if default_base > 1000 else 0.0)
        step = 1.6 if default_base > 1000 else 0.0
        for i in range(45):
            ts = now_ist - timedelta(minutes=(45 - i) * 5)
            o_p = round(price, 2)
            c_p = round(price + step, 2)
            h_p = round(max(o_p, c_p) + (4.5 if default_base > 1000 else 0.05), 2)
            l_p = round(min(o_p, c_p) - (3.0 if default_base > 1000 else 0.05), 2)
            bars_fb.append({
                "timestamp": ts,
                "open": o_p,
                "high": h_p,
                "low": l_p,
                "close": c_p,
                "volume": 125000.0 if default_base > 1000 else 0.0,
            })
            price = c_p
        return bars_fb

    def _fetch_nse_or_synthetic_option_chain(
        self,
        spot_ltp: float,
        india_vix: float,
    ) -> Tuple[List[Dict[str, Any]], datetime, str, float]:
        now_ist = datetime.now(IST)
        with self._lock:
            cached_exp_dt = self._last_known_expiry_dt
            cached_exp_str = self._last_known_expiry_str

        # If we previously learned the active weekly expiry from Fyers (e.g. 03-Nov), inherit it!
        if cached_exp_dt is not None and cached_exp_dt.date() >= now_ist.date():
            default_exp_dt = cached_exp_dt
            default_exp_str = cached_exp_str or cached_exp_dt.strftime("%d-%b-%Y")
            target_exp_date = default_exp_dt.date()
        else:
            days_ahead = (3 - now_ist.weekday()) % 7
            if days_ahead == 0 and now_ist.time() > dtime(14, 30):
                days_ahead = 7
            target_exp_date = (now_ist + timedelta(days=days_ahead)).date()
            default_exp_dt = datetime.combine(target_exp_date, dtime(15, 30), tzinfo=IST)
            default_exp_str = target_exp_date.strftime("%d-%b-%Y")

        if requests is not None:
            try:
                if self._nse_session is None or (time.monotonic() - self._nse_cookies_at) > 240:
                    sess = requests.Session()
                    sess.headers.update({
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                        ),
                        "Accept": "application/json,text/plain,*/*",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Referer": "https://www.nseindia.com/option-chain",
                    })
                    sess.get("https://www.nseindia.com", timeout=5)
                    self._nse_session = sess
                    self._nse_cookies_at = time.monotonic()

                resp = self._nse_session.get(
                    "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY",
                    timeout=6,
                )
                if resp.status_code == 200:
                    payload = resp.json()
                    records = payload.get("records") or {}
                    nse_spot = float(records.get("underlyingValue", 0.0) or 0.0)
                    exp_dates = records.get("expiryDates") or []
                    active_exp_str = exp_dates[0] if exp_dates else default_exp_str
                    try:
                        parsed_d = datetime.strptime(active_exp_str, "%d-%b-%Y").date()
                        active_exp_dt = datetime.combine(parsed_d, dtime(15, 30), tzinfo=IST)
                    except Exception:
                        active_exp_dt = default_exp_dt

                    eff_spot = nse_spot if nse_spot > 0 else spot_ltp
                    atm = int(round(eff_spot / 50.0) * 50)
                    rows: List[Dict[str, Any]] = []
                    for item in (payload.get("filtered") or {}).get("data") or records.get("data") or []:
                        k = int(round(float(item.get("strikePrice", 0) or 0)))
                        if abs(k - atm) > 400:
                            continue
                        ce = item.get("CE") or {}
                        pe = item.get("PE") or {}
                        ce_ltp = float(ce.get("lastPrice", 0.0) or 0.0)
                        pe_ltp = float(pe.get("lastPrice", 0.0) or 0.0)
                        rows.append({
                            "strike": k,
                            "ce_ltp": ce_ltp,
                            "ce_bid": float(ce.get("bidprice", ce_ltp) or ce_ltp),
                            "ce_ask": float(ce.get("askPrice", ce_ltp) or ce_ltp),
                            "ce_oi": int(ce.get("openInterest", 0) or 0),
                            "ce_chg_oi": int(ce.get("changeinOpenInterest", 0) or 0),
                            "ce_volume": int(ce.get("totalTradedVolume", 0) or 0),
                            "ce_symbol": f"NIFTY {active_exp_str} {k} CE",
                            "pe_ltp": pe_ltp,
                            "pe_bid": float(pe.get("bidprice", pe_ltp) or pe_ltp),
                            "pe_ask": float(pe.get("askPrice", pe_ltp) or pe_ltp),
                            "pe_oi": int(pe.get("openInterest", 0) or 0),
                            "pe_chg_oi": int(pe.get("changeinOpenInterest", 0) or 0),
                            "pe_volume": int(pe.get("totalTradedVolume", 0) or 0),
                            "pe_symbol": f"NIFTY {active_exp_str} {k} PE",
                        })
                    if rows:
                        return sorted(rows, key=lambda x: x["strike"]), active_exp_dt, active_exp_str, eff_spot
            except Exception as e:
                logger.debug(f"NSE Option Chain live fetch skipped/fallback: {e}")

        atm = int(round(spot_ltp / 50.0) * 50)
        sec_left = compute_seconds_to_expiry(default_exp_dt, now_ist)
        t_years = max(sec_left, 3600.0) / SECONDS_PER_YEAR
        sigma_base = max(india_vix / 100.0, 0.115)
        forward_est = round(spot_ltp * math.exp(RISK_FREE_RATE * t_years), 2)

        synth_rows: List[Dict[str, Any]] = []
        for offset in range(-300, 350, 50):
            k = atm + offset
            moneyness_skew = abs(offset) / 25000.0 * 0.18
            sigma_k = sigma_base + moneyness_skew

            ce_theo = round_to_nse_tick(max(black76_price(forward_est, k, t_years, sigma_k, "CE"), 2.0))
            pe_theo = round_to_nse_tick(max(black76_price(forward_est, k, t_years, sigma_k, "PE"), 2.0))

            dist_factor = max(1, 7 - abs(offset) // 50)
            synth_rows.append({
                "strike": k,
                "ce_ltp": ce_theo,
                "ce_bid": round_to_nse_tick(max(ce_theo - 0.20, 0.05)),
                "ce_ask": round_to_nse_tick(ce_theo + 0.20),
                "ce_oi": int(dist_factor * 185000 + (35000 if offset >= 0 else 0)),
                "ce_chg_oi": int(dist_factor * 14000 * (1 if offset > 0 else -0.4)),
                "ce_volume": int(dist_factor * 420000),
                "ce_symbol": f"NIFTY {default_exp_str} {k} CE",
                "pe_ltp": pe_theo,
                "pe_bid": round_to_nse_tick(max(pe_theo - 0.20, 0.05)),
                "pe_ask": round_to_nse_tick(pe_theo + 0.20),
                "pe_oi": int(dist_factor * 195000 + (40000 if offset <= 0 else 0)),
                "pe_chg_oi": int(dist_factor * 15500 * (1 if offset < 0 else -0.4)),
                "pe_volume": int(dist_factor * 410000),
                "pe_symbol": f"NIFTY {default_exp_str} {k} PE",
            })

        return synth_rows, default_exp_dt, default_exp_str, spot_ltp

    def _update_straddle_tracker(self, spot_ltp: float, chain_rows: List[Dict[str, Any]]) -> float:
        atm = int(round(spot_ltp / 50.0) * 50)
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        if self._straddle_session_date != today_str:
            self._straddle_session_date = today_str
            self._straddle_samples = []

        for r in chain_rows:
            if int(r.get("strike", 0)) == atm:
                s_ltp = float(r.get("ce_ltp", 0.0)) + float(r.get("pe_ltp", 0.0))
                if s_ltp > 5.0:
                    self._straddle_samples.append(s_ltp)
                    if len(self._straddle_samples) > 300:
                        self._straddle_samples = self._straddle_samples[-300:]
                break

        if self._straddle_samples:
            return round(sum(self._straddle_samples) / len(self._straddle_samples), 2)
        return 240.0

    @staticmethod
    def _parse_expiry_info(expiry_list: List[Dict[str, Any]]) -> Tuple[datetime, str]:
        now_ist = datetime.now(IST)
        if expiry_list:
            first = expiry_list[0]
            date_str = str(first.get("date", "")).strip()
            ep = first.get("expiry")
            if ep:
                try:
                    dt = datetime.fromtimestamp(int(ep), tz=IST).replace(hour=15, minute=30, second=0)
                    return dt, date_str or dt.strftime("%d-%b-%Y")
                except Exception:
                    pass
            if date_str:
                for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d"):
                    try:
                        d = datetime.strptime(date_str, fmt).date()
                        dt = datetime.combine(d, dtime(15, 30), tzinfo=IST)
                        return dt, d.strftime("%d-%b-%Y")
                    except Exception:
                        continue

        days_ahead = (3 - now_ist.weekday()) % 7
        target_d = (now_ist + timedelta(days=days_ahead)).date()
        dt = datetime.combine(target_d, dtime(15, 30), tzinfo=IST)
        return dt, target_d.strftime("%d-%b-%Y")


GLOBAL_NIFTY_OPTIONS_DATA = NiftyOptionsDataManager()
