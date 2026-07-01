"""Collector readiness snapshot queries."""
from __future__ import annotations

from datetime import date, timedelta

from ..connection import PostgreDB


def fetch_schema_columns(db: PostgreDB, table_names: list[str]) -> list[dict]:
    return db.fetch_all(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = ANY(%s)
        ORDER BY table_name, ordinal_position
        """,
        (table_names,),
    )


def fetch_macro_signal_coverage(db: PostgreDB, cutoff_date: date) -> list[dict]:
    return db.fetch_all(
        """
        SELECT signal_name_code,
               MAX(available_date) AS latest_available_date,
               COUNT(*) FILTER (WHERE source_code = 'LEGACY') AS legacy_count
        FROM macro_signals
        WHERE available_date <= %s
        GROUP BY signal_name_code
        ORDER BY signal_name_code
        """,
        (cutoff_date,),
    )


def fetch_finance_industry_coverage(db: PostgreDB, cutoff_date: date) -> list[dict]:
    return db.fetch_all(
        """
        WITH snapshot_date AS (
            SELECT MAX(base_date) AS base_date
            FROM wics_companies WHERE base_date <= %s
        ), report_counts AS (
            SELECT stock_code, COUNT(DISTINCT source_rcept_no) AS report_count
            FROM financial_statements
            WHERE available_date <= %s
              AND source_rcept_no NOT LIKE 'LEGACY:%%'
            GROUP BY stock_code
        )
        SELECT w.industry_code,
               COUNT(*) AS large_company_count,
               COUNT(*) FILTER (WHERE COALESCE(r.report_count, 0) >= 8) AS eligible_company_count
        FROM wics_companies w
        JOIN snapshot_date s ON s.base_date = w.base_date
        JOIN companies c ON c.stock_code = w.stock_code
        LEFT JOIN report_counts r ON r.stock_code = w.stock_code
        WHERE w.company_size_code = 'LARGE'
          AND c.status_code = 'ACTIVE'
          AND c.market_type_code = 'KOSPI'
        GROUP BY w.industry_code
        ORDER BY w.industry_code
        """,
        (cutoff_date, cutoff_date),
    )


def fetch_wics_summary(db: PostgreDB, cutoff_date: date) -> dict:
    return db.fetch_one(
        """
        SELECT MIN(base_date) AS earliest_date,
               MAX(base_date) AS latest_date,
               COUNT(DISTINCT base_date) AS snapshot_count
        FROM wics_companies
        WHERE base_date <= %s
        """,
        (cutoff_date,),
    ) or {}


def fetch_industry_price_coverage(db: PostgreDB, cutoff_date: date) -> list[dict]:
    return db.fetch_all(
        """
        SELECT industry_code, source_code, MIN(price_date) AS earliest_date
        FROM wics_industry_prices
        WHERE price_date <= %s
        GROUP BY industry_code, source_code
        ORDER BY industry_code, source_code
        """,
        (cutoff_date,),
    )


def fetch_constituent_coverage(db: PostgreDB, cutoff_date: date) -> dict:
    history_start = cutoff_date - timedelta(days=365 * 3)
    return db.fetch_one(
        """
        WITH snapshot_date AS (
            SELECT MAX(base_date) AS base_date
            FROM wics_companies WHERE base_date <= %s
        ), required AS (
            SELECT DISTINCT w.stock_code
            FROM wics_companies w
            JOIN snapshot_date s ON s.base_date = w.base_date
            JOIN companies c ON c.stock_code = w.stock_code
            WHERE c.market_type_code = 'KOSPI'
        ), coverage AS (
            SELECT stock_code, MIN(price_date) AS earliest_date
            FROM wics_constituent_prices
            WHERE price_date <= %s
            GROUP BY stock_code
        )
        SELECT MIN(c.earliest_date) AS earliest_date,
               COUNT(*) AS required_count,
               COUNT(c.stock_code) FILTER (WHERE c.earliest_date <= %s) AS covered_count
        FROM required r LEFT JOIN coverage c ON c.stock_code = r.stock_code
        """,
        (cutoff_date, cutoff_date, history_start),
    ) or {}


def fetch_source_duplicate_counts(db: PostgreDB) -> dict:
    return db.fetch_one(
        """
        SELECT
          (SELECT COUNT(*) FROM (
             SELECT signal_name_code, observation_date, revision_no
             FROM macro_signals GROUP BY 1,2,3 HAVING COUNT(*) > 1
          ) d) AS macro_signals,
          (SELECT COUNT(*) FROM (
             SELECT stock_code, base_date FROM wics_companies
             GROUP BY 1,2 HAVING COUNT(*) > 1
          ) d) AS wics_companies,
          (SELECT COUNT(*) FROM (
             SELECT stock_code, source_rcept_no, fs_div, sj_div,
                    COALESCE(account_id, account_nm), account_nm
             FROM financial_statements GROUP BY 1,2,3,4,5,6 HAVING COUNT(*) > 1
          ) d) AS financial_statements
        """
    ) or {}


def fetch_active_company_risk_snapshot(db: PostgreDB, cutoff_date: date) -> list[dict]:
    return db.fetch_all(
        """
        SELECT stock_code, risk_action_code, reason_code,
               source_dart_event_id, effective_date, expires_at,
               policy_version, is_manual_override
        FROM (
            SELECT DISTINCT ON (stock_code) *
            FROM company_risk_states
            WHERE effective_date <= %s
              AND (expires_at IS NULL OR expires_at >= %s)
            ORDER BY stock_code, is_manual_override DESC,
                     effective_date DESC, id DESC
        ) latest
        ORDER BY stock_code
        """,
        (cutoff_date, cutoff_date),
    )
