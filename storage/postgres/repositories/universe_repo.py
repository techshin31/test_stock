from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from ..connection import PostgreDB

_KST = ZoneInfo("Asia/Seoul")


DEFAULT_TEST_UNIVERSE_ROWS = [
    {"symbol": "005930", "fa_score": 95.0},  # 삼성전자
    {"symbol": "000660", "fa_score": 92.0},  # SK하이닉스
    {"symbol": "035420", "fa_score": 88.0},  # NAVER
    {"symbol": "005380", "fa_score": 85.0},  # 현대차
    {"symbol": "051910", "fa_score": 82.0},  # LG화학
]


def fetch_active_universe(db: PostgreDB, strategy_name: str) -> list[dict]:
    """universe 테이블에서 ACTIVE 및 SELL_ONLY 종목을 조회한다.

    Parameters
    ----------
    db : PostgreDB
        DB 연결 객체.
    strategy_name : str
        전략 이름 (예: "risk_neutral").

    Returns
    -------
    list[dict]
        universe 행 목록. 각 dict는 universe 테이블의 모든 컬럼을 포함한다.
        universe_status_code 컬럼으로 ACTIVE / SELL_ONLY 구분 가능.
    """
    return db.fetch_all(
        """
        SELECT u.*
        FROM universe u
        JOIN strategies s ON u.strategy_id = s.id
        WHERE s.name = %s
          AND u.universe_status_code IN ('ACTIVE', 'SELL_ONLY')
        ORDER BY u.universe_status_code, u.symbol
        """,
        (strategy_name,),
    )


def seed_test_universe(
    db: PostgreDB,
    strategy_name: str = "risk_neutral",
    rows: list[dict] | None = None,
    entry_date: date | None = None,
) -> int:
    """노트북 검증용 universe 샘플 데이터를 upsert한다.

    FA 외부 프로젝트가 universe를 채우기 전까지 로컬 테스트에서만 사용한다.
    운영 데이터로 사용하지 않도록 함수명에 test 목적을 명시했다.

    Parameters
    ----------
    db : PostgreDB
        DB 연결 객체.
    strategy_name : str
        테스트 데이터를 넣을 전략 이름.
    rows : list[dict] | None
        선택: symbol, market_type_code, instrument_type_code,
        universe_status_code, fa_score, entry_date, exit_deadline 값을 가진 행 목록.
        None이면 KOSPI 대형주 5개를 ACTIVE로 넣는다.
    entry_date : date | None
        rows에 entry_date가 없을 때 사용할 편입일. None이면 오늘 날짜.

    Returns
    -------
    int
        upsert 요청한 universe 행 수.
    """
    strategy = db.fetch_one(
        "SELECT id FROM strategies WHERE name = %s AND is_active = TRUE",
        (strategy_name,),
    )
    if strategy is None:
        raise ValueError(f"전략 '{strategy_name}'을 DB에서 찾을 수 없거나 비활성 상태입니다.")

    seed_rows = DEFAULT_TEST_UNIVERSE_ROWS if rows is None else rows
    seed_entry_date = entry_date or date.today()
    params_list = [
        (
            strategy["id"],
            row["symbol"],
            row.get("market_type_code", "KOSPI"),
            row.get("instrument_type_code", "STOCK"),
            row.get("universe_status_code", "ACTIVE"),
            row.get("fa_score"),
            row.get("entry_date", seed_entry_date),
            row.get("exit_deadline"),
        )
        for row in seed_rows
    ]
    if not params_list:
        return 0

    db.execute_many(
        """
        INSERT INTO universe (
            strategy_id,
            symbol,
            market_type_code,
            instrument_type_code,
            universe_status_code,
            fa_score,
            entry_date,
            exit_deadline
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (strategy_id, symbol)
        DO UPDATE SET
            market_type_code     = EXCLUDED.market_type_code,
            instrument_type_code = EXCLUDED.instrument_type_code,
            universe_status_code = EXCLUDED.universe_status_code,
            fa_score             = EXCLUDED.fa_score,
            entry_date           = EXCLUDED.entry_date,
            exit_deadline        = EXCLUDED.exit_deadline,
            updated_at           = NOW()
        """,
        params_list,
    )
    return len(params_list)


def fetch_universe_for_date(
    db: PostgreDB,
    strategy_name: str,
    as_of_date: date | None = None,
) -> list[dict]:
    """as_of_date 기준으로 유효한 ACTIVE/SELL_ONLY 유니버스 종목을 조회한다.

    entry_date <= as_of_date 이고 (exit_deadline IS NULL OR exit_deadline >= as_of_date)
    인 종목만 반환한다.

    Parameters
    ----------
    db : PostgreDB
    strategy_name : str
    as_of_date : date | None
        조회 기준일. None이면 오늘.

    Returns
    -------
    list[dict]
    """
    target_date = as_of_date or date.today()
    return db.fetch_all(
        """
        SELECT u.*
        FROM universe u
        JOIN strategies s ON u.strategy_id = s.id
        WHERE s.name = %s
          AND u.universe_status_code IN ('ACTIVE', 'SELL_ONLY')
          AND u.entry_date <= %s
          AND (u.exit_deadline IS NULL OR u.exit_deadline >= %s)
        ORDER BY u.universe_status_code, u.symbol
        """,
        (strategy_name, target_date, target_date),
    )


def sync_positions_to_universe(
    db: PostgreDB,
    strategy_name: str,
    positions: list[dict],
    as_of_date: date | None = None,
) -> list[str]:
    """보유 포지션 중 유니버스에 없는 종목을 SELL_ONLY로 등록한다.

    전일 투자했지만 오늘 유니버스에서 빠진 종목은 위험중립형 전략 규칙에 따라
    청산해야 한다. 이 함수는 해당 종목을 SELL_ONLY 상태로 유니버스에 추가해
    execution 루프가 매도 계획을 생성할 수 있게 한다.

    Parameters
    ----------
    db : PostgreDB
    strategy_name : str
    positions : list[dict]
        fetch_positions() 반환값 (qty > 0). symbol, market_type_code 컬럼 사용.
    as_of_date : date | None
        기준일. None이면 오늘.

    Returns
    -------
    list[str]
        SELL_ONLY로 새로 등록된 종목 코드 목록.
    """
    if not positions:
        return []

    target_date = as_of_date or date.today()
    universe_rows = fetch_universe_for_date(db, strategy_name, target_date)
    universe_symbols = {row["symbol"] for row in universe_rows}

    orphans = [p for p in positions if p["symbol"] not in universe_symbols]
    if not orphans:
        return []

    strategy = db.fetch_one(
        "SELECT id FROM strategies WHERE name = %s AND is_active = TRUE",
        (strategy_name,),
    )
    if strategy is None:
        raise ValueError(f"전략 '{strategy_name}'을 DB에서 찾을 수 없거나 비활성 상태입니다.")

    registered: list[str] = []
    for position in orphans:
        row = db.fetch_one(
            """
            INSERT INTO universe (
                strategy_id, symbol, market_type_code, instrument_type_code,
                universe_status_code, fa_score, entry_date, exit_deadline
            ) VALUES (%s,%s,%s,%s,'SELL_ONLY',NULL,%s,%s)
            ON CONFLICT (strategy_id, symbol) DO UPDATE SET
                market_type_code = EXCLUDED.market_type_code,
                instrument_type_code = EXCLUDED.instrument_type_code,
                universe_status_code = 'SELL_ONLY',
                entry_date = EXCLUDED.entry_date,
                exit_deadline = EXCLUDED.exit_deadline,
                updated_at = NOW()
            RETURNING symbol
            """,
            (
                strategy["id"], position["symbol"],
                position.get("market_type_code", "KOSPI"),
                position.get("instrument_type_code", "STOCK"),
                target_date, target_date,
            ),
        )
        if row is not None:
            registered.append(row["symbol"])
    return registered


def publish_fa_run(
    db: PostgreDB,
    run_id: int,
    *,
    strategy_name: str,
    enabled_market_types: list[str],
    publish_deadline_kst: time,
    force_exit_date: date,
    now_kst: datetime,
) -> dict:
    """FA 분석 결과를 universe 테이블에 원자적으로 발행한다.

    Returns
    -------
    dict
        run_id, active_symbols, sell_only_symbols, already_published 키를 포함.
    """
    local_now = now_kst.astimezone(_KST) if now_kst.tzinfo else now_kst.replace(tzinfo=_KST)

    with db.transaction() as conn:
        run = conn.execute(
            "SELECT * FROM fa_analysis_runs WHERE id = %s FOR UPDATE",
            (run_id,),
        ).fetchone()
        if run is None:
            raise ValueError(f"analysis run not found: {run_id}")
        if run["status_code"] == "PUBLISHED":
            rows = conn.execute(
                """
                SELECT symbol FROM universe
                WHERE strategy_id = %s AND universe_status_code = 'ACTIVE'
                ORDER BY symbol
                """,
                (run["strategy_id"],),
            ).fetchall()
            return {
                "run_id": run_id,
                "active_symbols": tuple(row["symbol"] for row in rows),
                "sell_only_symbols": (),
                "already_published": True,
            }
        if run["status_code"] != "PASS":
            raise ValueError(
                f"only PASS run can publish: {run['status_code']}"
            )

        effective_date: date = run["effective_date"]
        if local_now.date() > effective_date:
            raise ValueError("publish effective_date is in the past")

        strategy = conn.execute(
            "SELECT id, name, is_active FROM strategies WHERE id = %s FOR UPDATE",
            (run["strategy_id"],),
        ).fetchone()
        if strategy is None or not strategy["is_active"]:
            raise ValueError("strategy is missing or inactive")
        if strategy["name"] != strategy_name:
            raise ValueError("analyzer and trader strategy names differ")

        selected = conn.execute(
            """
            SELECT r.id, r.stock_code, r.fa_score,
                   c.market_type_code, c.status_code
            FROM fa_company_results r
            JOIN companies c ON c.stock_code = r.stock_code
            WHERE r.run_id = %s AND r.is_selected = TRUE AND r.is_eligible = TRUE
            ORDER BY r.stock_code
            """,
            (run_id,),
        ).fetchall()
        invalid = [
            row["stock_code"] for row in selected
            if row["market_type_code"] not in enabled_market_types
            or row["status_code"] != "ACTIVE"
            or len(row["stock_code"]) != 6
            or not row["stock_code"].isdigit()
        ]
        if invalid:
            raise ValueError(f"invalid selected companies: {sorted(invalid)}")

        symbols = tuple(row["stock_code"] for row in selected)
        blocked = conn.execute(
            """
            SELECT stock_code FROM (
                SELECT DISTINCT ON (stock_code) *
                FROM company_risk_states
                WHERE stock_code = ANY(%s)
                  AND effective_date <= %s
                  AND (expires_at IS NULL OR expires_at >= %s)
                ORDER BY stock_code, is_manual_override DESC,
                         effective_date DESC, id DESC
            ) latest
            WHERE risk_action_code IN ('BLOCK_BUY', 'SELL_ONLY')
            """,
            (list(symbols), effective_date, effective_date),
        ).fetchall()
        if blocked:
            raise ValueError(
                f"selected companies are buy blocked: "
                f"{sorted(row['stock_code'] for row in blocked)}"
            )

        # A forced re-analysis may legitimately replace an earlier publication
        # for the same effective date. Demote it inside this transaction before
        # promoting the new run so the partial unique index is never violated.
        conn.execute(
            """
            UPDATE fa_analysis_runs
            SET status_code = 'PASS', published_at = NULL
            WHERE strategy_id = %s
              AND effective_date = %s
              AND status_code = 'PUBLISHED'
              AND id <> %s
            """,
            (run["strategy_id"], effective_date, run_id),
        )

        sell_only = conn.execute(
            """
            UPDATE universe
            SET universe_status_code = 'SELL_ONLY',
                exit_deadline = %s,
                updated_at = NOW()
            WHERE strategy_id = %s
              AND universe_status_code = 'ACTIVE'
              AND NOT (symbol = ANY(%s))
            RETURNING symbol
            """,
            (force_exit_date, run["strategy_id"], list(symbols)),
        ).fetchall()

        for row in selected:
            conn.execute(
                """
                INSERT INTO universe (
                    strategy_id, symbol, market_type_code, instrument_type_code,
                    universe_status_code, fa_score, entry_date, exit_deadline,
                    source_fa_company_result_id
                ) VALUES (%s,%s,%s,'STOCK','ACTIVE',%s,%s,NULL,%s)
                ON CONFLICT (strategy_id, symbol) DO UPDATE SET
                    market_type_code = EXCLUDED.market_type_code,
                    instrument_type_code = 'STOCK',
                    universe_status_code = 'ACTIVE',
                    fa_score = EXCLUDED.fa_score,
                    entry_date = CASE
                        WHEN universe.universe_status_code = 'ACTIVE'
                        THEN universe.entry_date ELSE EXCLUDED.entry_date END,
                    exit_deadline = NULL,
                    source_fa_company_result_id = EXCLUDED.source_fa_company_result_id,
                    updated_at = NOW()
                """,
                (
                    run["strategy_id"], row["stock_code"],
                    row["market_type_code"], row["fa_score"],
                    effective_date, row["id"],
                ),
            )

        conn.execute(
            """
            UPDATE fa_analysis_runs
            SET status_code = 'PUBLISHED', published_at = NOW(),
                completed_at = COALESCE(completed_at, NOW())
            WHERE id = %s
            """,
            (run_id,),
        )
        return {
            "run_id": run_id,
            "active_symbols": tuple(sorted(symbols)),
            "sell_only_symbols": tuple(sorted(row["symbol"] for row in sell_only)),
            "already_published": False,
        }


def mark_empty_sell_only_removed(
    db: PostgreDB,
    strategy_name: str,
) -> list[str]:
    """Mark SELL_ONLY rows REMOVED only after synchronized position qty is zero."""
    rows = db.fetch_all(
        """
        UPDATE universe u
        SET universe_status_code = 'REMOVED',
            exit_deadline = NULL,
            updated_at = NOW()
        FROM strategies s
        WHERE u.strategy_id = s.id
          AND s.name = %s
          AND u.universe_status_code = 'SELL_ONLY'
          AND NOT EXISTS (
              SELECT 1 FROM positions p
              WHERE p.strategy_id = u.strategy_id
                AND p.symbol = u.symbol
                AND p.qty > 0
          )
        RETURNING u.symbol
        """,
        (strategy_name,),
    )
    return sorted(row["symbol"] for row in rows)
