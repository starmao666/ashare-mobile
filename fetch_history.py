"""Download real A-share daily bars with AkShare for local research.

Example:
  python fetch_history.py --codes 000001,600000,000858 --start 20230101 --end 20261028 --out data/daily_bars.csv
  python fetch_history.py --codes-file codes.txt --start 20230101 --end 20261028 --out data/daily_bars.csv

This script contacts a third-party public-data interface at runtime. Availability,
rate limits, field names and adjustment behavior can change. It never generates
synthetic/fallback prices. Verify the saved data before using it.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time
import pandas as pd
import baostock as bs

try:
    import akshare as ak
except ImportError as exc:
    raise SystemExit("AkShare not installed. Run: pip install -r requirements.txt") from exc


COLUMN_MAP = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交额": "amount",
    "换手率": "turnover",
    "涨跌幅": "pct_chg",
    "成交量": "volume",
}


def normalize_code(code: str) -> str:
    code = code.strip()
    if code.startswith(("sh", "sz", "bj")):
        code = code[2:]
    if not (len(code) == 6 and code.isdigit()):
        raise ValueError(f"Invalid A-share code: {code!r}")
    return code


def fetch_one(code: str, start: str, end: str, adjust: str) -> pd.DataFrame:
    """Try AkShare/Eastmoney first, then Baostock as a real-data fallback."""
    errors = []
    for attempt in range(3):
        try:
            raw = ak.stock_zh_a_hist(
                symbol=code, period="daily", start_date=start, end_date=end, adjust=adjust
            )
            if raw is None or raw.empty:
                raise ValueError("AkShare returned no rows")
            missing = set(COLUMN_MAP) - set(raw.columns)
            if missing:
                raise ValueError(f"provider columns changed; missing {sorted(missing)}")
            df = raw.rename(columns=COLUMN_MAP)
            return normalize_bars(df, code)
        except Exception as exc:
            errors.append(f"AkShare attempt {attempt + 1}: {exc}")
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))

    # Baostock uses its own public market-data service; no token is required.
    try:
        lg = bs.login()
        if getattr(lg, "error_code", "0") != "0":
            raise RuntimeError(f"Baostock login failed: {getattr(lg, 'error_msg', '')}")
        prefix = "sh." if code.startswith("6") else ("bj." if code.startswith(("4", "8", "9")) else "sz.")
        adjustflag = {"qfq": "2", "hfq": "1", "": "3"}[adjust]
        rs = bs.query_history_k_data_plus(
            prefix + code,
            "date,open,high,low,close,volume,amount,turn,pctChg",
            start_date=pd.to_datetime(start).strftime("%Y-%m-%d"),
            end_date=pd.to_datetime(end).strftime("%Y-%m-%d"),
            frequency="d",
            adjustflag=adjustflag,
        )
        if getattr(rs, "error_code", "0") != "0":
            raise RuntimeError(f"Baostock query failed: {getattr(rs, 'error_msg', '')}")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        bs.logout()
        if not rows:
            raise ValueError("Baostock returned no rows")
        df = pd.DataFrame(rows, columns=rs.fields)
        df = df.rename(columns={
            "date": "date", "open": "open", "high": "high", "low": "low",
            "close": "close", "volume": "volume", "amount": "amount",
            "turn": "turnover", "pctChg": "pct_chg",
        })
        df["code"] = code
        return normalize_bars(df, code)
    except Exception as exc:
        try:
            bs.logout()
        except Exception:
            pass
        errors.append(f"Baostock fallback: {exc}")
        raise RuntimeError(" | ".join(errors)) from exc


def normalize_bars(df: pd.DataFrame, code: str) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["code"] = code
    for col in ("open", "high", "low", "close", "amount", "turnover", "pct_chg", "volume"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close"])
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    df = df[df["high"] >= df[["open", "low", "close"]].max(axis=1)]
    df = df[df["low"] <= df[["open", "high", "close"]].min(axis=1)]
    return df.sort_values("date")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch real A-share daily bars (no synthetic data)")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--codes", help="Comma-separated stock codes, e.g. 000001,600000")
    src.add_argument("--codes-file", help="Text file with one code per line")
    parser.add_argument("--start", required=True, help="Start date YYYYMMDD")
    parser.add_argument("--end", required=True, help="End date YYYYMMDD")
    parser.add_argument("--adjust", choices=["", "qfq", "hfq"], default="qfq",
                        help="Price adjustment: qfq=前复权 (default), hfq=后复权, empty=不复权")
    parser.add_argument("--out", default="data/daily_bars.csv", help="Output CSV path")
    parser.add_argument("--pause", type=float, default=0.5, help="Pause between requests in seconds")
    args = parser.parse_args()

    for value in (args.start, args.end):
        if len(value) != 8 or not value.isdigit():
            parser.error("Dates must use YYYYMMDD")
    if args.start > args.end:
        parser.error("--start must be earlier than or equal to --end")
    if args.pause < 0:
        parser.error("--pause must be >= 0")

    if args.codes_file:
        codes = [line.strip() for line in Path(args.codes_file).read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.strip().startswith("#")]
    else:
        codes = args.codes.split(",")
    try:
        codes = list(dict.fromkeys(normalize_code(code) for code in codes))
    except ValueError as exc:
        parser.error(str(exc))
    if not codes:
        parser.error("No stock codes supplied")

    frames, failures = [], []
    for idx, code in enumerate(codes, 1):
        try:
            frame = fetch_one(code, args.start, args.end, args.adjust)
            if frame.empty:
                print(f"[{idx}/{len(codes)}] {code}: no rows returned")
            else:
                frames.append(frame)
                print(f"[{idx}/{len(codes)}] {code}: {len(frame)} rows")
        except Exception as exc:
            failures.append((code, str(exc)))
            print(f"[{idx}/{len(codes)}] {code}: FAILED: {exc}", file=sys.stderr)
        if idx < len(codes):
            time.sleep(args.pause)

    if not frames:
        raise SystemExit("No valid history downloaded; output was not created.")
    result = pd.concat(frames, ignore_index=True).sort_values(["code", "date"])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"Saved {len(result)} rows for {result['code'].nunique()} stocks to {out}")
    print(f"Date coverage: {result['date'].min().date()} through {result['date'].max().date()}")
    print(f"Adjustment: {args.adjust or 'none'}")
    if failures:
        print(f"Warning: {len(failures)} code(s) failed. Review logs; partial output only.")
        for code, message in failures:
            print(f"  {code}: {message}")


if __name__ == "__main__":
    main()
