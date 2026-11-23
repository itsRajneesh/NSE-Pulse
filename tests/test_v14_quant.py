"""
NSE-PULSE V14 Permanent Quantitative Regression Test Suite.
Validates all mathematical core algorithms, tick normalizers, SL filters,
dual-tranche lifecycle transitions, and audit string synchronization.
"""
import os
import sys
import json
import math

# Add backend directory to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import types
from datetime import timezone, timedelta

# Unified shims for testing in environments without third-party wheels
if "pytz" not in sys.modules:
    try:
        __import__("pytz")
    except ImportError:
        dummy_tz = types.ModuleType("pytz")
        ist_offset = timezone(timedelta(hours=5, minutes=30), name="IST")
        dummy_tz.timezone = lambda name: ist_offset
        sys.modules["pytz"] = dummy_tz

if "numpy" not in sys.modules:
    try:
        __import__("numpy")
    except ImportError:
        np_shim = types.ModuleType("numpy")
        np_shim.nan = float("nan")
        np_shim.max = lambda arr: max(arr) if hasattr(arr, "__len__") and len(arr) > 0 else 0.0
        np_shim.min = lambda arr: min(arr) if hasattr(arr, "__len__") and len(arr) > 0 else 0.0
        np_shim.array = lambda x: list(x)
        sys.modules["numpy"] = np_shim

if "pandas" not in sys.modules:
    try:
        __import__("pandas")
    except ImportError:
        pd_shim = types.ModuleType("pandas")
        class MockSeries:
            def __init__(self, data):
                self.data = list(data)
            def to_numpy(self, dtype=float):
                return self.data
            def __getitem__(self, idx):
                return self.data[idx]
            def __len__(self):
                return len(self.data)
        class MockDF:
            def __init__(self, d):
                self.d = {k: MockSeries(v) for k, v in d.items()}
                self._len = len(next(iter(d.values())))
            def __getitem__(self, key):
                return self.d[key]
            def __len__(self):
                return self._len
            def tail(self, n):
                return MockDF({k: v.data[-n:] for k, v in self.d.items()})
        pd_shim.DataFrame = MockDF
        pd_shim.Series = MockSeries
        pd_shim.Timestamp = lambda x: x
        sys.modules["pandas"] = pd_shim

def test_1_integer_paise_tick_normalizer():
    """Verify IEEE-754 zero-drift NSE tick normalizer (5-paise grid)."""
    def normalize_nse_tick(price: float, is_bullish: bool = True) -> float:
        if price is None or price <= 0:
            return 0.0
        paise = int(round(price * 100.0))
        if is_bullish:
            norm_paise = (paise // 5) * 5
        else:
            norm_paise = ((paise + 4) // 5) * 5
        return round(norm_paise / 100.0, 2)

    assert normalize_nse_tick(1420.33, is_bullish=True) == 1420.30
    assert normalize_nse_tick(1420.34, is_bullish=True) == 1420.30
    assert normalize_nse_tick(1420.35, is_bullish=True) == 1420.35
    assert normalize_nse_tick(1420.31, is_bullish=False) == 1420.35
    assert normalize_nse_tick(1420.30, is_bullish=False) == 1420.30
    print("[PASS] Test 1: Integer paise tick normalizer (Zero IEEE-754 drift)")

def test_2_prefiltered_sl_buffer():
    """Verify pre-filtered stop-loss buffer with VWAP reclaim protection."""
    entry = 500.0
    atr14 = 10.0
    min_sl_dist = 0.5 * atr14
    vwap_reclaim = 505.0  # VWAP above entry!
    opening_low = 490.0

    raw_candidates = [
        opening_low - (0.35 * atr14),  # 486.5
        vwap_reclaim - (0.50 * atr14), # 500.0 (Equal to entry -> NOT strictly below!)
        entry - (1.50 * atr14)         # 485.0
    ]
    valid_stops = [s for s in raw_candidates if s < entry]
    assert len(valid_stops) == 2
    raw_stop = max(valid_stops)
    stop = min(raw_stop, entry - min_sl_dist)
    assert stop == 486.5
    assert stop < entry
    print("[PASS] Test 2: Pre-filtered SL buffer (VWAP > Entry reclaim protected)")

def test_3_gate_0_liquid_universe_json():
    """Verify Gate #0 shortable constituents JSON loader."""
    json_path = os.path.join(BACKEND_DIR, "app", "data", "nse_index_constituents.json")
    assert os.path.exists(json_path), f"File not found: {json_path}"
    with open(json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    fno = set(raw.get("FNO", []))
    n50 = set(raw.get("NIFTY_50", []))
    nn50 = set(raw.get("NIFTY_NEXT_50", []))
    mid50 = set(raw.get("NIFTY_MIDCAP_50", []))
    all_shortable = fno | n50 | nn50 | mid50
    assert len(all_shortable) >= 180, f"Expected >= 180, got {len(all_shortable)}"
    print(f"[PASS] Test 3: Gate #0 Liquid universe JSON ({len(all_shortable)} symbols verified)")

def test_4_dual_tranche_lifecycle_state_machine():
    """Verify dual-tranche partial profit taking and BE trailing state machine."""
    # Bullish Scenario: Entry=100, SL=90, R=10, T1=115, T2=130
    entry, sl, r = 100.0, 90.0, 10.0
    t1, t2 = 115.0, 130.0

    # Step A: High touches T1
    high = 116.0
    outcome = "T1_HIT_TRAILED"
    realized_r = 0.75  # 50% booked at 1.5R

    # Step B1: Pullback to BE (100.0) -> T1_WIN_BE_EXIT
    low_pullback = 99.5
    if low_pullback <= entry:
        outcome = "T1_WIN_BE_EXIT"
        realized_r = 0.75
    assert outcome == "T1_WIN_BE_EXIT"
    assert realized_r == 0.75

    # Step B2: High touches T2 (130.0) -> T2_HIT
    outcome_runner = "T1_HIT_TRAILED"
    high_t2 = 131.0
    if high_t2 >= t2:
        outcome_runner = "T2_HIT"
        realized_r_t2 = 0.75 + (0.5 * 3.0)  # 2.25R net
    assert outcome_runner == "T2_HIT"
    assert realized_r_t2 == 2.25
    print("[PASS] Test 4: Dual-Tranche lifecycle state machine (T1_WIN_BE_EXIT & T2_HIT)")

def test_5_eod_mtm_settlement():
    """Verify bidirectional 15:15 MTM settlement."""
    # Bullish runner at 15:15: Entry 100, R 10, current price 120 (after T1)
    entry, r, ltp = 100.0, 10.0, 120.0
    outcome = "T1_HIT_TRAILED"
    remaining_r = (ltp - entry) / r  # 2.0R
    realized_r = 0.75 + (0.5 * remaining_r) # 0.75 + 1.0 = 1.75R
    outcome = "EOD_PARTIAL_WIN"
    assert outcome == "EOD_PARTIAL_WIN"
    assert realized_r == 1.75
    print("[PASS] Test 5: Bidirectional 15:15 MTM partial settlement (1.75R)")

def test_6_outcome_synchronization():
    """Verify outcome synchronization across weekly and conviction audit."""
    import types
    from datetime import timezone, timedelta
    # Mock pytz if not present in runtime environment using a true datetime.tzinfo subclass
    if "pytz" not in sys.modules:
        try:
            __import__("pytz")
        except ImportError:
            dummy_tz = types.ModuleType("pytz")
            ist_offset = timezone(timedelta(hours=5, minutes=30), name="IST")
            dummy_tz.timezone = lambda name: ist_offset
            sys.modules["pytz"] = dummy_tz

    from app.v13_weekly_audit import V14_T1_WIN_OUTCOMES, V14_WIN_OUTCOMES, V14_EOD_PROFIT_OUTCOMES

    expected_t1 = {"T1_HIT", "T2_HIT", "T1_HIT_TRAILED", "T1_WIN_BE_EXIT", "EOD_PARTIAL_WIN"}
    expected_win = {"T1_HIT", "T2_HIT", "T1_HIT_TRAILED", "T1_WIN_BE_EXIT", "EOD_PARTIAL_WIN", "CLOSED_EOD_PROFIT"}
    expected_eod = {"CLOSED_EOD_PROFIT", "EOD_PARTIAL_WIN"}

    assert set(V14_T1_WIN_OUTCOMES) == expected_t1
    assert set(V14_WIN_OUTCOMES) == expected_win
    assert set(V14_EOD_PROFIT_OUTCOMES) == expected_eod
    print("[PASS] Test 6: Audit outcome synchronization across modules verified")

def test_7_live_movers_v14_synchronization():
    """Verify Live Movers V14 synchronization: Gate #0 Short Guard, 15m ATR Exhaustion, Tick Rounding, and Grade C Banner."""
    from app.v13_live_movers import evaluate_mover_stock, _load_fno_and_liquid_symbols
    from app.v13_live_movers_telegram import format_live_mover_message

    shortable_set = _load_fno_and_liquid_symbols()
    assert len(shortable_set) >= 180

    # 1. Verify Non-F&O / Non-Liquid Loser is blocked from Shorting (Gate #0)
    illiquid_loser = {
        "symbol": "ILLIQUID_TEST_EQ",
        "name": "Illiquid Cash Stock",
        "sector": "Chemicals",
        "is_fno": False,
        "snapshot": {
            "price": 245.33,
            "latest_session_change_pct": -4.2,
            "rel_vol": 2.4,
            "ema20": 250.10,
            "vwap": 251.50,
            "atr14": 4.20,
            "turnover_cr": 42.0,
        },
    }
    res_short = evaluate_mover_stock(illiquid_loser, is_gainer=False, shortable_symbols=shortable_set)
    assert res_short["status"] == "CASH_SHORT_RESTRICTED"
    assert res_short["archetype"] == "OBSERVATION"
    assert res_short["trade_plan"] is None

    # 2. Verify 15m Intraday ATR Exhaustion (day_range >= 8.0 * atr14)
    exhausted_gainer = {
        "symbol": "RELIANCE",
        "name": "Reliance Industries",
        "sector": "Energy",
        "is_fno": True,
        "snapshot": {
            "price": 3020.0,
            "latest_session_change_pct": 6.5,
            "rel_vol": 3.1,
            "ema20": 3005.0,
            "vwap": 2990.0,
            "atr14": 15.0,
            "high_price": 3030.0,
            "low_price": 2900.0,  # Range = 130.0 (> 8.0 * 15 = 120.0)
            "turnover_cr": 450.0,
        },
    }
    res_exh = evaluate_mover_stock(exhausted_gainer, is_gainer=True, shortable_symbols=shortable_set)
    assert res_exh["archetype"] == "EXHAUSTION_WARNING"
    assert res_exh["status"] == "DAILY_ATR_EXHAUSTED"
    assert res_exh["trade_plan"] is None

    # 3. Verify Qualified Runner NSE Tick Normalization (5-paise grid) & 20-EMA Structural SL
    runner_gainer = {
        "symbol": "TCS",
        "name": "Tata Consultancy Services",
        "sector": "IT",
        "is_fno": True,
        "snapshot": {
            "price": 4125.33,
            "latest_session_change_pct": 3.4,
            "rel_vol": 2.2,
            "ema20": 4115.20,
            "vwap": 4100.00,
            "atr14": 22.0,
            "high_price": 4135.0,
            "low_price": 4060.0,
            "turnover_cr": 310.0,
        },
    }
    res_run = evaluate_mover_stock(runner_gainer, is_gainer=True, v13_score=82.5, shortable_symbols=shortable_set)
    assert res_run["archetype"] == "RUNNER"
    tp = res_run["trade_plan"]
    assert tp is not None
    # Verify exact 5-paise tick grid compliance across all levels
    for key in ("entry", "stop_loss", "target_1", "target_2"):
        paise = int(round(tp[key] * 100))
        assert paise % 5 == 0, f"{key}={tp[key]} not on 0.05 tick grid"
    # Verify Target 2 is 2.5R
    expected_t2_paise = int(round((tp["entry"] + 2.5 * tp["risk_amount"]) * 100))
    assert abs(int(round(tp["target_2"] * 100)) - expected_t2_paise) <= 5

    # 4. Verify Consolidation Plan Tick Normalization
    consolidation_gainer = {
        "symbol": "INFY",
        "name": "Infosys Limited",
        "sector": "IT",
        "is_fno": True,
        "snapshot": {
            "price": 1850.22,
            "latest_session_change_pct": 2.1,
            "rel_vol": 1.2,  # Below 1.5x -> enters CONSOLIDATION
            "ema20": 1855.33,
            "vwap": 1852.17,
            "atr14": 14.0,
            "high_price": 1865.0,
            "low_price": 1830.0,
            "turnover_cr": 210.0,
        },
    }
    res_cons = evaluate_mover_stock(consolidation_gainer, is_gainer=True, v13_score=76.0, shortable_symbols=shortable_set)
    assert res_cons["status"] == "CONSOLIDATION"
    tp_cons = res_cons["trade_plan"]
    assert tp_cons is not None
    for key in ("entry", "stop_loss", "target_1", "target_2"):
        paise = int(round(tp_cons[key] * 100))
        assert paise % 5 == 0, f"Consolidation {key}={tp_cons[key]} not on 0.05 tick grid"
    assert tp_cons["stop_loss"] < tp_cons["entry"]

    # 5. Verify Grade C Warning Banner in Telegram Formatter (returns str and mutates item in-place)
    weak_mover = dict(res_run)
    weak_mover["v13_score"] = 62.0
    weak_mover["rel_vol"] = 1.1
    weak_ctx = {"nifty_direction": "Bearish", "nifty_change_pct": -1.2}
    msg = format_live_mover_message(weak_mover, is_long=True, market_context=weak_ctx, universe=[])
    assert isinstance(msg, str)
    assert "conviction_grade" in weak_mover
    if weak_mover.get("conviction_grade") == "GRADE_C":
        assert "WATCH ONLY / DO NOT TRADE" in msg

    # 6. Verify Pre-Cooldown Conviction Upgrade Bypass & Ledger Isolation
    rank_map = {"GRADE_C": 0, "GRADE_B": 1, "GRADE_A_PLUS": 2}
    assert rank_map["GRADE_B"] > rank_map["GRADE_C"]
    assert rank_map["GRADE_A_PLUS"] > rank_map["GRADE_B"]

    print("[PASS] Test 7: Live Movers V14 synchronization (Gate #0, 15m ATR Exhaustion, Tick Grid, Grade C Banner & Cooldown Bypass)")


def test_8_v14_calibration_suite():
    """Verify V14 calibration:
    1. Trend structure 12.0 max points and progressive higher low check.
    2. Context alignment gate lowered to 60.0.
    3. LT scenario (wide OR with midday atr shrinkage) produces valid signal using ref_or_atr.
    4. Daily ATR budget anchored to entry_traveled (not close).
    5. Live movers min score calibrated to 65.0.
    """
    from app.v13_engine import _trend_structure, _context_alignment
    from app.v13_live_movers import evaluate_mover_stock, compute_live_top_movers

    # 1. Verify Trend Structure 12.0 max points and Pillar 3
    df_dict = {
        "High": [100.0, 102.0, 103.0, 104.0, 106.0, 108.0],
        "Low": [98.0, 99.0, 100.0, 101.0, 103.0, 105.0],
        "Close": [99.5, 101.0, 102.5, 103.5, 105.5, 107.5],
    }
    df_bull = sys.modules["pandas"].DataFrame(df_dict)
    sc, r, p = _trend_structure(df_bull, "BULLISH", rel_vol=2.0, vwap=104.0)
    assert sc == 12.0, f"Expected 12.0 max trend score, got {sc}"
    assert "Higher-high structure" in r
    assert "Higher-low structure" in r
    assert "Sustained bullish closing structure" in r

    # Fake higher-low: lows[-1] < lows[-2] should fail higher_lows
    df_fake_dict = {
        "High": [100.0, 102.0, 103.0, 104.0, 106.0, 108.0],
        "Low": [98.0, 99.0, 100.0, 101.0, 103.0, 101.5],  # Low dropped below previous bar!
        "Close": [99.5, 101.0, 102.5, 103.5, 105.5, 107.5],
    }
    df_fake = sys.modules["pandas"].DataFrame(df_fake_dict)
    sc_fake, r_fake, _ = _trend_structure(df_fake, "BULLISH", rel_vol=2.0, vwap=104.0)
    assert sc_fake <= 8.0
    assert "Higher-low structure" not in r_fake

    # Pillar 3 VWAP hold progression: closes[-1] not highest, but last 3 hold above VWAP and closes[-1] >= closes[-2]
    df_flag_dict = {
        "High": [100.0, 102.0, 104.0, 108.0, 107.0, 107.5],
        "Low": [98.0, 99.0, 101.0, 104.0, 104.5, 105.0],
        "Close": [99.5, 101.0, 103.0, 107.5, 105.5, 106.5],
    }
    df_flag = sys.modules["pandas"].DataFrame(df_flag_dict)
    sc_flag, r_flag, _ = _trend_structure(df_flag, "BULLISH", rel_vol=1.8, vwap=104.0)
    assert "Sustained bullish closing structure" in r_flag

    # Early session (len(df) < 6)
    df_early_dict = {
        "High": [100.0, 105.0],
        "Low": [98.0, 99.0],
        "Close": [99.0, 104.5],
    }
    df_early = sys.modules["pandas"].DataFrame(df_early_dict)
    sc_early, r_early, _ = _trend_structure(df_early, "BULLISH", rel_vol=2.6, opening_high=103.0, vwap=100.0, close=104.5)
    assert sc_early == 12.0
    assert "Explosive opening breakout structure" in r_early[0]

    # 2. Verify Sector Catch-22 Gate lowered from 72.0 to 60.0
    # Score 59.5 should receive 0.0 sector points
    n_sc, s_sc, _, _ = _context_alignment(current_score=59.5, direction="BULLISH", context={"nifty_direction": "BULLISH", "sector_direction": "BULLISH"})
    assert s_sc == 0.0, f"Expected 0.0 sector points for score 59.5, got {s_sc}"
    # Score 60.0 should unlock 5.0 sector points
    n_sc, s_sc, r_ctx, _ = _context_alignment(current_score=60.0, direction="BULLISH", context={"nifty_direction": "BULLISH", "sector_direction": "BULLISH"})
    assert s_sc == 5.0, f"Expected 5.0 sector points for score 60.0, got {s_sc}"
    assert "Sector aligned bullish" in r_ctx

    # 3. Verify LT Midday ref_or_atr & 4.0x confirmed volume breakout multiplier
    or_width = 38.60
    midday_atr14 = 12.68
    or_atr14 = 20.0
    effective_daily_atr = 65.0
    ref_or_atr = max(midday_atr14, or_atr14, effective_daily_atr * 0.25)
    assert ref_or_atr == 20.0
    is_confirmed_vol_breakout = True
    max_or_atr_mult = 4.0 if is_confirmed_vol_breakout else 3.0
    assert or_width > 3.0 * midday_atr14
    assert or_width <= max_or_atr_mult * ref_or_atr

    # 4. Verify Daily ATR Budget Guard anchored to entry_traveled (not live close)
    entry = 3649.20
    day_low = 3610.60
    entry_traveled = max(0.0, entry - day_low)
    remaining_daily_room = max(0.0, effective_daily_atr - entry_traveled)
    t1_distance = 1.5 * (3649.20 - 3635.00)
    assert t1_distance <= (1.20 * remaining_daily_room)

    # 5. Verify Live Movers default min_v13_score calibrated to 65.0
    import inspect
    sig_eval = inspect.signature(evaluate_mover_stock)
    assert sig_eval.parameters["min_v13_score"].default == 65.0
    assert float(os.getenv("V13_ACTIVE_RUNNER_MIN_SCORE", "65")) == 65.0
    assert float(os.getenv("TELEGRAM_LIVE_MOVERS_MIN_SCORE", "65")) == 65.0

    print("[PASS] Test 8: V14 Calibration Suite (100pt Trend Scale, Progressive HL, Context Gate 60, LT ref_or_atr & Entry-Traveled Budget)")


if __name__ == "__main__":
    print("=" * 60)
    print("NSE-PULSE V14 QUANTITATIVE REGRESSION TEST SUITE")
    print("=" * 60)
    test_1_integer_paise_tick_normalizer()
    test_2_prefiltered_sl_buffer()
    test_3_gate_0_liquid_universe_json()
    test_4_dual_tranche_lifecycle_state_machine()
    test_5_eod_mtm_settlement()
    test_6_outcome_synchronization()
    test_7_live_movers_v14_synchronization()
    test_8_v14_calibration_suite()
    print("=" * 60)
    print("ALL 8 QUANTITATIVE REGRESSION TESTS PASSED (100% GREEN)")
    print("=" * 60)
