"""Trading status monitoring queries."""
from __future__ import annotations

from datetime import date

from ..connection import PostgreDB


def fetch_daily_plan_counts(
    db: PostgreDB,
    strategy_name: str,
    plan_date: date,
) -> dict:
    """당일 trade_plans 진행 현황을 반환한다."""
    return db.fetch_one(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE tp.plan_status_code = 'DONE') AS done,
            COUNT(*) FILTER (WHERE tp.plan_status_code = 'SKIPPED') AS skipped,
            COUNT(*) FILTER (WHERE tp.plan_status_code IN ('PENDING', 'ORDERED')) AS pending
        FROM trade_plans tp
        JOIN strategies s ON tp.strategy_id = s.id
        WHERE s.name = %s AND tp.plan_date = %s
        """,
        (strategy_name, plan_date),
    ) or {}


def fetch_daily_execution_summary(
    db: PostgreDB,
    strategy_name: str,
    plan_date: date,
) -> dict:
    """당일 체결 수량 및 손익 합계를 반환한다."""
    return db.fetch_one(
        """
        SELECT
            COALESCE(SUM(e.qty), 0) AS total_filled_qty,
            COALESCE(SUM(e.net_amount), 0) AS daily_net
        FROM executions e
        JOIN orders o ON e.order_id = o.id
        JOIN strategies s ON o.strategy_id = s.id
        WHERE s.name = %s AND e.executed_at::date = %s
        """,
        (strategy_name, plan_date),
    ) or {}
