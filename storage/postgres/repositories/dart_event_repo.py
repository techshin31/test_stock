"""dart_events 테이블 레포지토리."""
from __future__ import annotations

from datetime import date

from ..connection import PostgreDB


def upsert_dart_events(db: PostgreDB, records: list[dict]) -> int:
    """DART 공시 이벤트를 bulk upsert한다.

    rcept_no가 UNIQUE이므로 동일 접수번호는 덮어쓴다.

    Parameters
    ----------
    records : list[dict]
        필수 키: stock_code, corp_code, rcept_no, rcept_dt, report_nm,
                 event_category_code, event_subtype_code
        선택 키: flr_nm, corp_cls, rm

    Returns
    -------
    int
        처리된 행 수
    """
    if not records:
        return 0

    params_list = [
        (
            r["stock_code"],
            r["corp_code"],
            r["rcept_no"],
            r["rcept_dt"],
            r["report_nm"],
            r["pblntf_ty"],
            r["event_category_code"],
            r["event_subtype_code"],
            r.get("flr_nm"),
            r.get("corp_cls"),
            r.get("rm"),
        )
        for r in records
    ]
    db.execute_many(
        """
        INSERT INTO dart_events (
            stock_code, corp_code, rcept_no, rcept_dt, report_nm,
            pblntf_ty, event_category_code, event_subtype_code,
            flr_nm, corp_cls, rm
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (rcept_no) DO UPDATE SET
            pblntf_ty           = EXCLUDED.pblntf_ty,
            event_category_code = EXCLUDED.event_category_code,
            event_subtype_code  = EXCLUDED.event_subtype_code,
            report_nm           = EXCLUDED.report_nm,
            flr_nm              = EXCLUDED.flr_nm,
            rm                  = EXCLUDED.rm,
            collected_at        = NOW()
        """,
        params_list,
    )
    return len(params_list)


def fetch_dart_events(
    db: PostgreDB,
    stock_codes: list[str] | None = None,
    event_categories: list[str] | None = None,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
) -> list[dict]:
    """DART 이벤트를 조건 조회한다.

    Parameters
    ----------
    stock_codes : list[str], optional
        종목코드 필터
    event_categories : list[str], optional
        이벤트 대분류 코드 필터 (예: ['SHAREHOLDER_RETURN'])
    start_date, end_date : date or str, optional
        공시일 기간 필터
    """
    conditions = []
    params: list = []

    if stock_codes:
        conditions.append("stock_code = ANY(%s)")
        params.append(stock_codes)
    if event_categories:
        conditions.append("event_category_code = ANY(%s)")
        params.append(event_categories)
    if start_date:
        conditions.append("rcept_dt >= %s::date")
        params.append(str(start_date))
    if end_date:
        conditions.append("rcept_dt <= %s::date")
        params.append(str(end_date))

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return db.fetch_all(
        f"SELECT * FROM dart_events {where} ORDER BY rcept_dt DESC, stock_code",
        tuple(params) if params else None,
    )


def fetch_latest_event_date(db: PostgreDB, stock_code: str) -> date | None:
    """종목의 가장 최근 공시일을 반환한다 (증분 수집 기준점용)."""
    row = db.fetch_one(
        "SELECT MAX(rcept_dt) AS latest FROM dart_events WHERE stock_code = %s",
        (stock_code,),
    )
    return row["latest"] if row else None


def fetch_event_date_bounds(db: PostgreDB, stock_code: str) -> dict:
    return db.fetch_one(
        """
        SELECT MIN(rcept_dt) AS earliest, MAX(rcept_dt) AS latest
        FROM dart_events
        WHERE stock_code = %s
        """,
        (stock_code,),
    ) or {"earliest": None, "latest": None}


def fetch_latest_regular_report(
    db: PostgreDB,
    stock_code: str,
    event_subtype_code: str,
    period_label: str,
) -> dict | None:
    """Return the latest receipt, with a deterministic revision number."""
    return db.fetch_one(
        """
        SELECT rcept_no, rcept_dt, report_nm, revision_no
        FROM (
            SELECT rcept_no, rcept_dt, report_nm,
                   ROW_NUMBER() OVER (ORDER BY rcept_dt, rcept_no) - 1 AS revision_no
            FROM dart_events
            WHERE stock_code = %s
              AND event_category_code = 'REGULAR_REPORT'
              AND event_subtype_code = %s
              AND report_nm LIKE %s
        ) versions
        ORDER BY rcept_dt DESC, rcept_no DESC
        LIMIT 1
        """,
        (stock_code, event_subtype_code, f"%{period_label}%"),
    )
