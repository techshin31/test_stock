import json

from core.analytics import paper_data_quality_remediation as remediation


def test_build_report_separates_current_availability_from_historical_rewrite(
    tmp_path, monkeypatch
):
    gap_path = tmp_path / "gaps.json"
    gap_path.write_text(
        json.dumps(
            {
                "date_reports": [
                    {
                        "observation_date": "2026-07-29",
                        "quality_issue": True,
                        "missing_ticker_counts": {"GOOD.KS": 2, "BAD.KS": 1},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    class Frame:
        empty = False
        index = [type("Date", (), {"date": lambda self: "2026-08-03"})()]
        __len__ = lambda self: 4

    monkeypatch.setattr(
        remediation,
        "download_stock_ohlcv",
        lambda ticker, _start, _end: None if ticker == "BAD.KS" else Frame(),
    )
    monkeypatch.setattr(
        remediation,
        "download_kospi_index",
        lambda _start, _end: Frame(),
    )

    report = remediation.build_report(
        gap_path, start="2026-07-01", end="2026-08-04"
    )

    assert report["historical_quality_issue_dates"] == ["2026-07-29"]
    assert report["remediation_summary"]["unavailable_vendor_symbols"] == ["BAD.KS"]
    assert report["remediation_summary"]["historical_rewrite_performed"] is False
    assert report["index_probe"]["status"].startswith("CURRENT_SOURCE_AVAILABLE")
