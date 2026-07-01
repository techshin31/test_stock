from ..connection import PostgreDB


def upsert_position(
    db: PostgreDB,
    strategy_name: str,
    symbol: str,
    data: dict,
) -> None:
    """KIS 잔고를 positions 테이블에 동기화한다 (upsert).

    (strategy_id, symbol, instrument_type_code) UNIQUE 제약에 따라
    존재하면 수량·평균단가를 갱신하고, 없으면 신규 삽입한다.

    Parameters
    ----------
    db : PostgreDB
        DB 연결 객체.
    strategy_name : str
        전략 이름 (예: "risk_neutral").
    symbol : str
        종목코드.
    data : dict
        필수: qty (int), avg_cost (float)
        선택: market_type_code, instrument_type_code, realized_pnl
    """
    db.execute(
        """
        INSERT INTO positions (
            strategy_id,
            symbol,
            market_type_code,
            instrument_type_code,
            qty,
            avg_cost,
            realized_pnl
        )
        SELECT s.id, %s, %s, %s, %s, %s, %s
        FROM strategies s
        WHERE s.name = %s
        ON CONFLICT (strategy_id, symbol, instrument_type_code)
        DO UPDATE SET
            qty        = EXCLUDED.qty,
            avg_cost   = EXCLUDED.avg_cost,
            realized_pnl = COALESCE(EXCLUDED.realized_pnl, positions.realized_pnl),
            updated_at = NOW()
        """,
        (
            symbol,
            data.get("market_type_code", "KOSPI"),
            data.get("instrument_type_code", "STOCK"),
            data["qty"],
            data["avg_cost"],
            data.get("realized_pnl", 0),
            strategy_name,
        ),
    )


def fetch_active_position_symbols(
    db: PostgreDB,
    strategy_name: str,
) -> list[str]:
    """전략의 현재 qty > 0 종목 코드 목록을 반환한다."""
    rows = db.fetch_all(
        """
        SELECT p.symbol
        FROM positions p
        JOIN strategies s ON p.strategy_id = s.id
        WHERE s.name = %s AND p.qty > 0
        """,
        (strategy_name,),
    )
    return [row["symbol"] for row in rows]


def zero_out_position(
    db: PostgreDB,
    strategy_name: str,
    symbol: str,
) -> None:
    """특정 종목의 포지션 수량을 0으로 업데이트한다."""
    db.execute(
        """
        UPDATE positions p
        SET qty = 0, updated_at = NOW()
        FROM strategies s
        WHERE p.strategy_id = s.id
          AND s.name = %s
          AND p.symbol = %s
        """,
        (strategy_name, symbol),
    )


def fetch_positions(
    db: PostgreDB,
    strategy_name: str,
) -> list[dict]:
    """전략의 현재 보유 포지션을 조회한다 (qty > 0인 종목만).

    Parameters
    ----------
    db : PostgreDB
        DB 연결 객체.
    strategy_name : str
        전략 이름.

    Returns
    -------
    list[dict]
        positions 행 목록. qty > 0인 종목만 반환.
    """
    return db.fetch_all(
        """
        SELECT p.*
        FROM positions p
        JOIN strategies s ON p.strategy_id = s.id
        WHERE s.name = %s
          AND p.qty > 0
        ORDER BY p.symbol
        """,
        (strategy_name,),
    )
