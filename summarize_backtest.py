"""Generate reproducible strategy metrics from backtest CSV outputs."""
import argparse
from pathlib import Path
import pandas as pd


def metrics(trades: pd.DataFrame, equity: pd.DataFrame, label: str) -> dict:
    equity = equity.copy()
    equity["date"] = pd.to_datetime(equity["date"], errors="coerce")
    equity["equity"] = pd.to_numeric(equity["equity"], errors="coerce")
    equity = equity.dropna(subset=["date", "equity"]).sort_values("date")
    pnl = pd.to_numeric(trades.get("pnl_after_modeled_fees", pd.Series(dtype=float)), errors="coerce").dropna()
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    if equity.empty:
        start = end = total_return = cagr = max_drawdown = float("nan")
    else:
        start, end = float(equity["equity"].iloc[0]), float(equity["equity"].iloc[-1])
        total_return = end / start - 1 if start else float("nan")
        days = max((equity["date"].iloc[-1] - equity["date"].iloc[0]).days, 1)
        cagr = (end / start) ** (365.25 / days) - 1 if start > 0 and end > 0 else float("nan")
        max_drawdown = float((equity["equity"] / equity["equity"].cummax() - 1).min())
    return {
        "strategy_period": label,
        "start_date": equity["date"].iloc[0].date().isoformat() if not equity.empty else "",
        "end_date": equity["date"].iloc[-1].date().isoformat() if not equity.empty else "",
        "start_equity": round(start, 2) if pd.notna(start) else "",
        "end_equity": round(end, 2) if pd.notna(end) else "",
        "total_return_pct": round(total_return * 100, 4) if pd.notna(total_return) else "",
        "cagr_pct": round(cagr * 100, 4) if pd.notna(cagr) else "",
        "max_drawdown_pct": round(max_drawdown * 100, 4) if pd.notna(max_drawdown) else "",
        "closed_trades": int(len(pnl)),
        "win_rate_pct": round((pnl > 0).mean() * 100, 4) if len(pnl) else "",
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 4) if len(losses) and losses.sum() < 0 else "",
        "net_closed_trade_pnl": round(float(pnl.sum()), 2) if len(pnl) else 0,
        "avg_trade_pnl": round(float(pnl.mean()), 2) if len(pnl) else "",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--out", default="data/strategy_summary.csv")
    args = parser.parse_args()
    root = Path(args.data_dir)
    rows = []
    for strategy in ("baseline", "pullback"):
        trades_path = root / f"{strategy}_trades.csv"
        equity_path = root / f"{strategy}_equity.csv"
        if not trades_path.exists() or not equity_path.exists():
            raise FileNotFoundError(f"Missing result CSV for {strategy}")
        trades = pd.read_csv(trades_path)
        equity = pd.read_csv(equity_path)
        rows.append(metrics(trades, equity, f"{strategy}:full"))
        # Time-based holdout: 2023-2024 is exploratory; 2025 onward is the
        # later, unseen period for a first robustness check.
        for label, start, end in (
            ("exploratory_2023_2024", "2023-01-01", "2024-12-31"),
            ("holdout_2025_plus", "2025-01-01", "2100-01-01"),
        ):
            mask = (pd.to_datetime(equity["date"]) >= start) & (pd.to_datetime(equity["date"]) <= end)
            period_equity = equity.loc[mask].copy()
            if not period_equity.empty:
                lo, hi = period_equity["date"].iloc[0], period_equity["date"].iloc[-1]
                period_trades = trades[
                    (pd.to_datetime(trades["exit_date"]) >= pd.Timestamp(start))
                    & (pd.to_datetime(trades["exit_date"]) <= pd.Timestamp(end))
                ]
                rows.append(metrics(period_trades, period_equity, f"{strategy}:{label}"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
