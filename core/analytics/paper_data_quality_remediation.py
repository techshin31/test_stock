"""Probe whether historical PAPER data gaps are recoverable today.

The probe is deliberately advisory: current source availability does not
rewrite a historical operational scan or make an old EOD report READY.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from data.loaders.kospi_data import download_kospi_index, download_stock_ohlcv


KST = ZoneInfo("Asia/Seoul")


def _load_missing_tickers(gap_report_path: Path) -> tuple[list[str], list[str]]:
    report = json.loads(gap_report_path.read_text(encoding="utf-8-sig"))
    dates = [
        str(row.get("observation_date"))
        for row in report.get("date_reports", [])
        if row.get("quality_issue")
    ]
    tickers = sorted(
        {
            str(ticker).strip().upper()
            for row in report.get("date_reports", [])
            for ticker in (row.get("missing_ticker_counts") or {})
            if str(ticker).strip()
        }
    )
    return dates, tickers


def _probe_stock(ticker: str, start: str, end: str) -> dict:
    try:
        frame = download_stock_ohlcv(ticker, start, end)
    except Exception as exc:  # pragma: no cover - vendor-specific failures
        return {
            "ticker": ticker,
            "status": "PROBE_ERROR",
            "error": f"{type(exc).__name__}: {exc}",
        }
    if frame is None or frame.empty:
        return {
            "ticker": ticker,
            "status": "UNAVAILABLE_VENDOR_SYMBOL",
            "latest_observation_date": None,
        }
    return {
        "ticker": ticker,
        "status": "CURRENT_SOURCE_AVAILABLE__HISTORICAL_GAP_NOT_REWRITTEN",
        "latest_observation_date": str(frame.index[-1].date()),
        "rows": int(len(frame)),
    }


def _probe_index(start: str, end: str) -> dict:
    try:
        series = download_kospi_index(start, end)
    except Exception as exc:  # pragma: no cover - vendor-specific failures
        return {
            "instrument": "^KS11",
            "status": "PROBE_ERROR",
            "error": f"{type(exc).__name__}: {exc}",
        }
    if series is None or series.empty:
        return {
            "instrument": "^KS11",
            "status": "UNAVAILABLE_VENDOR_INDEX",
            "latest_observation_date": None,
        }
    return {
        "instrument": "^KS11",
        "status": "CURRENT_SOURCE_AVAILABLE__HISTORICAL_GAP_NOT_REWRITTEN",
        "latest_observation_date": str(series.index[-1].date()),
        "rows": int(len(series)),
    }


def build_report(
    gap_report_path: Path,
    *,
    start: str,
    end: str,
    generated_at: dt.datetime | None = None,
) -> dict:
    gap_dates, tickers = _load_missing_tickers(gap_report_path)
    ticker_probes = [_probe_stock(ticker, start, end) for ticker in tickers]
    index_probe = _probe_index(start, end)
    generated = (generated_at or dt.datetime.now(KST)).astimezone(KST)
    unavailable = [
        row["ticker"]
        for row in ticker_probes
        if row["status"] == "UNAVAILABLE_VENDOR_SYMBOL"
    ]
    errors = [
        row for row in ticker_probes if row["status"] == "PROBE_ERROR"
    ]
    if index_probe["status"] == "PROBE_ERROR":
        errors.append(index_probe)
    return {
        "schema_version": 1,
        "generated_at": generated.isoformat(timespec="seconds"),
        "mode": "PAPER",
        "source_gap_report": str(gap_report_path),
        "probe_window": {"start": start, "end": end},
        "historical_quality_issue_dates": gap_dates,
        "ticker_probes": ticker_probes,
        "index_probe": index_probe,
        "remediation_summary": {
            "current_source_available_ticker_count": sum(
                row["status"].startswith("CURRENT_SOURCE_AVAILABLE")
                for row in ticker_probes
            ),
            "unavailable_vendor_symbols": unavailable,
            "probe_error_count": len(errors),
            "historical_rewrite_performed": False,
            "policy": (
                "Current source availability identifies transient/vendor gaps only; "
                "historical PAPER scans remain immutable until separately re-sourced."
            ),
        },
    }


def write_report(report: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Probe current source availability for historical PAPER data gaps."
    )
    parser.add_argument(
        "--gap-report", default="reports/analysis/paper_data_quality_gaps/latest.json"
    )
    parser.add_argument("--start", default="2026-07-01")
    parser.add_argument("--end", default="2026-08-04")
    parser.add_argument(
        "--output",
        default="reports/analysis/paper_data_quality_remediation/latest.json",
    )
    args = parser.parse_args()
    report = build_report(Path(args.gap_report), start=args.start, end=args.end)
    write_report(report, Path(args.output))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
