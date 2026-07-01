"""companies 테이블 레포지토리."""
from __future__ import annotations

from ..connection import PostgreDB


def upsert_companies(db: PostgreDB, records: list[dict]) -> int:
    """기업 기본정보를 bulk upsert한다.

    Parameters
    ----------
    records : list[dict]
        필수 키: stock_code, corp_code, company_name
        선택 키: market_type_code, status_code

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
            r["company_name"],
            r.get("market_type_code"),
            r.get("status_code", "ACTIVE"),
        )
        for r in records
    ]
    db.execute_many(
        """
        INSERT INTO companies (stock_code, corp_code, company_name, market_type_code, status_code)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (stock_code) DO UPDATE SET
            corp_code        = EXCLUDED.corp_code,
            company_name     = EXCLUDED.company_name,
            market_type_code = COALESCE(EXCLUDED.market_type_code, companies.market_type_code),
            status_code      = EXCLUDED.status_code
        """,
        params_list,
    )
    return len(params_list)


def fetch_all_companies(db: PostgreDB) -> list[dict]:
    """전체 기업 목록을 반환한다."""
    return db.fetch_all(
        "SELECT * FROM companies ORDER BY stock_code"
    )


def fetch_company(db: PostgreDB, stock_code: str) -> dict | None:
    """단일 기업 정보를 반환한다."""
    return db.fetch_one(
        "SELECT * FROM companies WHERE stock_code = %s",
        (stock_code,),
    )


def fetch_company_by_corp_code(db: PostgreDB, corp_code: str) -> dict | None:
    """DART 고유번호로 기업 정보를 조회한다."""
    return db.fetch_one(
        "SELECT * FROM companies WHERE corp_code = %s",
        (corp_code,),
    )


def fetch_active_companies(db: PostgreDB) -> list[dict]:
    """상태가 ACTIVE인 기업 목록만 반환한다."""
    return db.fetch_all(
        "SELECT * FROM companies WHERE status_code = 'ACTIVE' ORDER BY stock_code"
    )


def fetch_companies_by_market(db: PostgreDB, market_type_code: str) -> list[dict]:
    """거래소별 기업 목록을 반환한다."""
    return db.fetch_all(
        "SELECT * FROM companies WHERE market_type_code = %s ORDER BY stock_code",
        (market_type_code,),
    )


def fetch_analysis_companies(
    db: PostgreDB,
    company_size_codes: list[str] | None = None,
) -> list[dict]:
    """Return active KOSPI companies in the latest WICS snapshot."""
    size_condition = ""
    params = None
    if company_size_codes:
        size_condition = "AND w.company_size_code = ANY(%s)"
        params = (company_size_codes,)
    return db.fetch_all(
        f"""
        SELECT c.*, w.industry_code, w.company_size_code
        FROM companies c
        JOIN wics_companies w ON w.stock_code = c.stock_code
        WHERE w.base_date = (SELECT MAX(base_date) FROM wics_companies)
          AND c.status_code = 'ACTIVE'
          AND c.market_type_code = 'KOSPI'
          {size_condition}
        ORDER BY c.stock_code
        """,
        params,
    )


def fetch_company_statuses(
    db: PostgreDB,
    stock_codes: list[str] | None = None,
) -> list[dict]:
    if stock_codes:
        return db.fetch_all(
            """
            SELECT stock_code, market_type_code, status_code
            FROM companies
            WHERE stock_code = ANY(%s)
            ORDER BY stock_code
            """,
            (stock_codes,),
        )
    return db.fetch_all(
        """
        SELECT stock_code, market_type_code, status_code
        FROM companies ORDER BY stock_code
        """
    )
