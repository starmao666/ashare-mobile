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
    raw = ak.stock_zh_a_hist(
        symbol=code, period="daily", start_date=start, end_date=end, adjust=adjust
    )
    if raw is None or raw.empty:
        return pd.DataFrame()
    missing = set(COLUMN_MAP) - set(raw.columns)
    if missing:
        raise ValueError(f"{code}: provider columns changed; missing {sorted(missing)}")
    df = raw.rename(columns=COLUMN_MAP)
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
