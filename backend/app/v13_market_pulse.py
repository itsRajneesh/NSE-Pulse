"""
V13 Market Pulse & Radar Engine (Idea #1 & Idea #2)
===================================================
100% Standalone Quantitative Market Environment Filter & Structural Playbook.

Features:
1. Idea #2: "Should I Trade Today or Sit on Cash?" (Live Tradeability & Chop Filter)
   - Dual-Window Efficiency Ratio (Session ER + 6-Candle Rolling Impulse ER with 3-Lock V-Guard)
   - 1,468-Stock Institutional VWAP Breadth (Pure price >= vwap, strictly decoupled from net change)
   - Long-Bias Alignment Guard: Caps score <= 38/100 (RED) when broad market breadth < 38% (Bearish Sell-Off)
   - Range-Weighted Wick Ratio (Detects stop-loss hunting wicks vs institutional bodies)
   - Dynamic Time-Adjusted True Day Range Consumed (Wilder's ATR14 consumed fuel curve)
   - India VIX Level & Velocity Gauge
   - Single 0-100 Score, Traffic Light (GREEN/YELLOW/RED), and Position Sizing Advice (1.0x / 0.5x / 0.0x)

2. Idea #1: Next-Day & Pre-Market Structural Bias & Conditional Zones
   - 5-Pillar Weighted Directional Engine (-100 to +100):
     (1) Daily CLV & Close Momentum (25 pts)
     (2) Daily EMA20 & EMA50 Trend Structure (20 pts)
     (3) 1,468-Stock EOD Breadth Participation (25 pts)
     (4) Overnight Global Macro Overlay: S&P 500, Nasdaq, DXY, Brent Crude (20 pts)
     (5) India VIX Regime & Velocity (10 pts)
   - Outputs explicit Next-Session Bias (BULLISH / BEARISH / SIDEWAYS) + Conviction %
   - Static Locked Conditional Execution Zones anchored to completed session during live market
   - Targets & Supports projected strictly outside U_trig and L_trig boundaries

Zero-modification to v13_scanner.py or telegram/ledger.
Includes 90-second in-memory TTL caching with thread locking and direct Yahoo v8 chart API fetching.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import urllib.parse
from datetime import datetime, time as dtime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pytz
import requests
import yfinance as yf

from .config import IST_TZ

logger = logging.getLogger("v13_market_pulse")

# -------------------------------------------------------------------------
# In-Memory Cache & Locking
# -------------------------------------------------------------------------
_PULSE_LOCK = threading.Lock()
_PULSE_CACHE: Dict[str, Any] = {
    "data": None,
    "cached_at": 0.0,
    "macro_dfs": {},
    "macro_dfs_at": 0.0,
}

PULSE_CACHE_TTL_LIVE = 90.0      # 90 seconds during active session
PULSE_CACHE_TTL_OFF = 180.0      # 3 minutes outside market hours
MACRO_DFS_CACHE_TTL = 90.0       # 90s TTL for Yahoo Finance downloads

_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}


def _clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize multi-index columns, convert timezone to IST, remove tz, and sort index."""
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        if out.columns.nlevels >= 2:
            # Handle both (Ticker, PriceField) and (PriceField, Ticker)
            lvl0 = [str(c).strip().title() for c in out.columns.get_level_values(0)]
            if "Close" in lvl0:
                out.columns = out.columns.get_level_values(0)
            else:
                out.columns = out.columns.get_level_values(-1)

    out.columns = [str(c).strip().title() for c in out.columns]
    required = ["Open", "High", "Low", "Close"]
    if not set(required).issubset(out.columns):
        return pd.DataFrame()

    for col in required:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=required).copy()
    if out.empty:
        return pd.DataFrame()

    idx = pd.DatetimeIndex(out.index)
    if idx.tz is not None:
        idx = idx.tz_convert(IST_TZ).tz_localize(None)
    out.index = idx
    return out.sort_index()


def _reconcile_daily_from_intraday(
    df_1d: pd.DataFrame,
    df_5m: pd.DataFrame,
    now_ist: datetime,
) -> pd.DataFrame:
    """
    Multi-Session 5m-to-1d Reconciliation Engine.
    Scans all unique dates in df_5m with >= 10 bars.
    If a completed session (date < today OR (date == today and after 15:30 IST))
    is missing in df_1d or contains null/incomplete OHLC, synthesizes the exact
    daily bar from clean 5m bars and upserts into df_1d.
    Ensures strict tz-naive Asia/Kolkata index consistency.
    """
    if df_5m is None or df_5m.empty:
        return df_1d if df_1d is not None else pd.DataFrame()

    out_1d = df_1d.copy() if (df_1d is not None and not df_1d.empty) else pd.DataFrame(
        columns=["Open", "High", "Low", "Close", "Volume"]
    )

    today_date = now_ist.date()
    is_eod_settled = (now_ist.time() >= dtime(15, 30))

    # Group 5m bars by date
    date_groups = df_5m.groupby(df_5m.index.date)

    synthesized_rows: List[pd.DataFrame] = []

    for d, sub_5m in date_groups:
        # Only consider completed sessions with valid bar counts (>= 10 bars)
        if len(sub_5m) < 10:
            continue

        is_completed = (d < today_date) or (d == today_date and is_eod_settled)
        if not is_completed:
            continue

        # Check if date d already exists in out_1d with complete OHLC
        needs_synthesis = True
        if not out_1d.empty:
            existing_dates = out_1d.index.date
            if d in existing_dates:
                match_row = out_1d[existing_dates == d]
                if (
                    pd.notna(match_row["Open"].iloc[0])
                    and pd.notna(match_row["High"].iloc[0])
                    and pd.notna(match_row["Low"].iloc[0])
                    and pd.notna(match_row["Close"].iloc[0])
                    and float(match_row["Close"].iloc[0]) > 0
                ):
                    needs_synthesis = False

        if needs_synthesis:
            # Drop any incomplete/null row for date d
            if not out_1d.empty and d in out_1d.index.date:
                out_1d = out_1d[out_1d.index.date != d]

            row_ts = pd.Timestamp(d).replace(hour=9, minute=15, second=0, microsecond=0)
            synth_bar = pd.DataFrame(
                [{
                    "Open": float(sub_5m["Open"].iloc[0]),
                    "High": float(sub_5m["High"].max()),
                    "Low": float(sub_5m["Low"].min()),
                    "Close": float(sub_5m["Close"].iloc[-1]),
                    "Volume": float(sub_5m["Volume"].sum()) if "Volume" in sub_5m else 0.0,
                }],
                index=pd.DatetimeIndex([row_ts]),
            )
            synthesized_rows.append(synth_bar)

    if synthesized_rows:
        all_dfs = [out_1d] + synthesized_rows
        out_1d = pd.concat([df for df in all_dfs if not df.empty])
        out_1d = _clean_ohlcv(out_1d)

    return out_1d


def _fetch_yahoo_v8_chart(symbol: str, period: str, interval: str) -> pd.DataFrame:
    """
    Fetch OHLCV candles directly from Yahoo Finance v8 Chart JSON API.
    Bypasses yfinance crumb rate-limiting (HTTP 429) while returning identical OHLCV bars.
    Falls back to query2 and yf.download if needed.
    """
    encoded_sym = urllib.parse.quote(symbol)
    hosts = [
        "https://query1.finance.yahoo.com",
        "https://query2.finance.yahoo.com",
    ]

    for host in hosts:
        url = f"{host}/v8/finance/chart/{encoded_sym}?interval={interval}&range={period}&includePrePost=false"
        try:
            resp = requests.get(url, headers=_HTTP_HEADERS, timeout=8)
            if resp.status_code == 200:
                payload = resp.json()
                results = (payload.get("chart") or {}).get("result")
                if results and len(results) > 0:
                    res0 = results[0]
                    timestamps = res0.get("timestamp") or []
                    quotes = ((res0.get("indicators") or {}).get("quote") or [{}])[0]
                    if timestamps and quotes:
                        dt_index = (
                            pd.to_datetime(timestamps, unit="s", utc=True)
                            .tz_convert(IST_TZ)
                            .tz_localize(None)
                        )
                        df = pd.DataFrame(
                            {
                                "Open": quotes.get("open"),
                                "High": quotes.get("high"),
                                "Low": quotes.get("low"),
                                "Close": quotes.get("close"),
                                "Volume": quotes.get("volume") or [0] * len(timestamps),
                            },
                            index=dt_index,
                        )
                        cleaned = _clean_ohlcv(df)
                        if not cleaned.empty:
                            return cleaned
        except Exception as exc:
            logger.debug(f"Yahoo v8 fetch attempt failed on {host} for {symbol}: {exc}")

    # Secondary fallback to yfinance download
    try:
        df_yf = yf.download(
            symbol,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=False,
            threads=False,
            timeout=10,
        )
        cleaned = _clean_ohlcv(df_yf)
        if not cleaned.empty:
            return cleaned
    except Exception as exc:
        logger.debug(f"yfinance fallback failed for {symbol}: {exc}")

    return pd.DataFrame()


def _fetch_macro_data(
    force: bool = False,
    fallback_nifty_df: Optional[pd.DataFrame] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Fetch 5m and 1d candles for Nifty, VIX, US indices, DXY, and Crude.
    Cached for 90 seconds. Never overwrites valid cached DataFrames with empty ones.
    """
    global _PULSE_CACHE
    now = time.time()

    with _PULSE_LOCK:
        cached_dfs = _PULSE_CACHE.get("macro_dfs") or {}
        has_valid_cache = (
            isinstance(cached_dfs, dict)
            and not cached_dfs.get("nifty_1d", pd.DataFrame()).empty
            and not cached_dfs.get("nifty_5m", pd.DataFrame()).empty
        )
        if not force and has_valid_cache and (now - _PULSE_CACHE["macro_dfs_at"]) < MACRO_DFS_CACHE_TTL:
            return cached_dfs

    tickers = {
        "nifty_5m": ("^NSEI", "5d", "5m"),
        "vix_5m": ("^INDIAVIX", "5d", "5m"),
        "nifty_1d": ("^NSEI", "3mo", "1d"),
        "vix_1d": ("^INDIAVIX", "3mo", "1d"),
        "sp500_1d": ("^GSPC", "1mo", "1d"),
        "nasdaq_1d": ("^IXIC", "1mo", "1d"),
        "dxy_1d": ("DX-Y.NYB", "1mo", "1d"),
        "crude_1d": ("BZ=F", "1mo", "1d"),
    }

    with _PULSE_LOCK:
        prev_dfs: Dict[str, pd.DataFrame] = dict(_PULSE_CACHE.get("macro_dfs") or {})

    result: Dict[str, pd.DataFrame] = {}
    for key, (sym, period, interval) in tickers.items():
        df = _fetch_yahoo_v8_chart(sym, period=period, interval=interval)
        if not df.empty:
            result[key] = df
        elif key in prev_dfs and not prev_dfs[key].empty:
            # Retain last known valid DataFrame instead of caching an empty DataFrame
            result[key] = prev_dfs[key]
        else:
            result[key] = pd.DataFrame()

    # If nifty_5m is still empty and main.py provided its cached 15m Nifty DataFrame, use it!
    if result["nifty_5m"].empty and fallback_nifty_df is not None and not fallback_nifty_df.empty:
        result["nifty_5m"] = _clean_ohlcv(fallback_nifty_df)

    # Reconcile all completed sessions from nifty_5m into nifty_1d (5m-to-1d multi-session sync)
    if not result["nifty_5m"].empty:
        now_dt = datetime.now(IST_TZ)
        result["nifty_1d"] = _reconcile_daily_from_intraday(
            result["nifty_1d"], result["nifty_5m"], now_dt
        )

    with _PULSE_LOCK:
        if not result["nifty_1d"].empty:
            _PULSE_CACHE["macro_dfs"] = result
            _PULSE_CACHE["macro_dfs_at"] = time.time()

    return result


def _compute_universe_breadth(universe: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute 1,468-stock Breadth in pure RAM (< 1ms).
    Pure VWAP Breadth strictly checks `price >= vwap` without any `chg >= 0.15%` cross-contamination.
    """
    if not universe:
        return {
            "total_tracked": 0,
            "vwap_breadth_pct": 50.0,
            "ema20_breadth_pct": 50.0,
            "advancers": 0,
            "decliners": 0,
            "unchanged": 0,
            "adv_decline_ratio": 1.0,
            "leading_sectors": [],
            "lagging_sectors": [],
        }

    total_valid = 0
    above_vwap_cnt = 0
    above_ema20_cnt = 0
    adv_cnt = 0
    dec_cnt = 0
    unch_cnt = 0

    sector_stats: Dict[str, Dict[str, Any]] = {}

    for item in universe:
        snap = item.get("snapshot") or {}
        price = snap.get("price")
        if price is None or price <= 0:
            continue

        total_valid += 1
        vwap = snap.get("vwap")
        ema20 = snap.get("ema20")
        chg = snap.get("latest_session_change_pct") or 0.0
        sec = item.get("sector") or "General"

        is_above_vwap = (vwap is not None and price >= vwap)
        if is_above_vwap:
            above_vwap_cnt += 1

        if ema20 is not None and price > ema20:
            above_ema20_cnt += 1

        if chg > 0.05:
            adv_cnt += 1
        elif chg < -0.05:
            dec_cnt += 1
        else:
            unch_cnt += 1

        if sec not in sector_stats:
            sector_stats[sec] = {"total": 0, "above_vwap": 0, "sum_chg": 0.0}
        sector_stats[sec]["total"] += 1
        if is_above_vwap:
            sector_stats[sec]["above_vwap"] += 1
        sector_stats[sec]["sum_chg"] += chg

    if total_valid == 0:
        total_valid = 1

    vwap_breadth_pct = round((above_vwap_cnt / total_valid) * 100.0, 1)
    ema20_breadth_pct = round((above_ema20_cnt / total_valid) * 100.0, 1)
    adv_dec_ratio = round(adv_cnt / max(dec_cnt, 1), 2)

    sector_summary = []
    for s_name, s_data in sector_stats.items():
        if s_data["total"] >= 5:
            b_pct = (s_data["above_vwap"] / s_data["total"]) * 100.0
            avg_c = s_data["sum_chg"] / s_data["total"]
            sector_summary.append({
                "sector": s_name,
                "breadth_pct": round(b_pct, 1),
                "avg_change_pct": round(avg_c, 2),
                "stock_count": s_data["total"],
            })

    sector_summary.sort(key=lambda x: (x["breadth_pct"], x["avg_change_pct"]), reverse=True)
    leading_sectors = sector_summary[:4]
    lagging_sectors = sorted(sector_summary, key=lambda x: (x["breadth_pct"], x["avg_change_pct"]))[:4]

    return {
        "total_tracked": total_valid,
        "vwap_breadth_pct": vwap_breadth_pct,
        "ema20_breadth_pct": ema20_breadth_pct,
        "advancers": adv_cnt,
        "decliners": dec_cnt,
        "unchanged": unch_cnt,
        "adv_decline_ratio": adv_dec_ratio,
        "leading_sectors": leading_sectors,
        "lagging_sectors": lagging_sectors,
    }


def _get_target_session_info(now_ist: datetime) -> Tuple[str, str, str]:
    """
    Computes upcoming target trading session date and prefix.
    Returns: (target_date_str, prefix, headline)
    e.g. ("Wednesday, 21-Oct-2026", "TODAY", "Wednesday, 21-Oct-2026")
    """
    weekday = now_ist.weekday()
    # If weekday and before 15:30 IST, target session is today's trading session
    if weekday < 5 and now_ist.time() < dtime(15, 30):
        target_date = now_ist.date()
        date_str = target_date.strftime("%A, %d-%b-%Y")
        prefix = "TODAY" if now_ist.time() >= dtime(9, 15) else "UPCOMING SESSION"
        return date_str, prefix, date_str

    # After 15:30 IST or on weekend, target session is next weekday
    cur = now_ist.date() + timedelta(days=1)
    while cur.weekday() >= 5:  # Skip Saturday (5) & Sunday (6)
        cur += timedelta(days=1)

    date_str = cur.strftime("%A, %d-%b-%Y")
    diff_days = (cur - now_ist.date()).days
    prefix = "TOMORROW" if diff_days == 1 else "NEXT-SESSION"
    return date_str, prefix, date_str


def compute_v13_market_pulse(
    universe: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
    force_refresh: bool = False,
    fallback_nifty_df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """
    Main entry point for Market Pulse & Radar calculation.
    """
    global _PULSE_CACHE
    now_ts = time.time()
    now_ist = datetime.now(IST_TZ)

    is_live_hours = (
        now_ist.weekday() < 5
        and (
            (now_ist.hour > 9 or (now_ist.hour == 9 and now_ist.minute >= 15))
            and (now_ist.hour < 15 or (now_ist.hour == 15 and now_ist.minute <= 30))
        )
    )
    ttl = PULSE_CACHE_TTL_LIVE if is_live_hours else PULSE_CACHE_TTL_OFF

    # Fast in-memory cached return (only if cached data had real bars)
    with _PULSE_LOCK:
        cached_payload = _PULSE_CACHE.get("data")
        if not force_refresh and cached_payload is not None:
            cached_bars = (
                ((cached_payload.get("tradeability") or {}).get("factors") or {})
                .get("efficiency_ratio", {})
                .get("bars_count", 0)
            )
            if cached_bars > 0 and (now_ts - _PULSE_CACHE["cached_at"]) < ttl:
                return cached_payload

    # 1. Compute 1,468-Stock Breadth (< 1ms RAM)
    breadth = _compute_universe_breadth(universe)

    # 2. Fetch Macro Data (Nifty 5m/1d, VIX 5m/1d, US/Macro)
    macro_dfs = _fetch_macro_data(force=force_refresh, fallback_nifty_df=fallback_nifty_df)

    df_nifty_5m = macro_dfs.get("nifty_5m", pd.DataFrame())
    df_vix_5m = macro_dfs.get("vix_5m", pd.DataFrame())
    df_nifty_1d = macro_dfs.get("nifty_1d", pd.DataFrame())
    df_vix_1d = macro_dfs.get("vix_1d", pd.DataFrame())

    # 5m-to-1d multi-session sync: Ensure df_nifty_1d has all completed sessions
    if not df_nifty_5m.empty:
        df_nifty_1d = _reconcile_daily_from_intraday(df_nifty_1d, df_nifty_5m, now_ist)

    # ---------------------------------------------------------------------
    # Slice Latest Completed or Active Session's 5m Bars (Fix #2)
    # ---------------------------------------------------------------------
    df_today_5m = pd.DataFrame()
    session_date_5m = None
    if not df_nifty_5m.empty:
        # Group by date; if market is closed, ensure we pick the last full session (>= 10 bars)
        date_counts = df_nifty_5m.groupby(df_nifty_5m.index.date).size()
        if not is_live_hours:
            valid_dates = [d for d, cnt in date_counts.items() if cnt >= 10]
            latest_date = valid_dates[-1] if valid_dates else df_nifty_5m.index[-1].date()
        else:
            latest_date = df_nifty_5m.index[-1].date()
        session_date_5m = latest_date
        df_today_5m = df_nifty_5m[df_nifty_5m.index.date == latest_date].copy()

    n_bars = len(df_today_5m)

    # Context fallback values if network is completely unreachable
    ctx_close = float((market_context or {}).get("nifty_close") or 0.0)
    ctx_atr_pct = float((market_context or {}).get("nifty_atr_pct") or 0.8)

    if n_bars > 0:
        current_nifty_price = float(df_today_5m["Close"].iloc[-1])
    elif not df_nifty_1d.empty:
        current_nifty_price = float(df_nifty_1d["Close"].iloc[-1])
    elif ctx_close > 0:
        current_nifty_price = ctx_close
    else:
        current_nifty_price = 0.0

    # Daily 14-Day ATR computation on Nifty 1D
    if len(df_nifty_1d) >= 15:
        highs = df_nifty_1d["High"].astype(float)
        lows = df_nifty_1d["Low"].astype(float)
        closes = df_nifty_1d["Close"].astype(float)
        tr = pd.concat([
            highs - lows,
            (highs - closes.shift(1)).abs(),
            (lows - closes.shift(1)).abs(),
        ], axis=1).max(axis=1)
        rolling_atr = tr.rolling(14).mean()
        nifty_atr_14 = float(rolling_atr.iloc[-1]) if pd.notna(rolling_atr.iloc[-1]) else float(tr.mean())
    elif len(df_nifty_1d) >= 2:
        nifty_atr_14 = float((df_nifty_1d["High"] - df_nifty_1d["Low"]).mean())
    else:
        # Derive from market_context if daily df is unavailable
        nifty_atr_14 = max(current_nifty_price * (ctx_atr_pct / 100.0) * 3.5, 100.0)

    # Previous trading day's close (prior to active/latest session date)
    prev_close = current_nifty_price
    if not df_nifty_1d.empty:
        if session_date_5m is not None:
            prior_days = df_nifty_1d[df_nifty_1d.index.date < session_date_5m]
            if not prior_days.empty:
                prev_close = float(prior_days["Close"].iloc[-1])
            elif len(df_nifty_1d) >= 2:
                prev_close = float(df_nifty_1d["Close"].iloc[-2])
        elif len(df_nifty_1d) >= 2:
            prev_close = float(df_nifty_1d["Close"].iloc[-2])

    today_open = float(df_today_5m["Open"].iloc[0]) if n_bars > 0 else current_nifty_price
    # Header session change: current price vs previous day's close (standard NSE convention)
    today_net_chg_pts = current_nifty_price - prev_close
    today_net_chg_pct = (today_net_chg_pts / max(prev_close, 1.0)) * 100.0

    # Intraday displacement from 09:15 Open to latest Close
    intraday_open_to_close_pts = current_nifty_price - today_open

    # ---------------------------------------------------------------------
    # IDEA #2: Live Intraday Tradeability & Chop Filter Engine (0-100 Score)
    # ---------------------------------------------------------------------
    opening_discovery = (n_bars < 3 and is_live_hours)

    # Factor A: Dual-Window Efficiency Ratio (30 Points Max)
    # ---------------------------------------------------------------------
    if n_bars >= 1:
        sum_travel = float((df_today_5m["High"] - df_today_5m["Low"]).sum())
        er_session = abs(intraday_open_to_close_pts) / max(sum_travel, 1e-6)
    else:
        er_session = 0.0

    er_impulse_6 = er_session
    if n_bars >= 6:
        sub_6 = df_today_5m.iloc[-6:]
        c_6_ago = float(sub_6["Close"].iloc[0])
        sum_travel_6 = float((sub_6["High"] - sub_6["Low"]).sum())
        er_impulse_6 = abs(current_nifty_price - c_6_ago) / max(sum_travel_6, 1e-6)

    # 3-Lock V-Reversal Guard
    today_high = float(df_today_5m["High"].max()) if n_bars > 0 else current_nifty_price
    today_low = float(df_today_5m["Low"].min()) if n_bars > 0 else current_nifty_price
    intraday_range = max(today_high - today_low, 1e-6)

    bullish_v_recovery = (
        ((current_nifty_price - today_low) / intraday_range >= 0.60)
        and (breadth["vwap_breadth_pct"] >= 48.0)
    )
    bearish_v_rejection = (
        ((today_high - current_nifty_price) / intraday_range >= 0.60)
        and (breadth["vwap_breadth_pct"] <= 45.0)
    )

    v_reversal_qualified = (n_bars >= 6) and (er_impulse_6 >= 0.42) and bullish_v_recovery

    if v_reversal_qualified:
        er_effective = max(er_session, er_impulse_6)
        er_mode = "6_BAR_IMPULSE_ACTIVE"
    elif (n_bars >= 6) and (er_impulse_6 >= 0.42) and bearish_v_rejection:
        er_effective = er_session
        er_mode = "BEARISH_IMPULSE_REJECT"
    else:
        er_effective = er_session
        er_mode = "SESSION_CUMULATIVE"

    er_score = 0.0
    if er_effective >= 0.42:
        er_score = 24.0 + min(6.0, ((er_effective - 0.42) / 0.28) * 6.0)
    elif er_effective >= 0.22:
        er_score = 12.0 + ((er_effective - 0.22) / 0.20) * 11.0
    else:
        er_score = max(0.0, (er_effective / 0.22) * 11.0)
    er_score = round(min(30.0, er_score), 1)

    # Factor B: 1,468-Stock Institutional VWAP Breadth (25 Points Max)
    # CRITICAL QUANT FIX #3: Directional scoring for Long-Bias Screener
    # ---------------------------------------------------------------------
    b_pct = breadth["vwap_breadth_pct"]
    breadth_score = 0.0

    if b_pct >= 65.0:
        # Strong Bullish Institutional Participation
        breadth_score = 22.0 + min(3.0, ((b_pct - 65.0) / 20.0) * 3.0)
    elif 55.0 <= b_pct < 65.0:
        # Healthy Bullish Breadth
        breadth_score = 17.0 + ((b_pct - 55.0) / 10.0) * 4.9
    elif 48.0 <= b_pct < 55.0:
        # Neutral / Rotational Breadth
        breadth_score = 11.0 + ((b_pct - 48.0) / 7.0) * 5.9
    elif 38.0 <= b_pct < 48.0:
        # Weak / Bearish-Tilted Breadth
        breadth_score = 5.0 + ((b_pct - 38.0) / 10.0) * 5.9
    else:
        # Severe Bearish Distribution (< 38% stocks above VWAP)
        breadth_score = max(0.0, (b_pct / 38.0) * 4.9)

    # Divergence Guard
    divergence_flag: Optional[str] = None
    if today_net_chg_pct > 0.35 and b_pct < 42.0:
        divergence_flag = "INDEX_BREADTH_DIVERGENCE: Nifty propped up by heavyweights while broad market underperforms."
        breadth_score = max(0.0, breadth_score - 8.0)
    elif today_net_chg_pct < -0.35 and b_pct > 58.0:
        divergence_flag = "BULLISH_BREADTH_DIVERGENCE: Broad universe holding above VWAP despite index drag."
    elif b_pct < 38.0:
        divergence_flag = (
            f"BEARISH_DISTRIBUTION_ALERT: {round(100.0 - b_pct, 1)}% of universe trading below VWAP "
            f"(A/D {breadth['adv_decline_ratio']}x). High failure risk on Long Breakouts."
        )

    breadth_score = round(min(25.0, breadth_score), 1)

    # Factor C: Range-Weighted Wick Ratio (15 Points Max)
    # ---------------------------------------------------------------------
    if n_bars >= 1:
        wicks_sum = float(
            (
                (df_today_5m["High"] - df_today_5m["Low"])
                - (df_today_5m["Close"] - df_today_5m["Open"]).abs()
            ).sum()
        )
        ranges_sum = float((df_today_5m["High"] - df_today_5m["Low"]).sum())
        wick_ratio_rw = wicks_sum / max(ranges_sum, 1e-6)
    else:
        wick_ratio_rw = 1.0

    wick_score = 0.0
    if wick_ratio_rw <= 0.42:
        wick_score = 12.0 + min(3.0, ((0.42 - wick_ratio_rw) / 0.20) * 3.0)
    elif wick_ratio_rw <= 0.58:
        wick_score = 7.0 + ((0.58 - wick_ratio_rw) / 0.16) * 4.0
    else:
        wick_score = max(0.0, ((0.80 - wick_ratio_rw) / 0.22) * 6.0)
    wick_score = round(min(15.0, wick_score), 1)

    # Factor D: Dynamic Time-Adjusted True Day Range Consumed (15 Points Max)
    # When market is CLOSED (off-market), evaluate using Full-Session EOD curve!
    # ---------------------------------------------------------------------
    true_range_today = max(today_high, prev_close) - min(today_low, prev_close)
    tdrc_pct = round((true_range_today / max(nifty_atr_14, 1.0)) * 100.0, 1)

    now_time = now_ist.time()
    tdrc_score = 0.0

    if is_live_hours and now_time < dtime(10, 30):
        # Morning Session (09:15 - 10:30 IST)
        if 20.0 <= tdrc_pct <= 75.0:
            tdrc_score = 13.0 + min(2.0, ((tdrc_pct - 20.0) / 55.0) * 2.0)
        elif 12.0 <= tdrc_pct < 20.0:
            tdrc_score = 10.0
        elif tdrc_pct < 12.0:
            tdrc_score = 6.0
        elif 75.0 < tdrc_pct <= 105.0:
            tdrc_score = 9.0
        else:
            tdrc_score = 4.0
    elif is_live_hours and now_time < dtime(13, 30):
        # Mid Session (10:30 - 13:30 IST)
        if 35.0 <= tdrc_pct <= 90.0:
            tdrc_score = 13.0 + min(2.0, ((tdrc_pct - 35.0) / 55.0) * 2.0)
        elif tdrc_pct < 35.0:
            tdrc_score = 7.0
        elif 90.0 < tdrc_pct <= 110.0:
            tdrc_score = 8.0
        else:
            tdrc_score = 3.0
    else:
        # Late Session (13:30 - 15:30 IST) OR Completed EOD Session
        if 45.0 <= tdrc_pct <= 100.0:
            tdrc_score = 13.0 + min(2.0, ((tdrc_pct - 45.0) / 55.0) * 2.0)
        elif tdrc_pct < 45.0:
            tdrc_score = 6.0
        elif 100.0 < tdrc_pct <= 115.0:
            tdrc_score = 8.0
        else:
            tdrc_score = 3.0  # Fuel exhausted (> 115% ATR)

    tdrc_score = round(min(15.0, tdrc_score), 1)

    # Factor E: India VIX Level & Velocity (15 Points Max)
    # ---------------------------------------------------------------------
    current_vix = 15.0
    vix_chg_pct = 0.0
    if not df_vix_1d.empty:
        current_vix = float(df_vix_1d["Close"].iloc[-1])
        if len(df_vix_1d) >= 2:
            prev_vix = float(df_vix_1d["Close"].iloc[-2])
            vix_chg_pct = round(((current_vix - prev_vix) / max(prev_vix, 0.1)) * 100.0, 2)
    elif not df_vix_5m.empty:
        current_vix = float(df_vix_5m["Close"].iloc[-1])
        vix_open = float(df_vix_5m["Open"].iloc[0])
        vix_chg_pct = round(((current_vix - vix_open) / max(vix_open, 0.1)) * 100.0, 2)

    vix_score = 0.0
    if 11.0 <= current_vix <= 17.5 and vix_chg_pct <= 3.0:
        vix_score = 13.0 + min(2.0, max(0.0, (3.0 - vix_chg_pct) / 3.0) * 2.0)
    elif current_vix <= 21.0 and vix_chg_pct <= 6.0:
        vix_score = 7.0 + max(0.0, (6.0 - vix_chg_pct) / 6.0) * 3.0
    else:
        vix_score = max(0.0, 5.0 - min(5.0, max(0.0, vix_chg_pct - 6.0)))
    vix_score = round(min(15.0, vix_score), 1)

    # ---------------------------------------------------------------------
    # Total Score & Verdict with Strict Bearish Breadth Alignment (Fix #3)
    # ---------------------------------------------------------------------
    raw_total = er_score + breadth_score + wick_score + tdrc_score + vix_score
    raw_total_rounded = round(min(100.0, max(0.0, raw_total)), 1)
    total_score = raw_total_rounded

    is_severe_bearish_breadth = (b_pct < 38.0)
    is_weak_breadth = (38.0 <= b_pct < 46.0)

    cap_reason: Optional[str] = None
    if is_severe_bearish_breadth:
        # Cap total score <= 38.0 so Score and RED Verdict are 100% synchronized!
        capped_ceiling = round(22.0 + (b_pct / 38.0) * 15.0, 1)  # Maps 0..38% -> 22..37
        if total_score > capped_ceiling:
            cap_reason = f"Capped from {total_score:.1f} by Bearish Breadth"
            total_score = capped_ceiling
    elif is_weak_breadth:
        # Cannot be GREEN GO when < 46% of universe is above VWAP
        if total_score > 62.0:
            cap_reason = f"Capped from {total_score:.1f} by Weak Breadth"
            total_score = 62.0

    if opening_discovery:
        traffic_light = "YELLOW"
        verdict = "OPENING_DISCOVERY — WAIT FOR 9:30 ORB"
        position_sizing = "0.25x - 0.5x (Opening Caution)"
        action_summary = "Opening 15-minute price discovery in progress. Wait for the 9:30 AM Opening Range Breakout structure."
    elif is_severe_bearish_breadth:
        traffic_light = "RED"
        verdict = "NO-GO FOR LONGS — BEARISH SELL-OFF"
        position_sizing = "0.0x Longs (Cash / Short Bias Only)"
        action_summary = (
            f"Broad market under heavy institutional selling ({b_pct}% > VWAP, A/D {breadth['adv_decline_ratio']}x). "
            f"Avoid buying long breakouts; sit on cash or restrict to short setups."
        )
    elif total_score >= 68.0 and er_effective >= 0.28 and b_pct >= 50.0:
        traffic_light = "GREEN"
        verdict = "GO — BULLISH TREND ENVIRONMENT"
        position_sizing = "1.0x (100% Normal Size)"
        action_summary = (
            f"Clean intraday efficiency (ER {er_effective:.2f}) with strong breadth ({b_pct}% > VWAP). "
            f"Favorable conditions for V13 and Live Movers breakouts."
        )
    elif total_score >= 45.0 or (tdrc_pct > 115.0 and total_score >= 40.0):
        traffic_light = "YELLOW"
        verdict = "CAUTION — SELECTIVE / ROTATIONAL"
        position_sizing = "0.5x (50% Size)"
        action_summary = (
            f"Mixed/rotational regime ({b_pct}% > VWAP, ER {er_effective:.2f}). "
            f"Focus strictly on top accumulating sectors; book 50% quickly at Target 1."
        )
    else:
        traffic_light = "RED"
        verdict = "NO-GO — SIT ON CASH (CHOP / TRAP)"
        position_sizing = "0.0x - 0.25x (Cash Preservation)"
        action_summary = "High whipsaw environment with elevated stop-loss hunting. Avoid breakout chasing; preserve capital."

    # ---------------------------------------------------------------------
    # IDEA #1: Next-Day & Pre-Market Structural Bias & Conditional Zones
    # CRITICAL QUANT FIX: Deterministic Date-Based Reference Anchor
    # ---------------------------------------------------------------------
    today_d = now_ist.date()

    if is_live_hours or now_ist.time() < dtime(9, 15):
        # During live market (09:15 - 15:30) OR Pre-Market (< 09:15 AM):
        # Reference Anchor strictly targets the latest COMPLETED session BEFORE today (e.g. 2026-10-21)
        completed_days = df_nifty_1d[df_nifty_1d.index.date < today_d]
        stage_mode = "LIVE_SESSION_PLAYBOOK" if is_live_hours else "PRE_MARKET_OVERLAY"
    else:
        # After 15:30 IST or off-market after settlement:
        # Reference Anchor targets the latest completed session (<= today_d)
        completed_days = df_nifty_1d[df_nifty_1d.index.date <= today_d]
        if now_ist.time() >= dtime(15, 30):
            stage_mode = "EOD_HANDOVER"
        else:
            stage_mode = "OVERNIGHT_RADAR"

    if not completed_days.empty:
        ref_bar = completed_days.iloc[-1]
        prev_ref_bar = completed_days.iloc[-2] if len(completed_days) >= 2 else completed_days.iloc[-1]
    elif len(df_nifty_1d) >= 1:
        ref_bar = df_nifty_1d.iloc[-1]
        prev_ref_bar = df_nifty_1d.iloc[-2] if len(df_nifty_1d) >= 2 else df_nifty_1d.iloc[-1]
    else:
        ref_bar = pd.Series({
            "Open": today_open,
            "High": today_high,
            "Low": today_low,
            "Close": current_nifty_price,
        })
        prev_ref_bar = ref_bar
        stage_mode = "EOD_HANDOVER"

    ref_open = float(ref_bar["Open"])
    ref_high = float(ref_bar["High"])
    ref_low = float(ref_bar["Low"])
    ref_close = float(ref_bar["Close"])
    prev_ref_close = float(prev_ref_bar["Close"])
    ref_range = max(ref_high - ref_low, 1.0)
    ref_chg_pct = ((ref_close - prev_ref_close) / max(prev_ref_close, 1.0)) * 100.0

    # Stage 1: EOD Structure Handover
    clv_pct = round(((ref_close - ref_low) / ref_range) * 100.0, 1)

    # Daily EMA 20 & 50
    ema20_daily = ref_close
    ema50_daily = ref_close
    if len(df_nifty_1d) >= 5:
        c_series = df_nifty_1d["Close"].astype(float)
        ema20_daily = float(c_series.ewm(span=20, adjust=False).mean().iloc[-1])
        ema50_daily = float(c_series.ewm(span=50, adjust=False).mean().iloc[-1])

    # Volatility Compression (NR4 / NR7 / Inside Bar)
    compression_tag = "NORMAL_EXPANSION"
    if len(df_nifty_1d) >= 8:
        ranges = (df_nifty_1d["High"] - df_nifty_1d["Low"]).tail(8).values
        curr_r = ref_range
        is_nr4 = curr_r <= min(ranges[-4:-1])
        is_nr7 = curr_r <= min(ranges[-7:-1])
        if is_nr7:
            compression_tag = "NR7_VOLATILITY_COMPRESSION"
        elif is_nr4:
            compression_tag = "NR4_COMPRESSION"
        elif len(df_nifty_1d) >= 2:
            p_bar = prev_ref_bar
            if ref_high <= float(p_bar["High"]) and ref_low >= float(p_bar["Low"]):
                compression_tag = "INSIDE_BAR_COILING"

    # Stage 2: Overnight Global Macro Overlay
    sp500_df = macro_dfs.get("sp500_1d", pd.DataFrame())
    nasdaq_df = macro_dfs.get("nasdaq_1d", pd.DataFrame())
    dxy_df = macro_dfs.get("dxy_1d", pd.DataFrame())
    crude_df = macro_dfs.get("crude_1d", pd.DataFrame())

    def _calc_last_chg(df: pd.DataFrame) -> float:
        if len(df) >= 2:
            c_curr = float(df["Close"].iloc[-1])
            c_prev = float(df["Close"].iloc[-2])
            return ((c_curr - c_prev) / max(c_prev, 0.01)) * 100.0
        return 0.0

    sp500_chg = round(_calc_last_chg(sp500_df), 2)
    nasdaq_chg = round(_calc_last_chg(nasdaq_df), 2)
    dxy_chg = round(_calc_last_chg(dxy_df), 2)
    crude_chg = round(_calc_last_chg(crude_df), 2)

    # Tailwind score (-100 to +100)
    us_tailwind = (sp500_chg * 25.0) + (nasdaq_chg * 25.0)
    fx_headwind = (dxy_chg * -25.0) + (crude_chg * -15.0)
    macro_tailwind_score = round(max(-100.0, min(100.0, us_tailwind + fx_headwind)), 1)

    # ---------------------------------------------------------------------
    # CRITICAL QUANT FIX #6: 5-Pillar Weighted Next-Day Directional Engine (-100 to +100)
    # ---------------------------------------------------------------------
    # Pillar 1: Nifty Daily CLV & Session Momentum (-25 to +25 pts)
    clv_centered = (clv_pct - 50.0) / 50.0  # -1.0 to +1.0
    p1_clv_score = round(
        max(-25.0, min(25.0, (clv_centered * 16.0) + max(-9.0, min(9.0, ref_chg_pct * 6.0)))),
        1,
    )

    # Pillar 2: Daily EMA20 & EMA50 Structure (-20 to +20 pts)
    dist_ema20_pct = ((ref_close - ema20_daily) / max(ema20_daily, 1.0)) * 100.0
    dist_ema50_pct = ((ref_close - ema50_daily) / max(ema50_daily, 1.0)) * 100.0
    p2_ema_raw = 0.0
    if ref_close > ema20_daily:
        p2_ema_raw += 12.0
    else:
        p2_ema_raw -= 12.0
    if ref_close > ema50_daily:
        p2_ema_raw += 8.0
    else:
        p2_ema_raw -= 8.0
    p2_ema_score = round(max(-20.0, min(20.0, p2_ema_raw)), 1)

    # Pillar 3: 1,468-Stock EOD Universe Breadth (-25 to +25 pts)
    vwap_norm = max(-1.0, min(1.0, (b_pct - 50.0) / 28.0))
    ema20_norm = max(-1.0, min(1.0, (breadth["ema20_breadth_pct"] - 50.0) / 28.0))
    p3_breadth_score = round(max(-25.0, min(25.0, (vwap_norm * 16.0) + (ema20_norm * 9.0))), 1)

    # Pillar 4: Global Macro Overnight Cues (-20 to +20 pts)
    p4_macro_score = round(max(-20.0, min(20.0, (macro_tailwind_score / 100.0) * 20.0)), 1)

    # Pillar 5: India VIX Regime & Velocity (-10 to +10 pts)
    p5_vix_raw = 0.0
    if vix_chg_pct >= 3.0:
        p5_vix_raw -= min(8.0, vix_chg_pct * 1.2)
    elif vix_chg_pct <= -1.5:
        p5_vix_raw += min(7.0, abs(vix_chg_pct) * 1.5)
    if current_vix > 18.5:
        p5_vix_raw -= 3.0
    elif current_vix < 14.5 and vix_chg_pct <= 1.0:
        p5_vix_raw += 3.0
    p5_vix_score = round(max(-10.0, min(10.0, p5_vix_raw)), 1)

    next_day_score = round(
        max(-100.0, min(100.0, p1_clv_score + p2_ema_score + p3_breadth_score + p4_macro_score + p5_vix_score)),
        1,
    )

    if next_day_score >= 18.0:
        structural_bias = "BULLISH_BIAS"
        next_day_direction = "BULLISH"
        next_day_color = "GREEN"
        next_day_conviction_pct = min(94, int(round(52 + abs(next_day_score) * 0.45)))
        next_day_summary = (
            f"Bullish Structural Handover (Score {next_day_score:+.1f}/100, {next_day_conviction_pct}% Conviction). "
            f"Favor long breakouts above ₹{round(max(ref_high, ref_close + 0.25 * nifty_atr_14), 1):,.1f}."
        )
    elif next_day_score <= -18.0:
        structural_bias = "BEARISH_BIAS"
        next_day_direction = "BEARISH"
        next_day_color = "RED"
        next_day_conviction_pct = min(94, int(round(52 + abs(next_day_score) * 0.45)))
        next_day_summary = (
            f"Bearish Distribution Pressure (Score {next_day_score:+.1f}/100, {next_day_conviction_pct}% Conviction • "
            f"{round(100.0 - b_pct, 1)}% stocks < VWAP, CLV {clv_pct}%). "
            f"Downside bias active unless Nifty reclaims ₹{round(max(ref_high, ref_close + 0.25 * nifty_atr_14), 1):,.1f}."
        )
    else:
        structural_bias = "NEUTRAL_RANGE_BOUND"
        next_day_direction = "SIDEWAYS"
        next_day_color = "YELLOW"
        next_day_conviction_pct = int(round(55 + (18.0 - abs(next_day_score)) * 1.2))
        next_day_summary = (
            f"Balanced / Two-Way Equilibrium (Score {next_day_score:+.1f}/100). "
            f"Wait for Opening Range Breakout outside the chop zone before committing size."
        )

    # ---------------------------------------------------------------------
    # Static Conditional Execution Levels (CRITICAL QUANT FIX #4)
    # Targets projected strictly outside U_trig and L_trig!
    # ---------------------------------------------------------------------
    u_trig = round(max(ref_high, ref_close + (0.25 * nifty_atr_14)), 1)
    u_target_1 = round(u_trig + (0.40 * nifty_atr_14), 1)
    u_target_2 = round(u_trig + (0.80 * nifty_atr_14), 1)

    l_trig = round(min(ref_low, ref_close - (0.25 * nifty_atr_14)), 1)
    l_target_1 = round(l_trig - (0.40 * nifty_atr_14), 1)
    l_target_2 = round(l_trig - (0.80 * nifty_atr_14), 1)

    # Active Zone Determination
    if current_nifty_price >= u_trig:
        current_zone = "BULLISH_ACCEPTANCE"
        zone_color = "EMERALD"
        zone_guidance = f"Spot above {u_trig:,.1f}. Institutional buyers in control; favor long breakouts towards {u_target_1:,.1f}."
    elif current_nifty_price <= l_trig:
        current_zone = "BEARISH_BREAKDOWN"
        zone_color = "ROSE"
        zone_guidance = f"Spot below {l_trig:,.1f}. Sellers pressing lower; avoid fresh longs, downside support at {l_target_1:,.1f}."
    else:
        current_zone = "NO_TRADE_CHOP_ZONE"
        zone_color = "AMBER"
        zone_guidance = f"Spot (₹{current_nifty_price:,.1f}) inside chop range ({l_trig:,.1f} ↔ {u_trig:,.1f}). Wait for boundary break."

    # Gap Exhaustion Guard (only relevant when today's session is newer than ref_bar)
    ref_date_obj = ref_bar.name.date() if hasattr(ref_bar, "name") and hasattr(ref_bar.name, "date") else None
    gap_warning = None
    if session_date_5m and ref_date_obj and session_date_5m > ref_date_obj:
        gap_points = round(today_open - ref_close, 1)
        gap_ratio_atr = round(abs(gap_points) / max(nifty_atr_14, 1.0), 2)
        if gap_ratio_atr >= 0.70:
            gap_warning = f"Overnight Gap ({gap_points:+,.1f} pts = {int(gap_ratio_atr*100)}% ATR) consumed majority of day fuel. Beware of opening chase."

    # ---------------------------------------------------------------------
    # Final Structured Response Payload
    # ---------------------------------------------------------------------
    target_date_str, target_pfx, target_hdline = _get_target_session_info(now_ist)

    response_payload: Dict[str, Any] = {
        "generated_at": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
        "market_status": "LIVE" if is_live_hours else "CLOSED",
        "session_date": str(session_date_5m) if session_date_5m else now_ist.strftime("%Y-%m-%d"),
        "current_nifty_price": round(current_nifty_price, 2),
        "nifty_session_change_pts": round(today_net_chg_pts, 2),
        "nifty_session_change_pct": round(today_net_chg_pct, 2),
        "nifty_atr_14": round(nifty_atr_14, 1),

        # Idea #2: Live Tradeability & Chop Filter
        "tradeability": {
            "score": total_score,
            "raw_score": raw_total_rounded,
            "cap_reason": cap_reason,
            "traffic_light": traffic_light,
            "verdict": verdict,
            "position_sizing": position_sizing,
            "action_summary": action_summary,
            "opening_discovery": opening_discovery,
            "factors": {
                "efficiency_ratio": {
                    "score": er_score,
                    "max_score": 30.0,
                    "er_effective": round(er_effective, 3),
                    "er_session": round(er_session, 3),
                    "er_impulse_6": round(er_impulse_6, 3),
                    "mode": er_mode,
                    "v_reversal_qualified": v_reversal_qualified,
                    "bars_count": n_bars,
                },
                "vwap_breadth": {
                    "score": breadth_score,
                    "max_score": 25.0,
                    "vwap_breadth_pct": breadth["vwap_breadth_pct"],
                    "ema20_breadth_pct": breadth["ema20_breadth_pct"],
                    "advancers": breadth["advancers"],
                    "decliners": breadth["decliners"],
                    "adv_decline_ratio": breadth["adv_decline_ratio"],
                    "total_stocks_evaluated": breadth["total_tracked"],
                    "divergence_flag": divergence_flag,
                },
                "wick_ratio": {
                    "score": wick_score,
                    "max_score": 15.0,
                    "wick_ratio_rw": round(wick_ratio_rw, 3),
                    "wick_pct": round(wick_ratio_rw * 100.0, 1),
                    "quality": "CLEAN_BODIES" if wick_ratio_rw <= 0.42 else ("STOP_HUNT_WICKS" if wick_ratio_rw > 0.58 else "NORMAL"),
                },
                "range_consumed": {
                    "score": tdrc_score,
                    "max_score": 15.0,
                    "tdrc_pct": tdrc_pct,
                    "intraday_true_range": round(true_range_today, 1),
                    "status": "EXHAUSTED" if tdrc_pct > 100.0 else ("HEALTHY" if tdrc_score >= 11.0 or 35.0 <= tdrc_pct <= 100.0 else "COMPRESSED"),
                },
                "india_vix": {
                    "score": vix_score,
                    "max_score": 15.0,
                    "vix_level": round(current_vix, 2),
                    "vix_change_pct": vix_chg_pct,
                    "state": "FAVORABLE" if current_vix <= 17.5 and vix_chg_pct <= 3.0 else "ELEVATED_RISK",
                },
            },
            "leading_sectors": breadth["leading_sectors"],
            "lagging_sectors": breadth["lagging_sectors"],
        },

        # Idea #1: Next-Day & Pre-Market Structural Radar
        "radar": {
            "stage_mode": stage_mode,
            "structural_bias": structural_bias,
            "next_day_direction": next_day_direction,
            "next_day_color": next_day_color,
            "next_day_score": next_day_score,
            "next_day_conviction_pct": next_day_conviction_pct,
            "next_day_summary": next_day_summary,
            "target_session_date": target_date_str,
            "target_session_prefix": target_pfx,
            "target_session_headline": target_hdline,
            "pillar_scores": {
                "clv_momentum": p1_clv_score,
                "ema_structure": p2_ema_score,
                "universe_breadth": p3_breadth_score,
                "global_macro": p4_macro_score,
                "vix_regime": p5_vix_score,
            },
            "compression_tag": compression_tag,
            "current_zone": current_zone,
            "zone_color": zone_color,
            "zone_guidance": zone_guidance,
            "gap_warning": gap_warning,
            "anchored_reference_date": str(ref_bar.name.date()) if hasattr(ref_bar, "name") and hasattr(ref_bar.name, "date") else "PREV_SESSION",
            "conditional_zones": {
                "bullish_trigger": u_trig,
                "target_1": u_target_1,
                "target_2": u_target_2,
                "chop_zone_high": u_trig,
                "chop_zone_low": l_trig,
                "bearish_trigger": l_trig,
                "support_1": l_target_1,
                "support_2": l_target_2,
            },
            "stage_1_eod_structure": {
                "clv_pct": clv_pct,
                "ref_high": round(ref_high, 1),
                "ref_low": round(ref_low, 1),
                "ref_close": round(ref_close, 1),
                "ema20_daily": round(ema20_daily, 1),
                "ema50_daily": round(ema50_daily, 1),
            },
            "stage_2_global_macro": {
                "macro_tailwind_score": macro_tailwind_score,
                "sp500_chg_pct": sp500_chg,
                "nasdaq_chg_pct": nasdaq_chg,
                "dxy_chg_pct": dxy_chg,
                "crude_chg_pct": crude_chg,
            },
        },
    }

    # Only cache when valid bars were processed
    if n_bars > 0:
        with _PULSE_LOCK:
            _PULSE_CACHE["data"] = response_payload
            _PULSE_CACHE["cached_at"] = time.time()

    return response_payload
