"""1단계: 매크로 국면 판단

4가지 국면으로 분류:
    A — Risk-On  + 저금리
    B — Risk-On  + 고금리
    C — Risk-Off + 저금리
    D — Risk-Off + 고금리

구현체:
    BdiCopperMacroSignal — 구리 + BDI 3개월 이동평균 기울기 기반 (기본값)

다른 국면 판단 로직을 실험하려면 BaseMacroSignal 을 상속해 구현한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from ..data.loader_asset import load_asset
from .base import BaseMacroSignal


class Regime(str, Enum):
    A = "A"  # Risk-On  + 저금리
    B = "B"  # Risk-On  + 고금리
    C = "C"  # Risk-Off + 저금리
    D = "D"  # Risk-Off + 고금리

    def is_risk_on(self) -> bool:
        return self in (Regime.A, Regime.B)

    def is_high_rate(self) -> bool:
        return self in (Regime.B, Regime.D)


@dataclass
class MacroSignal:
    """날짜별 매크로 국면 조회 객체."""
    _regime_series: pd.Series  # index=Date, value=Regime

    def get_regime(self, date: pd.Timestamp) -> Regime:
        """date 이전 가장 최근 국면 반환."""
        past = self._regime_series[self._regime_series.index <= date]
        if past.empty:
            return Regime.A
        return past.iloc[-1]

    def to_series(self) -> pd.Series:
        return self._regime_series.copy()


def _slope(series: pd.Series, ma_window: int, slope_window: int) -> pd.Series:
    """이동평균의 기울기 (slope_window 기간 변화량)."""
    ma = series.rolling(ma_window).mean()
    return ma.diff(slope_window)


class BdiCopperMacroSignal(BaseMacroSignal):
    """구리 + BDI 3개월 이동평균 기울기 기반 국면 판단.

    Risk-On 조건: 구리 MA 기울기 > 0 AND BDI MA 기울기 > 0
    고금리 조건: TNX >= high_rate_tnx OR CPI YoY >= high_rate_cpi

    파라미터를 조정해 다른 기준을 실험할 수 있다.

    Args:
        ma_window:      이동평균 기간 (거래일 기준, 기본 63일 ≈ 3개월)
        slope_window:   기울기 계산 기간 (거래일 기준, 기본 21일 ≈ 1개월)
        high_rate_tnx:  고금리 판단 TNX 기준 (%)
        high_rate_cpi:  고금리 판단 CPI YoY 기준 (%)

    Example::

        # 기본 파라미터
        signal = BdiCopperMacroSignal()

        # 금리 기준을 3%로 낮춰 실험
        signal = BdiCopperMacroSignal(high_rate_tnx=3.0, high_rate_cpi=3.0)

        # 더 긴 MA로 노이즈 제거
        signal = BdiCopperMacroSignal(ma_window=126, slope_window=42)
    """

    def __init__(
        self,
        ma_window: int = 63,
        slope_window: int = 21,
        high_rate_tnx: float = 4.0,
        high_rate_cpi: float = 4.0,
    ) -> None:
        self.ma_window = ma_window
        self.slope_window = slope_window
        self.high_rate_tnx = high_rate_tnx
        self.high_rate_cpi = high_rate_cpi

    def compute(self, years: list[int]) -> MacroSignal:
        """매크로 자산 데이터를 로드해 날짜별 국면을 계산한다."""
        # MA warmup 을 위해 이전 연도 데이터도 로드
        load_years = sorted(set(years) | {min(years) - 1})

        copper = load_asset("copper", load_years)["Close"]
        bdry   = load_asset("bdry",   load_years)["Close"]
        tnx    = load_asset("tnx",    load_years)["Close"]
        cpi    = load_asset("cpi",    load_years)["CPI_YoY"]

        idx  = copper.index
        bdry = bdry.reindex(idx, method="ffill")
        tnx  = tnx.reindex(idx, method="ffill")
        cpi  = cpi.reindex(idx, method="ffill")

        copper_slope = _slope(copper, self.ma_window, self.slope_window)
        bdry_slope   = _slope(bdry,   self.ma_window, self.slope_window)
        is_risk_on   = (copper_slope > 0) & (bdry_slope > 0)

        # CPI는 발표 지연 → loader 에서 이미 ffill 처리
        is_high_rate = (tnx >= self.high_rate_tnx) | (cpi >= self.high_rate_cpi)

        def _classify(row) -> Regime:
            if row["risk_on"] and not row["high_rate"]:
                return Regime.A
            if row["risk_on"] and row["high_rate"]:
                return Regime.B
            if not row["risk_on"] and not row["high_rate"]:
                return Regime.C
            return Regime.D

        signals = pd.DataFrame({"risk_on": is_risk_on, "high_rate": is_high_rate})
        regime_series = signals.apply(_classify, axis=1)

        mask = regime_series.index.year.isin(years)
        return MacroSignal(_regime_series=regime_series[mask])


# 하위 호환성 유지
def compute_macro_signals(years: list[int]) -> MacroSignal:
    return BdiCopperMacroSignal().compute(years)
