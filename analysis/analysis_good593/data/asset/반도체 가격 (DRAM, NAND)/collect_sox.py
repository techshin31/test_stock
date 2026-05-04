"""
필라델피아 반도체 지수(^SOX) 데이터 수집 — 백테스팅용 년도별 CSV 생성

출력: sox_{year}.csv (Date, Open, High, Low, Close, Volume)
  - Date:   YYYY-MM-DD 오름차순
  - OHLC:   소수점 2자리 (단위: 지수 포인트)
  - Volume: 0 고정 (지수 — 실거래량 없음)

※ 신호 생성 전용 — SOX + 구리 동반 상승 시 IT·소재 섹터 편입 신호

Usage:
    python "collect_sox.py"
    python "collect_sox.py" --start-year 2022
    python "collect_sox.py" --start-year 2023 --end-year 2023
"""

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf

TICKER = "^SOX"
DECIMAL = 2
OUT_DIR = Path(__file__).parent


def download(start: str, end: str) -> pd.DataFrame:
    raw = yf.download(TICKER, start=start, end=end, auto_adjust=True, progress=False)
    if raw.empty:
        print(f"  ✘ 데이터 없음 ({start} ~ {end})")
        sys.exit(1)

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] for c in raw.columns]

    df = raw.reset_index().rename(columns={"Datetime": "Date", "index": "Date"})
    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
    df = df[["Date", "Open", "High", "Low", "Close", "Volume"]]
    df = df.drop_duplicates(subset="Date", keep="last").sort_values("Date").reset_index(drop=True)

    for col in ["Open", "High", "Low", "Close"]:
        df[col] = df[col].round(DECIMAL)
    df["Volume"] = 0  # 지수 — 거래량 없음

    return df


def save_by_year(df: pd.DataFrame) -> None:
    for year, group in df.groupby(df["Date"].str[:4]):
        path = OUT_DIR / f"sox_{year}.csv"
        group.to_csv(path, index=False)
        print(f"  ✔ {path.name}  ({len(group)}행)")


def parse_args() -> argparse.Namespace:
    today = date.today()
    p = argparse.ArgumentParser(description="필라델피아 반도체 지수(^SOX) 수집 — 년도별 CSV")
    p.add_argument("--start-year", type=int, default=2021)
    p.add_argument("--end-year", type=int, default=today.year)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.start_year > args.end_year:
        print(f"오류: start-year > end-year"); sys.exit(1)

    start = f"{args.start_year}-01-01"
    end   = f"{args.end_year + 1}-01-01"

    print(f"[SOX ^SOX] {args.start_year} ~ {args.end_year}")
    df = download(start, end)
    save_by_year(df)
    print("완료")


if __name__ == "__main__":
    main()
