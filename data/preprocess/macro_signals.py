"""매크로 시그널 전처리 및 DB 저장."""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Callable, Optional

import pandas as pd

from apps.worker.fa_contract import MACRO_SIGNALS
from core.utils.trading_calendar import is_krx_trading_day
from data.collectors.fred_collector import fetch_fred_vintage_observations
from data.loaders.commodities import download_copper, download_gold, download_wti
from data.loaders.fx import download_dollar_index, download_usdkrw
from data.loaders.hallyu_indicators import (
    download_gtrend_kdrama,
    download_gtrend_kpop,
    download_kr_tourist,
)
from data.loaders.manufacturing_indicators import download_semiprod, download_us_mfg_ip
from data.loaders.rates import download_cpi, download_tnx, download_us2y
from data.loaders.risk_indicators import download_bdry, download_gpr, download_sox, download_vix
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.macro_signal_repo import (
    fetch_latest_signal_dates,
    upsert_macro_signals,
)

# loader 반환 키 → (signal_name_code, category_code, frequency_code)
_SIGNAL_META: dict[str, tuple[str, str, str]] = {
    "copper": ("COPPER", "COMMODITY", "DAILY"),
    "gold":   ("GOLD",   "COMMODITY", "DAILY"),
    "wti":    ("WTI",    "COMMODITY", "DAILY"),
    "tnx":    ("TNX",    "RATES",     "DAILY"),
    "cpi":    ("CPI",    "RATES",     "MONTHLY"),
    "sox":    ("SOX",    "RISK",      "DAILY"),
    "bdry":   ("BDRY",   "RISK",      "DAILY"),
    "dxy":    ("DXY",    "FX",        "DAILY"),
    "vix":    ("VIX",    "RISK",      "DAILY"),
    "usdkrw": ("USDKRW", "FX",        "DAILY"),
    "us2y":   ("US2Y",   "RATES",     "DAILY"),
    "gpr":    ("GPR",    "RISK",      "MONTHLY"),
    "us_mfg_ip": ("US_MFG_IP", "MANUFACTURING", "MONTHLY"),
    "semiprod": ("SEMIPROD", "MANUFACTURING", "MONTHLY"),
    "gtrend_kpop": ("GTREND_KPOP", "HALLYU", "MONTHLY"),
    "gtrend_kdrama": ("GTREND_KDRAMA", "HALLYU", "MONTHLY"),
    "kr_tourist": ("KR_TOURIST", "HALLYU", "MONTHLY"),
}

# loader_key → 개별 다운로드 함수
_LOADERS = {
    "copper": download_copper,
    "gold":   download_gold,
    "wti":    download_wti,
    "tnx":    download_tnx,
    "cpi":    download_cpi,
    "sox":    download_sox,
    "bdry":   download_bdry,
    "dxy":    download_dollar_index,
    "vix":    download_vix,
    "usdkrw": download_usdkrw,
    "us2y":   download_us2y,
    "gpr":    download_gpr,
    "gtrend_kpop": download_gtrend_kpop,
    "gtrend_kdrama": download_gtrend_kdrama,
    "us_mfg_ip": download_us_mfg_ip,
}

_CONTRACT_BY_CODE = {contract.code: contract for contract in MACRO_SIGNALS}
# Google Trends 시그널은 요청 전 추가 대기가 필요 (429 방지)
_GTREND_PRE_SLEEP_SECONDS = 15.0


def _normalize_series(series: pd.Series, frequency_code: str) -> pd.Series:
    """시리즈 인덱스를 날짜(Date)로 정규화하고 결측값을 처리한다.

    - DAILY  : 거래일 기준, 최대 5영업일까지 forward fill
    - MONTHLY: 월 1일로 인덱스 정규화, 값 그대로 유지
    """
    s = series.copy().dropna()
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index)
    if s.index.tz is not None:
        s.index = s.index.tz_convert(None)

    s = s.sort_index()

    if frequency_code == "MONTHLY":
        s.index = s.index.to_period("M").to_timestamp()
    else:
        s = s.ffill(limit=5)

    return s.dropna()


def _series_to_records(
    series: pd.Series,
    signal_name_code: str,
    category_code: str,
    frequency_code: str,
) -> list[dict]:
    """pd.Series → upsert용 record 목록으로 변환한다."""
    contract = _CONTRACT_BY_CODE[signal_name_code]
    return [
        {
            "signal_name_code": signal_name_code,
            "category_code":    category_code,
            "observation_date": ts.date(),
            "available_date":   _next_krx_session(ts.date()),
            "value":            float(val),
            "frequency_code":   frequency_code,
            "source_code":      contract.source_code,
            "source_value_key": contract.source_value_key,
            "revision_no":      0,
        }
        for ts, val in series.items()
        if pd.notna(val)
    ]


def _series_to_records_release_date(
    series: pd.Series,
    signal_name_code: str,
    category_code: str,
    frequency_code: str,
    *,
    collected_date: date,
) -> list[dict]:
    """Convert source-release series using the collection date as availability."""
    contract = _CONTRACT_BY_CODE[signal_name_code]
    available_date = _next_krx_session(collected_date)
    return [
        {
            "signal_name_code": signal_name_code,
            "category_code": category_code,
            "observation_date": ts.date(),
            "available_date": available_date,
            "value": float(val),
            "frequency_code": frequency_code,
            "source_code": contract.source_code,
            "source_value_key": contract.source_value_key,
            "revision_no": 0,
        }
        for ts, val in series.items()
        if pd.notna(val)
    ]



def _next_krx_session(observation_date: date) -> date:
    candidate = observation_date + timedelta(days=1)
    for _ in range(10):
        if is_krx_trading_day(candidate.isoformat()):
            return candidate
        candidate += timedelta(days=1)
    raise ValueError(f"cannot find KRX session after {observation_date}")


def _cpi_vintages_to_records(rows: list[dict]) -> list[dict]:
    contract = _CONTRACT_BY_CODE["CPI"]
    return [
        {
            "signal_name_code": "CPI",
            "category_code": "RATES",
            "observation_date": row["observation_date"],
            "available_date": row["available_date"],
            "value": row["value"],
            "frequency_code": "MONTHLY",
            "source_code": contract.source_code,
            "source_value_key": contract.source_value_key,
            "revision_no": row["revision_no"],
        }
        for row in rows
    ]


def collect_and_save(
    db: PostgreDB,
    start: str,
    end: Optional[str] = None,
    fred_api_key: Optional[str] = None,
    kto_api_key: Optional[str] = None,
    source_release_collected_date: date | None = None,
    auto_start: bool = True,
) -> dict[str, int]:
    """모든 매크로 시그널을 수집·전처리하여 DB에 저장한다.

    Parameters
    ----------
    db : PostgreDB
    start, end : str
        수집 기간 (예: '2020-01-01', '2025-12-31').
        auto_start=True 이고 DB에 기존 데이터가 있으면 start는 fallback으로만 사용됩니다.
    fred_api_key : str, optional
        FRED API 키 (미입력 시 FRED_API_KEY 환경변수 참조)
    kto_api_key : str, optional
        KTO API 키 (미입력 시 KTO_API_KEY 환경변수 참조)
    source_release_collected_date : date, optional
        SOURCE_RELEASE_DATE 신호의 수집 기준일. 미입력 시 오늘.
    auto_start : bool, optional
        True이면 시그널별 최신 저장일 다음 날부터만 수집합니다. (기본값: False)

    Returns
    -------
    dict[str, int]
        signal_name_code별 upsert된 행 수. 수집 실패 또는 스킵 시 해당 시그널은 제외됩니다.
    """
    latest_dates: dict[str, date] = {}
    if auto_start:
        for row in fetch_latest_signal_dates(db, start=start, end=end):
            latest_dates[row["signal_name_code"]] = row["latest_date"]

    end_date = date.fromisoformat(end) if end else None
    effective_collected_date = source_release_collected_date or date.today()

    loaders_runtime: dict[str, Callable[[str, Optional[str]], pd.Series]] = {
        **_LOADERS,
        "us_mfg_ip": lambda s, e: download_us_mfg_ip(s, e, fred_api_key),
        "semiprod": lambda s, e: download_semiprod(s, e, fred_api_key),
        "kr_tourist": lambda s, e: download_kr_tourist(s, e, kto_api_key),
    }

    result: dict[str, int] = {}
    for loader_key, (signal_name_code, category_code, frequency_code) in _SIGNAL_META.items():
        effective_start = start
        if auto_start and signal_name_code in latest_dates:
            latest = latest_dates[signal_name_code]
            next_day = latest + timedelta(days=1)
            if end_date and next_day >= end_date:
                print(f"[macro_signals] {signal_name_code}: 최신 데이터 이미 존재, 스킵")
                continue
            if signal_name_code == "CPI":
                # 최근 3개월 revision 재수집, 그 이전은 스킵
                lookback = max(date.fromisoformat(start), latest - timedelta(days=90))
                effective_start = lookback.isoformat()
            else:
                effective_start = next_day.isoformat()

        try:
            if loader_key.startswith("gtrend_"):
                time.sleep(_GTREND_PRE_SLEEP_SECONDS)
            if loader_key == "cpi":
                vintages = fetch_fred_vintage_observations(
                    "CPIAUCSL", effective_start, end, fred_api_key
                )
                records = _cpi_vintages_to_records(vintages)
            else:
                series = loaders_runtime[loader_key](effective_start, end)
                normalized = _normalize_series(series, frequency_code)
                contract = _CONTRACT_BY_CODE[signal_name_code]
                if contract.available_date_rule == "SOURCE_RELEASE_DATE":
                    records = _series_to_records_release_date(
                        normalized,
                        signal_name_code,
                        category_code,
                        frequency_code,
                        collected_date=effective_collected_date,
                    )
                else:
                    records = _series_to_records(
                        normalized, signal_name_code, category_code, frequency_code
                    )
            if not records:
                print(f"[macro_signals] {signal_name_code}: 신규 데이터 없음, 스킵 (요청 시작일: {effective_start})")
                continue
            count = upsert_macro_signals(db, records)
            result[signal_name_code] = count
            print(f"[macro_signals] {signal_name_code}: {count}건 저장")
        except Exception as exc:
            print(f"[macro_signals] {signal_name_code} 저장 실패: {exc}")

    return result
