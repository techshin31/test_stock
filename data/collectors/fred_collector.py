"""FRED(Federal Reserve Economic Data) collector."""
from __future__ import annotations

import io
import os
from datetime import date

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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
    return session


_SESSION = _make_session()


def _ensure_utc_index(obj: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    if not isinstance(obj.index, pd.DatetimeIndex):
        obj.index = pd.to_datetime(obj.index)
    if obj.index.tz is None:
        obj.index = obj.index.tz_localize("UTC")
    else:
        obj.index = obj.index.tz_convert("UTC")
    return obj


def fetch_fred_series(
    series_id: str,
    start: str,
    end: str | date | None = None,
    api_key: str | None = None,
) -> pd.Series:
    """FRED에서 시계열을 가져온다.

    api_key 또는 환경변수 FRED_API_KEY가 있으면 JSON API를 사용하고,
    없으면 공개 CSV 엔드포인트를 사용한다.
    """
    api_key = api_key or os.environ.get("FRED_API_KEY")

    if api_key:
        params: dict = {
            "series_id": series_id,
            "observation_start": start,
            "file_type": "json",
            "api_key": api_key,
        }
        if end:
            params["observation_end"] = str(end)
        resp = _SESSION.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params=params,
            timeout=30,
        )
        if resp.status_code != 400:
            resp.raise_for_status()
            records = {
                obs["date"]: float(obs["value"])
                for obs in resp.json()["observations"]
                if obs["value"] != "."
            }
            series = pd.Series(records, name=series_id)
            series.index = pd.to_datetime(series.index)
            return _ensure_utc_index(series)
        # 400이면 공개 CSV 엔드포인트로 폴백

    resp = _SESSION.get(
        f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}",
        timeout=30,
    )
    resp.raise_for_status()
    text = resp.text.lstrip("﻿")
    df = pd.read_csv(io.StringIO(text))
    date_col = next((c for c in df.columns if "DATE" in c.strip().upper()), None)
    if date_col is None:
        raise ValueError(f"FRED CSV에서 DATE 컬럼을 찾을 수 없습니다: {list(df.columns)}")
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.set_index(date_col)
    df.columns = [series_id]
    series = pd.to_numeric(df[series_id], errors="coerce").dropna()
    series = series[series.index >= pd.Timestamp(start)]
    if end:
        series = series[series.index <= pd.Timestamp(str(end))]
    series = series.rename(series_id)
    return _ensure_utc_index(series)


def _parse_vintage_observations(observations: list[dict]) -> list[dict]:
    """Normalize FRED output_type=4 observations into revisioned rows."""
    grouped: dict[str, list[tuple[str, float]]] = {}
    for observation in observations:
        value = observation.get("value")
        if value in (None, "."):
            continue
        observation_date = str(observation["date"])
        item = (str(observation["realtime_start"]), float(value))
        if item not in grouped.setdefault(observation_date, []):
            grouped[observation_date].append(item)

    rows: list[dict] = []
    for observation_date, vintages in sorted(grouped.items()):
        for revision_no, (available_date, value) in enumerate(sorted(vintages)):
            rows.append({
                "observation_date": date.fromisoformat(observation_date),
                "available_date": date.fromisoformat(available_date),
                "value": value,
                "revision_no": revision_no,
            })
    return rows


def fetch_fred_vintage_observations(
    series_id: str,
    start: str,
    end: str | date | None = None,
    api_key: str | None = None,
) -> list[dict]:
    """Fetch all known FRED vintages including first release dates."""
    api_key = api_key or os.environ.get("FRED_API_KEY")
    if not api_key:
        raise ValueError("FRED_API_KEY is required for point-in-time CPI vintages")
    params: dict[str, str] = {
        "series_id": series_id,
        "observation_start": start,
        "file_type": "json",
        "api_key": api_key,
        "output_type": "4",
        "realtime_start": "1776-07-04",
        "realtime_end": "9999-12-31",
    }
    if end:
        params["observation_end"] = str(end)
    response = _SESSION.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params=params,
        timeout=60,
    )
    response.raise_for_status()
    return _parse_vintage_observations(response.json().get("observations", []))
