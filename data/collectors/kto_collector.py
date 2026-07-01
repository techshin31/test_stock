"""KTO inbound tourist statistics collector."""
from __future__ import annotations

import os
from typing import Optional

import pandas as pd
import requests

_DEFAULT_TOURIST_ENDPOINT = (
    "https://apis.data.go.kr/B551011/ImmigrationStatisticsService/getImmigrationStatisticsList"
)


def _extract_items(payload: dict) -> list[dict]:
    body = payload.get("response", {}).get("body", {})
    items = body.get("items", {}).get("item", [])
    if isinstance(items, dict):
        return [items]
    if isinstance(items, list):
        return items
    return []


def _first_present(item: dict, keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if key in item:
            return item[key]
    return None


def _parse_kto_tourist_items(items: list[dict]) -> pd.Series:
    records: dict[pd.Timestamp, float] = {}
    for item in items:
        raw_date = _first_present(item, ("baseYmd", "ym", "stdYm", "baseYm", "yyyymm", "date"))
        raw_count = _first_present(
            item,
            ("touristCnt", "inbnd_touris_num", "inbndTourisNum", "num", "count", "value"),
        )
        if raw_date is None or raw_count is None:
            continue

        text_date = str(raw_date).replace("-", "")[:6]
        ts = pd.to_datetime(text_date, format="%Y%m", errors="coerce")
        count = pd.to_numeric(str(raw_count).replace(",", ""), errors="coerce")
        if pd.notna(ts) and pd.notna(count):
            records[ts.to_period("M").to_timestamp()] = float(count)

    return pd.Series(records, name="KR_TOURIST").sort_index()


def fetch_kto_tourist_monthly(
    start: str,
    end: Optional[str] = None,
    api_key: Optional[str] = None,
) -> pd.Series:
    """외국인 관광객 월별 입국자 수를 가져온다."""
    api_key = api_key or os.environ.get("KTO_API_KEY")
    if not api_key:
        raise ValueError("KTO_API_KEY가 필요합니다.")

    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end) if end else pd.Timestamp.today()
    endpoint = os.environ.get("KTO_TOURIST_ENDPOINT", _DEFAULT_TOURIST_ENDPOINT)
    params = {
        "serviceKey": api_key,
        "numOfRows": 200,
        "pageNo": 1,
        "MobileOS": "ETC",
        "MobileApp": "QuantPilot",
        "_type": "json",
        "startYmd": start_dt.strftime("%Y%m"),
        "endYmd": end_dt.strftime("%Y%m"),
    }
    response = requests.get(endpoint, params=params, timeout=30)
    response.raise_for_status()

    series = _parse_kto_tourist_items(_extract_items(response.json()))
    return series.loc[start_dt:end_dt]
