import json

from core.analytics.operational_data_quality import build_report


def _row(
    timestamp,
    expected_date="2026-07-29",
    missing=None,
    stale=None,
    signal_evaluation=None,
):
    missing = missing or []
    stale = stale or []
    row = {
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
    if signal_evaluation is not None:
        row["data_health"]["signal_evaluation"] = signal_evaluation
    return row


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


def test_build_report_validates_signal_reason_evidence(tmp_path):
    path = tmp_path / "operational_health.jsonl"
    valid = {
        "evaluated_count": 4,
        "selected_count": 1,
        "target_weight_sum": 0.1,
        "reason_counts": {"ENTRY_CONDITIONS_NOT_MET": 3, "TRANSITION_ENTRY": 1},
    }
    invalid = {
        "evaluated_count": 4,
        "selected_count": 5,
        "target_weight_sum": -0.1,
        "reason_counts": {"ENTRY_CONDITIONS_NOT_MET": 2},
    }
    rows = [
        _row("2026-07-29T09:00:00+09:00", signal_evaluation=valid),
        _row("2026-07-29T09:01:00+09:00", signal_evaluation=invalid),
        _row("2026-07-29T09:02:00+09:00"),
    ]
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )

    report = build_report(path)

    signal = report["profile"]["signal_evaluation"]
    assert signal["observed_row_count"] == 2
    assert signal["valid_row_count"] == 1
    assert signal["invalid_row_count"] == 1
    assert signal["coverage_rate"] == 2 / 3
    assert signal["validity_rate"] == 0.5
    assert report["summary"]["signal_evaluation"] == signal
    assert report["date_reports"][0]["signal_evaluation"] == signal
    assert any("selected_count=5" in error for error in signal["errors"])
