"""Research-only daily-bar backtest for A-share CSV data.

Input CSV columns: date, code, open, high, low, close
Optional: amount, turnover, pct_chg, volume_ratio
No data is downloaded or fabricated by this module.

Signal (known after day t close): close > rolling MA20 and close is between
-3% and +2% on the day. This is deliberately a simple baseline, NOT the full
"first pullback after a strong rally" strategy. Entry is next available bar open.
Exit: stop -5%, take profit +8%, or max holding 5 bars. If stop and target are
both touched in one daily bar, stop is assumed first (conservative).
"""
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

REQUIRED = {"date", "code", "open", "high", "low", "close"}


def load_bars(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {', '.join(sorted(missing))}")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["code"] = df["code"].astype(str).str.zfill(6)
    df = df.dropna(subset=["date", "code", "open", "high", "low", "close"])
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    df = df[df["high"] >= df[["open", "low", "close"]].max(axis=1)]
    df = df[df["low"] <= df[["open", "high", "close"]].min(axis=1)]
    df = df.drop_duplicates(["code", "date"]).sort_values(["code", "date"])
    return df.reset_index(drop=True)


def run_backtest(bars: pd.DataFrame, stop_pct: float = 0.05,
                 target_pct: float = 0.08, max_hold: int = 5) -> pd.DataFrame:
    trades = []
    for code, group in bars.groupby("code", sort=False):
        g = group.sort_values("date").reset_index(drop=True).copy()
        g["ma20"] = g["close"].rolling(20, min_periods=20).mean()
        g["pct_chg_calc"] = g["close"].pct_change() * 100
        # This is a transparent baseline signal, not the finished pullback model.
        g["signal"] = (g["close"] > g["ma20"]) & g["pct_chg_calc"].between(-3, 2)
        i = 0
        while i < len(g) - 1:
            if not bool(g.loc[i, "signal"]):
                i += 1
                continue
            entry_i = i + 1
            entry = float(g.loc[entry_i, "open"])
            if entry <= 0:
                i += 1
                continue
            stop = entry * (1 - stop_pct)
            target = entry * (1 + target_pct)
            exit_i = min(entry_i + max_hold - 1, len(g) - 1)
            exit_price = float(g.loc[exit_i, "close"])
            exit_reason = "max_hold_or_data_end"
            actual_exit_i = exit_i
            for j in range(entry_i, exit_i + 1):
                low, high = float(g.loc[j, "low"]), float(g.loc[j, "high"])
                # Conservative tie-break: stop first if both levels touched.
                if low <= stop:
                    exit_price, exit_reason, actual_exit_i = stop, "stop_loss", j
                    break
                if high >= target:
                    exit_price, exit_reason, actual_exit_i = target, "take_profit", j
                    break
            ret = exit_price / entry - 1
            trades.append({
                "code": code,
                "signal_date": g.loc[i, "date"].date().isoformat(),
                "entry_date": g.loc[entry_i, "date"].date().isoformat(),
                "entry_price": round(entry, 4),
                "exit_date": g.loc[actual_exit_i, "date"].date().isoformat(),
                "exit_price": round(exit_price, 4),
                "exit_reason": exit_reason,
                "return_pct_before_costs": round(ret * 100, 4),
                "holding_bars": actual_exit_i - entry_i + 1,
            })
            # Avoid overlapping positions in the same ticker.
            i = actual_exit_i + 1
    return pd.DataFrame(trades, columns=[
        "code", "signal_date", "entry_date", "entry_price", "exit_date",
        "exit_price", "exit_reason", "return_pct_before_costs", "holding_bars"
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description="Research-only A-share daily-bar baseline backtest")
    parser.add_argument("csv", help="Historical daily-bar CSV; no synthetic data is generated")
    parser.add_argument("--stop", type=float, default=0.05, help="Stop loss fraction (default 0.05)")
    parser.add_argument("--target", type=float, default=0.08, help="Take-profit fraction (default 0.08)")
    parser.add_argument("--max-hold", type=int, default=5, help="Maximum trading bars held (default 5)")
    parser.add_argument("--out", default="backtest_trades.csv", help="Output trade CSV")
    args = parser.parse_args()
    if not (0 < args.stop < 1 and 0 < args.target < 5 and args.max_hold >= 1):
        parser.error("stop must be in (0,1), target in (0,5), max-hold >= 1")
    bars = load_bars(args.csv)
    if bars.empty:
        raise SystemExit("No valid rows found; no backtest was run.")
    trades = run_backtest(bars, args.stop, args.target, args.max_hold)
    out = Path(args.out)
    trades.to_csv(out, index=False, encoding="utf-8-sig")
    if trades.empty:
        print("No trades generated. This is not evidence of strategy performance.")
    else:
        returns = trades["return_pct_before_costs"] / 100
        wins = returns[returns > 0]
        losses = returns[returns < 0]
        equity = (1 + returns).cumprod()
        drawdown = equity / equity.cummax() - 1
        profit_factor = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else float("nan")
        print(f"Trades: {len(trades)}")
        print(f"Win rate: {(returns > 0).mean() * 100:.2f}%")
        print(f"Mean trade return before costs: {returns.mean() * 100:.2f}%")
        print(f"Profit factor: {profit_factor:.3f}")
        print(f"Trade-sequence max drawdown (not portfolio-weighted): {drawdown.min() * 100:.2f}%")
        print("Caution: excludes fees, slippage, price limits, suspensions and portfolio concurrency.")
    print(f"Saved trades to: {out}")


if __name__ == "__main__":
    main()
