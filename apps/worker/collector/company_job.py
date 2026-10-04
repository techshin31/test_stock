"""Collect official public financial filings and dilution-policy disclosures."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apps.worker.collector import public_company
from storage.postgres.connection import PostgreDB


def run(
    db: PostgreDB,
    years: list[int] | None = None,
    dart_start_date: str = "20200101",
    dart_end_date: str | None = None,
    show_progress: bool = True,
    company_size_codes: list[str] | None = None,
    cache_dir: Path = Path("logs/public-dart-xbrl"),
    output: Path = Path("reports/public-company-collection.json"),
) -> dict:
    """Collect key-free public data; preserve PARTIAL status and source evidence.

    Dates use YYYYMMDD. The end defaults to the Korean calendar date;
    omitted years select that end year's latest three years.
    """
    end = (datetime.strptime(dart_end_date, "%Y%m%d").date() if dart_end_date
           else datetime.now(ZoneInfo("Asia/Seoul")).date())
    start = datetime.strptime(dart_start_date, "%Y%m%d").date()
    if start > end:
        raise ValueError("collection start must not exceed end")
    effective_years = years or [end.year - 2, end.year - 1, end.year]
    return public_company.run(
        db, start=start, end=end, years=effective_years,
        company_size_codes=company_size_codes, cache_dir=cache_dir,
        output=output, show_progress=show_progress,
    )
