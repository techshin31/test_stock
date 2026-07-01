"""macro_signals 테이블 레포지토리."""
from __future__ import annotations

from datetime import date

import pandas as pd

from ..connection import PostgreDB


def upsert_macro_signals(db: PostgreDB, records: list[dict]) -> int:
    """매크로 시그널을 bulk upsert한다.

    Parameters
    ----------
    db : PostgreDB
    records : list[dict]
        필수 키: signal_name_code, category_code, value, frequency_code.
        Phase 1 키: observation_date, available_date, source_code,
        source_value_key, revision_no. Legacy signal_date input is accepted.

    Returns
    -------
    int
        처리된 행 수
    """
    if not records:
        return 0

    params_list = []
    for record in records:
        observation_date = record.get("observation_date", record.get("signal_date"))
        if observation_date is None:
            raise ValueError("macro record requires observation_date")
        available_date = record.get("available_date", observation_date)
        params_list.append(
            (
                record["signal_name_code"],
                record["category_code"],
                observation_date,
                observation_date,
                available_date,
                record["value"],
                record["frequency_code"],
                record.get("source_code", "LEGACY"),
                record.get("source_value_key"),
                int(record.get("revision_no", 0)),
            )
        )
    db.execute_many(
        """
        INSERT INTO macro_signals (
            signal_name_code, category_code, signal_date, observation_date,
            available_date, value, frequency_code, source_code,
            source_value_key, revision_no
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (signal_name_code, observation_date, revision_no)
        DO UPDATE SET
            category_code    = EXCLUDED.category_code,
            signal_date      = EXCLUDED.signal_date,
            available_date   = EXCLUDED.available_date,
            value            = EXCLUDED.value,
            frequency_code   = EXCLUDED.frequency_code,
            source_code      = EXCLUDED.source_code,
            source_value_key = EXCLUDED.source_value_key,
            collected_at     = NOW()
        """,
        params_list,
    )
    return len(params_list)


def fetch_macro_signals(
    db: PostgreDB,
    signal_names: list[str] | None = None,
    categories: list[str] | None = None,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
) -> list[dict]:
    """기간·시그널명·카테고리 조건으로 매크로 시그널을 조회한다.

    Parameters
    ----------
    signal_names : list[str], optional
        조회할 시그널 코드 목록 (예: ['COPPER', 'GOLD'])
    categories : list[str], optional
        조회할 카테고리 코드 목록 (예: ['COMMODITY', 'RATES'])
    start_date, end_date : date or str, optional
        조회 기간 (포함)

    Returns
    -------
    list[dict]
        signal_date 오름차순 정렬된 행 목록
    """
    return fetch_macro_signals_as_of(
        db,
        cutoff_date=end_date,
        signal_names=signal_names,
        categories=categories,
        start_observation_date=start_date,
        end_observation_date=end_date,
    )


def fetch_macro_signals_as_of(
    db: PostgreDB,
    cutoff_date: date | str | None,
    signal_names: list[str] | None = None,
    categories: list[str] | None = None,
    start_observation_date: date | str | None = None,
    end_observation_date: date | str | None = None,
) -> list[dict]:
    """Return the latest known revision for each observation at cutoff."""
    conditions = []
    params: list = []

    if signal_names:
        conditions.append("signal_name_code = ANY(%s)")
        params.append(signal_names)
    if categories:
        conditions.append("category_code = ANY(%s)")
        params.append(categories)
    if cutoff_date:
        conditions.append("available_date <= %s::date")
        params.append(str(cutoff_date))
    if start_observation_date:
        conditions.append("observation_date >= %s::date")
        params.append(str(start_observation_date))
    if end_observation_date:
        conditions.append("observation_date <= %s::date")
        params.append(str(end_observation_date))

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return db.fetch_all(
        f"""
        SELECT *
        FROM (
            SELECT DISTINCT ON (signal_name_code, observation_date)
                id, signal_name_code, category_code,
                observation_date AS signal_date, observation_date,
                available_date, value, frequency_code, source_code,
                source_value_key, revision_no, collected_at
            FROM macro_signals
            {where}
            ORDER BY signal_name_code, observation_date,
                     revision_no DESC, available_date DESC, collected_at DESC
        ) latest
        ORDER BY signal_name_code, observation_date
        """,
        tuple(params) if params else None,
    )


def fetch_macro_signals_as_df(
    db: PostgreDB,
    signal_names: list[str] | None = None,
    categories: list[str] | None = None,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
) -> pd.DataFrame:
    """fetch_macro_signals 결과를 피벗된 DataFrame으로 반환한다.

    Returns
    -------
    pd.DataFrame
        index: signal_date (DatetimeIndex), columns: signal_name_code, values: value
    """
    rows = fetch_macro_signals(db, signal_names, categories, start_date, end_date)
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    pivot = df.pivot(index="signal_date", columns="signal_name_code", values="value")
    pivot.index = pd.to_datetime(pivot.index)
    pivot.columns.name = None
    return pivot.sort_index()


def fetch_latest_signal_dates(
    db: PostgreDB,
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    """시그널별 가장 최근 수집 날짜를 반환한다.

    start/end를 지정하면 해당 기간 내 데이터만 대상으로 조회한다.
    """
    conditions: list[str] = []
    params: list[str] = []
    if start:
        conditions.append("signal_date >= %s")
        params.append(start)
    if end:
        conditions.append("signal_date <= %s")
        params.append(end)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return db.fetch_all(
        f"""
        SELECT signal_name_code, category_code, frequency_code,
               MAX(observation_date) FILTER (WHERE source_code <> 'LEGACY') AS latest_date
        FROM macro_signals
        {where}
        GROUP BY signal_name_code, category_code, frequency_code
        HAVING MAX(observation_date) FILTER (WHERE source_code <> 'LEGACY') IS NOT NULL
        ORDER BY signal_name_code
        """,
        tuple(params) if params else None,
    )
