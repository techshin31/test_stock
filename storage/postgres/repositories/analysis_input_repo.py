"""Content fingerprints for the point-in-time inputs to an FA analysis."""
from __future__ import annotations

from datetime import date

from ..connection import PostgreDB


# These are fixed repository identifiers, never caller-supplied SQL. Include
# historical values, not just coverage dates, to detect backfills/corrections.
_SOURCE_FILTERS = (
    ("macro_signals", "available_date <= %s::date AND observation_date <= %s::date", 2),
    ("wics_companies", "base_date <= %s::date", 1),
    ("wics_industry_prices", "price_date <= %s::date", 1),
    ("wics_constituent_prices", "price_date <= %s::date", 1),
    ("financial_statements", "available_date <= %s::date", 1),
    ("companies", "TRUE", 0),
    ("company_risk_states", "effective_date <= %s::date AND (expires_at IS NULL OR expires_at >= %s::date)", 2),
)


def fetch_analysis_source_fingerprints(
    db: PostgreDB,
    cutoff_date: date,
    *,
    reuse_quarter_scores: bool,
    model_version: str,
) -> dict[str, dict]:
    """Hash source content at the cutoff in PostgreSQL, returning small summaries.

    Sort fixed-length row digests rather than relying on physical row order.
    Ignore bookkeeping timestamps/IDs except source-selection tie breakers:
    industry prices use collection time and reused quarterly scores use IDs.
    Recomputed quarterly scores are outputs; only fingerprint that ledger when
    the request explicitly reuses it instead of rebuilding from raw finance.
    """
    sources = list(_SOURCE_FILTERS)
    if reuse_quarter_scores:
        sources.append(("company_quarter_fa", "available_date <= %s::date AND model_version = %s", 1))
    queries: list[str] = []
    params: list[object] = []
    for table, predicate, cutoff_count in sources:
        ignored = ['id', 'collected_at', 'created_at', 'updated_at', 'calculated_at']
        if table == 'wics_industry_prices':
            # The preferred-price query orders competing method versions by
            # collected_at. Recollection can change which value is analyzed.
            ignored.remove('collected_at')
        elif table == 'company_quarter_fa':
            # Selection uses id as its final tie breaker and lineage reference.
            ignored.remove('id')
        excluded_columns = ', '.join(f"'{column}'" for column in ignored)
        queries.append(f"""
            SELECT '{table}' AS source, COUNT(*) AS row_count,
                   encode(sha256(convert_to(
                       COALESCE(string_agg(row_hash, '' ORDER BY row_hash COLLATE "C"), ''),
                       'UTF8'
                   )), 'hex') AS content_hash
            FROM (
                SELECT encode(sha256(convert_to(
                    (to_jsonb(src) - ARRAY[{excluded_columns}]::text[])::text, 'UTF8'
                )), 'hex') AS row_hash
                FROM {table} src
                WHERE {predicate}
            ) rows
        """)
        params.extend([cutoff_date] * cutoff_count)
        if table == "company_quarter_fa":
            params.append(model_version)
    # UNION ALL obtains all fingerprints in a single statement snapshot and
    # avoids sending raw historical tables to Python merely to hash them.
    rows = db.fetch_all(" UNION ALL ".join(queries), tuple(params))
    return {
        row["source"]: {"row_count": int(row["row_count"]), "content_hash": row["content_hash"]}
        for row in rows
    }
