import numpy as np
import pandas as pd
from datetime import datetime
import pytz

from app.v13_engine import _calculate_wilder_atr_series, _atr, _daily_atr14, _relative_volume
from app.v13_live_movers import _calculate_tod_rel_vol
from app.v13_market_context import build_nifty_context
from app.v13_scanner import _apply_macro_breadth_veto

IST_TZ = pytz.timezone("Asia/Kolkata")


def test_wilder_atr_series_textbook():
    """Verify that _calculate_wilder_atr_series uses SMA-14 initial seed and recursive smoothing."""
    # Create 20 synthetic True Range values
    tr_values = [10.0] * 14 + [24.0, 10.0, 10.0, 10.0, 10.0, 10.0]
    idx = pd.date_range("2026-10-01", periods=20, freq="15min")
    tr_series = pd.Series(tr_values, index=idx)

    atr_series = _calculate_wilder_atr_series(tr_series, period=14)

    # 1. Bar 14 (index 13) must equal initial SMA = 10.0
    assert abs(atr_series.iloc[13] - 10.0) < 1e-6

    # 2. Bar 15 (index 14) with TR=24.0:
    # Expected ATR = (10.0 * 13 + 24.0) / 14 = (130 + 24) / 14 = 154 / 14 = 11.0
    assert abs(atr_series.iloc[14] - 11.0) < 1e-6
    print("test_wilder_atr_series_textbook PASSED!")


def test_relative_volume_participation_weighted_median():
    """Verify that _relative_volume avoids survivorship bias using participation-weighted median."""
    sessions = []
    
    # 20 Historical Dates
    for day_idx in range(1, 21):
        date_str = f"2026-09-{day_idx:02d}"
        times = ["09:15", "09:30", "09:45", "10:00", "10:15", "10:30"]
        idx = [pd.Timestamp(f"{date_str} {t}", tz="Asia/Kolkata") for t in times]
        
        if day_idx <= 12:
            vols = [0, 0, 0, 0, 500, 1000]
        else:
            active_vols = [1000, 2000, 3000, 5000, 8000, 10000, 15000, 20000]
            val = active_vols[day_idx - 13]
            vols = [val / 4.0] * 4 + [500, 1000]
            
        df_day = pd.DataFrame({
            "Open": [100.0] * 6,
            "High": [105.0] * 6,
            "Low": [95.0] * 6,
            "Close": [102.0] * 6,
            "Volume": vols,
        }, index=idx)
        sessions.append(df_day)

    # Current Day (Day 21): 10,000 shares traded by 10:15 AM
    curr_idx = [pd.Timestamp(f"2026-09-22 {t}", tz="Asia/Kolkata") for t in ["09:15", "09:30", "09:45", "10:00"]]
    curr_df = pd.DataFrame({
        "Open": [100.0] * 4,
        "High": [105.0] * 4,
        "Low": [95.0] * 4,
        "Close": [102.0] * 4,
        "Volume": [2500.0] * 4,
    }, index=curr_idx)
    sessions.append(curr_df)

    full_df = pd.concat(sessions).sort_index()

    rel_vol = _relative_volume(full_df, curr_df, lookback_sessions=20)

    assert abs(rel_vol - 3.85) < 0.05
    print(f"test_relative_volume_participation_weighted_median PASSED! (RelVol: {rel_vol}x)")


def test_relative_volume_uniform_50x_cap():
    """Verify that extreme volume surges are cleanly clamped at 50.0x."""
    t_hist = [pd.Timestamp(f"2026-09-01 {t}", tz="Asia/Kolkata") for t in ["09:15", "09:30"]]
    df_hist = pd.DataFrame({"Open": [10], "High": [11], "Low": [9], "Close": [10], "Volume": [1000.0, 500.0]}, index=t_hist)
    
    t_curr = [pd.Timestamp(f"2026-09-02 {t}", tz="Asia/Kolkata") for t in ["09:15", "09:30"]]
    df_curr = pd.DataFrame({"Open": [10], "High": [11], "Low": [9], "Close": [10], "Volume": [500000.0, 500000.0]}, index=t_curr)
    
    full_df = pd.concat([df_hist, df_curr]).sort_index()
    rel_vol = _relative_volume(full_df, df_curr, lookback_sessions=20)
    
    assert rel_vol == 50.0
    print(f"test_relative_volume_uniform_50x_cap PASSED! (RelVol capped at {rel_vol}x)")


def test_live_movers_timestamp_clamp_and_scaling():
    """Verify Live Movers intra-bar scaling and weekend/after-hours clamping."""
    snap_iso_live = "2026-10-23T10:15:00+05:30"
    rel_vol_live = _calculate_tod_rel_vol(
        session_vol=102000.0,
        snap_vol=100000.0,
        snap_rel_vol=2.0,
        snap_bar_end_iso=snap_iso_live,
    )
    assert 2.0 <= rel_vol_live <= 2.05
    print(f"test_live_movers_live_tick PASSED! (RelVol: {rel_vol_live}x)")

    snap_iso_friday_close = "2026-10-23T15:30:00+05:30"
    rel_vol_closed = _calculate_tod_rel_vol(
        session_vol=500000.0,
        snap_vol=500000.0,
        snap_rel_vol=3.5,
        snap_bar_end_iso=snap_iso_friday_close,
    )
    assert rel_vol_closed == 3.5
    print(f"test_live_movers_after_hours_clamp PASSED! (RelVol: {rel_vol_closed}x)")

    rel_vol_extreme = _calculate_tod_rel_vol(
        session_vol=20000000.0,
        snap_vol=100000.0,
        snap_rel_vol=45.0,
        snap_bar_end_iso=snap_iso_friday_close,
    )
    assert rel_vol_extreme == 50.0
    print(f"test_live_movers_uniform_50x_cap PASSED! (RelVol: {rel_vol_extreme}x)")


def test_nifty_context_zero_volume_and_short_covering_trap():
    """
    Verify Pillar 1A:
    1. When ^NSEI spot Volume is 0, nifty_vwap uses Typical Price Session Mean without NaN.
    2. When Nifty drops all day (below EMA20 and below Session TWAP/VWAP) and has a small 5-bar
       short-covering bounce (+0.20% over 5 bars), build_nifty_context does NOT flip to BULLISH.
    """
    idx = pd.date_range("2026-10-23 09:15", periods=25, freq="15min")
    # First 20 bars drop steadily from 23000 down to 22500, then last 5 bars bounce slightly to 22550
    closes = list(np.linspace(23000.0, 22500.0, 20)) + [22510.0, 22520.0, 22530.0, 22540.0, 22550.0]
    df_nifty = pd.DataFrame({
        "Open": closes,
        "High": [c + 20.0 for c in closes],
        "Low": [c - 20.0 for c in closes],
        "Close": closes,
        "Volume": [0.0] * 25,  # Spot index zero volume
    }, index=idx)

    ctx = build_nifty_context(df_nifty, idx[-1])
    assert ctx["nifty_vwap"] is not None and np.isfinite(ctx["nifty_vwap"])
    assert ctx["nifty_direction"] != "BULLISH"
    print(f"test_nifty_context_zero_volume_and_short_covering_trap PASSED! (dir={ctx['nifty_direction']}, vwap={ctx['nifty_vwap']})")


def test_macro_breadth_veto_double_lock():
    """Verify _apply_macro_breadth_veto forces BEARISH when macro_adv_ratio < 25% and NEUTRAL when < 35%."""
    ctx_crash = {"nifty_direction": "BULLISH", "macro_adv_ratio": 9.4}
    _apply_macro_breadth_veto(ctx_crash)
    assert ctx_crash["nifty_direction"] == "BEARISH"

    ctx_weak = {"nifty_direction": "BULLISH", "macro_adv_ratio": 31.0}
    _apply_macro_breadth_veto(ctx_weak)
    assert ctx_weak["nifty_direction"] == "NEUTRAL"

    ctx_strong = {"nifty_direction": "BEARISH", "macro_adv_ratio": 80.0}
    _apply_macro_breadth_veto(ctx_strong)
    assert ctx_strong["nifty_direction"] == "BULLISH"
    print("test_macro_breadth_veto_double_lock PASSED!")


if __name__ == "__main__":
    test_wilder_atr_series_textbook()
    test_relative_volume_participation_weighted_median()
    test_relative_volume_uniform_50x_cap()
    test_live_movers_timestamp_clamp_and_scaling()
    test_nifty_context_zero_volume_and_short_covering_trap()
    test_macro_breadth_veto_double_lock()
    print("\nALL QUANT HARDENING TESTS PASSED WITH 100% SUCCESS!")
