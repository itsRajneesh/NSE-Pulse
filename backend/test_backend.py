"""
Unit and Integration Tests for NSE Intraday Screener Backend.
Tests:
1. EMA 20 calculation accuracy
2. RSI 14 calculation accuracy
3. Relative Volume calculation
4. Trade parameters calculation (Entry, SL, Target 1, Target 2, Risk Amount)
5. Screener evaluation output
"""
import unittest
import pandas as pd
import numpy as np

from app.indicators import calculate_ema, calculate_rsi, calculate_relative_volume
from app.screener import evaluate_stock_signal
from app.models import SignalType
from app.data_fetcher import run_screener, get_market_status, get_stock_history_and_indicators


class TestQuantEngine(unittest.TestCase):

    def setUp(self):
        # Create a synthetic 15-minute price series
        np.random.seed(42)
        n = 50
        dates = pd.date_range(start="2026-09-01 09:15", periods=n, freq="15min")
        close = np.linspace(100, 120, n) + np.random.normal(0, 0.5, n)
        high = close + np.random.uniform(0.2, 1.0, n)
        low = close - np.random.uniform(0.2, 1.0, n)
        open_p = close + np.random.normal(0, 0.2, n)
        vol = np.random.randint(10000, 50000, n)
        # Add a volume spike at the end
        vol[-1] = 120000

        self.df = pd.DataFrame({
            'Open': open_p,
            'High': high,
            'Low': low,
            'Close': close,
            'Volume': vol
        }, index=dates)

    def test_ema_calculation(self):
        ema20 = calculate_ema(self.df['Close'], period=20)
        self.assertEqual(len(ema20), len(self.df))
        self.assertFalse(ema20.isna().all())
        # With upward trend, latest price should be higher than EMA20
        self.assertGreater(self.df['Close'].iloc[-1], ema20.iloc[-1])
        print('✓ test_ema_calculation passed')

    def test_rsi_calculation(self):
        rsi14 = calculate_rsi(self.df['Close'], period=14)
        self.assertEqual(len(rsi14), len(self.df))
        latest_rsi = rsi14.iloc[-1]
        self.assertGreaterEqual(latest_rsi, 0.0)
        self.assertLessEqual(latest_rsi, 100.0)
        # Upward trending series should have RSI > 50
        self.assertGreater(latest_rsi, 50.0)
        print(f'✓ test_rsi_calculation passed (Latest RSI: {latest_rsi:.2f})')

    def test_relative_volume(self):
        rel_vol, current_vol, avg_vol = calculate_relative_volume(self.df)
        self.assertEqual(current_vol, 120000)
        self.assertGreater(rel_vol, 1.5)
        print(f'✓ test_relative_volume passed (RelVol: {rel_vol}x)')

    def test_screener_signal_and_trade_params(self):
        # Create clear breakout setup
        df_breakout = self.df.copy()
        # Last candle breakout
        entry = 125.0
        sl = 121.0
        df_breakout.iloc[-1, df_breakout.columns.get_loc('High')] = entry
        df_breakout.iloc[-1, df_breakout.columns.get_loc('Low')] = sl
        df_breakout.iloc[-1, df_breakout.columns.get_loc('Close')] = entry
        # Ensure price change >= 1.5%
        df_breakout.iloc[0, df_breakout.columns.get_loc('Open')] = 100.0

        signal = evaluate_stock_signal(
            symbol="TESTSTOCK",
            name="Test Stock Ltd",
            sector="Information Technology",
            df_15m=df_breakout
        )

        self.assertEqual(signal.signal_type, SignalType.BULLISH)
        self.assertTrue(signal.is_active_signal)
        self.assertIsNotNone(signal.trade_params)
        
        tp = signal.trade_params
        # High = 125.0, Low = 121.0 -> Risk = 4.0
        expected_risk = round(entry - sl, 2)
        expected_t1 = round(entry + (expected_risk * 1.5), 2)
        expected_t2 = round(entry + (expected_risk * 2.0), 2)

        self.assertEqual(tp.entry_price, entry)
        self.assertEqual(tp.stop_loss, sl)
        self.assertEqual(tp.risk_amount, expected_risk)
        self.assertEqual(tp.target_1, expected_t1)
        self.assertEqual(tp.target_2, expected_t2)
        print(f'✓ test_screener_signal_and_trade_params passed: Entry={tp.entry_price}, SL={tp.stop_loss}, Risk={tp.risk_amount}, T1={tp.target_1}, T2={tp.target_2}')

    def test_data_fetcher_and_screener_response(self):
        resp = run_screener(mode="simulation")
        self.assertGreater(resp.total_scanned, 0)
        self.assertGreater(resp.active_signals_count, 0)
        self.assertTrue(hasattr(resp.market_status, 'session_message'))
        print(f'✓ test_data_fetcher passed: Scanned {resp.total_scanned} stocks, {resp.active_signals_count} active signals, Sentiment: {resp.market_sentiment}')

    def test_stock_history_endpoint(self):
        history = get_stock_history_and_indicators("RELIANCE")
        self.assertIsNotNone(history)
        self.assertEqual(history.symbol, "RELIANCE")
        self.assertGreater(len(history.candles), 0)
        self.assertGreater(len(history.ema20_series), 0)
        self.assertGreater(len(history.rsi_series), 0)
        print(f'✓ test_stock_history_endpoint passed for RELIANCE ({len(history.candles)} candles)')


if __name__ == '__main__':
    unittest.main()
