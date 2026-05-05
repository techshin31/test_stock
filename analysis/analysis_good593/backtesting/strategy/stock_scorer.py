"""3단계: FA 7지표 점수 기반 종목 선택

구현체:
    FaStockScorer — FA 7지표 합산 점수 상위 N종목 선택 (기본값)

다른 종목 선택 로직을 실험하려면 BaseStockScorer 를 상속해 구현한다.
"""
from __future__ import annotations

import pandas as pd

from ..data.loader_dart import get_latest_financials
from .base import BaseStockScorer


# ── 지표별 채점 함수 (0~2점) ────────────────────────────────────

def _score_opm(opm: float) -> int:
    """영업이익률."""
    if opm >= 0.10: return 2
    if opm >= 0.05: return 1
    return 0


def _score_growth(yoy: float) -> int:
    """매출 YoY 성장률."""
    if yoy >= 0.10: return 2
    if yoy >= 0.00: return 1
    return 0


def _score_debt(ratio: float) -> int:
    """부채비율 (부채/자본)."""
    if ratio < 1.0: return 2
    if ratio < 2.0: return 1
    return 0


def _score_ocf(ratio: float) -> int:
    """영업현금흐름 / 순이익."""
    if ratio > 1.0: return 2
    if ratio >= 0:  return 1
    return 0


def _score_per(per: float, sector_median: float) -> int:
    """PER (섹터 중앙값 대비)."""
    if per <= 0:                      return 0  # 적자
    if per < sector_median * 0.8:    return 2
    if per <= sector_median * 1.5:   return 1
    return 0


def _score_viability(net_income: float, op_cf: float) -> int:
    """재무 생존성: 영업현금흐름으로 현금 창출력 판단.

    현금 잔액 데이터 없이 op_cf로 적자 기업의 지속 가능성을 근사한다.
    - 흑자(net_income≥0): 패널티 없음 → 2점
    - 순손실이지만 영업현금 창출(감가상각 등): → 1점
    - 순손실 + 현금 소진: → 0점
    """
    if net_income >= 0:
        return 2
    if op_cf > 0:
        return 1
    return 0


# ── FA 점수 계산 ────────────────────────────────────────────────

def _compute_fa_scores(
    financials: pd.DataFrame,
    wics_snapshot: pd.DataFrame,
    sector_weights: dict[str, float],
    prev_financials: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """FA 7지표 점수를 계산한다.

    Args:
        financials:      get_latest_financials() 결과 (현재 시점)
        wics_snapshot:   특정 날짜의 WICS 스냅샷 (1일치)
        sector_weights:  {SEC_CD: weight}
        prev_financials: 1년 전 시점의 재무 데이터 (YoY 성장률 계산용)

    Returns:
        CMP_CD, CMP_KOR, SEC_CD, MKT_VAL, close, per, fa_score 컬럼 DataFrame
    """
    target_sectors = list(sector_weights.keys())
    wics_sub = wics_snapshot[wics_snapshot["SEC_CD"].isin(target_sectors)].copy()

    merged = wics_sub.merge(
        financials[["CMP_CD", "revenue", "op_income", "net_income",
                    "total_liab", "total_equity", "op_cf"]],
        on="CMP_CD",
        how="inner",
    )

    if merged.empty:
        return pd.DataFrame(columns=["CMP_CD", "SEC_CD", "fa_score"])

    merged["market_cap"] = merged["MKT_VAL"] * 1_000_000
    merged["per"] = merged.apply(
        lambda r: r["market_cap"] / r["net_income"] if r["net_income"] > 0 else float("nan"),
        axis=1,
    )

    sec_per_median = merged.groupby("SEC_CD")["per"].median()
    merged["sec_per_median"] = merged["SEC_CD"].map(sec_per_median)

    # YoY 성장률: 1년 전 재무 데이터와 비교
    if prev_financials is not None and not prev_financials.empty:
        prev_rev = prev_financials[["CMP_CD", "revenue"]].rename(
            columns={"revenue": "prev_revenue"}
        )
        merged = merged.merge(prev_rev, on="CMP_CD", how="left")

        def _calc_yoy(r) -> float:
            prev = r.get("prev_revenue")
            if pd.isna(prev) or prev == 0:
                return 0.0
            return (r["revenue"] - prev) / abs(prev)

        merged["yoy_growth"] = merged.apply(_calc_yoy, axis=1)
    else:
        merged["yoy_growth"] = 0.0

    def _row_score(r) -> int:
        s = 0
        if r["revenue"] and r["revenue"] != 0:
            s += _score_opm(r["op_income"] / r["revenue"])
        s += _score_growth(r["yoy_growth"])
        if r["total_equity"] and r["total_equity"] != 0:
            s += _score_debt(r["total_liab"] / r["total_equity"])
        if r["net_income"] and r["net_income"] != 0:
            s += _score_ocf(r["op_cf"] / r["net_income"])
        if pd.notna(r["per"]) and pd.notna(r["sec_per_median"]):
            s += _score_per(r["per"], r["sec_per_median"])
        s += 1  # 배당 데이터 없음 → 기본 1점
        op_cf_val = r["op_cf"] if pd.notna(r["op_cf"]) else 0.0
        s += _score_viability(r["net_income"], op_cf_val)
        return s

    merged["fa_score"] = merged.apply(_row_score, axis=1)
    return merged[["CMP_CD", "CMP_KOR", "SEC_CD", "MKT_VAL", "close", "per", "fa_score"]]


class FaStockScorer(BaseStockScorer):
    """FA 7지표 합산 점수 기반 종목 선택기.

    섹터별로 FA 점수 상위 top_n 개 종목을 선택하고
    섹터 비중을 균등 분할해 포트폴리오 비중을 산정한다.

    Args:
        top_n: 섹터당 편입 종목 수 (기본 5개)

    Example::

        # 섹터당 3종목
        scorer = FaStockScorer(top_n=3)

        # 섹터당 10종목 (분산 투자)
        scorer = FaStockScorer(top_n=10)
    """

    def __init__(self, top_n: int = 5) -> None:
        self.top_n = top_n

    def score(
        self,
        date: pd.Timestamp,
        sector_weights: dict[str, float],
        wics_df: pd.DataFrame,
        fa_df: pd.DataFrame,
    ) -> dict[str, float]:
        """{CMP_CD: 포트폴리오 비중} 반환. 합계 ≈ 0.99 (1% 현금 버퍼)."""
        return _score_stocks(date, sector_weights, wics_df, fa_df, self.top_n)


def _score_stocks(
    rebal_date: pd.Timestamp,
    sector_weights: dict[str, float],
    wics_df: pd.DataFrame,
    fa_df: pd.DataFrame,
    top_n: int = 5,
) -> dict[str, float]:
    """리밸런싱 날짜 기준 종목별 목표 비중을 계산한다."""
    snap = wics_df[wics_df["DATE"] <= rebal_date]
    if snap.empty:
        return {}
    latest_date = snap["DATE"].max()
    snapshot = snap[snap["DATE"] == latest_date]

    financials = get_latest_financials(fa_df, rebal_date)
    if financials.empty:
        return {}

    # 1년 전 재무 데이터로 YoY 성장률 계산
    prev_financials = get_latest_financials(fa_df, rebal_date - pd.DateOffset(years=1))

    scored = _compute_fa_scores(financials, snapshot, sector_weights, prev_financials)
    if scored.empty:
        return {}

    result: dict[str, float] = {}
    for sec_cd, sec_weight in sector_weights.items():
        sec_stocks = scored[scored["SEC_CD"] == sec_cd].copy()
        if sec_stocks.empty:
            continue
        top = sec_stocks.nlargest(top_n, "fa_score")
        per_stock_weight = sec_weight / len(top)
        for _, row in top.iterrows():
            result[row["CMP_CD"]] = per_stock_weight

    total = sum(result.values())
    if total > 0:
        factor = 0.99 / total
        result = {k: v * factor for k, v in result.items()}

    return result


# 하위 호환성 유지
def score_stocks(
    rebal_date: pd.Timestamp,
    sector_weights: dict[str, float],
    wics_df: pd.DataFrame,
    fa_df: pd.DataFrame,
    top_n: int = 5,
) -> dict[str, float]:
    return _score_stocks(rebal_date, sector_weights, wics_df, fa_df, top_n)
