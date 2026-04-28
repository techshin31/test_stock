from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timedelta
import os
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
COMPANY_PATH = ROOT / "etl" / "company" / "data" / "dart_company_2026.csv"
WICS_PATH = ROOT / "etl" / "wics" / "data" / "csv" / "wics_company_2026.csv"
OUTPUT_DIR = ROOT / "etl" / "stock" / "data"
MPLCONFIG_DIR = OUTPUT_DIR / ".mplconfig"


def load_company_codes() -> pd.DataFrame:
    df = pd.read_csv(COMPANY_PATH, dtype=str)
    df["CMP_CD"] = df["CMP_CD"].str.zfill(6)
    return df.loc[:, ["CMP_CD", "CMP_KOR", "DART_CD"]].rename(
        columns={
            "CMP_CD": "stock_code",
            "CMP_KOR": "company_name",
            "DART_CD": "corp_code",
        }
    )


def import_pykrx_stock():
    MPLCONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(MPLCONFIG_DIR))
    try:
        from pykrx import stock
    except ImportError as exc:
        raise RuntimeError(
            "pykrx가 설치되어 있지 않습니다. "
            "먼저 `pip install -r etl\\stock\\requirements.txt`를 실행해 주세요."
        ) from exc
    return stock


def normalize_snapshot_frame(df: pd.DataFrame, *, source: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["stock_code"])

    frame = df.reset_index().copy()

    if "티커" in frame.columns:
        frame = frame.rename(columns={"티커": "stock_code"})
    elif frame.columns[0] != "stock_code":
        frame = frame.rename(columns={frame.columns[0]: "stock_code"})

    rename_map = {
        "종가": "close_price",
        "시가": "open_price",
        "고가": "high_price",
        "저가": "low_price",
        "거래량": "volume",
        "거래대금": "trading_value",
        "등락률": "return_pct",
        "시가총액": "market_cap",
        "상장주식수": "shares_outstanding",
        "BPS": "bps",
        "PER": "per",
        "PBR": "pbr",
        "EPS": "eps",
        "DIV": "dividend_yield",
        "DPS": "dps",
    }
    frame = frame.rename(columns=rename_map)
    frame["stock_code"] = frame["stock_code"].astype(str).str.zfill(6)
    frame["snapshot_source"] = source
    return frame


def resolve_latest_trading_date(stock_api, requested_date: str, *, market: str = "KOSPI") -> str:
    end = datetime.strptime(requested_date, "%Y%m%d")
    for delta in range(14):
        candidate = (end - timedelta(days=delta)).strftime("%Y%m%d")
        probe = stock_api.get_market_ohlcv_by_ticker(candidate, market=market)
        if not probe.empty:
            return candidate
    raise RuntimeError(f"{requested_date} 기준 최근 14일 내 거래일 데이터를 찾지 못했습니다.")


def fetch_market_snapshot(snapshot_date: str, *, market: str = "KOSPI") -> pd.DataFrame:
    stock_api = import_pykrx_stock()
    actual_date = resolve_latest_trading_date(stock_api, snapshot_date, market=market)

    ohlcv = normalize_snapshot_frame(
        stock_api.get_market_ohlcv_by_ticker(actual_date, market=market),
        source="ohlcv",
    )
    market_cap = normalize_snapshot_frame(
        stock_api.get_market_cap_by_ticker(actual_date, market=market),
        source="market_cap",
    )
    fundamentals = normalize_snapshot_frame(
        stock_api.get_market_fundamental_by_ticker(actual_date, market=market),
        source="fundamental",
    )

    merged = ohlcv.merge(
        market_cap.drop(columns=["snapshot_source"], errors="ignore"),
        on="stock_code",
        how="outer",
        suffixes=("", "_cap"),
    )
    merged = merged.merge(
        fundamentals.drop(columns=["snapshot_source"], errors="ignore"),
        on="stock_code",
        how="left",
    )

    companies = load_company_codes()
    merged = companies.merge(merged, on="stock_code", how="left")
    merged["snapshot_date"] = actual_date
    merged["market"] = market
    merged["data_provider"] = "pykrx"
    return merged.sort_values(["company_name", "stock_code"], na_position="last")


def fetch_market_snapshot_from_wics_local() -> pd.DataFrame:
    wics = pd.read_csv(WICS_PATH, dtype={"CMP_CD": str, "DATE": str})
    wics["CMP_CD"] = wics["CMP_CD"].str.zfill(6)
    wics = wics.sort_values(["CMP_CD", "DATE"], ascending=[True, False]).drop_duplicates(subset=["CMP_CD"], keep="first")

    companies = load_company_codes()
    snapshot = companies.merge(
        wics.loc[
            :,
            [
                "CMP_CD",
                "DATE",
                "MKT_VAL",
                "INFO_TRD_AMT",
                "APT_SHR_CNT",
                "IDX_CD",
                "IDX_NM_KOR",
                "SEC_CD",
                "SEC_NM_KOR",
            ],
        ].rename(
            columns={
                "CMP_CD": "stock_code",
                "DATE": "snapshot_date",
                "MKT_VAL": "market_cap_wics_raw",
                "INFO_TRD_AMT": "trading_value_wics_raw",
                "APT_SHR_CNT": "shares_outstanding",
                "IDX_CD": "wics_index_code",
                "IDX_NM_KOR": "wics_index_name",
                "SEC_CD": "wics_large_code",
                "SEC_NM_KOR": "wics_large_name",
            }
        ),
        on="stock_code",
        how="left",
    )
    snapshot["market"] = "KOSPI"
    snapshot["data_provider"] = "wics_local_fallback"
    return snapshot.sort_values(["company_name", "stock_code"], na_position="last")


def month_end_dates(start_date: str, end_date: str) -> list[str]:
    start = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")

    dates: list[str] = []
    cursor = datetime(start.year, start.month, 1)
    while cursor <= end:
        if cursor.month == 12:
            next_month = datetime(cursor.year + 1, 1, 1)
        else:
            next_month = datetime(cursor.year, cursor.month + 1, 1)
        month_end = next_month - timedelta(days=1)
        if month_end >= start and month_end <= end:
            dates.append(month_end.strftime("%Y%m%d"))
        cursor = next_month
    return dates


def fetch_market_snapshots_by_month(start_date: str, end_date: str, *, market: str = "KOSPI") -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for target_date in month_end_dates(start_date, end_date):
        try:
            frames.append(fetch_market_snapshot(target_date, market=market))
        except Exception as exc:
            print(f"[WARN] {target_date} 수집 실패: {exc}")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def parse_args() -> ArgumentParser:
    parser = ArgumentParser(description="KOSPI 시장 참조데이터(주가/시총/PER/PBR/배당)를 수집합니다.")
    parser.add_argument("--date", default=datetime.today().strftime("%Y%m%d"), help="기준일 (YYYYMMDD)")
    parser.add_argument("--start-date", help="월말 시계열 수집 시작일 (YYYYMMDD)")
    parser.add_argument("--end-date", help="월말 시계열 수집 종료일 (YYYYMMDD)")
    parser.add_argument("--market", default="KOSPI", help="pykrx 시장 구분값")
    return parser


def main() -> None:
    parser = parse_args()
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        snapshot = fetch_market_snapshot(args.date, market=args.market)
    except Exception as exc:
        print(f"[WARN] pykrx 수집 실패, WICS 로컬 데이터로 대체합니다: {exc}")
        snapshot = fetch_market_snapshot_from_wics_local()

    snapshot_path = OUTPUT_DIR / f"market_reference_snapshot_{snapshot['snapshot_date'].iloc[0]}.csv"
    snapshot.to_csv(snapshot_path, index=False, encoding="utf-8-sig")
    print(f"Saved market snapshot: {snapshot_path}")

    if args.start_date and args.end_date:
        monthly = fetch_market_snapshots_by_month(args.start_date, args.end_date, market=args.market)
        if not monthly.empty:
            monthly_path = OUTPUT_DIR / f"market_reference_monthly_{args.start_date}_{args.end_date}.csv"
            monthly.to_csv(monthly_path, index=False, encoding="utf-8-sig")
            print(f"Saved monthly market reference: {monthly_path}")


if __name__ == "__main__":
    main()
