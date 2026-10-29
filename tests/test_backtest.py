"""Unit tests use tiny synthetic fixtures only to test mechanics, never to report market performance."""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backtest import load_bars, run_backtest


class BacktestTests(unittest.TestCase):
    def test_load_bars_drops_invalid_ohlc(self):
        frame = pd.DataFrame([
            {"date": "2024-01-02", "code": "1", "open": 10, "high": 11, "low": 9, "close": 10.5},
            {"date": "2024-01-03", "code": "1", "open": 10, "high": 9, "low": 8, "close": 10.2},
        ])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.csv"
            frame.to_csv(path, index=False)
            result = load_bars(str(path))
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["code"], "000001")

    def test_short_history_produces_no_ma20_signal(self):
        rows = []
        for day in range(1, 15):
            rows.append({
                "date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=day),
                "code": "000001", "open": 10, "high": 10.5, "low": 9.5, "close": 10.1
            })
        trades = run_backtest(pd.DataFrame(rows))
        self.assertTrue(trades.empty)

    def test_no_trades_for_empty_input(self):
        trades = run_backtest(pd.DataFrame(columns=[
            "date", "code", "open", "high", "low", "close"
        ]))
        self.assertTrue(trades.empty)


if __name__ == "__main__":
    unittest.main()
