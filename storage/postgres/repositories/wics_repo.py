"""wics_companies 테이블 레포지토리."""
from __future__ import annotations

from datetime import date

from ..connection import PostgreDB


def upsert_wics_companies(db: PostgreDB, records: list[dict]) -> int:
    """WICS 구성종목 스냅샷을 bulk upsert한다.

    Parameters
    ----------
    records : list[dict]
        필수 키: stock_code, base_date, sector_code, industry_code
        선택 키: mkt_val, trd_amt, sec_rate, idx_rate, company_size_code

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
            r["base_date"],
            r["sector_code"],
            r["industry_code"],
            r.get("mkt_val"),
            r.get("trd_amt"),
            r.get("sec_rate"),
            r.get("idx_rate"),
            r.get("company_size_code"),
        )
        for r in records
    ]
    db.execute_many(
        """
        INSERT INTO wics_companies (
            stock_code, base_date, sector_code, industry_code,
            mkt_val, trd_amt, sec_rate, idx_rate, company_size_code
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (stock_code, base_date) DO UPDATE SET
            sector_code   = EXCLUDED.sector_code,
            industry_code = EXCLUDED.industry_code,
            mkt_val       = EXCLUDED.mkt_val,
            trd_amt       = EXCLUDED.trd_amt,
            sec_rate      = EXCLUDED.sec_rate,
            idx_rate      = EXCLUDED.idx_rate,
            company_size_code = EXCLUDED.company_size_code,
            collected_at  = NOW()
        """,
        params_list,
    )
    return len(params_list)


def fetch_wics_companies(
    db: PostgreDB,
    stock_codes: list[str] | None = None,
    sector_codes: list[str] | None = None,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
) -> list[dict]:
    """WICS 구성종목을 조건 조회한다.

    Parameters
    ----------
    stock_codes : list[str], optional
        종목코드 필터
    sector_codes : list[str], optional
        WICS 대분류 코드 필터 (예: ['G45', 'G35'])
    start_date, end_date : date or str, optional
        기준일 기간 필터
    """
    conditions = []
    params: list = []

    if stock_codes:
        conditions.append("stock_code = ANY(%s)")
        params.append(stock_codes)
    if sector_codes:
        conditions.append("sector_code = ANY(%s)")
        params.append(sector_codes)
    if start_date:
        conditions.append("base_date >= %s::date")
        params.append(str(start_date))
    if end_date:
        conditions.append("base_date <= %s::date")
        params.append(str(end_date))

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return db.fetch_all(
        f"SELECT * FROM wics_companies {where} ORDER BY base_date, stock_code",
        tuple(params) if params else None,
    )


def fetch_collected_dates(db: PostgreDB) -> list[date]:
    """이미 수집된 기준일 목록을 반환한다 (중복 수집 방지용)."""
    rows = db.fetch_all(
        "SELECT DISTINCT base_date FROM wics_companies ORDER BY base_date"
    )
    return [r["base_date"] for r in rows]


def fetch_latest_wics_date(db: PostgreDB) -> date | None:
    """가장 최근 수집 기준일을 반환한다."""
    row = db.fetch_one("SELECT MAX(base_date) AS latest FROM wics_companies")
    return row["latest"] if row else None


def fetch_wics_on_date(db: PostgreDB, base_date: date | str) -> list[dict]:
    """특정 날짜의 전체 WICS 구성종목을 반환한다."""
    return db.fetch_all(
        "SELECT * FROM wics_companies WHERE base_date = %s::date ORDER BY mkt_val DESC NULLS LAST",
        (str(base_date),),
    )


def fetch_latest_wics_snapshot(
    db: PostgreDB,
    cutoff_date: date | str,
) -> list[dict]:
    """Return the latest complete WICS snapshot on or before cutoff."""
    return db.fetch_all(
        """
        SELECT *
        FROM wics_companies
        WHERE base_date = (
            SELECT MAX(base_date)
            FROM wics_companies
            WHERE base_date <= %s::date
        )
        ORDER BY industry_code, mkt_val DESC NULLS LAST, stock_code
        """,
        (str(cutoff_date),),
    )


def fetch_distinct_stock_codes(db: PostgreDB) -> list[str]:
    """wics_companies에 있는 고유 stock_code 목록을 반환한다."""
    rows = db.fetch_all(
        "SELECT DISTINCT stock_code FROM wics_companies ORDER BY stock_code"
    )
    return [r["stock_code"] for r in rows]


def fetch_kospi_wics_stock_codes(db: PostgreDB) -> list[str]:
    """Return WICS constituents supported by the v1 KOSPI price provider."""
    rows = db.fetch_all(
        """
        SELECT DISTINCT w.stock_code
        FROM wics_companies w
        JOIN companies c ON c.stock_code = w.stock_code
        WHERE c.market_type_code = 'KOSPI'
        ORDER BY w.stock_code
        """
    )
    return [row["stock_code"] for row in rows]
