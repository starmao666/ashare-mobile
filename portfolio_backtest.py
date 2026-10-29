"""Portfolio-level research backtest for CSV daily bars.

This improves on the single-ticker baseline by enforcing a shared cash balance
and per-trade risk budget. Signals are evaluated after each date's close and
entries occur at the next available date's open. Daily OHLC bars cannot reveal
intraday event ordering, so stop-loss is assumed first when stop and target are
both touched. This is a research approximation, not a broker-grade simulator.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

REQUIRED = {"date", "code", "open", "high", "low", "close"}


def prepare(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {', '.join(sorted(missing))}")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["code"] = df["code"].astype(str).str.zfill(6)
    df = df.dropna(subset=list(REQUIRED))
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    df = df[df["high"] >= df[["open", "low", "close"]].max(axis=1)]
    df = df[df["low"] <= df[["open", "high", "close"]].min(axis=1)]
    df = df.drop_duplicates(["date", "code"]).sort_values(["date", "code"])
    return df.reset_index(drop=True)


def build_signals(df: pd.DataFrame, strategy: str = "baseline") -> pd.DataFrame:
    parts = []
    for code, group in df.groupby("code", sort=False):
        g = group.sort_values("date").copy()
        g["ma20"] = g["close"].rolling(20, min_periods=20).mean()
        g["day_return"] = g["close"].pct_change()
        baseline_signal = (g["close"] > g["ma20"]) & g["day_return"].between(-0.03, 0.02)
        if strategy == "baseline":
            g["signal"] = baseline_signal
        elif strategy == "pullback":
            # Research proxy: rising MA20, prior 5-session gain >= 5%,
            # close near MA20, and a modest red/flat day.
            g["ma20_rising"] = g["ma20"] > g["ma20"].shift(5)
            g["prior_5d_gain"] = g["close"].shift(1) / g["close"].shift(6) - 1
            near_ma = g["close"].between(g["ma20"] * 0.97, g["ma20"] * 1.03)
            g["signal"] = (
                g["ma20_rising"] & (g["prior_5d_gain"] >= 0.05) & near_ma
                & g["day_return"].between(-0.03, 0.01)
            )
        elif strategy == "trend_pullback":
            # Trend/momentum framework: only past/current data; enter after
            # positive medium-term momentum and a modest pullback in an uptrend.
            g["ma60"] = g["close"].rolling(60, min_periods=60).mean()
            g["momentum20"] = g["close"].shift(1) / g["close"].shift(21) - 1
            trend = (g["close"] > g["ma20"]) & (g["ma20"] > g["ma60"])
            g["signal"] = trend & (g["momentum20"] > 0) & g["day_return"].between(-0.035, 0.005)
        else:
            raise ValueError("strategy must be 'baseline', 'pullback', or 'trend_pullback'")
        parts.append(g)
    if not parts:
        result = df.copy()
        result["ma20"] = pd.Series(dtype="float64")
        result["day_return"] = pd.Series(dtype="float64")
        result["signal"] = pd.Series(dtype="bool")
        return result
    return pd.concat(parts, ignore_index=True).sort_values(["date", "code"])


def backtest_portfolio(df: pd.DataFrame, initial_cash: float = 1_000_000,
                       risk_fraction: float = 0.0075, stop_fraction: float = 0.05,
                       target_fraction: float = 0.08, max_hold: int = 5,
                       max_positions: int = 5, fee_rate: float = 0.0003,
                       strategy: str = "baseline") -> tuple[pd.DataFrame, pd.DataFrame]:
    if initial_cash <= 0 or not (0 < risk_fraction < 1) or not (0 < stop_fraction < 1):
        raise ValueError("capital/risk/stop parameters are invalid")
    if target_fraction <= 0 or max_hold < 1 or max_positions < 1 or fee_rate < 0:
        raise ValueError("target/holding/position/fee parameters are invalid")

    data = build_signals(df, strategy=strategy)
    dates = sorted(data["date"].dropna().unique())
    by_date = {d: frame.set_index("code", drop=False) for d, frame in data.groupby("date")}
    cash = float(initial_cash)
    positions = {}
    trades, equity_rows = [], []
    pending = {}
    for day_index, date in enumerate(dates):
        todays = by_date.get(date)
        if todays is None:
            continue

        # Estimate current equity using today's close for existing holdings before sizing new entries.
        market_value_before_entries = 0.0
        for held_code, held_pos in positions.items():
            if held_code in todays.index:
                held_row = todays.loc[held_code]
                if isinstance(held_row, pd.DataFrame):
                    held_row = held_row.iloc[0]
                mark = float(held_row["close"])
            else:
                mark = held_pos["entry_price"]
            market_value_before_entries += held_pos["shares"] * mark
        equity_value = cash + market_value_before_entries

        # Entries are queued from the previous session close, never same-close fills.
        for code, signal_date in list(pending.items()):
            if code in positions or len(positions) >= max_positions or code not in todays.index:
                continue
            row = todays.loc[code]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            entry = float(row["open"])
            if entry <= 0:
                continue
            risk_cash = max(equity_value, 0.0) * risk_fraction
            risk_per_share = entry * stop_fraction
            shares_by_risk = int(risk_cash / risk_per_share / 100) * 100
            shares_by_cash = int(cash / (entry * (1 + fee_rate)) / 100) * 100
            shares = min(shares_by_risk, shares_by_cash)
            if shares < 100:
                continue
            cost = shares * entry
            fee = cost * fee_rate
            cash -= cost + fee
            positions[code] = {
                "entry_date": pd.Timestamp(date), "entry_price": entry, "shares": shares,
                "stop": entry * (1 - stop_fraction), "target": entry * (1 + target_fraction),
                "bars_held": 0, "entry_fee": fee, "signal_date": pd.Timestamp(signal_date).date().isoformat(),
            }
        pending = {}

        # Exit logic uses today's high/low and conservative stop-first tie break.
        for code in list(positions):
            if code not in todays.index:
                # No quote today: do not invent an exit price; keep position marked at last close.
                continue
            row = todays.loc[code]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            pos = positions[code]
            pos["bars_held"] += 1
            low, high = float(row["low"]), float(row["high"])
            close = float(row["close"])
            reason, price = None, close
            if low <= pos["stop"]:
                reason, price = "stop_loss", pos["stop"]
            elif high >= pos["target"]:
                reason, price = "take_profit", pos["target"]
            elif pos["bars_held"] >= max_hold:
                reason, price = "max_hold", close
            if reason:
                proceeds = pos["shares"] * price
                exit_fee = proceeds * fee_rate
                cash += proceeds - exit_fee
                pnl = (price - pos["entry_price"]) * pos["shares"] - pos["entry_fee"] - exit_fee
                trades.append({
                    "code": code, "signal_date": pos.get("signal_date"),
                    "entry_date": pos["entry_date"].date().isoformat(),
                    "exit_date": pd.Timestamp(date).date().isoformat(),
                    "entry_price": pos["entry_price"], "exit_price": price,
                    "shares": pos["shares"], "exit_reason": reason,
                    "pnl_after_modeled_fees": round(pnl, 2),
                    "return_pct_on_entry_value": round((price / pos["entry_price"] - 1) * 100, 4),
                    "holding_bars": pos["bars_held"],
                })
                del positions[code]

        # Mark-to-market equity at close; missing quote uses entry price conservatively.
        market_value = 0.0
        for code, pos in positions.items():
            if code in todays.index:
                row = todays.loc[code]
                if isinstance(row, pd.DataFrame):
                    row = row.iloc[0]
                mark = float(row["close"])
            else:
                mark = pos["entry_price"]
            market_value += pos["shares"] * mark
        equity = cash + market_value
        equity_rows.append({"date": pd.Timestamp(date).date().isoformat(), "cash": round(cash, 2),
                            "market_value": round(market_value, 2), "equity": round(equity, 2)})

        # Queue today's after-close signals for next date.
        if day_index < len(dates) - 1:
            for code, row in todays.iterrows():
                if code not in positions and bool(row["signal"]):
                    pending[code] = pd.Timestamp(date)

    return pd.DataFrame(trades), pd.DataFrame(equity_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Portfolio-level research backtest")
    parser.add_argument("csv")
    parser.add_argument("--capital", type=float, default=1_000_000)
    parser.add_argument("--risk", type=float, default=0.0075)
    parser.add_argument("--stop", type=float, default=0.05)
    parser.add_argument("--target", type=float, default=0.08)
    parser.add_argument("--max-hold", type=int, default=5)
    parser.add_argument("--max-positions", type=int, default=5)
    parser.add_argument("--fee", type=float, default=0.0003, help="Per-side fee approximation")
    parser.add_argument("--strategy", choices=["baseline", "pullback", "trend_pullback"], default="baseline",
                        help="baseline, first-pullback proxy, or trend-confirmed pullback")
    parser.add_argument("--out", default="portfolio_trades.csv")
    parser.add_argument("--equity-out", default="portfolio_equity.csv")
    args = parser.parse_args()
    df = prepare(args.csv)
    if df.empty:
        raise SystemExit("No valid history rows; no backtest run.")
    trades, equity = backtest_portfolio(df, args.capital, args.risk, args.stop,
                                        args.target, args.max_hold, args.max_positions, args.fee, args.strategy)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.equity_out).parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(args.out, index=False, encoding="utf-8-sig")
    equity.to_csv(args.equity_out, index=False, encoding="utf-8-sig")
    print(f"Valid bars: {len(df)} | stocks: {df['code'].nunique()}")
    print(f"Trades: {len(trades)}")
    if not equity.empty:
        eq = equity["equity"]
        peak = eq.cummax()
        dd = eq / peak - 1
        print(f"Final equity: {eq.iloc[-1]:.2f} (initial {args.capital:.2f})")
        print(f"Max equity drawdown: {dd.min() * 100:.2f}%")
    if not trades.empty:
        print(f"Win rate: {(trades['pnl_after_modeled_fees'] > 0).mean() * 100:.2f}%")
    print("Research approximation only: fees are simplified; slippage, price limits, taxes, "
          "suspensions and corporate-action execution are not fully modeled.")


if __name__ == "__main__":
    main()
