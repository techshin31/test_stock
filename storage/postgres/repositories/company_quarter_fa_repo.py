"""Repository for the versioned quarterly company FA ledger."""
from __future__ import annotations

import json
from datetime import date

from ..connection import PostgreDB


_VALUE_COLUMNS = (
    "revenue", "operating_income", "net_income", "total_assets",
    "total_liabilities", "total_equity", "current_assets", "current_liabilities",
    "operating_cashflow", "capex", "fcf", "market_cap", "market_data_date",
    "operating_margin", "roe", "roa", "debt_ratio", "current_ratio",
    "ocf_to_revenue", "ocf_to_net_income", "revenue_growth_yoy",
    "operating_income_growth_yoy", "operating_margin_change_yoy",
    "operating_cashflow_change_yoy", "per_proxy", "pbr_proxy", "level_score",
    "change_score", "risk_penalty", "risk_score", "fa_score", "level_confidence",
    "change_confidence", "score_confidence", "score_model_code", "is_eligible",
    "excluded_reason_code",
)


def upsert_company_quarter_fa(db: PostgreDB, rows: list[dict]) -> int:
    if not rows:
        return 0
    base_columns = (
        "stock_code", "source_rcept_no", "fiscal_year", "fiscal_quarter",
        "reprt_code", "fs_div", "period_end", "available_date", "model_version",
    )
    all_columns = base_columns + _VALUE_COLUMNS + ("score_detail",)
    params = [
        tuple(row.get(column) for column in base_columns + _VALUE_COLUMNS)
        + (json.dumps(row.get("score_detail", {}), ensure_ascii=False, default=str),)
        for row in rows
    ]
    placeholders = ", ".join(["%s"] * (len(all_columns) - 1) + ["%s::jsonb"])
    updates = ", ".join(
        f"{column} = EXCLUDED.{column}"
        for column in all_columns
        if column not in {"stock_code", "source_rcept_no", "fs_div", "model_version"}
    )
    db.execute_many(
        f"""
        INSERT INTO company_quarter_fa ({', '.join(all_columns)})
        VALUES ({placeholders})
        ON CONFLICT (stock_code, source_rcept_no, fs_div, model_version)
        DO UPDATE SET {updates}, calculated_at = NOW()
        """,
        params,
    )
    return len(params)


def fetch_latest_company_fa_as_of(
    db: PostgreDB,
    cutoff_date: date,
    model_version: str,
    stock_codes: list[str] | None = None,
) -> list[dict]:
    conditions = ["available_date <= %s", "model_version = %s"]
    params: list[object] = [cutoff_date, model_version]
    if stock_codes:
        conditions.append("stock_code = ANY(%s)")
        params.append(stock_codes)
    return db.fetch_all(
        f"""
        SELECT DISTINCT ON (stock_code) *
        FROM company_quarter_fa
        WHERE {' AND '.join(conditions)}
        ORDER BY stock_code, available_date DESC, period_end DESC, id DESC
        """,
        tuple(params),
    )
