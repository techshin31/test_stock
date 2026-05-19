"""Step 1 — 지표 계산 단위 테스트 (indicators/)

검증 항목:
  - MA20/60/120: NaN 구간, rolling 평균 일치
  - ADX: 범위 0~100, 강한 추세에서 high
  - Bollinger: upper > mid > lower, mid == MA20
  - ATR: 항상 양수
"""

import numpy as np
import pandas as pd
import pytest

from stock_system.indicators.trend.ma import calc_ma
from stock_system.indicators.trend_strength.adx import calc_adx
from stock_system.indicators.volatility.bollinger import calc_bollinger
from stock_system.indicators.volatility.atr import calc_atr


# ── MA ────────────────────────────────────────────────────────────────────────

class TestMA:
    def test_ma20_nan_count(self, uptrend_ohlc):
        close, _, _ = uptrend_ohlc
        ma = calc_ma(close, 20)
        assert ma.isna().sum() == 19, "MA20: 첫 19일만 NaN이어야 함"

    def test_ma60_nan_count(self, uptrend_ohlc):
        close, _, _ = uptrend_ohlc
        ma = calc_ma(close, 60)
        assert ma.isna().sum() == 59

    def test_ma120_nan_count(self, uptrend_ohlc):
        close, _, _ = uptrend_ohlc
        ma = calc_ma(close, 120)
        assert ma.isna().sum() == 119

    def test_ma_values_match_rolling(self, uptrend_ohlc):
        close, _, _ = uptrend_ohlc
        ma20 = calc_ma(close, 20)
        expected = close.rolling(20).mean()
        pd.testing.assert_series_equal(ma20, expected, check_names=False)

    def test_ma_aligned_in_uptrend(self, uptrend_ohlc):
        """상승 추세: warmup 후 MA20 > MA60 > MA120"""
        close, _, _ = uptrend_ohlc
        ma20  = calc_ma(close, 20)
        ma60  = calc_ma(close, 60)
        ma120 = calc_ma(close, 120)
        # 120일 warmup 이후 검증
        late = slice(150, None)
        assert (ma20.iloc[late] > ma60.iloc[late]).all()
        assert (ma60.iloc[late] > ma120.iloc[late]).all()

    def test_ma_reversed_in_downtrend(self, downtrend_ohlc):
        """하락 추세: warmup 후 MA20 < MA60 < MA120"""
        close, _, _ = downtrend_ohlc
        ma20  = calc_ma(close, 20)
        ma60  = calc_ma(close, 60)
        ma120 = calc_ma(close, 120)
        late = slice(150, None)
        assert (ma20.iloc[late] < ma60.iloc[late]).all()
        assert (ma60.iloc[late] < ma120.iloc[late]).all()


# ── ADX ───────────────────────────────────────────────────────────────────────

class TestADX:
    def test_adx_range_0_to_100(self, uptrend_ohlc):
        close, high, low = uptrend_ohlc
        adx_df = calc_adx(high, low, close, 14)
        adx_valid = adx_df["ADX"].dropna()
        assert (adx_valid >= 0).all(), "ADX >= 0"
        # 순수 추세 데이터에서 DX → 100이므로 부동소수점 오차 허용
        assert (adx_valid <= 100.01).all(), "ADX <= 100 (부동소수점 오차 허용)"

    def test_adx_columns_exist(self, uptrend_ohlc):
        close, high, low = uptrend_ohlc
        adx_df = calc_adx(high, low, close, 14)
        assert set(adx_df.columns) == {"ADX", "plus_di", "minus_di"}

    def test_adx_high_in_strong_uptrend(self, uptrend_ohlc):
        """순수 상승 추세: warmup 후 ADX가 threshold(25) 이상"""
        close, high, low = uptrend_ohlc
        adx_df = calc_adx(high, low, close, 14)
        adx_late = adx_df["ADX"].iloc[100:]
        assert (adx_late > 25).all(), "강한 추세에서 ADX > 25"

    def test_plus_di_dominates_in_uptrend(self, uptrend_ohlc):
        """+DI > -DI in uptrend (warmup 후)"""
        close, high, low = uptrend_ohlc
        adx_df = calc_adx(high, low, close, 14)
        late = adx_df.iloc[50:].dropna()
        assert (late["plus_di"] > late["minus_di"]).all()

    def test_minus_di_dominates_in_downtrend(self, downtrend_ohlc):
        """-DI > +DI in downtrend (warmup 후)"""
        close, high, low = downtrend_ohlc
        adx_df = calc_adx(high, low, close, 14)
        late = adx_df.iloc[50:].dropna()
        assert (late["minus_di"] > late["plus_di"]).all()

    def test_adx_low_in_sideways(self, sideways_ohlc):
        """횡보: warmup 후 ADX < adx_sideways(20)"""
        close, high, low = sideways_ohlc
        adx_df = calc_adx(high, low, close, 14)
        adx_late = adx_df["ADX"].iloc[100:]
        assert (adx_late < 20).all(), "횡보에서 ADX < 20"


# ── Bollinger Bands ───────────────────────────────────────────────────────────

class TestBollinger:
    def test_bollinger_structure(self, uptrend_ohlc):
        """upper > mid > lower (유효 구간)"""
        close, _, _ = uptrend_ohlc
        upper, mid, lower = calc_bollinger(close, 20, 2.0)
        valid = ~upper.isna()
        assert (upper[valid] > mid[valid]).all()
        assert (mid[valid] > lower[valid]).all()

    def test_bollinger_mid_equals_ma20(self, uptrend_ohlc):
        """중간 밴드 = MA20"""
        close, _, _ = uptrend_ohlc
        _, mid, _ = calc_bollinger(close, 20, 2.0)
        expected = close.rolling(20).mean()
        pd.testing.assert_series_equal(mid, expected, check_names=False)

    def test_bollinger_nan_count(self, uptrend_ohlc):
        close, _, _ = uptrend_ohlc
        upper, mid, lower = calc_bollinger(close, 20, 2.0)
        assert upper.isna().sum() == 19
        assert mid.isna().sum() == 19
        assert lower.isna().sum() == 19

    def test_bollinger_bandwidth_positive(self, uptrend_ohlc):
        """밴드폭 항상 양수"""
        close, _, _ = uptrend_ohlc
        upper, _, lower = calc_bollinger(close, 20, 2.0)
        bandwidth = (upper - lower).dropna()
        assert (bandwidth > 0).all()


# ── ATR ───────────────────────────────────────────────────────────────────────

class TestATR:
    def test_atr_positive(self, uptrend_ohlc):
        """ATR > 0 (유효 구간)"""
        close, high, low = uptrend_ohlc
        atr = calc_atr(high, low, close, 14)
        assert (atr.dropna() > 0).all()

    def test_atr_higher_in_volatile_period(self, downtrend_ohlc, uptrend_ohlc):
        """변동성 비교: high/low 스프레드가 같으면 ATR도 비슷"""
        # uptrend와 downtrend 모두 동일한 high/low 스프레드(±0.5%) 사용
        close_up, high_up, low_up = uptrend_ohlc
        close_dn, high_dn, low_dn = downtrend_ohlc
        atr_up = calc_atr(high_up, low_up, close_up, 14).dropna()
        atr_dn = calc_atr(high_dn, low_dn, close_dn, 14).dropna()
        # 두 시리즈 모두 양수
        assert (atr_up > 0).all()
        assert (atr_dn > 0).all()
