from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from pydantic import ValidationError

from app.config import NIFTY_500_STOCKS
from app.v13_models import V13Signal
import app.v13_scanner as v13_scanner
from app.v13_scanner import validate_v13_history, scan_v13_universe
from app.v13_market_context import build_nifty_context
import app.main as v13_main


class TestV13Infrastructure(unittest.TestCase):


    def test_v13_nifty_cache_hit_and_copy_isolation(self):
        index = pd.date_range(
            "2026-09-11 09:15",
            periods=2,
            freq="15min",
        )
        fake_nifty = pd.DataFrame(
            {
                "Open": [100.0, 101.0],
                "High": [101.0, 102.0],
                "Low": [99.0, 100.0],
                "Close": [100.5, 101.5],
                "Volume": [1000, 1100],
            },
            index=index,
        )

        v13_main._V13_NIFTY_CACHE = None
        v13_main._V13_NIFTY_CACHE_AT = 0.0

        calls = []

        def fake_download(*args, **kwargs):
            calls.append((args, kwargs))
            return fake_nifty.copy()

        with patch.object(v13_main.yf, "download", side_effect=fake_download):
            first = v13_main._get_v13_nifty_data()
            first.loc[first.index[0], "Close"] = 999.0
            second = v13_main._get_v13_nifty_data()

        self.assertEqual(len(calls), 1)
        self.assertEqual(float(second["Close"].iloc[0]), 100.5)
        self.assertIsNot(first, second)

        v13_main._V13_NIFTY_CACHE = None
        v13_main._V13_NIFTY_CACHE_AT = 0.0


    def test_v13_nifty_cache_ttl_expiry(self):
        index = pd.date_range(
            "2026-09-11 09:15",
            periods=2,
            freq="15min",
        )
        fake_nifty = pd.DataFrame(
            {
                "Open": [100.0, 101.0],
                "High": [101.0, 102.0],
                "Low": [99.0, 100.0],
                "Close": [100.5, 101.5],
                "Volume": [1000, 1100],
            },
            index=index,
        )

        original_ttl = v13_main.V13_NIFTY_CACHE_TTL_SECONDS
        v13_main.V13_NIFTY_CACHE_TTL_SECONDS = 0
        v13_main._V13_NIFTY_CACHE = None
        v13_main._V13_NIFTY_CACHE_AT = 0.0

        calls = []

        def fake_download(*args, **kwargs):
            calls.append((args, kwargs))
            return fake_nifty.copy()

        try:
            with patch.object(v13_main.yf, "download", side_effect=fake_download):
                first = v13_main._get_v13_nifty_data()
                second = v13_main._get_v13_nifty_data()

            self.assertFalse(first.empty)
            self.assertFalse(second.empty)
            self.assertEqual(len(calls), 2)
        finally:
            v13_main.V13_NIFTY_CACHE_TTL_SECONDS = original_ttl
            v13_main._V13_NIFTY_CACHE = None
            v13_main._V13_NIFTY_CACHE_AT = 0.0


    def test_v13_nifty_empty_response_is_not_cached(self):
        v13_main._V13_NIFTY_CACHE = None
        v13_main._V13_NIFTY_CACHE_AT = 0.0

        calls = []

        def fake_download(*args, **kwargs):
            calls.append((args, kwargs))
            return pd.DataFrame()

        try:
            with patch.object(v13_main.yf, "download", side_effect=fake_download):
                first = v13_main._get_v13_nifty_data()
                second = v13_main._get_v13_nifty_data()

            self.assertTrue(first.empty)
            self.assertTrue(second.empty)
            self.assertEqual(len(calls), 2)
            self.assertIsNone(v13_main._V13_NIFTY_CACHE)
        finally:
            v13_main._V13_NIFTY_CACHE = None
            v13_main._V13_NIFTY_CACHE_AT = 0.0

    def test_signal_model_contract(self):
        signal = V13Signal(
            symbol="TEST",
            name="Test Stock",
            sector="Test Sector",
            direction="BULLISH",
            setup="TEST_SETUP",
            stage="WATCH",
            score=72.0,
            signal_time="2026-09-11T15:15:00+05:30",
            market={},
            price=100.0,
            risk={
                "entry": 100.0,
                "stop_loss": 98.0,
                "target_1": 103.0,
                "target_2": 105.0,
                "risk_amount": 2.0,
                "risk_reward_t1": "1.50R",
                "risk_reward_t2": "2.50R",
            },
            indicators={},
            confirmation={},
        )

        self.assertEqual(signal.symbol, "TEST")
        self.assertEqual(signal.stage, "WATCH")
        self.assertEqual(signal.score, 72.0)

    def test_signal_model_rejects_unknown_field(self):
        with self.assertRaises(ValidationError):
            V13Signal(
                symbol="TEST",
                name="Test Stock",
                sector="Test Sector",
                direction="BULLISH",
                setup="TEST_SETUP",
                stage="WATCH",
                score=72.0,
                signal_time="2026-09-11T15:15:00+05:30",
                risk={},
                indicators={},
                confirmation={},
                unexpected_field="MUST_FAIL",
            )

    def test_history_validator_requires_seven_sessions(self):
        dates_6 = pd.date_range(
            "2026-09-01 09:15",
            periods=6,
            freq="D",
        )

        df_6 = pd.DataFrame(
            {
                "Open": np.full(6, 100.0),
                "High": np.full(6, 101.0),
                "Low": np.full(6, 99.0),
                "Close": np.full(6, 100.0),
                "Volume": np.full(6, 1000),
            },
            index=dates_6,
        )

        self.assertFalse(validate_v13_history(df_6))

        dates_7 = pd.date_range(
            "2026-09-01 09:15",
            periods=7,
            freq="D",
        )

        df_7 = pd.DataFrame(
            {
                "Open": np.full(7, 100.0),
                "High": np.full(7, 101.0),
                "Low": np.full(7, 99.0),
                "Close": np.full(7, 100.0),
                "Volume": np.full(7, 1000),
            },
            index=dates_7,
        )

        self.assertTrue(validate_v13_history(df_7))

    def test_exact_500_universe_guard(self):
        self.assertEqual(len(NIFTY_500_STOCKS), 500)

        with self.assertRaises(ValueError):
            scan_v13_universe(NIFTY_500_STOCKS[:-1])

    def test_v13_single_ticker_multiindex_response_is_parsed(self):
        fields = ["Open", "High", "Low", "Close", "Volume"]
        index = pd.date_range("2026-09-11 09:15", periods=2, freq="15min")
        columns = pd.MultiIndex.from_product(
            [["AFCONS.NS"], fields],
            names=["Ticker", "Price"],
        )
        data = [
            [100.0, 101.0, 99.0, 100.5, 1000],
            [100.5, 102.0, 100.0, 101.5, 1200],
        ]
        fake_df = pd.DataFrame(data, index=index, columns=columns)

        calls = []

        def fake_download(*args, **kwargs):
            tickers = kwargs.get("tickers", args[0] if args else None)
            calls.append(list(tickers))
            return fake_df.copy()

        with patch.object(v13_scanner, "yf") as fake_yf:
            fake_yf.download.side_effect = fake_download
            with v13_scanner._V13_CACHE_LOCK:
                v13_scanner._V13_CACHE.clear()

            result = v13_scanner._download_v13_chunk(["AFCONS.NS"])

        self.assertIn("AFCONS.NS", result)
        self.assertEqual(
            list(result["AFCONS.NS"].columns),
            fields,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(float(result["AFCONS.NS"]["Close"].iloc[-1]), 101.5)

    def test_v13_cache_single_ticker_hit_and_copy_isolation(self):
        calls = []

        def fake_download(*args, **kwargs):
            calls.append(list(kwargs["tickers"]))
            return pd.DataFrame(
                {
                    "Open": [100.0],
                    "High": [101.0],
                    "Low": [99.0],
                    "Close": [100.5],
                    "Volume": [1000.0],
                },
                index=pd.DatetimeIndex(["2026-09-14 09:15:00"]),
            )

        original = v13_scanner.yf.download
        original_ttl = v13_scanner.V13_CACHE_TTL_SECONDS

        try:
            v13_scanner._V13_CACHE.clear()
            v13_scanner.V13_CACHE_TTL_SECONDS = 300
            v13_scanner.yf.download = fake_download

            first = v13_scanner._download_v13_chunk(["A.NS"])
            first["A.NS"].loc[:, "Close"] = 999.0

            second = v13_scanner._download_v13_chunk(["A.NS"])

            self.assertEqual(calls, [["A.NS"]])
            self.assertEqual(float(second["A.NS"]["Close"].iloc[0]), 100.5)
        finally:
            v13_scanner.yf.download = original
            v13_scanner.V13_CACHE_TTL_SECONDS = original_ttl
            v13_scanner._V13_CACHE.clear()

    def test_v13_cache_ttl_expiry(self):
        calls = []

        def fake_download(*args, **kwargs):
            calls.append(list(kwargs["tickers"]))
            return pd.DataFrame(
                {
                    "Open": [100.0],
                    "High": [101.0],
                    "Low": [99.0],
                    "Close": [100.5],
                    "Volume": [1000.0],
                },
                index=pd.DatetimeIndex(["2026-09-14 09:15:00"]),
            )

        original = v13_scanner.yf.download
        original_ttl = v13_scanner.V13_CACHE_TTL_SECONDS

        try:
            v13_scanner._V13_CACHE.clear()
            v13_scanner.V13_CACHE_TTL_SECONDS = 0
            v13_scanner.yf.download = fake_download

            v13_scanner._download_v13_chunk(["A.NS"])
            v13_scanner._download_v13_chunk(["A.NS"])

            self.assertEqual(calls, [["A.NS"], ["A.NS"]])
        finally:
            v13_scanner.yf.download = original
            v13_scanner.V13_CACHE_TTL_SECONDS = original_ttl
            v13_scanner._V13_CACHE.clear()

    def test_v13_cache_partial_batch_fetches_only_missing(self):
        calls = []

        def fake_download(*args, **kwargs):
            tickers = list(kwargs["tickers"])
            calls.append(tickers)

            index = pd.DatetimeIndex(["2026-09-14 09:15:00"])

            if len(tickers) == 1:
                return pd.DataFrame(
                    {
                        "Open": [100.0],
                        "High": [101.0],
                        "Low": [99.0],
                        "Close": [100.5],
                        "Volume": [1000.0],
                    },
                    index=index,
                )

            arrays = [
                (ticker, field)
                for ticker in tickers
                for field in ["Open", "High", "Low", "Close", "Volume"]
            ]
            columns = pd.MultiIndex.from_tuples(arrays)

            row = []
            for ticker in tickers:
                row.extend([100.0, 101.0, 99.0, 100.5, 1000.0])

            return pd.DataFrame([row], columns=columns, index=index)

        original = v13_scanner.yf.download

        try:
            v13_scanner._V13_CACHE.clear()
            v13_scanner.yf.download = fake_download

            first = v13_scanner._download_v13_chunk(["A.NS", "B.NS"])
            second = v13_scanner._download_v13_chunk(["A.NS", "B.NS", "C.NS"])

            self.assertEqual(sorted(first.keys()), ["A.NS", "B.NS"])
            self.assertEqual(sorted(second.keys()), ["A.NS", "B.NS", "C.NS"])
            self.assertEqual(calls, [["A.NS", "B.NS"], ["C.NS"]])
        finally:
            v13_scanner.yf.download = original
            v13_scanner._V13_CACHE.clear()

    def test_v13_cache_empty_response_is_not_cached(self):
        calls = []

        def fake_download(*args, **kwargs):
            calls.append(list(kwargs["tickers"]))
            return pd.DataFrame()

        original = v13_scanner.yf.download

        try:
            v13_scanner._V13_CACHE.clear()
            v13_scanner.yf.download = fake_download

            first = v13_scanner._download_v13_chunk(["A.NS"])
            second = v13_scanner._download_v13_chunk(["A.NS"])

            self.assertEqual(first, {})
            self.assertEqual(second, {})
            self.assertEqual(calls, [["A.NS"], ["A.NS"], ["A.NS"], ["A.NS"], ["A.NS"], ["A.NS"]])
            self.assertEqual(len(v13_scanner._V13_CACHE), 0)
        finally:
            v13_scanner.yf.download = original
            v13_scanner._V13_CACHE.clear()

    def test_nifty_context_is_point_in_time(self):
        index = pd.date_range(
            "2026-09-11 09:15",
            periods=30,
            freq="15min",
        )

        close = np.linspace(100.0, 110.0, 30)

        df = pd.DataFrame(
            {
                "Open": close,
                "High": close + 1.0,
                "Low": close - 1.0,
                "Close": close,
                "Volume": np.full(30, 1000),
            },
            index=index,
        )

        cutoff = index[19]

        context = build_nifty_context(df, cutoff)

        self.assertTrue(context)
        self.assertEqual(context["signal_time"], cutoff.isoformat())
        self.assertLessEqual(
            pd.Timestamp(context["signal_time"]),
            cutoff,
        )
        self.assertEqual(context["bars_used"], 20)



    def test_v13_retry_fail_fail_success(self):
        calls = []

        def fake_download(**kwargs):
            calls.append(kwargs["tickers"])
            if len(calls) < 3:
                raise RuntimeError("temporary failure")
            return pd.DataFrame({
                "Open": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "Close": [100.5],
                "Volume": [1000],
            })

        with patch.object(v13_scanner.yf, "download", side_effect=fake_download):
            with patch.object(v13_scanner.time, "sleep") as sleep_mock:
                result = v13_scanner._download_v13_with_retry(["A.NS"])

        self.assertIsNotNone(result)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleep_mock.call_count, 2)

    def test_v13_retry_exhaustion_returns_none(self):
        calls = []

        def fake_download(**kwargs):
            calls.append(kwargs["tickers"])
            raise RuntimeError("persistent failure")

        with patch.object(v13_scanner.yf, "download", side_effect=fake_download):
            with patch.object(v13_scanner.time, "sleep") as sleep_mock:
                result = v13_scanner._download_v13_with_retry(["A.NS"])

        self.assertIsNone(result)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleep_mock.call_count, 2)

    def test_v13_retry_empty_response_returns_none(self):
        calls = []

        def fake_download(**kwargs):
            calls.append(kwargs["tickers"])
            return pd.DataFrame()

        with patch.object(v13_scanner.yf, "download", side_effect=fake_download):
            with patch.object(v13_scanner.time, "sleep") as sleep_mock:
                result = v13_scanner._download_v13_with_retry(["A.NS"])

        self.assertIsNone(result)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleep_mock.call_count, 2)

if __name__ == "__main__":
    unittest.main()


