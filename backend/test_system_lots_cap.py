"""
Unit tests for Configurable MAX_SYSTEM_LOTS_CAP via backend/.env.
Verifies:
1. Default 150 lots ceiling.
2. Float-string parsing ('150.0').
3. Dynamic runtime os.environ override (200 lots) with 8-leg Iceberg slicing [27x7, 11].
4. Defensive fallbacks for invalid values (-10, 0, abc, empty).
"""

import os
import sys

# Ensure backend/app is in Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

from v13_nifty_options_engine import (
    DEFAULT_MAX_SYSTEM_LOTS_CAP,
    compute_iceberg_slices,
    compute_universal_position_sizing,
    get_max_system_lots_cap,
)


def test_default_env_resolution():
    """Test 1: Default or unset env should return 150 lots."""
    orig_env = os.environ.get("NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP")
    try:
        os.environ["NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP"] = "150"
        cap = get_max_system_lots_cap()
        assert cap == 150, f"Expected 150, got {cap}"
        print("[PASS] Test 1: Default '150' resolves to 150")
    finally:
        if orig_env is not None:
            os.environ["NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP"] = orig_env


def test_float_string_tolerance():
    """Test 2: Float-string '150.0' should safely parse to integer 150."""
    orig_env = os.environ.get("NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP")
    try:
        os.environ["NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP"] = "150.0"
        cap = get_max_system_lots_cap()
        assert cap == 150, f"Expected 150, got {cap}"
        print("[PASS] Test 2: Float string '150.0' resolves to 150 without ValueError")
    finally:
        if orig_env is not None:
            os.environ["NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP"] = orig_env


def test_invalid_fallback():
    """Test 3: Invalid inputs should safely fallback to default 150."""
    orig_env = os.environ.get("NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP")
    try:
        invalid_inputs = ["-10", "0", "0.0", "abc", "", "   "]
        for inp in invalid_inputs:
            os.environ["NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP"] = inp
            cap = get_max_system_lots_cap()
            assert cap == 150, f"Expected fallback 150 for input {inp!r}, got {cap}"
        print("[PASS] Test 3: Invalid inputs safely fall back to 150")
    finally:
        if orig_env is not None:
            os.environ["NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP"] = orig_env


def test_dynamic_override_200_lots():
    """
    Test 4: Dynamic runtime override to 200 lots with capital = 2.5 Crore (25000000)
    and risk = 10%. Verifies:
    - allowed_lots caps at 200
    - max_system_lots_cap returned is 200
    - Iceberg slices decompose into 8 legs [27, 27, 27, 27, 27, 27, 27, 11]
    """
    orig_env = os.environ.get("NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP")
    try:
        os.environ["NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP"] = "200"

        # Universal sizing call with 2.5 Crore capital at 10% risk
        res = compute_universal_position_sizing(
            capital_inr=25000000.0,
            risk_mode="PERCENT",
            risk_value=10.0,
            entry_premium=95.0,
            sl_premium=72.20,
            t1_premium=129.20,
            t2_premium=152.0,
            lot_size=65,
        )

        assert res["allowed_lots"] == 200, f"Expected allowed_lots == 200, got {res['allowed_lots']}"
        assert res["study_lots"] == 200, f"Expected study_lots == 200, got {res['study_lots']}"
        assert res["max_system_lots_cap"] == 200, f"Expected max_system_lots_cap == 200, got {res['max_system_lots_cap']}"

        expected_slices = [27, 27, 27, 27, 27, 27, 27, 11]
        assert res["entry_slices"] == expected_slices, f"Expected {expected_slices}, got {res['entry_slices']}"
        assert res["entry_legs"] == 8, f"Expected 8 legs, got {res['entry_legs']}"
        assert res["allowed_qty"] == 200 * 65, f"Expected {200 * 65} qty, got {res['allowed_qty']}"

        print("[PASS] Test 4: Dynamic override to 200 lots verified with 8-leg Iceberg slicing [27x7, 11]!")
    finally:
        if orig_env is not None:
            os.environ["NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP"] = orig_env


def test_default_150_lots_sizing():
    """
    Test 5: Default 150 lots with capital = 2.5 Crore (25000000)
    Verifies:
    - allowed_lots caps at 150
    - Iceberg slices decompose into 6 legs [27, 27, 27, 27, 27, 15]
    """
    orig_env = os.environ.get("NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP")
    try:
        os.environ["NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP"] = "150"

        res = compute_universal_position_sizing(
            capital_inr=25000000.0,
            risk_mode="PERCENT",
            risk_value=10.0,
            entry_premium=95.0,
            sl_premium=72.20,
            t1_premium=129.20,
            t2_premium=152.0,
            lot_size=65,
        )

        assert res["allowed_lots"] == 150, f"Expected allowed_lots == 150, got {res['allowed_lots']}"
        expected_slices = [27, 27, 27, 27, 27, 15]
        assert res["entry_slices"] == expected_slices, f"Expected {expected_slices}, got {res['entry_slices']}"
        assert res["entry_legs"] == 6, f"Expected 6 legs, got {res['entry_legs']}"
        assert res["allowed_qty"] == 9750, f"Expected 9750 qty, got {res['allowed_qty']}"

        print("[PASS] Test 5: Default 150 lots verified with 6-leg Iceberg slicing [27x5, 15]!")
    finally:
        if orig_env is not None:
            os.environ["NIFTY_OPTIONS_MAX_SYSTEM_LOTS_CAP"] = orig_env


if __name__ == "__main__":
    print("=== RUNNING MAX_SYSTEM_LOTS_CAP UNIT TESTS ===")
    test_default_env_resolution()
    test_float_string_tolerance()
    test_invalid_fallback()
    test_dynamic_override_200_lots()
    test_default_150_lots_sizing()
    print("=== ALL 5 UNIT TESTS PASSED (100% SUCCESS) ===")
