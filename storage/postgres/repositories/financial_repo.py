"""financial_statements · fa_metrics 테이블 레포지토리."""
from __future__ import annotations

import hashlib
from datetime import date

from ..connection import PostgreDB


# ── financial_statements ──────────────────────────────────────────────────────

def upsert_financial_statements(db: PostgreDB, records: list[dict]) -> int:
    """DART 재무제표 원본을 bulk upsert한다.

    Parameters
    ----------
    records : list[dict]
        필수 키: stock_code, corp_code, bsns_year, fs_div, sj_div, account_nm
        Phase 1 키: source_rcept_no, rcept_dt, available_date,
        period_start, period_end, cumulative amounts, revision_no.

    Returns
    -------
    int
        처리된 행 수
    """
    if not records:
        return 0

    params_list = []
    for record in records:
        reprt_code = record.get("reprt_code", "11011")
        legacy_key = hashlib.md5(
            f"{record['stock_code']}:{record['bsns_year']}:{reprt_code}".encode("ascii")
        ).hexdigest()[:13]
        source_rcept_no = record.get("source_rcept_no") or f"LEGACY:{legacy_key}"
        # Legacy annual collector calls remain executable until Phase 2. These
        # rows carry a LEGACY receipt and are rejected by the readiness gate.
        available_date = record.get("available_date") or record.get("rcept_dt") or date.today()
        params_list.append(
            (
                record["stock_code"], record["corp_code"], int(record["bsns_year"]),
                reprt_code, record["fs_div"], record["sj_div"],
                record.get("account_id"), record["account_nm"], source_rcept_no,
                record.get("rcept_dt"), available_date, record.get("period_start"),
                record.get("period_end"), record.get("thstrm_amount"),
                record.get("frmtrm_amount"), record.get("bfefrmtrm_amount"),
                record.get("thstrm_add_amount"), record.get("frmtrm_add_amount"),
                int(record.get("revision_no", 0)),
            )
        )
    db.execute_many(
        """
        INSERT INTO financial_statements (
            stock_code, corp_code, bsns_year, reprt_code,
            fs_div, sj_div, account_id, account_nm, source_rcept_no,
            rcept_dt, available_date, period_start, period_end,
            thstrm_amount, frmtrm_amount, bfefrmtrm_amount,
            thstrm_add_amount, frmtrm_add_amount, revision_no
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (
            stock_code, source_rcept_no, fs_div, sj_div,
            (COALESCE(account_id, account_nm)), account_nm
        )
        DO UPDATE SET
            bsns_year          = EXCLUDED.bsns_year,
            reprt_code         = EXCLUDED.reprt_code,
            rcept_dt           = EXCLUDED.rcept_dt,
            available_date     = EXCLUDED.available_date,
            period_start       = EXCLUDED.period_start,
            period_end         = EXCLUDED.period_end,
            thstrm_amount      = EXCLUDED.thstrm_amount,
            frmtrm_amount      = EXCLUDED.frmtrm_amount,
            bfefrmtrm_amount   = EXCLUDED.bfefrmtrm_amount,
            thstrm_add_amount  = EXCLUDED.thstrm_add_amount,
            frmtrm_add_amount  = EXCLUDED.frmtrm_add_amount,
            revision_no        = EXCLUDED.revision_no,
            collected_at       = NOW()
        """,
        params_list,
    )
    return len(params_list)


def fetch_financial_statements(
    db: PostgreDB,
    stock_code: str,
    bsns_year: int,
    fs_div: str = "CFS",
    reprt_code: str = "11011",
) -> list[dict]:
    """단일 종목·연도의 재무제표 전체를 반환한다."""
    return db.fetch_all(
        """
        WITH latest_receipt AS (
            SELECT source_rcept_no
            FROM financial_statements
            WHERE stock_code = %s AND bsns_year = %s
              AND fs_div = %s AND reprt_code = %s
              AND source_rcept_no NOT LIKE 'LEGACY:%%'
            ORDER BY available_date DESC, revision_no DESC,
                     source_rcept_no DESC, id DESC
            LIMIT 1
        )
        SELECT f.* FROM financial_statements f
        WHERE f.source_rcept_no = (SELECT source_rcept_no FROM latest_receipt)
        ORDER BY sj_div, id
        """,
        (stock_code, bsns_year, fs_div, reprt_code),
    )


def fetch_financial_statements_as_of(
    db: PostgreDB,
    cutoff_date,
    stock_codes: list[str] | None = None,
) -> list[dict]:
    """Return report versions that were available at the requested cutoff."""
    conditions = ["available_date <= %s::date", "source_rcept_no NOT LIKE 'LEGACY:%%'"]
    params: list = [str(cutoff_date)]
    if stock_codes:
        conditions.append("stock_code = ANY(%s)")
        params.append(stock_codes)
    where = " AND ".join(conditions)
    return db.fetch_all(
        f"""
        SELECT *
        FROM financial_statements
        WHERE {where}
        ORDER BY stock_code, period_end, available_date, source_rcept_no,
                 fs_div, sj_div, account_nm
        """,
        tuple(params),
    )


def fetch_collected_years(
    db: PostgreDB,
    stock_code: str,
    fs_div: str = "CFS",
    reprt_code: str = "11011",
) -> list[int]:
    """종목별 이미 수집된 사업연도 목록을 반환한다 (캐시 체크용)."""
    rows = db.fetch_all(
        """
        SELECT DISTINCT bsns_year FROM financial_statements
        WHERE stock_code = %s AND fs_div = %s AND reprt_code = %s
        ORDER BY bsns_year
        """,
        (stock_code, fs_div, reprt_code),
    )
    return [r["bsns_year"] for r in rows]


def fetch_collected_receipts(db: PostgreDB, stock_code: str) -> set[str]:
    rows = db.fetch_all(
        """
        SELECT DISTINCT source_rcept_no
        FROM financial_statements
        WHERE stock_code = %s
        """,
        (stock_code,),
    )
    return {row["source_rcept_no"] for row in rows}


# ── fa_metrics ────────────────────────────────────────────────────────────────

def upsert_fa_metrics(db: PostgreDB, records: list[dict]) -> int:
    """FA 지표를 bulk upsert한다.

    Parameters
    ----------
    records : list[dict]
        필수 키: stock_code, bsns_year
        선택 키: fs_div, fiscal_year_end, roe, roa, operating_margin,
                 debt_ratio, current_ratio, fcf

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
            int(r["bsns_year"]),
            r.get("fs_div", "CFS"),
            r.get("fiscal_year_end"),
            r.get("roe"),
            r.get("roa"),
            r.get("operating_margin"),
            r.get("debt_ratio"),
            r.get("current_ratio"),
            r.get("fcf"),
        )
        for r in records
    ]
    history_params = [
        (
            r["stock_code"], int(r["bsns_year"]), r.get("fs_div", "CFS"),
            r.get("source_rcept_no") or f"LEGACY:{r['stock_code']}:{r['bsns_year']}",
            r.get("available_date") or r.get("fiscal_year_end") or date.today(),
            r.get("model_version", "annual-fa-v2.0.0"), r.get("fiscal_year_end"),
            r.get("roe"), r.get("roa"), r.get("operating_margin"),
            r.get("debt_ratio"), r.get("current_ratio"), r.get("fcf"),
        )
        for r in records
    ]
    ensure_fa_metrics_history_table(db)
    with db.transaction() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO fa_metrics (
                    stock_code, bsns_year, fs_div, fiscal_year_end,
                    roe, roa, operating_margin, debt_ratio, current_ratio, fcf
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (stock_code, bsns_year, fs_div) DO UPDATE SET
                    fiscal_year_end=COALESCE(EXCLUDED.fiscal_year_end,fa_metrics.fiscal_year_end),
                    roe=EXCLUDED.roe, roa=EXCLUDED.roa,
                    operating_margin=EXCLUDED.operating_margin,
                    debt_ratio=EXCLUDED.debt_ratio,
                    current_ratio=EXCLUDED.current_ratio,
                    fcf=EXCLUDED.fcf, calculated_at=NOW()
                """,
                params_list,
            )
            cur.executemany(
                """
                INSERT INTO fa_metrics_history (
                    stock_code, bsns_year, fs_div, source_rcept_no, available_date,
                    model_version, fiscal_year_end, roe, roa, operating_margin,
                    debt_ratio, current_ratio, fcf
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (stock_code, source_rcept_no, fs_div, model_version)
                DO UPDATE SET
                    bsns_year=EXCLUDED.bsns_year,
                    available_date=EXCLUDED.available_date,
                    fiscal_year_end=EXCLUDED.fiscal_year_end,
                    roe=EXCLUDED.roe, roa=EXCLUDED.roa,
                    operating_margin=EXCLUDED.operating_margin,
                    debt_ratio=EXCLUDED.debt_ratio,
                    current_ratio=EXCLUDED.current_ratio,
                    fcf=EXCLUDED.fcf, calculated_at=NOW()
                """,
                history_params,
            )
    return len(params_list)


def ensure_fa_metrics_history_table(db: PostgreDB) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS fa_metrics_history (
            id BIGSERIAL PRIMARY KEY,
            stock_code VARCHAR(10) NOT NULL REFERENCES companies(stock_code),
            bsns_year SMALLINT NOT NULL,
            fs_div VARCHAR(5) NOT NULL DEFAULT 'CFS',
            source_rcept_no VARCHAR(32) NOT NULL,
            available_date DATE NOT NULL,
            model_version VARCHAR(50) NOT NULL,
            fiscal_year_end DATE,
            roe NUMERIC(10,6), roa NUMERIC(10,6),
            operating_margin NUMERIC(10,6), debt_ratio NUMERIC(10,6),
            current_ratio NUMERIC(10,6), fcf NUMERIC(20,0),
            calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(stock_code, source_rcept_no, fs_div, model_version)
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_fa_metrics_history_asof "
        "ON fa_metrics_history(stock_code, available_date DESC, model_version)"
    )


def fetch_fa_metrics(
    db: PostgreDB,
    stock_codes: list[str] | None = None,
    bsns_year: int | None = None,
    fs_div: str = "CFS",
) -> list[dict]:
    """FA 지표를 조회한다.

    Parameters
    ----------
    stock_codes : list[str], optional
        조회할 종목코드 목록. None이면 전체.
    bsns_year : int, optional
        조회할 사업연도. None이면 전체.
    fs_div : str
        재무제표 구분 (CFS/OFS).
    """
    conditions = ["fs_div = %s"]
    params: list = [fs_div]

    if stock_codes:
        conditions.append("stock_code = ANY(%s)")
        params.append(stock_codes)
    if bsns_year:
        conditions.append("bsns_year = %s")
        params.append(bsns_year)

    where = "WHERE " + " AND ".join(conditions)
    return db.fetch_all(
        f"SELECT * FROM fa_metrics {where} ORDER BY stock_code, bsns_year",
        tuple(params),
    )


def fetch_latest_fa_metrics(
    db: PostgreDB,
    stock_codes: list[str] | None = None,
    fs_div: str = "CFS",
) -> list[dict]:
    """종목별 가장 최근 사업연도 FA 지표를 반환한다."""
    conditions = ["fs_div = %s"]
    params: list = [fs_div]

    if stock_codes:
        conditions.append("stock_code = ANY(%s)")
        params.append(stock_codes)

    where = "WHERE " + " AND ".join(conditions)
    return db.fetch_all(
        f"""
        SELECT DISTINCT ON (stock_code)
            stock_code, bsns_year, fs_div,
            roe, roa, operating_margin, debt_ratio, current_ratio, fcf, calculated_at
        FROM fa_metrics
        {where}
        ORDER BY stock_code, bsns_year DESC
        """,
        tuple(params),
    )
