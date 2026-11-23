import unittest
import pandas as pd

from app.v13_confirmation import confirm_h3


class TestV13H3Confirmation(unittest.TestCase):

    def make_candles(self, rows):
        index = pd.date_range(
            "2026-09-11 14:00:00",
            periods=len(rows),
            freq="5min",
        )
        return pd.DataFrame(rows, index=index, columns=["Open", "High", "Low", "Close", "Volume"])


    def test_bullish_h3_trade_ready(self):
        candles = self.make_candles([
            [100, 101, 99, 100, 1000],   # trigger
            [100, 101, 99.5, 100.5, 1000],  # retest
            [100, 102, 100.5, 101.5, 1000], # reclaim
            [101.5, 102.5, 101, 102, 1000], # hold 1
            [102, 103, 101.5, 102.5, 1000], # hold 2
            [102.5, 104, 102, 103.5, 1000], # hold 3
            [103.5, 105, 103, 104.5, 1000], # next 5m entry
        ])

        result = confirm_h3(
            candles=candles,
            signal_time=pd.Timestamp("2026-09-11 14:00:00"),
            direction="BULLISH",
            opening_range_high=100.0,
            opening_range_low=95.0,
        )

        self.assertTrue(result.confirmed)
        self.assertTrue(result.trade_ready)
        self.assertEqual(result.direction, "BULLISH")
        self.assertEqual(result.next_candle_open, 103.5)


    def test_bearish_h3_trade_ready(self):
        candles = self.make_candles([
            [100, 101, 99, 100, 1000],   # trigger
            [99, 100.5, 98.5, 99.5, 1000],  # retest
            [99, 99.5, 97.5, 98, 1000],      # reclaim
            [98, 98.5, 96.5, 97, 1000],      # hold 1
            [97, 97.5, 95.5, 96, 1000],      # hold 2
            [96, 96.5, 94.5, 95, 1000],      # hold 3
            [95, 95.5, 93.5, 94, 1000],      # next 5m entry
        ])

        result = confirm_h3(
            candles=candles,
            signal_time=pd.Timestamp("2026-09-11 14:00:00"),
            direction="BEARISH",
            opening_range_high=105.0,
            opening_range_low=100.0,
        )

        self.assertTrue(result.confirmed)
        self.assertTrue(result.trade_ready)
        self.assertEqual(result.direction, "BEARISH")
        self.assertEqual(result.next_candle_open, 95.0)


    def test_missing_next_candle_is_not_trade_ready(self):
        candles = self.make_candles([
            [100, 101, 99, 100, 1000],
            [100, 101, 99.5, 100.5, 1000],
            [100.5, 102, 100.5, 101.5, 1000],
            [101.5, 102.5, 101, 102, 1000],
            [102, 103, 101.5, 102.5, 1000],
            [102.5, 104, 102, 103.5, 1000],
        ])

        result = confirm_h3(
            candles=candles,
            signal_time=pd.Timestamp("2026-09-11 14:00:00"),
            direction="BULLISH",
            opening_range_high=100.0,
            opening_range_low=95.0,
        )

        self.assertTrue(result.confirmed)
        self.assertFalse(result.trade_ready)
        self.assertIsNone(result.next_candle_open)


    def test_invalid_direction_fails_closed(self):
        candles = self.make_candles([
            [100, 101, 99, 100, 1000],
        ])

        result = confirm_h3(
            candles=candles,
            signal_time=pd.Timestamp("2026-09-11 14:00:00"),
            direction="SIDEWAYS",
            opening_range_high=100.0,
            opening_range_low=95.0,
        )

        self.assertFalse(result.confirmed)
        self.assertFalse(result.trade_ready)


if __name__ == "__main__":
    unittest.main()
