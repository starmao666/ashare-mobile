import unittest
import pandas as pd
from portfolio_backtest import (backtest_portfolio, prepare, is_locked_limit_up, is_locked_limit_down, is_suspended)


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


    def test_stop_loss_gap_uses_open_not_unreachable_stop(self):
        dates = pd.date_range("2024-01-01", periods=27, freq="B")
        rows = []
        for i, date in enumerate(dates):
            open_price = close = 10.0
            high, low = 10.2, 9.8
            if i == 24:
                open_price, high, low, close = 10.0, 10.2, 9.9, 10.1
            elif i == 25:
                open_price, high, low, close = 10.1, 10.2, 10.0, 10.1
            elif i == 26:
                # Opens through a 5% stop: execution must use 9.0 open, not 9.595 stop.
                open_price, high, low, close = 9.0, 9.2, 8.8, 9.0
            rows.append({"date": date, "code": "000001", "open": open_price,
                         "high": high, "low": low, "close": close})
        trades, _ = backtest_portfolio(
            pd.DataFrame(rows), initial_cash=100_000, risk_fraction=0.0075,
            stop_fraction=0.05, target_fraction=0.08, max_hold=2,
            max_positions=1, fee_rate=0.0003, sell_tax_rate=0.0005,
            slippage_rate=0.0005, strategy="baseline"
        )
        self.assertEqual(len(trades), 1)
        trade = trades.iloc[0]
        self.assertEqual(trade["exit_reason"], "stop_loss")
        self.assertAlmostEqual(trade["exit_trigger_price"], 9.0, places=6)
        self.assertLess(trade["exit_price"], 9.0)

    def test_locked_limit_and_suspension_detection(self):
        up = pd.Series({"open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0,
                        "pct_chg": 10.0, "volume": 1000, "amount": 10000})
        down = pd.Series({"open": 9.0, "high": 9.0, "low": 9.0, "close": 9.0,
                          "pct_chg": -10.0, "volume": 1000, "amount": 10000})
        suspended = pd.Series({"open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0,
                               "pct_chg": 0.0, "volume": 0, "amount": 0})
        normal = pd.Series({"open": 10.0, "high": 10.2, "low": 9.8, "close": 10.1,
                            "pct_chg": 1.0, "volume": 1000, "amount": 10000})
        self.assertTrue(is_locked_limit_up(up))
        self.assertTrue(is_locked_limit_down(down))
        self.assertTrue(is_suspended(suspended))
        self.assertFalse(is_locked_limit_up(normal))
        self.assertFalse(is_locked_limit_down(normal))
        self.assertFalse(is_suspended(normal))


    def test_t_plus_one_and_costs_are_applied(self):
        dates = pd.date_range("2024-01-01", periods=27, freq="B")
        rows = []
        for i, date in enumerate(dates):
            close = 10.0
            open_price = 10.0
            high = 10.2
            low = 9.8
            if i == 24:
                close = 10.1  # Signal after this close.
                open_price, high, low = 10.0, 10.2, 9.9
            elif i == 25:
                open_price, high, low, close = 10.1, 10.2, 10.0, 10.1
            elif i == 26:
                open_price, high, low, close = 9.4, 9.6, 9.0, 9.3  # Stop hit next session.
            rows.append({"date": date, "code": "000001", "open": open_price,
                         "high": high, "low": low, "close": close})
        trades, equity = backtest_portfolio(
            pd.DataFrame(rows), initial_cash=100_000, risk_fraction=0.0075,
            stop_fraction=0.05, target_fraction=0.08, max_hold=2,
            max_positions=1, fee_rate=0.0003, sell_tax_rate=0.0005,
            slippage_rate=0.0005, strategy="baseline"
        )
        self.assertEqual(len(trades), 1)
        trade = trades.iloc[0]
        self.assertEqual(trade["entry_date"], dates[25].date().isoformat())
        self.assertEqual(trade["exit_date"], dates[26].date().isoformat())
        self.assertEqual(trade["exit_reason"], "stop_loss")
        self.assertGreater(trade["entry_fee"], 0)
        self.assertGreater(trade["exit_fee"], 0)
        self.assertGreater(trade["sell_tax"], 0)
        self.assertLess(trade["exit_price"], trade["exit_trigger_price"])
        self.assertLess(trade["pnl_after_modeled_costs"], 0)


if __name__ == "__main__":
    unittest.main()
