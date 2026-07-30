from datetime import datetime
from zoneinfo import ZoneInfo

from core.utils.wics_sector_refresh import required_wics_session_date


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
