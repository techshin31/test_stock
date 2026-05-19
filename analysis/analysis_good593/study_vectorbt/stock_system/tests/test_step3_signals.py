"""Step 3 — 매수/매도 신호 생성 단위 테스트 (profiles/neutral.py)

검증 항목:
  - 매수 신호 3종: entry1(40%), entry2(70%), entry_range(30%) size 값
  - entry1/entry2 동시 발생 불가
  - entry2: entry1 후 60거래일 이내만 발생
  - DOWNTREND에서 매수 신호 없음
  - 매도 신호 size 값: ATR stop(0%), dead_cross(10%), transition_from_up(40%)
  - ATR stop 최우선: 다른 신호 덮어쓰기
"""

import numpy as np
import pandas as pd
import pytest

from stock_system.profiles.neutral import make_signals


@pytest.fixture(scope="module")
def uptrend_signals(uptrend_ohlc, kospi_up):
    close, high, low = uptrend_ohlc
    return make_signals(close, high, low, kospi=kospi_up, use_adx_mode=True)


@pytest.fixture(scope="module")
def sideways_signals(sideways_ohlc):
    close, high, low = sideways_ohlc
    return make_signals(close, high, low, kospi=None, use_adx_mode=True)


@pytest.fixture(scope="module")
def downtrend_signals(downtrend_ohlc, kospi_up):
    close, high, low = downtrend_ohlc
    return make_signals(close, high, low, kospi=kospi_up, use_adx_mode=True)


@pytest.fixture(scope="module")
def mixed_signals(mixed_ohlc, kospi_up):
    """상승→급락→하락: ATR stop / dead_cross / transition_from_up 포함"""
    close, high, low = mixed_ohlc
    return make_signals(close, high, low, kospi=kospi_up, use_adx_mode=True)


# ── 매수 신호 ─────────────────────────────────────────────────────────────────

class TestBuySignals:
    def test_entry1_fires_in_uptrend(self, uptrend_signals):
        """상승 추세 데이터에서 entry1 신호 발생"""
        _, _, _, detail = uptrend_signals
        assert detail["entry1"].sum() > 0, "상승 추세에서 entry1 신호 없음"

    def test_entry1_size_is_04(self, uptrend_signals):
        """entry1 발생일 → size = 0.4 (40%)"""
        _, _, size_series, detail = uptrend_signals
        entry1 = detail["entry1"] & ~detail["atr_stop"]
        if entry1.sum() == 0:
            pytest.skip("entry1(atr_stop 제외) 없음")
        assert (size_series[entry1] == 0.4).all()

    def test_entry2_size_is_07(self, uptrend_signals):
        """entry2 발생일 → size = 0.7 (70%)"""
        _, _, size_series, detail = uptrend_signals
        entry2 = detail["entry2"] & ~detail["atr_stop"]
        if entry2.sum() == 0:
            pytest.skip("entry2(atr_stop 제외) 없음")
        assert (size_series[entry2] == 0.7).all()

    def test_entry_range_size_is_03(self, sideways_signals):
        """SIDEWAYS BB하단 돌파 → size = 0.3 (30%)
        단, 같은 날 dead_cross가 발생하면 0.1로 덮어씌워지므로 제외"""
        _, _, size_series, detail = sideways_signals
        er = detail["entry_range"] & ~detail["atr_stop"] & ~detail["dead_cross"]
        if er.sum() == 0:
            pytest.skip("entry_range(atr_stop·dead_cross 제외) 없음")
        assert (size_series[er] == 0.3).all()

    def test_no_simultaneous_entry1_entry2(self, uptrend_signals):
        """entry1과 entry2 동시 발생 불가"""
        _, _, _, detail = uptrend_signals
        assert (detail["entry1"] & detail["entry2"]).sum() == 0

    def test_entry2_requires_entry1_within_60days(self, uptrend_signals):
        """entry2: entry1 후 60거래일 이내에만 발생"""
        _, _, _, detail = uptrend_signals
        entry1, entry2 = detail["entry1"], detail["entry2"]
        for d in entry2[entry2].index:
            # d 이전 60 거래일 내 entry1 존재 확인
            window = entry1.loc[:d].iloc[-60:]
            assert window.any(), f"{d}: entry1 없이 entry2 발생"

    def test_entry1_on_first_uptrend_day(self, uptrend_ohlc, kospi_up):
        """entry1 = UPTREND 첫날 (UPTREND & ~UPTREND.shift(1))"""
        close, high, low = uptrend_ohlc
        _, _, _, detail = make_signals(close, high, low, kospi=kospi_up, use_adx_mode=True)
        UPTREND = detail["masks"]["UPTREND"]
        expected_entry1 = UPTREND & ~UPTREND.shift(1).fillna(False)
        pd.testing.assert_series_equal(detail["entry1"], expected_entry1, check_names=False)


# ── DOWNTREND 매수 신호 차단 ──────────────────────────────────────────────────

class TestNoBuyInDowntrend:
    def test_no_entry1_in_downtrend(self, downtrend_signals):
        _, _, _, detail = downtrend_signals
        down = detail["masks"]["DOWNTREND"]
        assert detail["entry1"][down].sum() == 0, "DOWNTREND 날 entry1 발생"

    def test_no_entry2_in_downtrend(self, downtrend_signals):
        _, _, _, detail = downtrend_signals
        down = detail["masks"]["DOWNTREND"]
        assert detail["entry2"][down].sum() == 0, "DOWNTREND 날 entry2 발생"

    def test_no_entry_range_in_downtrend(self, downtrend_signals):
        _, _, _, detail = downtrend_signals
        down = detail["masks"]["DOWNTREND"]
        assert detail["entry_range"][down].sum() == 0, "DOWNTREND 날 entry_range 발생"

    def test_downtrend_size_is_zero(self, downtrend_signals):
        """DOWNTREND 국면: size = 0.0 (전량 청산)"""
        _, _, size_series, detail = downtrend_signals
        down = detail["masks"]["DOWNTREND"]
        downtrend_with_size = down & size_series.notna()
        if downtrend_with_size.sum() == 0:
            pytest.skip("DOWNTREND 날 size 없음")
        assert (size_series[downtrend_with_size] == 0.0).all()


# ── 매도 신호 ─────────────────────────────────────────────────────────────────

class TestSellSignals:
    def test_atr_stop_size_is_zero(self, mixed_signals):
        """ATR stop(급락일) → size = 0.0"""
        _, exits, size_series, detail = mixed_signals
        atr_stop = detail["atr_stop"]
        if atr_stop.sum() == 0:
            pytest.skip("ATR stop 신호 없음 (mixed_ohlc에서 급락 확인 필요)")
        assert (size_series[atr_stop] == 0.0).all()

    def test_atr_stop_included_in_exits(self, mixed_signals):
        """ATR stop 발생일 → exits에 포함"""
        _, exits, _, detail = mixed_signals
        atr_stop = detail["atr_stop"]
        if atr_stop.sum() == 0:
            pytest.skip("ATR stop 신호 없음")
        assert exits[atr_stop].all()

    def test_atr_stop_overrides_other_signals(self, mixed_ohlc, kospi_up):
        """ATR stop이 발생한 날은 항상 0.0 — 다른 신호 무시"""
        close, high, low = mixed_ohlc
        _, _, size_series, detail = make_signals(
            close, high, low, kospi=kospi_up, use_adx_mode=True
        )
        atr_stop = detail["atr_stop"]
        if atr_stop.sum() == 0:
            pytest.skip("ATR stop 신호 없음")
        # ATR stop 발생일: 다른 어떤 신호가 있어도 size = 0.0
        assert (size_series[atr_stop] == 0.0).all()

    def test_dead_cross_size_is_01(self, mixed_signals):
        """데드크로스(MA20 < MA60) → size = 0.1"""
        _, _, size_series, detail = mixed_signals
        # dead_cross 발생 + ATR stop/DOWNTREND 없는 날만 검증
        dc_only = detail["dead_cross"] & ~detail["atr_stop"] & ~detail["masks"]["DOWNTREND"]
        if dc_only.sum() == 0:
            pytest.skip("pure dead_cross(ATR stop·DOWNTREND 제외) 없음")
        assert (size_series[dc_only] == 0.1).all()

    def test_transition_from_up_size_is_04(self, mixed_signals):
        """UPTREND → TRANSITION 첫날 → size = 0.4 (1차 익절)
        단, 같은 날 dead_cross도 발생하면 0.1로 덮어씌워지므로 제외"""
        _, _, size_series, detail = mixed_signals
        tfu = (
            detail["transition_from_up"]
            & ~detail["atr_stop"]
            & ~detail["masks"]["DOWNTREND"]
            & ~detail["dead_cross"]   # dead_cross가 나중에 0.1로 덮어씌움
        )
        if tfu.sum() == 0:
            pytest.skip("transition_from_up(ATR stop·DOWNTREND·dead_cross 제외) 없음")
        assert (size_series[tfu] == 0.4).all()

    def test_bb_exit_sideways_size_is_zero(self, sideways_signals):
        """SIDEWAYS BB상단 하향돌파 → size = 0.0"""
        _, _, size_series, detail = sideways_signals
        bb_exit = detail["bb_exit_sideways"] & ~detail["atr_stop"]
        if bb_exit.sum() == 0:
            pytest.skip("bb_exit_sideways 없음")
        assert (size_series[bb_exit] == 0.0).all()

    def test_dead_cross_included_in_exits(self, mixed_signals):
        """데드크로스 → exits에 포함"""
        _, exits, _, detail = mixed_signals
        dc = detail["dead_cross"]
        if dc.sum() == 0:
            pytest.skip("dead_cross 없음")
        assert exits[dc].all()


# ── 신호 반환 구조 ─────────────────────────────────────────────────────────────

class TestSignalStructure:
    def test_make_signals_returns_four_values(self, uptrend_signals):
        assert len(uptrend_signals) == 4

    def test_size_series_dtype_float(self, uptrend_signals):
        _, _, size_series, _ = uptrend_signals
        assert size_series.dtype == float

    def test_detail_keys_complete(self, uptrend_signals):
        _, _, _, detail = uptrend_signals
        required = {
            "regime", "masks", "adx_df",
            "entry1", "entry2", "entry_range",
            "transition_from_up", "dead_cross", "bb_exit_sideways", "atr_stop",
        }
        assert required.issubset(set(detail.keys()))

    def test_entries_union(self, uptrend_signals):
        """entries = entry1 | entry2 | entry_range"""
        entries, _, _, detail = uptrend_signals
        expected = detail["entry1"] | detail["entry2"] | detail["entry_range"]
        pd.testing.assert_series_equal(entries, expected, check_names=False)

    def test_size_nan_on_no_signal_days(self, uptrend_signals):
        """신호 없는 날 → size = NaN (포지션 유지)"""
        _, _, size_series, detail = uptrend_signals
        UPTREND    = detail["masks"]["UPTREND"]
        DOWNTREND  = detail["masks"]["DOWNTREND"]
        SIDEWAYS   = detail["masks"]["SIDEWAYS"]
        any_signal = detail["entry1"] | detail["entry2"] | detail["entry_range"] | \
                     detail["dead_cross"] | detail["bb_exit_sideways"] | \
                     detail["atr_stop"] | DOWNTREND | detail["transition_from_up"]
        no_signal = ~any_signal
        assert size_series[no_signal].isna().all()
