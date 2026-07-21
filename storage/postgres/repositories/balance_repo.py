from datetime import date

from ..connection import PostgreDB


def insert_balance_history(
    db: PostgreDB,
    strategy_name: str,
    snapshot: dict,
    *,
    execution_venue_code: str,
    account_scope: str,
) -> None:
    """장 마감 후 잔고 스냅샷을 balance_history 테이블에 저장한다.

    Parameters
    ----------
    db : PostgreDB
        DB 연결 객체.
    strategy_name : str
        전략 이름.
    snapshot : dict
        필수: cash (float), stock_value (float), total_value (float)
        선택: daily_return (float), date (date | str) → recorded_at에 사용
    """
    db.execute(
        """
        INSERT INTO balance_history (
            strategy_id,
            execution_venue_code,
            account_scope,
            cash,
            stock_value,
            total_value,
            daily_return,
            recorded_at
        )
        SELECT s.id, %s, %s, %s, %s, %s, %s, COALESCE(%s::timestamptz, NOW())
        FROM strategies s
        WHERE s.name = %s
        """,
        (
            execution_venue_code,
            account_scope,
            snapshot["cash"],
            snapshot["stock_value"],
            snapshot["total_value"],
            snapshot.get("daily_return"),
            str(snapshot["date"]) if "date" in snapshot else None,
            strategy_name,
        ),
    )


def fetch_latest_total_value(
    db: PostgreDB,
    strategy_name: str,
    *,
    execution_venue_code: str,
    account_scope: str,
) -> float | None:
    """직전 balance_history 스냅샷의 total_value를 반환한다. 없으면 None."""
    row = db.fetch_one(
        """
        SELECT bh.total_value
        FROM balance_history bh
        JOIN strategies s ON bh.strategy_id = s.id
        WHERE s.name = %s
          AND bh.execution_venue_code = %s
          AND bh.account_scope = %s
        ORDER BY bh.recorded_at DESC
        LIMIT 1
        """,
        (strategy_name, execution_venue_code, account_scope),
    )
    return float(row["total_value"]) if row is not None else None


def fetch_balance_history(
    db: PostgreDB,
    strategy_name: str,
    start_date: date = None,
    end_date: date = None,
    *,
    execution_venue_code: str,
    account_scope: str,
) -> list[dict]:
    """기간별 잔고 히스토리를 조회한다.

    Parameters
    ----------
    db : PostgreDB
        DB 연결 객체.
    strategy_name : str
        전략 이름.
    start_date : date, optional
        조회 시작일 (포함).
    end_date : date, optional
        조회 종료일 (포함).

    Returns
    -------
    list[dict]
        balance_history 행 목록 (recorded_at 오름차순).
    """
    return db.fetch_all(
        """
        SELECT bh.*
        FROM balance_history bh
        JOIN strategies s ON bh.strategy_id = s.id
        WHERE s.name = %s
          AND bh.execution_venue_code = %s
          AND bh.account_scope = %s
          AND (%s::date IS NULL OR bh.recorded_at::date >= %s::date)
          AND (%s::date IS NULL OR bh.recorded_at::date <= %s::date)
        ORDER BY bh.recorded_at
        """,
        (
            strategy_name,
            execution_venue_code,
            account_scope,
            start_date,
            start_date,
            end_date,
            end_date,
        ),
    )
