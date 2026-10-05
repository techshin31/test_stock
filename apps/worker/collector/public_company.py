"""Public company collection without depending on the authenticated DART API."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from apps.worker.collector import public_finance
from apps.worker.company_risk import refresh_company_risk_states
from core.utils.io import write_json
from data.collectors.public_dart_events import PublicDartEventsClient, REPORT_TYPES
from data.collectors.public_dart_xbrl import PublicDartClient
from data.loaders.company_data import rebuild_annual_fa_metrics
from storage.postgres.repositories.dart_event_repo import upsert_dart_events


def run(db, *, start: date, end: date, years: list[int], company_size_codes=None,
        cache_dir=Path("logs/public-dart-xbrl"), output=Path("reports/public-company-collection.json"),
        show_progress=True):
    sizes = company_size_codes or ["LARGE"]
    stocks = [row["stock_code"] for row in db.fetch_all("""
        SELECT stock_code FROM wics_companies
        WHERE base_date=(SELECT MAX(base_date) FROM wics_companies WHERE base_date<=%s)
          AND company_size_code=ANY(%s) ORDER BY stock_code
    """, (end, sizes))]
    summary = {"source": "DART_PUBLIC", "status": "RUNNING", "start": start,
               "end": end, "company_size_codes": sizes,
               "risk_disclosure_coverage": "NOT_COLLECTED"}
    try:
        finance = public_finance.run(db, PublicDartClient(cache_dir), start=start, end=end,
                                    years=set(years), stock_codes=stocks, show_progress=show_progress,
                                    allow_no_new_filings=True)
        summary["finance"] = finance
        # Fetch every policy type before writing; partial transport responses
        # must never establish complete policy coverage.
        risk_start = min(start, end - timedelta(days=90))
        summary["risk_start"] = risk_start
        risk_client = PublicDartEventsClient(cache_dir)
        events, counts = risk_client.events(risk_start, end)
        summary.update(store_policy_events(db, events, counts, start=risk_start, end=end,
                                          sizes=sizes, source_pages=getattr(risk_client, "source_pages", [])))
        summary["annual_fa_metrics"] = rebuild_annual_fa_metrics(db)
        summary["status"] = finance["status"]
        return summary
    except Exception:
        summary["status"] = "FAILED"
        raise
    finally:
        from apps.worker.collector.monitor import record_collection
        record_collection(summary, db)
        if output:
            write_json(Path(output), summary)


def store_policy_events(db, events, counts, *, start, end, sizes, source_pages=None):
    """Store verified policy rows for current and historical requested members."""
    identities = {r["corp_code"]: r for r in db.fetch_all("SELECT stock_code,corp_code FROM companies")}
    requested = {r["stock_code"] for r in db.fetch_all("""
        SELECT DISTINCT stock_code FROM wics_companies
        WHERE base_date BETWEEN %s AND %s AND company_size_code=ANY(%s)
    """, (start, end, sizes))}
    records = [{**event, "stock_code": identities[event["corp_code"]]["stock_code"]}
               for event in events if event["corp_code"] in identities
               and identities[event["corp_code"]]["stock_code"] in requested]
    with db.transaction():
        upsert_dart_events(db, records)
    return {"dart_events": len(records), "risk_report_codes": list(REPORT_TYPES),
            "risk_source_row_counts": counts, "risk_source_pages": source_pages or [],
            "risk_disclosure_coverage": "POLICY_SCOPE_ONLY", "risk_start": start,
            "risk_scope_stock_count": len(requested),
            "company_risk_states": refresh_company_risk_states(db, end)}
