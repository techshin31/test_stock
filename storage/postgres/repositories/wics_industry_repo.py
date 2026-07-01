"""Point-in-time repository for WICS industry index prices."""
from __future__ import annotations

from datetime import date

from ..connection import PostgreDB


def upsert_wics_industry_prices(db: PostgreDB, records: list[dict]) -> int:
    if not records:
        return 0
    params = [
        (
            row["industry_code"],
            row["price_date"],
            row["index_value"],
            row["source_code"],
            row.get("constituent_base_date"),
            row.get("method_version", "OFFICIAL"),
        )
        for row in records
    ]
    db.execute_many(
        """
        INSERT INTO wics_industry_prices (
            industry_code, price_date, index_value, source_code,
            constituent_base_date, method_version
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (industry_code, price_date, source_code, method_version)
        DO UPDATE SET
            index_value = EXCLUDED.index_value,
            constituent_base_date = EXCLUDED.constituent_base_date,
            collected_at = NOW()
        """,
        params,
    )
    return len(params)


def fetch_wics_industry_prices(
    db: PostgreDB,
    cutoff_date: date | str,
    industry_codes: list[str] | None = None,
    start_date: date | str | None = None,
    source_priority: tuple[str, ...] = ("WISEINDEX", "DERIVED"),
) -> list[dict]:
    """Return one preferred source row per industry and date at cutoff."""
    conditions = ["price_date <= %s::date"]
    params: list[object] = [str(cutoff_date)]
    if industry_codes:
        conditions.append("industry_code = ANY(%s)")
        params.append(industry_codes)
    if start_date:
        conditions.append("price_date >= %s::date")
        params.append(str(start_date))
    params.append(list(source_priority))
    where = " AND ".join(conditions)
    return db.fetch_all(
        f"""
        SELECT *
        FROM (
            SELECT DISTINCT ON (industry_code, price_date)
                id, industry_code, price_date, index_value, source_code,
                constituent_base_date, method_version, collected_at
            FROM wics_industry_prices
            WHERE {where}
            ORDER BY industry_code, price_date,
                     array_position(%s::text[], source_code), collected_at DESC
        ) preferred
        ORDER BY industry_code, price_date
        """,
        tuple(params),
    )


def upsert_wics_constituent_prices(db: PostgreDB, records: list[dict]) -> int:
    if not records:
        return 0
    params = [
        (row["stock_code"], row["price_date"], row["close"], row.get("source_code", "YAHOO"))
        for row in records
    ]
    db.execute_many(
        """
        INSERT INTO wics_constituent_prices (
            stock_code, price_date, close, source_code
        )
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (stock_code, price_date, source_code)
        DO UPDATE SET close = EXCLUDED.close, collected_at = NOW()
        """,
        params,
    )
    return len(params)


def fetch_latest_constituent_price_dates(db: PostgreDB) -> dict[str, date]:
    rows = db.fetch_all(
        """
        SELECT stock_code, MAX(price_date) AS latest_date
        FROM wics_constituent_prices
        GROUP BY stock_code
        """
    )
    return {row["stock_code"]: row["latest_date"] for row in rows}


def fetch_wics_constituent_prices(
    db: PostgreDB,
    cutoff_date: date | str,
    start_date: date | str | None = None,
    stock_codes: list[str] | None = None,
) -> list[dict]:
    conditions = ["price_date <= %s::date"]
    params: list[object] = [str(cutoff_date)]
    if start_date:
        conditions.append("price_date >= %s::date")
        params.append(str(start_date))
    if stock_codes:
        conditions.append("stock_code = ANY(%s)")
        params.append(stock_codes)
    return db.fetch_all(
        f"""
        SELECT stock_code, price_date, close, source_code, collected_at
        FROM wics_constituent_prices
        WHERE {' AND '.join(conditions)}
        ORDER BY stock_code, price_date
        """,
        tuple(params),
    )
