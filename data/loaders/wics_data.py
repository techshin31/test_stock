"""WICS 섹터 데이터 로더.

DB 캐시 우선 전략:
- 이미 수집된 날짜는 WiseIndex API를 호출하지 않는다.
- 없는 날짜만 수집 후 DB에 저장한다.
"""
from __future__ import annotations

import time
from datetime import date

import pandas as pd

try:
    from tqdm import tqdm as _tqdm
    _HAS_TQDM = True
except ImportError:
    _HAS_TQDM = False

def _get_size_category(rank: float) -> str | None:
    if pd.isna(rank):
        return None
    if rank <= 100:
        return "LARGE"
    elif rank <= 300:
        return "MID"
    return "SMALL"


from data.collectors.wics_collector import (
    WICS_INDUSTRY_CODES,
    fetch_wics_json,
    parse_wics_companies,
)
from storage.postgres.connection import PostgreDB
from core.utils.trading_calendar import is_krx_trading_day
from storage.postgres.repositories.wics_repo import (
    fetch_collected_dates,
    fetch_wics_companies,
    fetch_wics_on_date,
    upsert_wics_companies,
)


def collect_wics_companies(
    db: PostgreDB,
    date_list: list[str],
    wics_codes: list[int] | None = None,
    *,
    sleep_seconds: float = 0.5,
    show_progress: bool = True,
    force_refresh: bool = False,
) -> int:
    """지정 날짜 목록의 WICS 구성종목을 수집해 DB에 저장한다.

    이미 수집된 날짜는 건너뛴다.

    Parameters
    ----------
    db : PostgreDB
    date_list : list[str]
        수집할 날짜 목록 (YYYYMMDD 형식)
    wics_codes : list[int], optional
        수집할 WICS 중분류 코드 목록. None이면 전체 25개 코드.
    sleep_seconds : float
        API 호출 간 대기 시간
    show_progress : bool
        tqdm 진행바 출력 여부

    Returns
    -------
    int
        새로 수집한 날짜 수
    """
    codes = wics_codes or WICS_INDUSTRY_CODES
    already_collected = {d.strftime("%Y%m%d") for d in fetch_collected_dates(db)}

    missing_dates = [
        d for d in date_list
        if (force_refresh or d not in already_collected) and is_krx_trading_day(d)
    ]
    if show_progress:
        print(f"[WICS] 신규 수집 대상: {len(missing_dates)}건 / 전체 {len(date_list)}건")
    if not missing_dates:
        return 0

    iterator = _tqdm(missing_dates, desc="WICS 수집") if (show_progress and _HAS_TQDM) else missing_dates
    collected = 0

    for date_str in iterator:
        day_records: list[dict] = []

        for wics_code in codes:
            time.sleep(sleep_seconds)
            try:
                data = fetch_wics_json(date_str, wics_code)
                df = parse_wics_companies(date_str, wics_code, data)
            except Exception as e:
                print(f"[WARN] WICS {wics_code} / {date_str} 수집 실패: {e}")
                continue

            if df.empty:
                continue
            day_records.extend(df.to_dict("records"))

        if day_records:
            df_day = pd.DataFrame(day_records)
            df_day["_rank"] = df_day["mkt_val"].rank(method="first", ascending=False)
            df_day["company_size_code"] = df_day["_rank"].apply(_get_size_category)
            day_records = df_day.drop(columns=["_rank"]).to_dict("records")
            upsert_wics_companies(db, day_records)
            collected += 1
        else:
            print(f"[WICS][WARN] {date_str}: API 데이터 없음 (비거래일 오판 또는 데이터 미게시) — 저장 건너뜀")

    return collected


def load_wics_df(
    db: PostgreDB,
    stock_codes: list[str] | None = None,
    sector_codes: list[str] | None = None,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
) -> pd.DataFrame:
    """WICS 구성종목 데이터를 DataFrame으로 반환한다.

    Parameters
    ----------
    db : PostgreDB
    stock_codes : list[str], optional
        종목코드 필터
    sector_codes : list[str], optional
        WICS 대분류 코드 필터 (예: ['G45', 'G35'])
    start_date, end_date : date or str, optional
        기준일 기간 필터

    Returns
    -------
    pd.DataFrame
        columns: stock_code, base_date, sector_code, industry_code,
                 mkt_val, trd_amt, sec_rate, idx_rate, size_category
    """
    rows = fetch_wics_companies(db, stock_codes, sector_codes, start_date, end_date)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["base_date"] = pd.to_datetime(df["base_date"])
    return df


def load_latest_wics_df(db: PostgreDB) -> pd.DataFrame:
    """가장 최근 날짜의 WICS 전체 구성종목을 DataFrame으로 반환한다."""
    from storage.postgres.repositories.wics_repo import fetch_latest_wics_date
    latest = fetch_latest_wics_date(db)
    if latest is None:
        return pd.DataFrame()
    rows = fetch_wics_on_date(db, latest)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["base_date"] = pd.to_datetime(df["base_date"])
    return df
