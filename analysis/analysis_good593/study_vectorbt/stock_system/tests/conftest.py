"""공통 테스트 픽스처 — 순수 추세/횡보 합성 OHLC 데이터 제공"""

import numpy as np
import pandas as pd
import pytest


N = 400  # warmup 120일 + 실제 검증 280일


@pytest.fixture(scope="session")
def dates():
    return pd.date_range("2020-01-02", periods=N, freq="B")


@pytest.fixture(scope="session")
def uptrend_ohlc(dates):
    """순수 상승 추세 — 0.5%/일, MA정배열 + ADX 높음(→100)"""
    t     = np.arange(N)
    close = pd.Series(100.0 * 1.005 ** t, index=dates, name="test")
    high  = close * 1.005
    low   = close * 0.995
    return close, high, low


@pytest.fixture(scope="session")
def downtrend_ohlc(dates):
    """순수 하락 추세 — -0.5%/일, MA역배열 + ADX 높음(→100)"""
    t     = np.arange(N)
    close = pd.Series(100.0 * 0.995 ** t, index=dates, name="test")
    high  = close * 1.005
    low   = close * 0.995
    return close, high, low


@pytest.fixture(scope="session")
def sideways_ohlc(dates):
    """횡보 — 사인파 + 노이즈, ADX 낮음(SIDEWAYS 유발), BB 돌파 포함"""
    rng   = np.random.default_rng(7)
    t     = np.arange(N)
    noise = rng.normal(0, 2.5, N)   # 노이즈로 BB 하단 돌파 유발
    close = pd.Series(
        np.clip(100.0 + 5.0 * np.sin(2 * np.pi * t / 10) + noise, 70, None),
        index=dates, name="test",
    )
    high  = close * 1.003
    low   = close * 0.997
    return close, high, low


@pytest.fixture(scope="session")
def mixed_ohlc(dates):
    """상승 200일 → 급락(-10%) → 하락 200일
    ATR stop / dead_cross / transition_from_up 신호 유발용"""
    t     = np.arange(N)
    half  = N // 2

    up_prices   = 100.0 * 1.005 ** t[:half]
    crash_price = up_prices[-1] * 0.90   # -10% 급락
    dn_prices   = crash_price * 0.997 ** np.arange(N - half)

    close = pd.Series(np.concatenate([up_prices, dn_prices]), index=dates, name="test")
    high  = close * 1.005
    low   = close * 0.995
    return close, high, low


@pytest.fixture(scope="session")
def kospi_up(dates):
    """상승 KOSPI — KOSPI_MA60 위 → UPTREND 허용"""
    t = np.arange(N)
    return pd.Series(2000.0 * 1.003 ** t, index=dates, name="KOSPI")


@pytest.fixture(scope="session")
def kospi_down(dates):
    """하락 KOSPI — KOSPI_MA60 아래 → UPTREND 차단"""
    t = np.arange(N)
    return pd.Series(2000.0 * 0.997 ** t, index=dates, name="KOSPI")


@pytest.fixture(scope="session")
def neutral_profile():
    from stock_system.profiles import neutral
    return neutral
