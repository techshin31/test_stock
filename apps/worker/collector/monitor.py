"""Persist collection outcomes per database and make incomplete coverage explicit."""
from datetime import date, datetime
import hashlib
import json
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from apps.backtester.config import build_db_config
from core.utils.io import write_json

KNOWN_GAPS = {"XBRL_CONFLICTING_DUPLICATE_FACT", "XBRL_CFS_BALANCE_MISSING", "NO_ELIGIBLE_FINANCIAL_FILINGS"}
KST = ZoneInfo("Asia/Seoul")


def health_path(db=None):
    config = getattr(db, "_connection_kwargs", None) or build_db_config()
    identity = [str(config.get(k, "")) for k in ("host", "port", "user")]
    identity.append(config.get("dbname") or config.get("database"))
    key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:20]
    root = Path(os.getenv("COLLECTION_HEALTH_DIR") or Path(__file__).resolve().parents[3] / "logs/collection")
    return root / key / "company.json"


def record_collection(summary, db=None):
    write_json(health_path(db), {**summary, "checked_at": datetime.now(KST).isoformat()})


def collection_health(cutoff, *, db=None, now=None):
    now = now or datetime.now(KST)
    try:
        data = json.loads(health_path(db).read_text())
        checked = datetime.fromisoformat(data["checked_at"])
        end, start = date.fromisoformat(str(data["end"])), date.fromisoformat(str(data["risk_start"]))
        failures = (data.get("finance") or {}).get("failures") or []
        allowed = data.get("status") == "PASS" or (data.get("status") == "PARTIAL"
                  and bool(failures) and all(f.get("reason") in KNOWN_GAPS for f in failures))
        pages = data.get("risk_source_pages") or []
        report_codes = {"11306", "11308", "11324", "11325", "11326"}
        complete_pages = (set(data.get("risk_report_codes") or []) == report_codes
                          and {p.get("report_code") for p in pages} == report_codes
                          and all(re.fullmatch(r"[a-f0-9]{64}", p.get("sha256", "")) and p.get("bytes", 0) > 0 for p in pages))
        for code in report_codes:
            total = (data.get("risk_source_row_counts") or {}).get(code)
            code_pages = [p for p in pages if p.get("report_code") == code]
            complete_pages = (complete_pages and isinstance(total, int) and total >= 0
                              and sorted(p["page"] for p in code_pages) == list(range(1, max(1, (total + 99) // 100) + 1))
                              and all(p.get("total_rows") == total for p in code_pages))
        age = (now - checked).total_seconds()
        good = (allowed and complete_pages and data.get("source") == "DART_PUBLIC"
                and "LARGE" in (data.get("company_size_codes") or [])
                and data.get("risk_disclosure_coverage") == "POLICY_SCOPE_ONLY"
                and start <= cutoff <= end and 0 <= age <= 2 * 86400)
        return {"status": "PASS" if good else "BLOCKED", "checked_at": checked.isoformat(),
                "source_status": data.get("status"), "risk_scope": data.get("risk_disclosure_coverage"),
                "source_end": end.isoformat(), "financial_gaps": failures,
                "reason": None if good else "COLLECTION_STALE_FAILED_OR_OUT_OF_SCOPE"}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {"status": "BLOCKED", "reason": "COLLECTION_EVIDENCE_MISSING_OR_INVALID"}
