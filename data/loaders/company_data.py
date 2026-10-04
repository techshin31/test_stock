"""Read collected financials/disclosures and rebuild annual FA metrics.

Collection uses apps.worker.collector.public_company and official public XBRL.
These database loaders never call the authenticated DART API.
"""
from __future__ import annotations

import pandas as pd

from data.preprocess.financial_statements import calc_fa_metrics_from_db_rows
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.dart_event_repo import fetch_dart_events
from storage.postgres.repositories.financial_repo import (
    fetch_financial_statements,
    fetch_latest_fa_metrics,
    upsert_fa_metrics,
)


def load_fa_metrics_df(
    db: PostgreDB,
    stock_codes: list[str] | None = None,
    fs_div: str = "CFS",
) -> pd.DataFrame:
    """최신 FA 지표를 피벗 DataFrame으로 반환한다.

    Returns
    -------
    pd.DataFrame
        index: stock_code, columns: roe, roa, operating_margin, debt_ratio, current_ratio, fcf
    """
    rows = fetch_latest_fa_metrics(db, stock_codes, fs_div)
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.set_index("stock_code")
    metric_cols = ["roe", "roa", "operating_margin", "debt_ratio", "current_ratio", "fcf"]
    return df[[c for c in metric_cols if c in df.columns]]


def rebuild_annual_fa_metrics(db: PostgreDB, *, batch_size: int = 200) -> int:
    """최신 정정공시 기준으로 연간 FA 캐시와 버전 원장을 재생성한다."""
    groups = db.fetch_all(
        """
        SELECT DISTINCT stock_code, bsns_year, fs_div
        FROM financial_statements
        WHERE reprt_code = '11011'
          AND source_rcept_no NOT LIKE 'LEGACY:%%'
        ORDER BY stock_code, bsns_year, fs_div
        """
    )
    pending = []
    rebuilt = 0
    for group in groups:
        rows = fetch_financial_statements(
            db, group["stock_code"], group["bsns_year"], group["fs_div"], "11011"
        )
        metric = calc_fa_metrics_from_db_rows(
            rows, group["stock_code"], group["bsns_year"], group["fs_div"]
        )
        if metric:
            pending.append(metric)
        if len(pending) >= batch_size:
            rebuilt += upsert_fa_metrics(db, pending)
            pending.clear()
    if pending:
        rebuilt += upsert_fa_metrics(db, pending)
    return rebuilt


def load_dart_events_df(
    db: PostgreDB,
    stock_codes: list[str] | None = None,
    event_categories: list[str] | None = None,
    start_date=None,
    end_date=None,
) -> pd.DataFrame:
    """DART 이벤트를 DataFrame으로 반환한다."""
    rows = fetch_dart_events(db, stock_codes, event_categories, start_date, end_date)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)
