"""Caldara & Iacoviello GPR collector."""
from __future__ import annotations

import io
from typing import Optional

import pandas as pd
import requests

GPR_EXCEL_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"


def _parse_month_column(raw_col: "pd.Series") -> "pd.DatetimeIndex":
    """month 컬럼을 DatetimeIndex로 변환한다.

    Excel 버전에 따라 저장 형식이 다양:
    - 정수/float: 202301 또는 202301.0
    - 문자열: "202301"
    - 날짜 객체: datetime(2023, 1, 1)
    """
    # 이미 datetime이면 바로 변환
    if pd.api.types.is_datetime64_any_dtype(raw_col):
        return pd.to_datetime(raw_col)

    # 날짜 객체나 이미 파싱 가능한 형태 시도
    try:
        converted = pd.to_datetime(raw_col)
        if converted.notna().sum() > len(raw_col) * 0.8:
            return converted
    except Exception:
        pass

    # YYYYMM 정수/float 형식: "202301.0" → "202301"
    month_strs = raw_col.astype(str).str.replace(r"\.0+$", "", regex=True).str.strip()
    return pd.to_datetime(month_strs, format="%Y%m", errors="coerce")


def _parse_gpr_monthly(content: bytes) -> pd.Series:
    df = pd.read_excel(io.BytesIO(content))
    lower_columns = {str(column).strip().lower(): column for column in df.columns}
    month_col = lower_columns.get("month")
    gpr_col = lower_columns.get("gpr")
    if month_col is None or gpr_col is None:
        raise ValueError(f"GPR 파일에서 month/GPR 컬럼을 찾을 수 없습니다: {list(df.columns)}")

    dates = _parse_month_column(df[month_col])
    values = pd.to_numeric(df[gpr_col], errors="coerce")
    series = pd.Series(values.values, index=dates, name="GPR").dropna()
    series = series[series.index.notna()].sort_index()
    series.index = series.index.to_period("M").to_timestamp()
    return series


def fetch_gpr_monthly(start: str, end: Optional[str] = None) -> pd.Series:
    """Caldara & Iacoviello GPR Index 월간 시리즈를 가져온다."""
    response = requests.get(GPR_EXCEL_URL, timeout=30)
    response.raise_for_status()
    series = _parse_gpr_monthly(response.content)

    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end) if end else pd.Timestamp.today()
    return series.loc[start_dt:end_dt]

