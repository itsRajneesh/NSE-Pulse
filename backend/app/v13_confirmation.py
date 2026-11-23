from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class H3Confirmation:
    confirmed: bool
    trade_ready: bool
    direction: str
    trigger_time: Optional[pd.Timestamp] = None
    retest_time: Optional[pd.Timestamp] = None
    reclaim_time: Optional[pd.Timestamp] = None
    hold_3_closes: bool = False
    next_candle_time: Optional[pd.Timestamp] = None
    next_candle_open: Optional[float] = None
    reason: str = ""


def _result(
    *,
    confirmed: bool,
    trade_ready: bool,
    direction: str,
    reason: str,
    trigger_time: Optional[pd.Timestamp] = None,
    retest_time: Optional[pd.Timestamp] = None,
    reclaim_time: Optional[pd.Timestamp] = None,
    hold_3_closes: bool = False,
    next_candle_time: Optional[pd.Timestamp] = None,
    next_candle_open: Optional[float] = None,
) -> H3Confirmation:
    return H3Confirmation(
        confirmed=confirmed,
        trade_ready=trade_ready,
        direction=direction,
        trigger_time=trigger_time,
        retest_time=retest_time,
        reclaim_time=reclaim_time,
        hold_3_closes=hold_3_closes,
        next_candle_time=next_candle_time,
        next_candle_open=next_candle_open,
        reason=reason,
    )


def confirm_h3(
    candles: pd.DataFrame,
    signal_time: pd.Timestamp,
    direction: str,
    opening_range_high: float,
    opening_range_low: float,
    rel_vol: float = 1.0,
) -> H3Confirmation:
    """
    Production H3 confirmation.

    Bullish:
        trigger -> retest OR high -> reclaim close > OR high
        -> 3 subsequent completed closes > OR high
        -> next 5m candle OPEN.

    Bearish:
        trigger -> retest OR low -> reclaim close < OR low
        -> 3 subsequent completed closes < OR low
        -> next 5m candle OPEN.

    Confirmation is same-session only and fails closed when required
    candles/data are missing.
    """
    direction = str(direction).upper().strip()

    if direction not in {"BULLISH", "BEARISH"}:
        return _result(
            confirmed=False,
            trade_ready=False,
            direction=direction,
            reason="INVALID_DIRECTION",
        )

    if candles is None or candles.empty:
        return _result(
            confirmed=False,
            trade_ready=False,
            direction=direction,
            reason="NO_CANDLES",
        )

    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(set(candles.columns)):
        return _result(
            confirmed=False,
            trade_ready=False,
            direction=direction,
            reason="MISSING_OHLC_COLUMNS",
        )

    try:
        signal_ts = pd.Timestamp(signal_time)
    except Exception:
        return _result(
            confirmed=False,
            trade_ready=False,
            direction=direction,
            reason="INVALID_SIGNAL_TIME",
        )

    x = candles.copy()
    x = x.dropna(subset=["Open", "High", "Low", "Close"]).copy()

    if x.empty:
        return _result(
            confirmed=False,
            trade_ready=False,
            direction=direction,
            reason="NO_VALID_CANDLES",
        )

    try:
        idx = pd.DatetimeIndex(x.index)
    except Exception:
        return _result(
            confirmed=False,
            trade_ready=False,
            direction=direction,
            reason="INVALID_CANDLE_INDEX",
        )

    if idx.tz is not None:
        idx = idx.tz_localize(None)

    if signal_ts.tzinfo is not None:
        signal_ts = signal_ts.tz_localize(None)

    x.index = idx
    x = x[~x.index.duplicated(keep="first")].sort_index()

    # Only candles at/after the engine signal are eligible.
    after_signal = x[x.index >= signal_ts].copy()
    if after_signal.empty:
        return _result(
            confirmed=False,
            trade_ready=False,
            direction=direction,
            reason="TRIGGER_MISSING",
        )

    # The first available candle at/after signal_time is the trigger.
    trigger_time = after_signal.index[0]
    trigger_session = trigger_time.date()

    # Production H3 is strictly same-session.
    session = after_signal[after_signal.index.date == trigger_session].copy()

    if session.empty:
        return _result(
            confirmed=False,
            trade_ready=False,
            direction=direction,
            reason="TRIGGER_SESSION_MISSING",
        )

    trigger_pos = 0

    if direction == "BULLISH":
        level = float(opening_range_high)

        # Retest: later candle touches/returns to OR high.
        retest_pos = None
        for pos in range(trigger_pos + 1, len(session)):
            if float(session.iloc[pos]["Low"]) <= level:
                retest_pos = pos
                break

        if retest_pos is None:
            return _result(
                confirmed=False,
                trade_ready=False,
                direction=direction,
                trigger_time=trigger_time,
                reason="NO_RETEST",
            )

        retest_time = session.index[retest_pos]

        # Reclaim: later candle CLOSE strictly above OR high.
        reclaim_pos = None
        for pos in range(retest_pos + 1, len(session)):
            if float(session.iloc[pos]["Close"]) > level:
                reclaim_pos = pos
                break

    else:
        level = float(opening_range_low)

        # Retest: later candle touches/returns to OR low.
        retest_pos = None
        for pos in range(trigger_pos + 1, len(session)):
            if float(session.iloc[pos]["High"]) >= level:
                retest_pos = pos
                break

        if retest_pos is None:
            return _result(
                confirmed=False,
                trade_ready=False,
                direction=direction,
                trigger_time=trigger_time,
                reason="NO_RETEST",
            )

        retest_time = session.index[retest_pos]

        # Reclaim: later candle CLOSE strictly below OR low.
        reclaim_pos = None
        for pos in range(retest_pos + 1, len(session)):
            if float(session.iloc[pos]["Close"]) < level:
                reclaim_pos = pos
                break

    if reclaim_pos is None:
        return _result(
            confirmed=False,
            trade_ready=False,
            direction=direction,
            trigger_time=trigger_time,
            retest_time=retest_time,
            reason="RETEST_NO_RECLAIM",
        )

    reclaim_time = session.index[reclaim_pos]

    # Fast-track H3 confirmation: 1 completed close if rel_vol >= 2.0x, else 3 closes.
    required_hold_count = 1 if rel_vol >= 2.0 else 3
    hold_start = reclaim_pos + 1
    hold_end = hold_start + required_hold_count
    hold_window = session.iloc[hold_start:hold_end].copy()

    if len(hold_window) < required_hold_count:
        return _result(
            confirmed=False,
            trade_ready=False,
            direction=direction,
            trigger_time=trigger_time,
            retest_time=retest_time,
            reclaim_time=reclaim_time,
            reason="INSUFFICIENT_HOLD_CANDLES",
        )

    closes = pd.to_numeric(hold_window["Close"], errors="coerce")

    if direction == "BULLISH":
        hold_ok = bool((closes > level).all())
    else:
        hold_ok = bool((closes < level).all())

    if not hold_ok:
        return _result(
            confirmed=False,
            trade_ready=False,
            direction=direction,
            trigger_time=trigger_time,
            retest_time=retest_time,
            reclaim_time=reclaim_time,
            hold_3_closes=False,
            reason="HOLD_3_CLOSSES_FAILED",
        )

    # Next candle after the third completed hold candle is the entry candle.
    next_pos = hold_end

    if next_pos >= len(session):
        return _result(
            confirmed=True,
            trade_ready=False,
            direction=direction,
            trigger_time=trigger_time,
            retest_time=retest_time,
            reclaim_time=reclaim_time,
            hold_3_closes=True,
            reason="NEXT_5M_CANDLE_MISSING",
        )

    next_candle = session.iloc[next_pos]
    next_time = session.index[next_pos]
    next_open = float(next_candle["Open"])

    return _result(
        confirmed=True,
        trade_ready=True,
        direction=direction,
        trigger_time=trigger_time,
        retest_time=retest_time,
        reclaim_time=reclaim_time,
        hold_3_closes=True,
        next_candle_time=next_time,
        next_candle_open=next_open,
        reason="H3_CONFIRMED_NEXT_5M_OPEN",
    )
