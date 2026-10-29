import unittest
import pandas as pd
from portfolio_backtest import backtest_portfolio, prepare


class PortfolioTests(unittest.TestCase):
    def test_prepare_drops_invalid_bars(self):
        frame = pd.DataFrame([
            {"date":"2024-01-02","code":"1","open":10,"high":11,"low":9,"close":10.5},
            {"date":"2024-01-03","code":"1","open":10,"high":9,"low":8,"close":10.2},
        ])
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.csv"
            frame.to_csv(path, index=False)
            result = prepare(str(path))
        self.assertEqual(len(result), 1)

    def test_empty_bars_returns_empty_outputs(self):
        cols = ["date", "code", "open", "high", "low", "close"]
        trades, equity = backtest_portfolio(pd.DataFrame(columns=cols))
        self.assertTrue(trades.empty)
        self.assertTrue(equity.empty)


if __name__ == "__main__":
    unittest.main()
