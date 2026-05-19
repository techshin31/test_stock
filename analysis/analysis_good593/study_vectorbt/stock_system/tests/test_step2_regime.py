"""Step 2 — 시장 국면 판별 단위 테스트 (strategies/regime.py)

검증 항목:
  - 4국면 상호 배타성 (하루에 정확히 1개 국면)
  - ADX 모드: SIDEWAYS/UPTREND/DOWNTREND/TRANSITION 조건
  - 판별 우선순위: SIDEWAYS > DOWNTREND
  - MA+KOSPI 모드: SIDEWAYS 미존재
  - KOSPI_MA60 필터: UPTREND 차단
"""

import numpy as np
import pandas as pd
import pytest

from stock_system.strategies.regime import calc_regime


# ── 4국면 상호 배타성 ─────────────────────────────────────────────────────────

class TestMutualExclusivity:
    def test_uptrend_mutual_exclusivity(self, uptrend_ohlc, kospi_up):
        close, high, low = uptrend_ohlc
        _, masks, _ = calc_regime(close, high, low, kospi=kospi_up, use_adx_mode=True)
        overlap = (
            masks["UPTREND"].astype(int)
            + masks["DOWNTREND"].astype(int)
            + masks["SIDEWAYS"].astype(int)
            + masks["TRANSITION"].astype(int)
        )
        assert (overlap == 1).all(), "하루에 정확히 1개 국면이어야 함"

    def test_downtrend_mutual_exclusivity(self, downtrend_ohlc, kospi_up):
        close, high, low = downtrend_ohlc
        _, masks, _ = calc_regime(close, high, low, kospi=kospi_up, use_adx_mode=True)
        overlap = (
            masks["UPTREND"].astype(int)
            + masks["DOWNTREND"].astype(int)
            + masks["SIDEWAYS"].astype(int)
            + masks["TRANSITION"].astype(int)
        )
        assert (overlap == 1).all()

    def test_sideways_mutual_exclusivity(self, sideways_ohlc):
        close, high, low = sideways_ohlc
        _, masks, _ = calc_regime(close, high, low, use_adx_mode=True)
        overlap = (
            masks["UPTREND"].astype(int)
            + masks["DOWNTREND"].astype(int)
            + masks["SIDEWAYS"].astype(int)
            + masks["TRANSITION"].astype(int)
        )
        assert (overlap == 1).all()


# ── ADX 모드 — 국면별 조건 ────────────────────────────────────────────────────

class TestADXMode:
    def test_uptrend_detected_in_uptrend_data(self, uptrend_ohlc, kospi_up):
        """순수 상승 추세: warmup 후 UPTREND 국면 존재"""
        close, high, low = uptrend_ohlc
        _, masks, _ = calc_regime(close, high, low, kospi=kospi_up, use_adx_mode=True)
        assert masks["UPTREND"].iloc[150:].sum() > 0, "상승 추세 데이터에서 UPTREND 미검출"

    def test_uptrend_ma_condition(self, uptrend_ohlc, kospi_up):
        """UPTREND 국면: MA정배열 (MA20 > MA60 > MA120) 확인"""
        close, high, low = uptrend_ohlc
        _, masks, _ = calc_regime(close, high, low, kospi=kospi_up, use_adx_mode=True)
        uptrend_days = masks["UPTREND"]
        if uptrend_days.sum() == 0:
            pytest.skip("UPTREND 국면 없음")
        assert (masks["ma_s"][uptrend_days] > masks["ma_m"][uptrend_days]).all()
        assert (masks["ma_m"][uptrend_days] > masks["ma_l"][uptrend_days]).all()

    def test_uptrend_adx_condition(self, uptrend_ohlc, kospi_up):
        """UPTREND 국면: ADX > threshold (25)"""
        close, high, low = uptrend_ohlc
        _, masks, adx_df = calc_regime(
            close, high, low, kospi=kospi_up,
            adx_threshold=25.0, adx_sideways=20.0, use_adx_mode=True,
        )
        uptrend_days = masks["UPTREND"]
        if uptrend_days.sum() == 0:
            pytest.skip("UPTREND 국면 없음")
        assert (adx_df["ADX"][uptrend_days] > 25.0).all()

    def test_downtrend_detected_in_downtrend_data(self, downtrend_ohlc, kospi_up):
        """순수 하락 추세: warmup 후 DOWNTREND 국면 존재"""
        close, high, low = downtrend_ohlc
        _, masks, _ = calc_regime(close, high, low, kospi=kospi_up, use_adx_mode=True)
        assert masks["DOWNTREND"].iloc[150:].sum() > 0, "하락 추세 데이터에서 DOWNTREND 미검출"

    def test_downtrend_ma_condition(self, downtrend_ohlc, kospi_up):
        """DOWNTREND 국면: MA역배열 (MA20 < MA60 < MA120)"""
        close, high, low = downtrend_ohlc
        _, masks, _ = calc_regime(close, high, low, kospi=kospi_up, use_adx_mode=True)
        downtrend_days = masks["DOWNTREND"]
        if downtrend_days.sum() == 0:
            pytest.skip("DOWNTREND 국면 없음")
        assert (masks["ma_s"][downtrend_days] < masks["ma_m"][downtrend_days]).all()
        assert (masks["ma_m"][downtrend_days] < masks["ma_l"][downtrend_days]).all()

    def test_sideways_adx_condition(self, sideways_ohlc):
        """SIDEWAYS 국면: ADX < adx_sideways (20)"""
        close, high, low = sideways_ohlc
        _, masks, adx_df = calc_regime(
            close, high, low,
            adx_threshold=25.0, adx_sideways=20.0, use_adx_mode=True,
        )
        sideways_days = masks["SIDEWAYS"]
        if sideways_days.sum() == 0:
            pytest.skip("SIDEWAYS 국면 없음")
        adx_on_sideways = adx_df["ADX"][sideways_days].dropna()
        assert (adx_on_sideways < 20.0).all()

    def test_sideways_detected_in_oscillating_data(self, sideways_ohlc):
        """횡보 데이터: warmup 후 SIDEWAYS 국면 존재"""
        close, high, low = sideways_ohlc
        _, masks, _ = calc_regime(close, high, low, use_adx_mode=True)
        assert masks["SIDEWAYS"].iloc[100:].sum() > 0, "횡보 데이터에서 SIDEWAYS 미검출"


# ── 판별 우선순위 ─────────────────────────────────────────────────────────────

class TestRegimePriority:
    def test_sideways_excludes_downtrend(self, sideways_ohlc):
        """SIDEWAYS 국면 날 → DOWNTREND 동시 불가"""
        close, high, low = sideways_ohlc
        _, masks, _ = calc_regime(close, high, low, use_adx_mode=True)
        sideways_days = masks["SIDEWAYS"]
        assert masks["DOWNTREND"][sideways_days].sum() == 0

    def test_sideways_excludes_uptrend(self, sideways_ohlc):
        """SIDEWAYS 국면 날 → UPTREND 동시 불가"""
        close, high, low = sideways_ohlc
        _, masks, _ = calc_regime(close, high, low, use_adx_mode=True)
        sideways_days = masks["SIDEWAYS"]
        assert masks["UPTREND"][sideways_days].sum() == 0

    def test_sideways_excludes_transition(self, sideways_ohlc):
        """SIDEWAYS와 TRANSITION은 정의상 상호 배타 (TRANSITION = ~SIDEWAYS & ...)"""
        close, high, low = sideways_ohlc
        _, masks, _ = calc_regime(close, high, low, use_adx_mode=True)
        sideways_days = masks["SIDEWAYS"]
        assert masks["TRANSITION"][sideways_days].sum() == 0

    def test_masks_contain_required_keys(self, uptrend_ohlc, kospi_up):
        close, high, low = uptrend_ohlc
        _, masks, _ = calc_regime(close, high, low, kospi=kospi_up)
        required = {"UPTREND", "DOWNTREND", "SIDEWAYS", "TRANSITION", "ma_s", "ma_m", "ma_l", "adx"}
        assert required.issubset(set(masks.keys()))


# ── MA+KOSPI 모드 ─────────────────────────────────────────────────────────────

class TestMAKospiMode:
    def test_no_sideways_in_ma_kospi_mode(self, uptrend_ohlc, kospi_up):
        """MA+KOSPI 모드: SIDEWAYS 국면 없음"""
        close, high, low = uptrend_ohlc
        _, masks, _ = calc_regime(close, high, low, kospi=kospi_up, use_adx_mode=False)
        assert masks["SIDEWAYS"].sum() == 0, "MA+KOSPI 모드에서 SIDEWAYS가 존재하면 안 됨"

    def test_uptrend_exists_in_ma_kospi_mode(self, uptrend_ohlc, kospi_up):
        """MA+KOSPI 모드: 상승 추세 데이터에서 UPTREND 검출"""
        close, high, low = uptrend_ohlc
        _, masks, _ = calc_regime(close, high, low, kospi=kospi_up, use_adx_mode=False)
        assert masks["UPTREND"].iloc[150:].sum() > 0

    def test_downtrend_exists_in_ma_kospi_mode(self, downtrend_ohlc, kospi_up):
        """MA+KOSPI 모드: 하락 추세 데이터에서 DOWNTREND 검출"""
        close, high, low = downtrend_ohlc
        _, masks, _ = calc_regime(close, high, low, kospi=kospi_up, use_adx_mode=False)
        assert masks["DOWNTREND"].iloc[150:].sum() > 0

    def test_ma_kospi_mutual_exclusivity(self, uptrend_ohlc, kospi_up):
        """MA+KOSPI 모드에서도 4국면 상호 배타성 유지"""
        close, high, low = uptrend_ohlc
        _, masks, _ = calc_regime(close, high, low, kospi=kospi_up, use_adx_mode=False)
        overlap = (
            masks["UPTREND"].astype(int)
            + masks["DOWNTREND"].astype(int)
            + masks["SIDEWAYS"].astype(int)
            + masks["TRANSITION"].astype(int)
        )
        assert (overlap == 1).all()


# ── KOSPI 필터 ────────────────────────────────────────────────────────────────

class TestKospiFilter:
    def test_kospi_down_reduces_uptrend(self, uptrend_ohlc, kospi_up, kospi_down):
        """하락 KOSPI → MA정배열 + ADX 충족해도 UPTREND 차단"""
        close, high, low = uptrend_ohlc
        _, masks_up, _   = calc_regime(close, high, low, kospi=kospi_up,   use_adx_mode=True)
        _, masks_down, _ = calc_regime(close, high, low, kospi=kospi_down, use_adx_mode=True)
        uptrend_with    = masks_up["UPTREND"].sum()
        uptrend_without = masks_down["UPTREND"].sum()
        assert uptrend_without < uptrend_with, "하락 KOSPI가 UPTREND를 차단해야 함"

    def test_kospi_down_blocked_days_become_transition(self, uptrend_ohlc, kospi_down):
        """KOSPI 차단으로 인해 UPTREND → TRANSITION 전환"""
        close, high, low = uptrend_ohlc
        _, masks_no_k, _ = calc_regime(close, high, low, use_adx_mode=True)
        _, masks_with_k, _ = calc_regime(close, high, low, kospi=kospi_down, use_adx_mode=True)

        # KOSPI 없으면 UPTREND였던 날이 KOSPI 적용 후 TRANSITION이 되어야 함
        was_uptrend = masks_no_k["UPTREND"]
        now_transition = masks_with_k["TRANSITION"]
        blocked = was_uptrend & now_transition
        # 순수 상승 추세 + 하락 KOSPI → 모든 UPTREND가 차단됨
        if masks_no_k["UPTREND"].sum() > 0:
            assert blocked.sum() > 0, "KOSPI 차단으로 일부 날이 TRANSITION이 되어야 함"

    def test_no_kospi_filter_allows_more_uptrend(self, uptrend_ohlc):
        """KOSPI 필터 없으면 UPTREND 더 많이 발생"""
        close, high, low = uptrend_ohlc
        _, masks_no_k, _ = calc_regime(close, high, low, kospi=None, use_adx_mode=True)
        # KOSPI 없이도 상승 추세에서 UPTREND 검출
        assert masks_no_k["UPTREND"].iloc[150:].sum() > 0
