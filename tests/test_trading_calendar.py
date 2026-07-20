from datetime import date

import pytest

from core.utils.trading_calendar import (
    is_krx_trading_day,
    previous_krx_trading_day,
)


def test_2026_constitution_day_is_not_a_krx_session():
    assert is_krx_trading_day("2026-07-17") is False
    assert previous_krx_trading_day(date(2026, 7, 20)) == date(2026, 7, 16)


def test_additional_holiday_can_be_configured_without_deploy(monkeypatch):
    monkeypatch.setenv("KRX_ADDITIONAL_HOLIDAYS", "2026-08-03")
    assert is_krx_trading_day("2026-08-03") is False


def test_invalid_additional_holiday_fails_closed(monkeypatch):
    monkeypatch.setenv("KRX_ADDITIONAL_HOLIDAYS", "03-08-2026")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        is_krx_trading_day("2026-08-03")
