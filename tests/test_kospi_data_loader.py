import pandas as pd
import pytest

from data.loaders import kospi_data


def test_download_multiple_stocks_retries_only_the_initial_failures(monkeypatch):
    calls = []
    attempts = {"000001.KS": 0, "000002.KS": 0}

    def fake_download(ticker, _start, _end):
        calls.append(ticker)
        attempts[ticker] += 1
        if ticker == "000002.KS" and attempts[ticker] == 1:
            return None
        return pd.DataFrame({"close": [100.0]})

    monkeypatch.setattr(kospi_data, "download_stock_ohlcv", fake_download)
    monkeypatch.setattr(kospi_data.time, "sleep", lambda _seconds: None)

    result = kospi_data.download_multiple_stocks(
        ["000001.KS", "000002.KS", "000001.KS"],
        start="2026-07-01",
        end="2026-07-29",
        show_progress=False,
        sleep_seconds=0,
        retry_backoff_seconds=0,
    )

    assert sorted(result) == ["000001.KS", "000002.KS"]
    assert calls == ["000001.KS", "000002.KS", "000002.KS"]


def test_download_multiple_stocks_rejects_invalid_retry_configuration():
    with pytest.raises(ValueError, match="retry_attempts"):
        kospi_data.download_multiple_stocks(
            [], "2026-07-01", "2026-07-29", retry_attempts=-1
        )
