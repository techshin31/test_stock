"""WiseIndex WICS sector data collector."""
from __future__ import annotations

import time

import pandas as pd
import requests
from pandas import json_normalize
from requests.adapters import HTTPAdapter
from requests.exceptions import (
    ChunkedEncodingError,
    ConnectionError as RequestsConnectionError,
    ContentDecodingError,
    Timeout as RequestsTimeout,
)
from urllib3.util.retry import Retry


_CONNECT_TIMEOUT = 20
_READ_TIMEOUT = 180
_REQUEST_TIMEOUT = (_CONNECT_TIMEOUT, _READ_TIMEOUT)
_MAX_ATTEMPTS = 4
_BACKOFF_BASE = 3.0
_TRANSIENT_ERRORS = (
    RequestsTimeout,
    RequestsConnectionError,
    ChunkedEncodingError,
    ContentDecodingError,
)

# WICS 중분류 코드 전체 목록 (02_codes_seed.sql과 동일)
WICS_INDUSTRY_CODES: list[int] = [
    1010, 1510,
    2010, 2020, 2030,
    2510, 2520, 2530, 2550, 2560,
    3010, 3020, 3030,
    3510, 3520,
    4010, 4020, 4030, 4040,
    4510, 4520, 4530,
    5010, 5020,
    5510,
]


def _make_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=False,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    })
    return session


_SESSION = _make_session()


def fetch_wics_json(date: str, wics_code: int) -> dict:
    """WiseIndex에서 특정 날짜·중분류 코드의 구성종목 JSON을 반환한다.

    Parameters
    ----------
    date : str
        기준일 (YYYYMMDD)
    wics_code : int
        WICS 중분류 코드 (4자리, 예: 4530)

    Returns
    -------
    dict
        WiseIndex API 원본 응답. list, info, sector, size 키 포함.
    """
    url = (
        "https://www.wiseindex.com/Index/GetIndexComponets"
        f"?ceil_yn=0&dt={date}&sec_cd=G{wics_code}"
    )
    for attempt in range(_MAX_ATTEMPTS):
        try:
            r = _SESSION.get(url, timeout=_REQUEST_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except _TRANSIENT_ERRORS:
            if attempt >= _MAX_ATTEMPTS - 1:
                raise
            time.sleep(_BACKOFF_BASE * (2 ** attempt))
    return {}


def parse_wics_companies(date: str, wics_code: int, data: dict) -> pd.DataFrame:
    """fetch_wics_json 응답을 구성종목 DataFrame으로 변환한다.

    Parameters
    ----------
    date : str
        기준일 (YYYYMMDD)
    wics_code : int
        WICS 중분류 코드 (4자리)
    data : dict
        fetch_wics_json의 반환값

    Returns
    -------
    pd.DataFrame
        columns: stock_code, base_date, sector_code, industry_code,
                 mkt_val, trd_amt, sec_rate, idx_rate
        빈 list면 빈 DataFrame 반환.
    """
    if not data or not data.get("list"):
        return pd.DataFrame()

    df = json_normalize(data, record_path=["list"])

    # 종목코드 6자리 보정
    df["stock_code"] = df["CMP_CD"].astype(str).str.zfill(6)
    df["base_date"] = pd.to_datetime(date, format="%Y%m%d").date()

    # SEC_CD in component rows is the parent sector (for example G45).
    # The requested index code is the authoritative industry group.
    industry_code = f"G{int(wics_code):04d}"
    sector_code = industry_code[:3]
    df["industry_code"] = industry_code
    df["sector_code"] = sector_code

    # 섹터 정보 (sec_rate, idx_rate)
    sec_rate, idx_rate = None, None
    if data.get("sector"):
        matched = [s for s in data["sector"] if s.get("SEC_CD") == sector_code]
        if matched:
            sec_rate = matched[0].get("SEC_RATE")
            idx_rate = matched[0].get("IDX_RATE")

    df["mkt_val"] = pd.to_numeric(df.get("MKT_VAL", pd.Series(dtype="float64")), errors="coerce")
    df["trd_amt"] = pd.to_numeric(df.get("TRD_AMT", pd.Series(dtype="float64")), errors="coerce")
    df["sec_rate"] = sec_rate
    df["idx_rate"] = idx_rate
    df["company_size_code"] = None

    keep = ["stock_code", "base_date", "sector_code", "industry_code",
            "mkt_val", "trd_amt", "sec_rate", "idx_rate", "company_size_code"]
    return df[keep].reset_index(drop=True)
