"""WICS 섹터 분류 전처리 — wics_companies 데이터에서 섹터 신호를 생성한다."""
from __future__ import annotations

from datetime import date

import pandas as pd


def get_sector_mapping(
    rows: list[dict],
    as_of_date: date | str | None = None,
) -> dict[str, str]:
    """wics_companies 행 목록에서 종목코드 → 섹터코드(대분류) 매핑을 반환한다.

    Parameters
    ----------
    rows : list[dict]
        wics_repo.fetch_wics_companies() 반환값
    as_of_date : date or str, optional
        기준일 지정 시 해당 날짜 데이터만 사용. None이면 최신 날짜 기준.

    Returns
    -------
    dict[str, str]
        {stock_code: sector_code}
    """
    if not rows:
        return {}

    df = pd.DataFrame(rows)
    df["base_date"] = pd.to_datetime(df["base_date"]).dt.date

    if as_of_date is not None:
        target = pd.to_datetime(as_of_date).date() if isinstance(as_of_date, str) else as_of_date
        df = df[df["base_date"] == target]
    else:
        latest = df["base_date"].max()
        df = df[df["base_date"] == latest]

    return dict(zip(df["stock_code"], df["sector_code"]))


def get_industry_mapping(
    rows: list[dict],
    as_of_date: date | str | None = None,
) -> dict[str, str]:
    """종목코드 → 중분류(industry_code) 매핑을 반환한다."""
    if not rows:
        return {}

    df = pd.DataFrame(rows)
    df["base_date"] = pd.to_datetime(df["base_date"]).dt.date

    if as_of_date is not None:
        target = pd.to_datetime(as_of_date).date() if isinstance(as_of_date, str) else as_of_date
        df = df[df["base_date"] == target]
    else:
        latest = df["base_date"].max()
        df = df[df["base_date"] == latest]

    return dict(zip(df["stock_code"], df["industry_code"]))


def calc_sector_weights(
    rows: list[dict],
    as_of_date: date | str | None = None,
) -> pd.DataFrame:
    """날짜 기준 섹터별 시가총액 비중을 계산한다.

    Parameters
    ----------
    rows : list[dict]
        wics_repo.fetch_wics_companies() 반환값
    as_of_date : date or str, optional
        기준일. None이면 최신 날짜.

    Returns
    -------
    pd.DataFrame
        index: sector_code, columns: mkt_val, weight
        weight = 해당 섹터 시가총액 / 전체 시가총액
    """
    if not rows:
        return pd.DataFrame(columns=["sector_code", "mkt_val", "weight"])

    df = pd.DataFrame(rows)
    df["base_date"] = pd.to_datetime(df["base_date"]).dt.date
    df["mkt_val"] = pd.to_numeric(df["mkt_val"], errors="coerce")

    if as_of_date is not None:
        target = pd.to_datetime(as_of_date).date() if isinstance(as_of_date, str) else as_of_date
        df = df[df["base_date"] == target]
    else:
        latest = df["base_date"].max()
        df = df[df["base_date"] == latest]

    sector_mv = df.groupby("sector_code")["mkt_val"].sum()
    total_mv = sector_mv.sum()
    result = pd.DataFrame({"mkt_val": sector_mv})
    result["weight"] = result["mkt_val"] / total_mv if total_mv > 0 else 0.0
    return result.sort_values("weight", ascending=False).reset_index()


def filter_universe_by_sector(
    universe_symbols: list[str],
    rows: list[dict],
    sector_codes: list[str],
    as_of_date: date | str | None = None,
) -> list[str]:
    """유니버스 종목 중 지정한 섹터에 속하는 종목만 반환한다.

    Parameters
    ----------
    universe_symbols : list[str]
        universe 테이블의 종목코드 목록
    rows : list[dict]
        wics_repo.fetch_wics_companies() 반환값
    sector_codes : list[str]
        필터링할 WICS 대분류 코드 목록 (예: ['G45', 'G35'])

    Returns
    -------
    list[str]
        섹터 조건을 만족하는 종목코드 목록
    """
    mapping = get_sector_mapping(rows, as_of_date)
    return [s for s in universe_symbols if mapping.get(s) in sector_codes]
