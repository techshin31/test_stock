"""
달러 인덱스 선물(DX=F) 가격 데이터 수집 — 백테스팅용 년도별 CSV 생성

출력: dxy_{year}.csv (Date, Open, High, Low, Close, Volume)
  - Date:  YYYY-MM-DD 오름차순
  - OHLC:  소수점 4자리 (단위: 지수 포인트)
  - Volume: 정수 (선물 거래량, 없으면 0)

※ 신호 생성 전용 — 달러 강/약세로 금·원자재 매매 신호 생성
   달러 강세(MA 상향) → 금·구리 축소 / 달러 약세(MA 하향) → 실물자산 확대

Usage:
    python "collect_dxy.py"
    python "collect_dxy.py" --start-year 2022
    python "collect_dxy.py" --start-year 2023 --end-year 2023
"""

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf

TICKER = "DX-Y.NYB"  # ICE Dollar Index (DX=F 는 야후파이낸스에서 지원 종료)
DECIMAL = 4
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
    df["Volume"] = df["Volume"].fillna(0).astype(int)

    return df


def save_by_year(df: pd.DataFrame) -> None:
    for year, group in df.groupby(df["Date"].str[:4]):
        path = OUT_DIR / f"dxy_{year}.csv"
        group.to_csv(path, index=False)
        print(f"  ✔ {path.name}  ({len(group)}행)")


def parse_args() -> argparse.Namespace:
    today = date.today()
    p = argparse.ArgumentParser(description="달러 인덱스(DX=F) 수집 — 년도별 CSV")
    p.add_argument("--start-year", type=int, default=2021)
    p.add_argument("--end-year", type=int, default=today.year)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.start_year > args.end_year:
        print(f"오류: start-year > end-year"); sys.exit(1)

    start = f"{args.start_year}-01-01"
    end   = f"{args.end_year + 1}-01-01"

    print(f"[달러 DX-Y.NYB] {args.start_year} ~ {args.end_year}")
    df = download(start, end)
    save_by_year(df)
    print("완료")


if __name__ == "__main__":
    main()
