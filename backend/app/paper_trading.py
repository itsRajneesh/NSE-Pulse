"""
Paper Trading / Shadow Trading Logger

IMPORTANT:
- No real orders are placed.
- This module only records prediction signals and their outcomes.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


PAPER_TRADING_FILE = (
    Path(__file__).resolve().parent.parent / "paper_trading_signals.csv"
)


FIELDNAMES = [
    "signal_id",
    "scan_time",
    "signal_time",
    "symbol",
    "name",
    "sector",
    "direction",
    "setup_type",
    "score",
    "ltp",
    "entry_price",
    "stop_loss",
    "target_1",
    "target_2",
    "risk_amount",
    "risk_reward_t1",
    "risk_reward_t2",
    "ema20",
    "rsi14",
    "rel_vol",
    "vwap",
    "atr14",
    "opening_range_high",
    "opening_range_low",
    "previous_day_high",
    "previous_day_low",
    "reasons",
    "status",
    "outcome",
    "outcome_price",
    "outcome_time",
    "realized_r",
]


def _safe_value(value: Any) -> Any:
    """Convert pandas/numpy values into CSV-safe Python values."""
    if value is None:
        return ""

    try:
        if hasattr(value, "item"):
            value = value.item()
    except Exception:
        pass

    return value


def _next_signal_id() -> str:
    """Generate a simple sequential paper-trade ID."""
    if not PAPER_TRADING_FILE.exists():
        return "PT-00001"

    try:
        with PAPER_TRADING_FILE.open(
            "r",
            newline="",
            encoding="utf-8",
        ) as file:
            rows = list(csv.DictReader(file))

        return f"PT-{len(rows) + 1:05d}"

    except Exception:
        return f"PT-{datetime.now().strftime('%Y%m%d%H%M%S')}"


def ensure_paper_trading_file() -> None:
    """Create the CSV with headers if it does not exist."""
    if PAPER_TRADING_FILE.exists():
        return

    with PAPER_TRADING_FILE.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FIELDNAMES,
        )
        writer.writeheader()


def record_prediction(setup: Any) -> str:
    """
    Record one prediction setup.

    This function accepts the existing PredictionSetup object,
    without changing the prediction engine itself.
    """
    ensure_paper_trading_file()

    signal_id = _next_signal_id()

    reasons = getattr(setup, "reasons", [])

    if isinstance(reasons, list):
        reasons_text = " | ".join(str(reason) for reason in reasons)
    else:
        reasons_text = str(reasons)

    row: Dict[str, Any] = {
        "signal_id": signal_id,
        "scan_time": datetime.now().isoformat(timespec="seconds"),
        "signal_time": getattr(setup, "last_updated", ""),
        "symbol": getattr(setup, "symbol", ""),
        "name": getattr(setup, "name", ""),
        "sector": getattr(setup, "sector", ""),
        "direction": getattr(setup, "signal_type", ""),
        "setup_type": getattr(setup, "setup_type", ""),
        "score": getattr(setup, "confidence_score", ""),
        "ltp": getattr(setup, "ltp", ""),
        "entry_price": getattr(setup, "entry_price", ""),
        "stop_loss": getattr(setup, "stop_loss", ""),
        "target_1": getattr(setup, "target_1", ""),
        "target_2": getattr(setup, "target_2", ""),
        "risk_amount": getattr(setup, "risk_amount", ""),
        "risk_reward_t1": getattr(setup, "risk_reward_ratio_t1", ""),
        "risk_reward_t2": getattr(setup, "risk_reward_ratio_t2", ""),
        "ema20": getattr(setup, "ema20", ""),
        "rsi14": getattr(setup, "rsi14", ""),
        "rel_vol": getattr(setup, "rel_vol", ""),
        "vwap": getattr(setup, "vwap", ""),
        "atr14": getattr(setup, "atr14", ""),
        "opening_range_high": getattr(setup, "opening_range_high", ""),
        "opening_range_low": getattr(setup, "opening_range_low", ""),
        "previous_day_high": getattr(setup, "previous_day_high", ""),
        "previous_day_low": getattr(setup, "previous_day_low", ""),
        "reasons": reasons_text,
        "status": "OPEN",
        "outcome": "",
        "outcome_price": "",
        "outcome_time": "",
    }

    row = {
        key: _safe_value(value)
        for key, value in row.items()
    }

    with PAPER_TRADING_FILE.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FIELDNAMES,
        )
        writer.writerow(row)

    return signal_id


def get_open_paper_trades() -> List[Dict[str, str]]:
    """Return all currently OPEN paper trades."""
    ensure_paper_trading_file()

    with PAPER_TRADING_FILE.open(
        "r",
        newline="",
        encoding="utf-8",
    ) as file:
        rows = list(csv.DictReader(file))

    return [
        row
        for row in rows
        if row.get("status") == "OPEN"
    ]


def get_all_paper_trades() -> List[Dict[str, Any]]:
    """Return all recorded paper trades with numeric fields normalized."""

    ensure_paper_trading_file()

    numeric_fields = {
        "score",
        "ltp",
        "entry_price",
        "stop_loss",
        "target_1",
        "target_2",
        "risk_amount",
        "ema20",
        "rsi14",
        "rel_vol",
        "vwap",
        "atr14",
        "opening_range_high",
        "opening_range_low",
        "previous_day_high",
        "previous_day_low",
        "outcome_price",
        "realized_r",
    }

    with PAPER_TRADING_FILE.open(
        "r",
        newline="",
        encoding="utf-8",
    ) as file:
        rows = list(csv.DictReader(file))

    normalized_rows: List[Dict[str, Any]] = []

    for row in rows:
        normalized = dict(row)

        for field in numeric_fields:
            value = normalized.get(field)

            if value is None or value == "":
                normalized[field] = None
                continue

            try:
                normalized[field] = float(value)
            except (TypeError, ValueError):
                normalized[field] = None

        normalized_rows.append(normalized)

    return normalized_rows
    
def qualifies_for_v12(setup: Any) -> bool:
    """
    V12 shadow-trading rule.

    Rule:
    - BULLISH
    - DEVELOPING_BREAKOUT_LONG
    - Setup Score 70-74
    - Signal time between 12:00 and 14:00 IST
    """

    direction = str(
        getattr(setup, "signal_type", "")
    ).upper()

    setup_type = str(
        getattr(setup, "setup_type", "")
    ).upper()

    score = getattr(
        setup,
        "confidence_score",
        None,
    )

    if direction != "BULLISH":
        return False

    if setup_type != "DEVELOPING_BREAKOUT_LONG":
        return False

    try:
        score = float(score)
    except (TypeError, ValueError):
        return False

    if not 70.0 <= score <= 74.0:
        return False

    # ---------------------------------------------------------
    # Time filter: 12:00 to 14:00 IST
    # ---------------------------------------------------------

    last_updated = getattr(
        setup,
        "last_updated",
        "",
    )

    if not last_updated:
        return False

    try:
        from datetime import datetime

        signal_time = datetime.strptime(
            last_updated,
            "%d %b %Y, %I:%M:%S %p IST",
        ).time()

        start_time = datetime.strptime(
            "12:00 PM",
            "%I:%M %p",
        ).time()

        end_time = datetime.strptime(
            "02:00 PM",
            "%I:%M %p",
        ).time()

        if not (start_time <= signal_time <= end_time):
            return False

    except (ValueError, TypeError):
        return False

    return True

def is_duplicate_signal(setup: Any) -> bool:
    """
    Prevent the same stock/setup/candle from being logged repeatedly.

    The API may be refreshed every minute, so the same signal can
    appear multiple times before the next 15-minute candle arrives.
    """

    if not PAPER_TRADING_FILE.exists():
        return False

    symbol = str(getattr(setup, "symbol", ""))
    setup_type = str(getattr(setup, "setup_type", ""))
    last_updated = str(getattr(setup, "last_updated", ""))

    try:
        with PAPER_TRADING_FILE.open(
            "r",
            newline="",
            encoding="utf-8",
        ) as file:
            rows = csv.DictReader(file)

            for row in rows:
                if (
                    row.get("symbol") == symbol
                    and row.get("setup_type") == setup_type
                    and row.get("signal_time") == last_updated
                    and row.get("status") == "OPEN"
                ):
                    return True

    except Exception:
        return False

    return False

def update_open_trade_outcome(
    symbol: str,
    df_15m: Any,
) -> int:
    """
    Check existing OPEN paper trades for one symbol against
    future 15-minute candles.

    Returns:
        Number of trades closed by this update.
    """

    if df_15m is None or df_15m.empty:
        return 0

    ensure_paper_trading_file()

    # ---------------------------------------------------------
    # Read all existing paper trades
    # ---------------------------------------------------------
    try:
        with PAPER_TRADING_FILE.open(
            "r",
            newline="",
            encoding="utf-8",
        ) as file:
            rows = list(csv.DictReader(file))
    except Exception:
        return 0

    if not rows:
        return 0

    symbol = str(symbol).upper().replace(".NS", "")

    updated = False
    closed_count = 0

    # ---------------------------------------------------------
    # Process only OPEN trades for this symbol
    # ---------------------------------------------------------
    for trade in rows:

        if trade.get("status") != "OPEN":
            continue

        trade_symbol = str(
            trade.get("symbol", "")
        ).upper().replace(".NS", "")

        if trade_symbol != symbol:
            continue

        try:
            entry_price = float(trade["entry_price"])
            stop_loss = float(trade["stop_loss"])
            target_1 = float(trade["target_1"])
            target_2 = float(trade["target_2"])
            risk_amount = float(trade["risk_amount"])
        except (TypeError, ValueError, KeyError):
            continue

        if risk_amount <= 0:
            continue

        direction = str(
            trade.get("direction", "")
        ).upper()

        signal_time_text = str(
            trade.get("signal_time", "")
        ).strip()

        if not signal_time_text:
            continue

        # -----------------------------------------------------
        # Convert signal timestamp
        # -----------------------------------------------------
        try:
            signal_time = datetime.strptime(
                signal_time_text,
                "%d %b %Y, %I:%M:%S %p IST",
            )

        except (ValueError, TypeError):
            continue

        # -----------------------------------------------------
        # Check only candles STRICTLY AFTER signal time.
        # -----------------------------------------------------
        for candle_time, candle in df_15m.iterrows():

            if hasattr(candle_time, "to_pydatetime"):
                candle_dt = candle_time.to_pydatetime()
            else:
                candle_dt = candle_time

            # Remove timezone for comparison if necessary.
            if hasattr(candle_dt, "tzinfo") and candle_dt.tzinfo is not None:
                candle_dt_naive = candle_dt.replace(tzinfo=None)
            else:
                candle_dt_naive = candle_dt

            if candle_dt_naive <= signal_time:
                continue

            try:
                candle_high = float(candle["High"])
                candle_low = float(candle["Low"])
            except (TypeError, ValueError, KeyError):
                continue

            outcome = None
            outcome_price = None
            realized_r = None

            # -------------------------------------------------
            # BULLISH TRADE
            #
            # IMPORTANT:
            # SL is checked FIRST.
            # This preserves the backtest SL-first rule.
            # -------------------------------------------------
            if direction == "BULLISH":

                if candle_low <= stop_loss:
                    outcome = "SL_FIRST"
                    outcome_price = stop_loss
                    realized_r = -1.0

                elif candle_high >= target_2:
                    outcome = "T2_FIRST"
                    outcome_price = target_2
                    realized_r = 2.5

                elif candle_high >= target_1:
                    outcome = "T1_FIRST"
                    outcome_price = target_1
                    realized_r = 1.5

            # -------------------------------------------------
            # BEARISH TRADE
            # -------------------------------------------------
            elif direction == "BEARISH":

                if candle_high >= stop_loss:
                    outcome = "SL_FIRST"
                    outcome_price = stop_loss
                    realized_r = -1.0

                elif candle_low <= target_2:
                    outcome = "T2_FIRST"
                    outcome_price = target_2
                    realized_r = 2.5

                elif candle_low <= target_1:
                    outcome = "T1_FIRST"
                    outcome_price = target_1
                    realized_r = 1.5

            if outcome is None:
                continue

            # -------------------------------------------------
            # CLOSE THE PAPER TRADE
            # -------------------------------------------------
            trade["status"] = "CLOSED"
            trade["outcome"] = outcome
            trade["outcome_price"] = str(
                round(float(outcome_price), 2)
            )
            trade["outcome_time"] = (
                candle_dt.strftime(
                    "%d %b %Y, %I:%M:%S %p IST"
                )
            )
            trade["realized_r"] = str(
                round(float(realized_r), 2)
            )

            updated = True
            closed_count += 1

            # One trade can only have one final outcome.
            break

    # ---------------------------------------------------------
    # Write updated CSV only if something changed
    # ---------------------------------------------------------
    if updated:
        try:
            with PAPER_TRADING_FILE.open(
                "w",
                newline="",
                encoding="utf-8",
            ) as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=FIELDNAMES,
                )
                writer.writeheader()
                writer.writerows(rows)

        except Exception as e:
            print(
                f"Paper trade outcome update failed "
                f"for {symbol}: {e}"
            )
            return 0

    return closed_count