import json
from typing import Any

import psycopg

from ..connection import PostgreDB


class DuplicateOrderError(RuntimeError):
    """동일한 멱등성 키의 주문이 이미 존재한다."""


def ensure_order_status_history_table(db: PostgreDB) -> None:
    """기존 개발 DB에도 주문 상태 이력 테이블을 준비한다."""
    db.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS order_status_history (
            id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
            order_id            UUID            NOT NULL REFERENCES orders(id),
            broker_order_id     VARCHAR(100),
            order_status_code   VARCHAR(50)     NOT NULL,
            event_type          VARCHAR(50)     NOT NULL,
            filled_qty          NUMERIC(18, 4),
            remaining_qty       NUMERIC(18, 4),
            avg_fill_price      NUMERIC(18, 4),
            message             TEXT,
            raw_payload         JSONB,
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_order_status_history_order_id ON order_status_history(order_id)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_order_status_history_broker_order_id ON order_status_history(broker_order_id)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_order_status_history_created_at ON order_status_history(created_at)"
    )
    db.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255)")
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_idempotency_key "
        "ON orders(idempotency_key) WHERE idempotency_key IS NOT NULL"
    )


def _insert_history_row(
    conn: psycopg.Connection,
    order_id: str,
    status_code: str,
    *,
    event_type: str,
    broker_order_id: str | None = None,
    filled_qty: float | None = None,
    remaining_qty: float | None = None,
    avg_fill_price: float | None = None,
    message: str | None = None,
    raw_payload: dict[str, Any] | list[Any] | None = None,
) -> None:
    """이미 열린 psycopg Connection 위에서 order_status_history 행을 삽입한다.

    db.transaction() 블록 안에서 orders INSERT/UPDATE 와 같은 트랜잭션으로
    묶을 때 사용한다. 직접 호출하지 말 것 — 공개 API는 record_order_status_history.
    """
    payload = json.dumps(raw_payload, ensure_ascii=False) if raw_payload is not None else None
    conn.execute(
        """
        INSERT INTO order_status_history (
            order_id,
            broker_order_id,
            order_status_code,
            event_type,
            filled_qty,
            remaining_qty,
            avg_fill_price,
            message,
            raw_payload
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        """,
        (
            order_id,
            broker_order_id,
            status_code,
            event_type,
            filled_qty,
            remaining_qty,
            avg_fill_price,
            message,
            payload,
        ),
    )


def record_order_status_history(
    db: PostgreDB,
    order_id: str,
    status_code: str,
    *,
    event_type: str,
    broker_order_id: str | None = None,
    filled_qty: float | None = None,
    remaining_qty: float | None = None,
    avg_fill_price: float | None = None,
    message: str | None = None,
    raw_payload: dict[str, Any] | list[Any] | None = None,
) -> None:
    """주문 상태 변화 또는 브로커 조회 이벤트를 append-only로 기록한다."""
    ensure_order_status_history_table(db)
    payload = json.dumps(raw_payload, ensure_ascii=False) if raw_payload is not None else None
    db.execute(
        """
        INSERT INTO order_status_history (
            order_id,
            broker_order_id,
            order_status_code,
            event_type,
            filled_qty,
            remaining_qty,
            avg_fill_price,
            message,
            raw_payload
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        """,
        (
            order_id,
            broker_order_id,
            status_code,
            event_type,
            filled_qty,
            remaining_qty,
            avg_fill_price,
            message,
            payload,
        ),
    )


def create_order(db: PostgreDB, data: dict) -> str:
    """orders 테이블에 신규 주문을 생성한다.

    trade_plans 행(plan dict) 또는 임시 dict를 모두 수용한다.
    strategy_id가 있으면 그대로 사용하고, 없으면 strategy_name으로 조회한다.
    plan_id는 data["plan_id"] → data["id"] 순서로 찾는다
    (trade_plans 행에서 id가 plan id를 의미할 때).

    Parameters
    ----------
    db : PostgreDB
        DB 연결 객체.
    data : dict
        필수: symbol, order_side_code
              + (strategy_id) 또는 (strategy_name)
              + (qty 또는 planned_qty)
        선택: market_type_code, instrument_type_code,
              order_type_code, price / planned_price, plan_id / id

    Returns
    -------
    str
        생성된 orders.id (UUID 문자열).
    """
    # strategy_id 결정
    if "strategy_id" in data and data["strategy_id"] is not None:
        strategy_id = data["strategy_id"]
    else:
        row = db.fetch_one(
            "SELECT id FROM strategies WHERE name = %s",
            (data["strategy_name"],),
        )
        strategy_id = row["id"]

    # plan_id: 명시적 plan_id → trade_plans 행의 id → None
    plan_id = data.get("plan_id") or (
        data.get("id") if "planned_qty" in data else None
    )

    qty   = data.get("qty") or data.get("planned_qty")
    price = data.get("price") or data.get("planned_price")

    ensure_order_status_history_table(db)
    with db.transaction() as conn:
        row = conn.execute(
            """
            INSERT INTO orders (
                strategy_id,
                plan_id,
                symbol,
                market_type_code,
                instrument_type_code,
                order_side_code,
                order_type_code,
                qty,
                price,
                order_status_code,
                submitted_at,
                idempotency_key
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', NULL, %s)
            ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING
            RETURNING id::text
            """,
            (
                strategy_id,
                plan_id,
                data["symbol"],
                data.get("market_type_code", "KOSPI"),
                data.get("instrument_type_code", "STOCK"),
                data["order_side_code"],
                data.get("order_type_code", "MARKET"),
                qty,
                price,
                data.get("idempotency_key"),
            ),
        ).fetchone()
        if row is None:
            raise DuplicateOrderError(
                f"duplicate idempotency key: {data.get('idempotency_key')}"
            )
        _insert_history_row(
            conn,
            row["id"],
            "PENDING",
            event_type="CREATE",
            filled_qty=0,
            remaining_qty=qty,
            message="local order intent created before broker submission",
        )
    return row["id"]


def mark_order_submitted(db: PostgreDB, order_id: str) -> None:
    """브로커 API 호출 직전에 로컬 주문을 SUBMITTED로 전환한다."""
    update_order_status(
        db,
        order_id,
        "SUBMITTED",
        event_type="BROKER_REQUEST",
        note="broker order request started",
    )


def attach_broker_order_id(
    db: PostgreDB,
    order_id: str,
    broker_order_id: str,
    raw_payload: dict[str, Any] | None = None,
) -> None:
    """증권사 주문번호를 orders 행에 연결하고 상태를 ACCEPTED로 갱신한다.

    Parameters
    ----------
    db : PostgreDB
        DB 연결 객체.
    order_id : str
        orders.id (UUID).
    broker_order_id : str
        증권사 주문번호 (KIS ODNO).
    """
    ensure_order_status_history_table(db)
    with db.transaction() as conn:
        conn.execute(
            """
            UPDATE orders
            SET broker_order_id   = %s,
                order_status_code = 'ACCEPTED',
                submitted_at      = COALESCE(submitted_at, NOW()),
                updated_at        = NOW()
            WHERE id = %s
            """,
            (broker_order_id, order_id),
        )
        _insert_history_row(
            conn,
            order_id,
            "ACCEPTED",
            event_type="ACCEPTED",
            broker_order_id=broker_order_id,
            message="broker order id attached",
            raw_payload=raw_payload,
        )


def update_order_status(
    db: PostgreDB,
    order_id: str,
    status_code: str,
    filled_qty: float = None,
    avg_fill_price: float = None,
    note: str = None,
    remaining_qty: float = None,
    broker_order_id: str = None,
    event_type: str = "STATUS_UPDATE",
    raw_payload: dict[str, Any] | list[Any] = None,
) -> None:
    """주문 상태를 갱신한다.

    Parameters
    ----------
    db : PostgreDB
        DB 연결 객체.
    order_id : str
        orders.id (UUID).
    status_code : str
        새 주문 상태 코드 (예: "FILLED", "CANCELLED", "REJECTED").
    filled_qty : float, optional
        완전 체결 수량 (FILLED 상태 시 사용).
    avg_fill_price : float, optional
        평균 체결 단가 (FILLED 상태 시 사용).
    note : str, optional
        비고 (오류 메시지, 취소 사유 등).
    """
    fields = ["order_status_code = %s", "updated_at = NOW()"]
    values: list = [status_code]

    if filled_qty is not None:
        fields.append("filled_qty = %s")
        values.append(filled_qty)
    if avg_fill_price is not None:
        fields.append("avg_fill_price = %s")
        values.append(avg_fill_price)
    if note is not None:
        fields.append("note = %s")
        values.append(note)
    if status_code == "FILLED":
        fields.append("filled_at = NOW()")
    elif status_code == "CANCELLED":
        fields.append("cancelled_at = NOW()")

    values.append(order_id)
    ensure_order_status_history_table(db)
    with db.transaction() as conn:
        conn.execute(
            f"UPDATE orders SET {', '.join(fields)} WHERE id = %s",
            tuple(values),
        )
        _insert_history_row(
            conn,
            order_id,
            status_code,
            event_type=event_type,
            broker_order_id=broker_order_id,
            filled_qty=filled_qty,
            remaining_qty=remaining_qty,
            avg_fill_price=avg_fill_price,
            message=note,
            raw_payload=raw_payload,
        )


def fetch_order_by_broker_id(
    db: PostgreDB,
    broker_order_id: str,
) -> dict | None:
    """증권사 주문번호로 orders 행을 조회한다.

    Parameters
    ----------
    db : PostgreDB
        DB 연결 객체.
    broker_order_id : str
        증권사 주문번호 (KIS ODNO).

    Returns
    -------
    dict | None
        orders 행. 존재하지 않으면 None.
    """
    return db.fetch_one(
        "SELECT * FROM orders WHERE broker_order_id = %s",
        (broker_order_id,),
    )


def fetch_open_orders_by_plan(
    db: PostgreDB,
    plan_id: int,
) -> list[dict]:
    """재주문 전에 확인해야 하는 열린 주문을 조회한다."""
    return db.fetch_all(
        """
        SELECT *
        FROM orders
        WHERE plan_id = %s
          AND order_status_code IN ('SUBMITTED', 'ACCEPTED', 'PARTIAL', 'MODIFIED')
        ORDER BY created_at, id
        """,
        (plan_id,),
    )
