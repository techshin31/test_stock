import json

from core.analytics.operational_incident_evidence import build_report


def test_incident_evidence_separates_safety_controls_from_failures(tmp_path):
    path = tmp_path / "health.jsonl"
    rows = [
        {
            "timestamp": "2026-07-31T10:00:00+09:00",
            "operational_status": "ORDER_SUPPRESSION",
            "data_health": {"order_suppressions": {"total": 1, "by_reason": {"PRICE_GUARD_COOLDOWN": 1}}},
        },
        {
            "timestamp": "2026-07-31T10:01:00+09:00",
            "operational_status": "ERROR",
            "last_error": "BROKER_TIMEOUT",
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    report = build_report(path)

    assert report["summary"]["episode_count"] == 2
    assert report["summary"]["safety_control_episode_count"] == 1
    assert report["summary"]["non_safety_episode_count"] == 1
    assert "does not reclassify" in report["summary"]["policy"]
