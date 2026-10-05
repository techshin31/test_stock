"""Read-only, per-company validated-quarter coverage and collector freshness."""
from apps.worker.collector.monitor import collection_health
from storage.postgres.repositories.financial_coverage import VALID_FINANCIAL_QUARTERS_CTE


def inspect_quality(db, cutoff):
    rows = db.fetch_all(f"""WITH {VALID_FINANCIAL_QUARTERS_CTE}
        SELECT w.stock_code, c.company_name, c.status_code, c.market_type_code,
               COALESCE(r.report_count,0) AS validated_quarters
        FROM wics_companies w LEFT JOIN companies c USING(stock_code)
        LEFT JOIN report_counts r USING(stock_code)
        WHERE w.base_date=(SELECT MAX(base_date) FROM wics_companies WHERE base_date<=%s)
          AND w.company_size_code='LARGE' ORDER BY w.stock_code""", (cutoff, cutoff))
    for row in rows:
        row["eligible_source_history"] = (row["validated_quarters"] >= 8
             and row["status_code"] == "ACTIVE" and row["market_type_code"] == "KOSPI")
        row["exclusion_reason"] = (None if row["eligible_source_history"] else
             "UNSUPPORTED_MARKET_OR_STATUS" if row["market_type_code"] != "KOSPI" or row["status_code"] != "ACTIVE"
             else "FEWER_THAN_EIGHT_VALID_QUARTERS")
    collector = collection_health(cutoff, db=db)
    return {"status": "PASS" if rows and collector["status"] == "PASS" else "BLOCKED",
            "cutoff": cutoff, "collection": collector, "companies": rows,
            "coverage": {"eligible": sum(r["eligible_source_history"] for r in rows), "total": len(rows),
                         "supported_active_kospi": sum(r["status_code"] == "ACTIVE" and r["market_type_code"] == "KOSPI" for r in rows)},
            "read_only": True}


def check_quality(cutoff=None):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import psycopg
    from psycopg.rows import dict_row
    from apps.backtester.config import load_env, build_db_config
    from apps.system.diagnostics import ReadOnlyDatabase
    from apps.system.recovery import parameters
    from core.utils.trading_calendar import previous_krx_trading_day

    load_env()
    cutoff = cutoff or previous_krx_trading_day(datetime.now(ZoneInfo("Asia/Seoul")).date())
    with psycopg.connect(**parameters(build_db_config()), row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        return inspect_quality(ReadOnlyDatabase(conn), cutoff)
