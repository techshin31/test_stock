from datetime import date

from ..connection import PostgreDB


def insert_execution(
    db: PostgreDB,
    order_id: str,
    data: dict,
) -> str:
    """체결 내역을 executions 테이블에 저장한다.

    Parameters
    ----------
    db : PostgreDB
        DB 연결 객체.
    order_id : str
        연결된 orders.id (UUID).
    data : dict
        필수: symbol, order_side_code, qty, price, amount, net_amount
        선택: market_type_code, instrument_type_code,
              commission, tax, slippage, executed_at

    Returns
    -------
    str
        생성된 executions.id (UUID 문자열).
    """
    row = db.fetch_one(
        """
        INSERT INTO executions (
            order_id,
            symbol,
            market_type_code,
            instrument_type_code,
            order_side_code,
            qty,
            price,
            amount,
            commission,
            tax,
            slippage,
            net_amount,
            executed_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, NOW()))
        RETURNING id::text
        """,
        (
            order_id,
            data["symbol"],
            data.get("market_type_code", "KOSPI"),
            data.get("instrument_type_code", "STOCK"),
            data["order_side_code"],
            data["qty"],
            data["price"],
            data["amount"],
            data.get("commission", 0),
            data.get("tax", 0),
            data.get("slippage", 0),
            data["net_amount"],
            data.get("executed_at"),
        ),
    )
    return row["id"]


def fetch_executions_by_date(
    db: PostgreDB,
    target_date: date,
    strategy_name: str = None,
) -> list[dict]:
    """특정 날짜의 체결 내역을 조회한다.

    Parameters
    ----------
    db : PostgreDB
        DB 연결 객체.
    target_date : date
        조회할 체결일.
    strategy_name : str, optional
        전략 이름. 지정하면 해당 전략 주문의 체결만 반환한다.

    Returns
    -------
    list[dict]
        executions 행 목록.
    """
    if strategy_name:
        return db.fetch_all(
            """
            SELECT e.*
            FROM executions e
            JOIN orders o ON e.order_id = o.id
            JOIN strategies s ON o.strategy_id = s.id
            WHERE s.name = %s
              AND e.executed_at::date = %s
            ORDER BY e.executed_at
            """,
            (strategy_name, target_date),
        )
    return db.fetch_all(
        "SELECT * FROM executions WHERE executed_at::date = %s ORDER BY executed_at",
        (target_date,),
    )


def fetch_executions_by_order(
    db: PostgreDB,
    order_id: str,
) -> list[dict]:
    """특정 주문의 체결 내역을 조회한다.

    Parameters
    ----------
    db : PostgreDB
        DB 연결 객체.
    order_id : str
        orders.id (UUID).

    Returns
    -------
    list[dict]
        executions 행 목록 (체결 시각 오름차순).
    """
    return db.fetch_all(
        "SELECT * FROM executions WHERE order_id = %s ORDER BY executed_at",
        (order_id,),
    )


def fetch_execution_qty_by_order(
    db: PostgreDB,
    order_id: str,
) -> int:
    """특정 주문에 대해 이미 저장된 체결 수량 합계를 반환한다."""
    row = db.fetch_one(
        """
        SELECT COALESCE(SUM(qty), 0) AS qty
        FROM executions
        WHERE order_id = %s
        """,
        (order_id,),
    )
    return int(row["qty"] or 0)


def fetch_execution_totals_by_order(db: PostgreDB, order_id: str) -> dict:
    """이미 저장된 누적 체결 수량과 금액을 반환한다."""
    row = db.fetch_one(
        """
        SELECT COALESCE(SUM(qty), 0) AS qty,
               COALESCE(SUM(amount), 0) AS amount
        FROM executions
        WHERE order_id = %s
        """,
        (order_id,),
    )
    return {"qty": float(row["qty"] or 0), "amount": float(row["amount"] or 0)}
