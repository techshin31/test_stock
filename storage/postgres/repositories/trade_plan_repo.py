from datetime import date

from ..connection import PostgreDB


def upsert_trade_plan(db: PostgreDB, data: dict) -> int:
    """trade_plans 테이블에 거래 계획을 upsert한다.

    (plan_date, strategy_id, symbol) UNIQUE 제약이 있으므로
    재실행 시 기존 계획을 갱신한다 (ON CONFLICT DO UPDATE).

    Parameters
    ----------
    db : PostgreDB
        DB 연결 객체.
    data : dict
        필수: strategy_name, plan_date, symbol, market_type_code
        선택: instrument_type_code, order_side_code, planned_qty, planned_price,
              order_type_code, plan_status_code(기본 "PENDING"), trade_reason_code,
              prev_weight, target_weight, regime_code, price_deviation_limit

        order_side_code/planned_qty는 NULL을 허용한다 — 오늘 전략 신호/주문 의도가
        없는 종목(plan_status_code="SKIPPED")도 trade_plans에 기록해 유니버스
        전체의 의사결정 내역을 추적할 수 있게 한다.

    Returns
    -------
    int
        생성 또는 갱신된 trade_plans.id.
    """
    row = db.fetch_one(
        """
        INSERT INTO trade_plans (
            strategy_id,
            plan_date,
            symbol,
            market_type_code,
            instrument_type_code,
            order_side_code,
            planned_qty,
            planned_price,
            order_type_code,
            plan_status_code,
            trade_reason_code,
            prev_weight,
            target_weight,
            regime_code,
            price_deviation_limit
        )
        SELECT
            s.id,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s,
            %s, %s, %s, %s, %s
        FROM strategies s
        WHERE s.name = %s
        ON CONFLICT (plan_date, strategy_id, symbol)
        DO UPDATE SET
            order_side_code       = EXCLUDED.order_side_code,
            planned_qty           = EXCLUDED.planned_qty,
            planned_price         = EXCLUDED.planned_price,
            order_type_code       = EXCLUDED.order_type_code,
            plan_status_code      = EXCLUDED.plan_status_code,
            trade_reason_code     = EXCLUDED.trade_reason_code,
            prev_weight           = EXCLUDED.prev_weight,
            target_weight         = EXCLUDED.target_weight,
            regime_code           = EXCLUDED.regime_code,
            price_deviation_limit = EXCLUDED.price_deviation_limit,
            updated_at            = NOW()
        RETURNING id
        """,
        (
            data["plan_date"],
            data["symbol"],
            data["market_type_code"],
            data.get("instrument_type_code", "STOCK"),
            data.get("order_side_code"),
            data.get("planned_qty"),
            data.get("planned_price"),
            data.get("order_type_code", "MARKET"),
            data.get("plan_status_code", "PENDING"),
            data.get("trade_reason_code"),
            data.get("prev_weight"),
            data.get("target_weight"),
            data.get("regime_code"),
            data.get("price_deviation_limit"),
            data["strategy_name"],
        ),
    )
    return row["id"]


def fetch_pending_trade_plans(
    db: PostgreDB,
    plan_date: date,
    strategy_name: str,
) -> list[dict]:
    """당일 PENDING 상태의 거래 계획을 조회한다.

    매도 계획을 먼저 반환해 현금 확보 후 매수가 가능하게 한다.

    Parameters
    ----------
    db : PostgreDB
        DB 연결 객체.
    plan_date : date
        조회할 거래일.
    strategy_name : str
        전략 이름.

    Returns
    -------
    list[dict]
        trade_plans 행 목록. SELL → BUY 순서로 정렬.
    """
    return db.fetch_all(
        """
        SELECT tp.*
        FROM trade_plans tp
        JOIN strategies s ON tp.strategy_id = s.id
        WHERE s.name = %s
          AND tp.plan_date = %s
          AND tp.plan_status_code = 'PENDING'
        ORDER BY
            CASE tp.order_side_code WHEN 'SELL' THEN 0 ELSE 1 END,
            tp.id
        """,
        (strategy_name, plan_date),
    )


def fetch_executable_trade_plans(
    db: PostgreDB,
    plan_date: date,
    strategy_name: str,
) -> list[dict]:
    """당일 실행 대상 계획을 조회한다.

    PENDING은 아직 시도 전인 계획이고, ORDERED는 일부 주문 시도 후
    잔여 수량을 재시도할 수 있는 계획이다.
    """
    return db.fetch_all(
        """
        SELECT tp.*
        FROM trade_plans tp
        JOIN strategies s ON tp.strategy_id = s.id
        WHERE s.name = %s
          AND tp.plan_date = %s
          AND tp.plan_status_code IN ('PENDING', 'ORDERED')
        ORDER BY
            CASE tp.order_side_code WHEN 'SELL' THEN 0 ELSE 1 END,
            tp.id
        """,
        (strategy_name, plan_date),
    )


def fetch_trade_plan_progress(
    db: PostgreDB,
    plan_id: int,
) -> dict:
    """계획 1건의 누적 주문/체결 진행률을 조회한다."""
    return db.fetch_one(
        """
        SELECT
            tp.id,
            tp.planned_qty,
            COALESCE(SUM(o.filled_qty), 0) AS filled_qty,
            COUNT(o.id) AS order_count,
            COUNT(o.id) FILTER (
                WHERE o.order_status_code IN ('SUBMITTED', 'ACCEPTED', 'PARTIAL', 'MODIFIED')
            ) AS open_order_count,
            COALESCE(SUM(o.qty) FILTER (
                WHERE o.order_status_code NOT IN ('REJECTED', 'CANCELLED')
            ), 0) AS ordered_qty
        FROM trade_plans tp
        LEFT JOIN orders o ON o.plan_id = tp.id
        WHERE tp.id = %s
        GROUP BY tp.id, tp.planned_qty
        """,
        (plan_id,),
    )


def mark_trade_plan_status(
    db: PostgreDB,
    plan_id: int,
    status_code: str,
) -> None:
    """거래 계획의 처리 상태를 변경한다.

    Parameters
    ----------
    db : PostgreDB
        DB 연결 객체.
    plan_id : int
        trade_plans.id.
    status_code : str
        새 상태 코드 (예: "ORDERED", "DONE", "SKIPPED", "CANCELLED").
    """
    db.execute(
        "UPDATE trade_plans SET plan_status_code = %s, updated_at = NOW() WHERE id = %s",
        (status_code, plan_id),
    )


def mark_trade_plan_company_risk_blocked(
    db: PostgreDB,
    plan_id: int,
) -> None:
    db.execute(
        """
        UPDATE trade_plans
        SET plan_status_code = 'SKIPPED',
            trade_reason_code = 'COMPANY_RISK_BLOCKED',
            reason = 'active company_risk_states entry blocked BUY execution',
            updated_at = NOW()
        WHERE id = %s
        """,
        (plan_id,),
    )
