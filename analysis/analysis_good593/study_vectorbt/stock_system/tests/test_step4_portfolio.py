"""Step 4 — 자금 배분 단위 테스트 (portfolio.py)

검증 항목:
  - build_size_df(): 3단계 배분 시나리오
      Case 1: 신호 없음 → 전체 NaN
      Case 2: 합계 ≤ 100% → 각자 목표비중 그대로
      Case 3: 합계 > 100% → 합계 = 1.0으로 정규화
  - MOMENTUM_WINDOW 상수 (UPTREND:126, TRANSITION:63, SIDEWAYS:21)
  - add_cash_etf(): ETF 주차 동작
      신호 없음(ffill=0) → ETF 100%
      주식 40% → ETF 60%
      주식 100% → ETF NaN
      잔여 < 1% → ETF NaN
      hold 구간 → 이전 포지션 반영
"""

import numpy as np
import pandas as pd
import pytest

from stock_system.portfolio import build_size_df, add_cash_etf


# ── 상수 검증 ─────────────────────────────────────────────────────────────────

class TestConstants:
    def test_momentum_window(self):
        from stock_system.profiles import neutral
        assert neutral.MOMENTUM_WINDOW == {"UPTREND": 126, "TRANSITION": 63, "SIDEWAYS": 21}

    def test_fees_slippage(self):
        from stock_system.profiles import neutral
        assert neutral.FEES    == 0.0015
        assert neutral.SLIPPAGE == 0.001

    def test_entry_sizes(self):
        from stock_system.profiles import neutral
        assert neutral.ENTRY1_SIZE      == 0.4
        assert neutral.ENTRY2_SIZE      == 0.7
        assert neutral.ENTRY_RANGE_SIZE == 0.3


# ── build_size_df ─────────────────────────────────────────────────────────────

class TestBuildSizeDf:
    def test_nan_rows_exist_for_no_signal(self, dates, uptrend_ohlc, neutral_profile):
        """신호 없는 날 → 해당 종목 NaN (Case 1: 전체 NaN 행 존재)"""
        close, high, low = uptrend_ohlc
        close_df = pd.DataFrame({"A": close})
        high_df  = pd.DataFrame({"A": high})
        low_df   = pd.DataFrame({"A": low})

        size_df, _ = build_size_df(neutral_profile, close_df, high_df, low_df)
        # warmup 구간 전체 NaN 행 존재 (MA120 준비 전)
        all_nan_rows = size_df.isna().all(axis=1)
        assert all_nan_rows.sum() > 0, "NaN 행이 전혀 없음"

    def test_single_stock_total_never_exceeds_one(self, uptrend_ohlc, neutral_profile):
        """단일 종목: 총 비중이 1.0을 초과하지 않음"""
        close, high, low = uptrend_ohlc
        close_df = pd.DataFrame({"A": close})
        high_df  = pd.DataFrame({"A": high})
        low_df   = pd.DataFrame({"A": low})

        size_df, _ = build_size_df(neutral_profile, close_df, high_df, low_df)
        positive_rows = (size_df > 0).any(axis=1)
        if positive_rows.sum() == 0:
            pytest.skip("양수 신호 없음")
        totals = size_df[positive_rows].sum(axis=1)
        assert (totals <= 1.0 + 1e-6).all()

    def test_single_stock_entry1_preserves_size(self, uptrend_ohlc, neutral_profile):
        """단일 종목 entry1: 합계 0.4 ≤ 1.0 → size 그대로 0.4 (Case 2)"""
        from stock_system.profiles.neutral import make_signals
        close, high, low = uptrend_ohlc
        close_df = pd.DataFrame({"A": close})
        high_df  = pd.DataFrame({"A": high})
        low_df   = pd.DataFrame({"A": low})

        size_df, _ = build_size_df(neutral_profile, close_df, high_df, low_df)
        _, _, size_raw, detail = make_signals(close, high, low, use_adx_mode=True)

        entry1_only = detail["entry1"] & ~detail["atr_stop"]
        if entry1_only.sum() == 0:
            pytest.skip("entry1(atr_stop 제외) 없음")

        result = size_df.loc[entry1_only, "A"].dropna()
        if result.empty:
            pytest.skip("해당 날의 size 없음")
        assert (result == 0.4).all()

    def test_dual_stock_total_never_exceeds_one(self, uptrend_ohlc, neutral_profile):
        """두 종목: 동일 신호가 겹쳐도 총 비중 ≤ 1.0 (Case 3 정규화)"""
        close, high, low = uptrend_ohlc
        close_df = pd.DataFrame({"A": close, "B": close})
        high_df  = pd.DataFrame({"A": high,  "B": high})
        low_df   = pd.DataFrame({"A": low,   "B": low})

        size_df, _ = build_size_df(neutral_profile, close_df, high_df, low_df)
        both_positive = (size_df > 0).all(axis=1)
        if both_positive.sum() == 0:
            pytest.skip("두 종목 동시 양수 신호 없음")
        totals = size_df[both_positive].sum(axis=1)
        assert (totals <= 1.0 + 1e-6).all(), "두 종목 합계가 1.0 초과"

    def test_dual_stock_equal_weight_when_identical(self, uptrend_ohlc, neutral_profile):
        """두 동일 종목 overflow: 각각 0.5 (동일 모멘텀 → 50:50 분배)"""
        close, high, low = uptrend_ohlc
        close_df = pd.DataFrame({"A": close, "B": close})
        high_df  = pd.DataFrame({"A": high,  "B": high})
        low_df   = pd.DataFrame({"A": low,   "B": low})

        size_df, _ = build_size_df(neutral_profile, close_df, high_df, low_df)
        # entry2 overflow: 0.7 + 0.7 = 1.4 > 1.0 → 각각 0.5
        overflow_mask = (size_df > 0).all(axis=1) & (size_df.sum(axis=1).round(4) == 1.0)
        if overflow_mask.sum() == 0:
            pytest.skip("overflow(정규화) 행 없음")
        assert (size_df.loc[overflow_mask, "A"] - size_df.loc[overflow_mask, "B"]).abs().max() < 1e-6

    def test_signal_info_returned(self, uptrend_ohlc, neutral_profile):
        """signal_info dict 반환 확인"""
        close, high, low = uptrend_ohlc
        close_df = pd.DataFrame({"A": close})
        high_df  = pd.DataFrame({"A": high})
        low_df   = pd.DataFrame({"A": low})

        _, signal_info = build_size_df(neutral_profile, close_df, high_df, low_df)
        assert "A" in signal_info
        assert "진입 횟수" in signal_info["A"]
        assert "1차 익절"  in signal_info["A"]
        assert "2차 청산"  in signal_info["A"]


# ── add_cash_etf ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def etf_fixtures(dates):
    """add_cash_etf 테스트용 수동 구성 DataFrame (5일)"""
    idx = dates[:5]
    # 5일: NaN, 0.4, NaN, 0.7, 0.1
    size_df  = pd.DataFrame({"A": [np.nan, 0.4, np.nan, 0.7, 0.1]}, index=idx)
    close_df = pd.DataFrame({"A": [100.0] * 5}, index=idx)
    high_df  = close_df.copy()
    low_df   = close_df.copy()
    etf_price = pd.Series([1000.0] * 5, index=idx)
    return size_df, close_df, high_df, low_df, etf_price


class TestAddCashEtf:
    def test_etf_column_added(self, etf_fixtures):
        size_df, close_df, high_df, low_df, etf_price = etf_fixtures
        size_out, close_out, _, _ = add_cash_etf(size_df, close_df, high_df, low_df, etf_price)
        assert "단기채" in size_out.columns
        assert "단기채" in close_out.columns

    def test_original_columns_preserved(self, etf_fixtures):
        size_df, close_df, high_df, low_df, etf_price = etf_fixtures
        size_out, close_out, _, _ = add_cash_etf(size_df, close_df, high_df, low_df, etf_price)
        assert "A" in size_out.columns
        assert "A" in close_out.columns

    def test_no_signal_day_etf_full(self, etf_fixtures):
        """Day 0: 주식 NaN (ffill→0) → ETF = 1.0"""
        size_df, close_df, high_df, low_df, etf_price = etf_fixtures
        size_out, _, _, _ = add_cash_etf(size_df, close_df, high_df, low_df, etf_price)
        assert abs(size_out["단기채"].iloc[0] - 1.0) < 1e-6

    def test_entry_day_etf_complement(self, etf_fixtures):
        """Day 1: 주식 0.4 → ETF = 0.6"""
        size_df, close_df, high_df, low_df, etf_price = etf_fixtures
        size_out, _, _, _ = add_cash_etf(size_df, close_df, high_df, low_df, etf_price)
        assert abs(size_out["단기채"].iloc[1] - 0.6) < 1e-6

    def test_hold_day_etf_uses_ffill(self, etf_fixtures):
        """Day 2: 주식 NaN(hold, ffill=0.4) → ETF = 0.6"""
        size_df, close_df, high_df, low_df, etf_price = etf_fixtures
        size_out, _, _, _ = add_cash_etf(size_df, close_df, high_df, low_df, etf_price)
        assert abs(size_out["단기채"].iloc[2] - 0.6) < 1e-6

    def test_high_position_day_etf_small(self, etf_fixtures):
        """Day 3: 주식 0.7 → ETF = 0.3"""
        size_df, close_df, high_df, low_df, etf_price = etf_fixtures
        size_out, _, _, _ = add_cash_etf(size_df, close_df, high_df, low_df, etf_price)
        assert abs(size_out["단기채"].iloc[3] - 0.3) < 1e-6

    def test_min_weight_threshold(self, dates):
        """잔여 < min_weight(1%) → ETF NaN"""
        idx = dates[:3]
        # 주식 0.995: 잔여 0.005 < 0.01 → NaN
        size_df  = pd.DataFrame({"A": [0.995, 0.995, 0.995]}, index=idx)
        close_df = pd.DataFrame({"A": [100.0] * 3}, index=idx)
        etf_price = pd.Series([1000.0] * 3, index=idx)
        size_out, _, _, _ = add_cash_etf(size_df, close_df, close_df.copy(),
                                          close_df.copy(), etf_price, min_weight=0.01)
        assert size_out["단기채"].isna().all(), "잔여 < 1%일 때 ETF NaN이어야 함"

    def test_full_position_etf_nan(self, dates):
        """주식 합계 ≥ 100% → ETF NaN"""
        idx = dates[:3]
        size_df  = pd.DataFrame({"A": [0.6, 0.6, 0.6], "B": [0.5, 0.5, 0.5]}, index=idx)
        close_df = pd.DataFrame({"A": [100.0]*3, "B": [200.0]*3}, index=idx)
        etf_price = pd.Series([1000.0] * 3, index=idx)
        size_out, _, _, _ = add_cash_etf(size_df, close_df, close_df.copy(),
                                          close_df.copy(), etf_price)
        assert size_out["단기채"].isna().all(), "주식 합계 100% 초과 → ETF NaN"

    def test_etf_close_aligned_to_index(self, etf_fixtures):
        """ETF 종가가 close_df 인덱스에 맞게 정렬됨"""
        size_df, close_df, high_df, low_df, etf_price = etf_fixtures
        _, close_out, _, _ = add_cash_etf(size_df, close_df, high_df, low_df, etf_price)
        assert (close_out["단기채"] == 1000.0).all()
