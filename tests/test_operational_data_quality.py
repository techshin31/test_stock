import json

from core.analytics.operational_data_quality import build_report


def _row(timestamp, expected_date="2026-07-29", missing=None, stale=None):
    missing = missing or []
    stale = stale or []
    return {
        "timestamp": timestamp,
        "data_health": {
            "expected_date": expected_date,
            "expected_count": 4,
            "fresh_count": 4 - len(set(missing) | set(stale)),
            "stale_count": len(stale),
            "missing_count": len(missing),
            "missing_tickers": missing,
            "stale_tickers": stale,
            "dependency_errors": [],
        },
    }


def test_build_report_profiles_gaps_by_date_and_preserves_blockers(tmp_path):
    path = tmp_path / "operational_health.jsonl"
    rows = [
        _row("2026-07-29T09:00:00+09:00"),
        _row("2026-07-29T09:01:00+09:00", missing=["153131.KS"]),
        _row("2026-07-29T09:02:00+09:00", missing=["153131.KS"]),
        _row("2026-07-29T09:03:00+09:00", missing=["153131.KS"]),
        _row("2026-07-28T09:00:00+09:00", expected_date="2026-07-28"),
        _row(
            "2026-07-28T09:01:00+09:00",
            expected_date="2026-07-28",
            missing=["A.KS", "B.KS"],
        ),
    ]
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\nnot-json\n",
        encoding="utf-8",
    )

    report = build_report(path)

    assert report["profile"]["row_count"] == len(rows)
    assert report["profile"]["parse_error_count"] == 1
    assert report["summary"]["blocked_dates"] == ["2026-07-28", "2026-07-29"]

    by_date = {row["observation_date"]: row for row in report["date_reports"]}
    assert by_date["2026-07-29"]["gap_classification"] == "PERSISTENT_TICKER_GAP"
    assert by_date["2026-07-29"]["missing_ticker_counts"] == {"153131.KS": 3}
    assert by_date["2026-07-28"]["missing_observation_count"] == 2
    assert by_date["2026-07-28"]["data_freshness_rate"] == 0.5
    assert by_date["2026-07-28"]["cell_freshness_rate"] == 0.75
    assert by_date["2026-07-28"]["expected_dates"] == ["2026-07-28"]
    assert "never rewrites" in report["summary"]["evidence_policy"]
