from datetime import date, datetime
import json
from zoneinfo import ZoneInfo

from core.utils.wics_sector_refresh import (
    _reusable_refresh_result,
    _status_payload,
    required_wics_session_date,
)


KST = ZoneInfo("Asia/Seoul")


def test_required_wics_session_uses_previous_session_before_post_close_window():
    now = datetime(2026, 7, 30, 15, 39, tzinfo=KST)

    assert required_wics_session_date(now).isoformat() == "2026-07-29"


def test_required_wics_session_uses_current_session_after_post_close_window():
    now = datetime(2026, 7, 30, 15, 40, tzinfo=KST)

    assert required_wics_session_date(now).isoformat() == "2026-07-30"


def test_required_wics_session_skips_known_krx_holiday():
    now = datetime(2026, 7, 17, 16, 0, tzinfo=KST)

    assert required_wics_session_date(now).isoformat() == "2026-07-16"


def test_status_payload_exposes_partial_constituent_quality():
    payload = _status_payload(
        status="READY",
        target_date=date(2026, 7, 30),
        sector_state={
            "latest_date": date(2026, 7, 30),
            "industry_count": 25,
        },
        refresh_result={
            "snapshot_dates_saved": 1,
            "price_refresh": {
                "failed_stock_codes": ["074610", "000300"],
                "derived_rows": 25,
                "derived_rebuild_status": "PARTIAL_INPUT",
            },
        },
    )

    assert payload["status"] == "READY"
    assert payload["input_quality"] == {
        "status": "PARTIAL",
        "failed_stock_count": 2,
        "failed_stock_codes": ["074610", "000300"],
        "derived_rows": 25,
        "coverage_guard": "PER_INDUSTRY_MINIMUM",
        "minimum_industry_coverage": 0.8,
    }


def test_same_session_refresh_preserves_validated_input_quality(tmp_path):
    status_path = tmp_path / "wics_sector_refresh_status.json"
    refresh_result = {
        "snapshot_dates_saved": 0,
        "price_refresh": {
            "failed_stock_codes": ["074610"],
            "derived_rows": 25,
            "derived_rebuild_status": "PARTIAL_INPUT",
        },
    }
    status_path.write_text(
        json.dumps(
            {
                "target_date": "2026-07-30",
                "refresh_result": refresh_result,
                "input_quality": {"status": "PARTIAL"},
            }
        ),
        encoding="utf-8",
    )

    assert _reusable_refresh_result(
        status_path,
        date(2026, 7, 30),
    ) == refresh_result
    assert _reusable_refresh_result(
        status_path,
        date(2026, 7, 31),
    ) is None
