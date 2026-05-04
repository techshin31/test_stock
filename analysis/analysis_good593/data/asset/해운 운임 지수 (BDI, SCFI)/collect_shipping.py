"""
해운 운임 지수 수집 — 백테스팅용 년도별 CSV 생성

수집 방법 (3가지 모드):
  1. --mode bdry     : BDRY ETF (BDI 추종 ETF, yfinance 자동 수집) ← 권장
  2. --mode stooq    : stooq.com API key 사용 (BDI 원지수, CAPTCHA 1회 필요)
  3. --mode convert  : 기존 shipping_index_5yr.csv를 BDI/SCFI로 분리·변환

출력:
  bdry_{year}.csv — BDRY ETF 일봉 (mode: bdry)
  bdi_{year}.csv  — BDI 원지수 일봉 (mode: stooq / convert)
  scfi_{year}.csv — SCFI 일봉 (mode: convert)

  공통 포맷: Date, Open, High, Low, Close, Volume
  - Date:   YYYY-MM-DD 오름차순
  - OHLC:   소수점 2자리
  - Volume: BDRY는 실거래량 / BDI·SCFI는 0 고정

Usage:
    # ── BDRY ETF (자동 수집 권장) ──────────────────────────────────
    python "collect_shipping.py" --mode bdry
    python "collect_shipping.py" --mode bdry --start-year 2022
    python "collect_shipping.py" --mode bdry --start-year 2022 --end-year 2023

    # ── stooq.com BDI 원지수 ───────────────────────────────────────
    # 1) https://stooq.com/q/d/?s=bdi&get_apikey 접속 → CAPTCHA 풀기 → API key 복사
    # 2) 아래 명령 실행
    python "collect_shipping.py" --mode stooq --apikey YOUR_API_KEY
    python "collect_shipping.py" --mode stooq --apikey YOUR_API_KEY --start-year 2022

    # ── 기존 CSV 파일 변환 ─────────────────────────────────────────
    python "collect_shipping.py" --mode convert
    python "collect_shipping.py" --mode convert --start-year 2022 --end-year 2023
"""

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf

OUT_DIR = Path(__file__).parent
SOURCE_FILE = OUT_DIR / "shipping_index_5yr.csv"


# ── 공통 정제 ──────────────────────────────────

def _clean_ohlcv(df: pd.DataFrame, decimal: int = 2, volume_fixed: int | None = None) -> pd.DataFrame:
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    df = df.reset_index()
    date_col = next((c for c in df.columns if str(c).lower() in ("date", "datetime", "index")), None)
    if date_col:
        df = df.rename(columns={date_col: "Date"})

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["Date"])

    for col in ["Open", "High", "Low", "Close"]:
        if col not in df.columns:
            df[col] = df.get("Close", 0)

    df = df[["Date", "Open", "High", "Low", "Close", "Volume"] if "Volume" in df.columns
            else ["Date", "Open", "High", "Low", "Close"]]

    for col in ["Open", "High", "Low", "Close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").round(decimal)

    df["Volume"] = 0 if volume_fixed is not None else df.get("Volume", 0).fillna(0).astype(int)
    if volume_fixed is not None:
        df["Volume"] = volume_fixed

    df = df[["Date", "Open", "High", "Low", "Close", "Volume"]]
    df = df.drop_duplicates(subset="Date", keep="last").sort_values("Date").reset_index(drop=True)
    return df


def _save_by_year(df: pd.DataFrame, prefix: str, start_year: int, end_year: int) -> None:
    df = df[df["Date"].str[:4].astype(int).between(start_year, end_year)]
    if df.empty:
        print(f"  ✘ {prefix}: 기간 내 데이터 없음"); return
    for year, group in df.groupby(df["Date"].str[:4]):
        path = OUT_DIR / f"{prefix}_{year}.csv"
        group.to_csv(path, index=False)
        print(f"  ✔ {path.name}  ({len(group)}행)")


# ── Mode 1: BDRY ETF ──────────────────────────

def collect_bdry(start_year: int, end_year: int) -> None:
    """BDRY (Breakwave Dry Bulk Shipping ETF) — BDI 추종 ETF, yfinance 자동 수집."""
    print("  [BDRY] Breakwave Dry Bulk Shipping ETF (BDI 추종)")
    start = f"{start_year}-01-01"
    end   = f"{end_year + 1}-01-01"

    raw = yf.download("BDRY", start=start, end=end, auto_adjust=True, progress=False)
    if raw.empty:
        print("  ✘ BDRY 데이터 없음"); return

    df = _clean_ohlcv(raw, decimal=2, volume_fixed=None)  # 실거래량 사용
    _save_by_year(df, "bdry", start_year, end_year)


# ── Mode 2: stooq BDI 원지수 ─────────────────

def collect_stooq_bdi(apikey: str, start_year: int, end_year: int) -> None:
    """stooq.com API key로 BDI 원지수 수집."""
    import urllib.request
    from io import StringIO

    print("  [BDI] Baltic Dry Index (stooq.com)")
    d1 = f"{start_year}0101"
    d2 = f"{end_year}1231"
    url = f"https://stooq.com/q/d/l/?s=bdi&d1={d1}&d2={d2}&i=d&apikey={apikey}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            content = r.read().decode()
    except Exception as e:
        print(f"  ✘ stooq 연결 실패: {e}"); return

    if "apikey" in content.lower() or "No data" in content:
        print("  ✘ API key가 유효하지 않거나 데이터 없음")
        print("  → https://stooq.com/q/d/?s=bdi&get_apikey 에서 API key 발급"); return

    try:
        df_raw = pd.read_csv(StringIO(content))
    except Exception as e:
        print(f"  ✘ CSV 파싱 실패: {e}"); return

    # stooq 컬럼: Date, Open, High, Low, Close, Volume
    df_raw.columns = [c.strip().capitalize() for c in df_raw.columns]
    df = _clean_ohlcv(df_raw, decimal=2, volume_fixed=0)
    _save_by_year(df, "bdi", start_year, end_year)


# ── Mode 3: 기존 CSV 변환 ─────────────────────

def _parse_shipping_blocks() -> list[pd.DataFrame]:
    """shipping_index_5yr.csv에서 BDI/SCFI 블록을 분리해 파싱."""
    if not SOURCE_FILE.exists():
        print(f"  ✘ 파일 없음: {SOURCE_FILE.name}")
        print("  → 수동으로 데이터를 수집하고 shipping_index_5yr.csv로 저장하세요.")
        return []

    with open(SOURCE_FILE, encoding="utf-8-sig") as f:
        lines = f.readlines()

    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        first = stripped.split(",")[0].strip().lower()
        if first in ("date", "날짜", "index"):
            if current:
                blocks.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append(current)

    from io import StringIO
    result = []
    for block in blocks:
        try:
            result.append(pd.read_csv(StringIO("".join(block))))
        except Exception:
            pass
    return result


def _normalize_shipping_df(df: pd.DataFrame) -> pd.DataFrame:
    """한국어 컬럼명 포함 파생 컬럼 제거 후 표준화."""
    mapping = {}
    for col in df.columns:
        lower = col.strip().lower()
        if lower in ("date", "날짜"):
            mapping[col] = "Date"
        elif lower in ("open", "시가"):
            mapping[col] = "Open"
        elif lower in ("high", "고가"):
            mapping[col] = "High"
        elif lower in ("low", "저가"):
            mapping[col] = "Low"
        elif lower in ("close", "종가", "price"):
            mapping[col] = "Close"
    df = df[[c for c in df.columns if c in mapping]].rename(columns=mapping)
    for col in ["Open", "High", "Low"]:
        if col not in df.columns:
            df[col] = df.get("Close", 0)
    return df


def convert_existing(start_year: int, end_year: int) -> None:
    blocks = _parse_shipping_blocks()
    if not blocks:
        return

    labels = ["bdi", "scfi"]
    for i, raw in enumerate(blocks[:2]):
        label = labels[i]
        normalized = _normalize_shipping_df(raw)
        if normalized.empty or "Date" not in normalized.columns:
            print(f"  ✘ {label}: Date 컬럼 없음"); continue
        df = _clean_ohlcv(normalized, decimal=2, volume_fixed=0)
        print(f"\n  [{label.upper()}]")
        _save_by_year(df, label, start_year, end_year)


# ── CLI ───────────────────────────────────────

def parse_args() -> argparse.Namespace:
    today = date.today()
    p = argparse.ArgumentParser(
        description="BDI / SCFI / BDRY 해운 지수 — 년도별 CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
모드 선택:
  bdry     BDRY ETF 자동 수집 (권장)
  stooq    stooq.com API key로 BDI 원지수 수집 (--apikey 필요)
  convert  기존 shipping_index_5yr.csv → bdi/scfi 분리 변환
        """,
    )
    p.add_argument("--mode", choices=["bdry", "stooq", "convert"], default="bdry")
    p.add_argument("--start-year", type=int, default=2021)
    p.add_argument("--end-year",   type=int, default=today.year)
    p.add_argument("--apikey", type=str, default=None,
                   help="stooq.com API key (--mode stooq 시 필수)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.start_year > args.end_year:
        print("오류: start-year > end-year"); sys.exit(1)

    print(f"[해운 운임] {args.start_year} ~ {args.end_year}  (mode: {args.mode})")

    if args.mode == "bdry":
        collect_bdry(args.start_year, args.end_year)

    elif args.mode == "stooq":
        if not args.apikey:
            print("오류: --mode stooq 는 --apikey 가 필요합니다.")
            print("  1) https://stooq.com/q/d/?s=bdi&get_apikey 접속")
            print("  2) CAPTCHA 풀기 → 링크에서 apikey 값 복사")
            print("  3) python collect_shipping.py --mode stooq --apikey YOUR_KEY")
            sys.exit(1)
        collect_stooq_bdi(args.apikey, args.start_year, args.end_year)

    elif args.mode == "convert":
        convert_existing(args.start_year, args.end_year)

    print("완료")


if __name__ == "__main__":
    main()
