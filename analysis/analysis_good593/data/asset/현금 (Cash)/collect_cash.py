"""
현금(Cash) 관련 지표 수집 — 백테스팅용 년도별 CSV 생성

수집 대상:
  1. TNX (미국 10년 국채금리, ^TNX)
     → tnx_{year}.csv (Date, Open, High, Low, Close, Volume)
       - OHLC: 소수점 4자리 (단위: %)
       - Volume: 0 고정 (금리 지수)

  2. CPI (미국 소비자물가지수, FRED CPIAUCSL)
     → cpi_{year}.csv (Date, Close, CPI_YoY)
       - 월봉 → 일봉 forward-fill 확장
       - 발표 지연 15일 적용 (룩어헤드 바이어스 방지)
       - CPI_YoY: YoY 변화율(%), 초기 NaN → 0.0

Usage:
    python "collect_cash.py"
    python "collect_cash.py" --start-year 2022
    python "collect_cash.py" --start-year 2023 --end-year 2023
    python "collect_cash.py" --only tnx   # TNX만
    python "collect_cash.py" --only cpi   # CPI만
"""

import argparse
import sys
from datetime import date
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

OUT_DIR = Path(__file__).parent


# ── TNX ───────────────────────────────────────

def collect_tnx(start: str, end: str) -> None:
    print(f"  [TNX ^TNX] 미국 10년 국채금리")
    raw = yf.download("^TNX", start=start, end=end, auto_adjust=True, progress=False)
    if raw.empty:
        print(f"  ✘ TNX 데이터 없음"); return

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] for c in raw.columns]

    df = raw.reset_index().rename(columns={"Datetime": "Date", "index": "Date"})
    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
    df = df[["Date", "Open", "High", "Low", "Close", "Volume"]]
    df = df.drop_duplicates(subset="Date", keep="last").sort_values("Date").reset_index(drop=True)

    for col in ["Open", "High", "Low", "Close"]:
        df[col] = df[col].round(4)
    df["Volume"] = 0  # 금리 지수 — 거래량 없음

    for year, group in df.groupby(df["Date"].str[:4]):
        path = OUT_DIR / f"tnx_{year}.csv"
        group.to_csv(path, index=False)
        print(f"  ✔ {path.name}  ({len(group)}행)")


# ── CPI ───────────────────────────────────────

def collect_cpi(start: str, end: str) -> None:
    print(f"  [CPI FRED:CPIAUCSL] 미국 소비자물가지수")

    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ✘ FRED 연결 실패: {e}"); return

    monthly = pd.read_csv(StringIO(resp.text))
    monthly.columns = ["Date", "Close"]
    monthly["Date"] = pd.to_datetime(monthly["Date"])
    monthly["Close"] = pd.to_numeric(monthly["Close"], errors="coerce")
    monthly = monthly.dropna(subset=["Close"]).sort_values("Date").reset_index(drop=True)

    # YoY 계산 (발표 지연 적용 전 원본 날짜 기준)
    monthly["CPI_YoY"] = monthly["Close"].pct_change(12).mul(100).round(2).fillna(0.0)

    # 발표 지연 15일 적용 (룩어헤드 바이어스 방지)
    # 예) 2021-04-01 CPI → 2021-04-16부터 사용 가능
    monthly["Date"] = monthly["Date"] + pd.Timedelta(days=15)
    monthly = monthly.set_index("Date")

    start_dt = pd.to_datetime(start)
    end_dt   = pd.to_datetime(end)

    # daily 인덱스를 monthly 최솟값부터 생성해야 ffill이 첫 날짜부터 채워짐
    full_start = min(start_dt, monthly.index.min())
    full_idx   = pd.date_range(start=full_start, end=end_dt, freq="B")

    daily = monthly.reindex(full_idx).ffill().reset_index()
    daily.columns = ["Date", "Close", "CPI_YoY"]
    daily["Date"] = daily["Date"].dt.strftime("%Y-%m-%d")
    daily["Close"] = daily["Close"].round(3)
    daily["CPI_YoY"] = daily["CPI_YoY"].fillna(0.0)

    # 요청 기간으로 필터
    daily = daily[(daily["Date"] >= start) & (daily["Date"] <= end)].reset_index(drop=True)
    if daily.empty:
        print(f"  ✘ 기간 내 CPI 데이터 없음"); return

    for year, group in daily.groupby(daily["Date"].str[:4]):
        path = OUT_DIR / f"cpi_{year}.csv"
        group.to_csv(path, index=False)
        print(f"  ✔ {path.name}  ({len(group)}행)")


# ── CLI ───────────────────────────────────────

def parse_args() -> argparse.Namespace:
    today = date.today()
    p = argparse.ArgumentParser(description="TNX / CPI 수집 — 년도별 CSV")
    p.add_argument("--start-year", type=int, default=2021)
    p.add_argument("--end-year",   type=int, default=today.year)
    p.add_argument("--only", choices=["tnx", "cpi"], default=None,
                   help="지정 시 해당 자산만 수집")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.start_year > args.end_year:
        print("오류: start-year > end-year"); sys.exit(1)

    start = f"{args.start_year}-01-01"
    end   = f"{args.end_year}-12-31"         # CPI는 year 마지막 날까지
    end_yf = f"{args.end_year + 1}-01-01"   # yfinance end exclusive

    print(f"[현금 지표] {args.start_year} ~ {args.end_year}")

    if args.only in (None, "tnx"):
        collect_tnx(start, end_yf)
    if args.only in (None, "cpi"):
        collect_cpi(start, end)

    print("완료")


if __name__ == "__main__":
    main()
