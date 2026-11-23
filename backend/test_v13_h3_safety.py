import unittest
import pandas as pd

from app.v13_confirmation import confirm_h3


class TestV13H3Safety(unittest.TestCase):

    def test_cross_session_confirmation_is_rejected(self):
        index = pd.DatetimeIndex([
            "2026-09-11 15:00:00",  # trigger
            "2026-09-11 15:05:00",  # retest
            "2026-09-11 15:10:00",  # reclaim
            "2026-09-11 15:15:00",  # hold 1
            "2026-09-11 15:20:00",  # hold 2
            "2026-09-14 09:15:00",  # next session - must NOT count as hold 3
        ])

        candles = pd.DataFrame([
            [100, 101, 99, 100, 1000],
            [100, 101, 99.5, 100.5, 1000],
            [100.5, 102, 100.5, 101.5, 1000],
            [101.5, 102.5, 101, 102, 1000],
            [102, 103, 101.5, 102.5, 1000],
            [102.5, 104, 102, 103.5, 1000],
        ], index=index, columns=["Open", "High", "Low", "Close", "Volume"])

        result = confirm_h3(
            candles=candles,
            signal_time=pd.Timestamp("2026-09-11 15:00:00"),
            direction="BULLISH",
            opening_range_high=100.0,
            opening_range_low=95.0,
        )

        self.assertFalse(result.confirmed)
        self.assertFalse(result.trade_ready)
        self.assertEqual(result.reason, "INSUFFICIENT_HOLD_CANDLES")


    def test_three_close_hold_failure_rejects_confirmation(self):
        index = pd.date_range(
            "2026-09-11 14:00:00",
            periods=7,
            freq="5min",
        )

        candles = pd.DataFrame([
            [100, 101, 99, 100, 1000],
            [100, 101, 99.5, 100.5, 1000],
            [100.5, 102, 100.5, 101.5, 1000],
            [101.5, 102.5, 101, 102, 1000],
            [102, 103, 99.5, 99.8, 1000],
            [99.8, 101, 99, 100.5, 1000],
            [100.5, 102, 100, 101, 1000],
        ], index=index, columns=["Open", "High", "Low", "Close", "Volume"])

        result = confirm_h3(
            candles=candles,
            signal_time=pd.Timestamp("2026-09-11 14:00:00"),
            direction="BULLISH",
            opening_range_high=100.0,
            opening_range_low=95.0,
        )

        self.assertFalse(result.confirmed)
        self.assertFalse(result.trade_ready)
        self.assertFalse(result.hold_3_closes)
        self.assertEqual(result.reason, "HOLD_3_CLOSSES_FAILED")


if __name__ == "__main__":
    unittest.main()
