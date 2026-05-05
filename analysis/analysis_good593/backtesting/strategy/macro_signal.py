"""1단계: 매크로 국면 판단

4가지 국면으로 분류:
    A — Risk-On  + 저금리
    B — Risk-On  + 고금리
    C — Risk-Off + 저금리
    D — Risk-Off + 고금리
"""
from __future__ import annotations
from enum import Enum
from dataclasses import dataclass

import pandas as pd

from ..data.loader_asset import load_asset

# 3개월 이동평균 기울기 기준 (약 63거래일)
_MA_WINDOW = 63
# 기울기 계산 기간 (1개월 변화량, 약 21거래일)
_SLOPE_WINDOW = 21
# 고금리 기준
_HIGH_RATE_TNX = 4.0   # TNX(%) 기준
_HIGH_RATE_CPI = 4.0   # CPI YoY(%) 기준


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
            return Regime.A  # 데이터 없으면 기본값
        return past.iloc[-1]

    def to_series(self) -> pd.Series:
        return self._regime_series.copy()


def _slope(series: pd.Series, ma_window: int, slope_window: int) -> pd.Series:
    """3개월 이동평균의 1개월 변화량."""
    ma = series.rolling(ma_window).mean()
    return ma.diff(slope_window)


def compute_macro_signals(years: list[int]) -> MacroSignal:
    """매크로 자산 데이터를 로드해 날짜별 국면을 계산한다."""
    # 신호 계산에 이전 연도 데이터도 필요 (MA warmup)
    load_years = sorted(set(years) | {min(years) - 1})

    copper = load_asset("copper", load_years)["Close"]
    bdry   = load_asset("bdry",   load_years)["Close"]
    tnx    = load_asset("tnx",    load_years)["Close"]
    cpi    = load_asset("cpi",    load_years)["CPI_YoY"]

    # 공통 거래일 인덱스로 정렬
    idx = copper.index
    bdry   = bdry.reindex(idx, method="ffill")
    tnx    = tnx.reindex(idx, method="ffill")
    cpi    = cpi.reindex(idx, method="ffill")

    # Risk-On: 구리 & BDI 3M MA 모두 상승 추세
    copper_slope = _slope(copper, _MA_WINDOW, _SLOPE_WINDOW)
    bdry_slope   = _slope(bdry,   _MA_WINDOW, _SLOPE_WINDOW)
    is_risk_on   = (copper_slope > 0) & (bdry_slope > 0)

    # 고금리: TNX ≥ 4% OR CPI YoY ≥ 4%
    # CPI는 발표 지연 → 이미 loader에서 ffill 처리됨
    is_high_rate = (tnx >= _HIGH_RATE_TNX) | (cpi >= _HIGH_RATE_CPI)

    def _classify(row):
        if row["risk_on"] and not row["high_rate"]:
            return Regime.A
        if row["risk_on"] and row["high_rate"]:
            return Regime.B
        if not row["risk_on"] and not row["high_rate"]:
            return Regime.C
        return Regime.D

    signals = pd.DataFrame({"risk_on": is_risk_on, "high_rate": is_high_rate})
    regime_series = signals.apply(_classify, axis=1)

    # 요청 연도 범위만 반환
    mask = regime_series.index.year.isin(years)
    return MacroSignal(_regime_series=regime_series[mask])
