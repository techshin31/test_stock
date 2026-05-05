"""3단계: FA 7지표 점수 기반 종목 선택

각 지표 0~2점 → 합산 점수 상위 N개 종목 선택.
"""
from __future__ import annotations
import pandas as pd

from ..data.loader_dart import get_latest_financials
from ..data.loader_wics import load_wics


# ── 점수 기준 ────────────────────────────────────────────────
def _score_opm(opm: float) -> int:
    """영업이익률."""
    if opm >= 0.10:  return 2
    if opm >= 0.05:  return 1
    return 0

def _score_growth(yoy: float) -> int:
    """매출 YoY 성장률."""
    if yoy >= 0.10:  return 2
    if yoy >= 0.00:  return 1
    return 0

def _score_debt(ratio: float) -> int:
    """부채비율 (부채/자본)."""
    if ratio < 1.0:  return 2
    if ratio < 2.0:  return 1
    return 0

def _score_ocf(ratio: float) -> int:
    """영업현금흐름 / 순이익."""
    if ratio > 1.0:  return 2
    if ratio >= 0:   return 1
    return 0

def _score_per(per: float, sector_median: float) -> int:
    """PER (섹터 중앙값 대비)."""
    if per <= 0:           return 0  # 적자
    if per < sector_median * 0.8:   return 2
    if per <= sector_median * 1.5:  return 1
    return 0

def _score_cash_burn(net_income: float, cash: float, monthly_expense: float) -> int:
    """적자 기업 현금 생존성 (개월 수)."""
    if net_income >= 0:
        return 2  # 흑자 기업은 패널티 없음
    if monthly_expense <= 0:
        return 1
    months = cash / monthly_expense if monthly_expense > 0 else 999
    if months > 24:  return 2
    if months > 12:  return 1
    return 0


def _compute_fa_scores(
    financials: pd.DataFrame,
    wics_snapshot: pd.DataFrame,
    sector_weights: dict[str, float],
) -> pd.DataFrame:
    """FA 7지표 점수 계산.

    Args:
        financials: get_latest_financials() 결과
        wics_snapshot: 특정 날짜의 WICS 스냅샷 (DATE 기준 1일치)
        sector_weights: {SEC_CD: weight}

    Returns:
        CMP_CD, SEC_CD, fa_score 컬럼 포함 DataFrame
    """
    # 대상 섹터 종목 필터
    target_sectors = list(sector_weights.keys())
    wics_sub = wics_snapshot[wics_snapshot["SEC_CD"].isin(target_sectors)].copy()

    # 재무 데이터 merge
    merged = wics_sub.merge(financials[
        ["CMP_CD", "revenue", "op_income", "net_income", "total_liab", "total_equity", "op_cf"]
    ], on="CMP_CD", how="inner")

    if merged.empty:
        return pd.DataFrame(columns=["CMP_CD", "SEC_CD", "fa_score"])

    # PER = 시가총액(원) / 순이익(원)
    merged["market_cap"] = merged["MKT_VAL"] * 1_000_000
    merged["per"] = merged.apply(
        lambda r: r["market_cap"] / r["net_income"] if r["net_income"] > 0 else float("nan"),
        axis=1,
    )

    # 섹터별 PER 중앙값
    sec_per_median = merged.groupby("SEC_CD")["per"].median()
    merged["sec_per_median"] = merged["SEC_CD"].map(sec_per_median)

    # 전년도 매출 (YoY 성장률 — 동일 reprt_code 기준, 여기선 frmtrm_amount가 없으므로 근사 생략)
    # 실제 구현 시 frmtrm_amount 컬럼 활용 권장
    # 여기서는 thstrm_amount(당기) vs 이전 스냅샷 값 비교로 대체
    merged["yoy_growth"] = 0.0  # placeholder: 별도 전처리 필요

    # 각 지표 점수
    def row_score(r) -> int:
        s = 0
        # 1. 수익성 OPM
        if r["revenue"] and r["revenue"] != 0:
            s += _score_opm(r["op_income"] / r["revenue"])
        # 2. 성장성 (placeholder)
        s += _score_growth(r["yoy_growth"])
        # 3. 재무안정성
        if r["total_equity"] and r["total_equity"] != 0:
            s += _score_debt(r["total_liab"] / r["total_equity"])
        # 4. 현금흐름
        if r["net_income"] and r["net_income"] != 0:
            s += _score_ocf(r["op_cf"] / r["net_income"])
        # 5. 밸류에이션 PER
        if pd.notna(r["per"]) and pd.notna(r["sec_per_median"]):
            s += _score_per(r["per"], r["sec_per_median"])
        # 6. 주주환원 (배당 데이터 없음 → 기본 1점)
        s += 1
        # 7. 재무생존성 (흑자 기업 → 2점)
        s += _score_cash_burn(r["net_income"], 0, 0)
        return s

    merged["fa_score"] = merged.apply(row_score, axis=1)
    return merged[["CMP_CD", "CMP_KOR", "SEC_CD", "MKT_VAL", "close", "per", "fa_score"]]


def score_stocks(
    rebal_date: pd.Timestamp,
    sector_weights: dict[str, float],
    wics_df: pd.DataFrame,
    fa_df: pd.DataFrame,
    top_n: int = 5,
) -> dict[str, float]:
    """리밸런싱 날짜 기준 종목별 목표 비중 반환.

    Returns:
        {CMP_CD: portfolio_weight}  합계 ≤ 1.0 (99% 투자, 1% 현금 버퍼)
    """
    # WICS 스냅샷 (rebal_date 당일 또는 직전 거래일)
    snap = wics_df[wics_df["DATE"] <= rebal_date]
    if snap.empty:
        return {}
    latest_date = snap["DATE"].max()
    snapshot = snap[snap["DATE"] == latest_date]

    # 가장 최근 공시 재무 데이터
    financials = get_latest_financials(fa_df, rebal_date)
    if financials.empty:
        return {}

    # FA 점수 계산
    scored = _compute_fa_scores(financials, snapshot, sector_weights)
    if scored.empty:
        return {}

    # 섹터별 상위 top_n 종목 선택
    result: dict[str, float] = {}
    for sec_cd, sec_weight in sector_weights.items():
        sec_stocks = scored[scored["SEC_CD"] == sec_cd].copy()
        if sec_stocks.empty:
            continue

        top = sec_stocks.nlargest(top_n, "fa_score")
        per_stock_weight = sec_weight / len(top)

        for _, row in top.iterrows():
            result[row["CMP_CD"]] = per_stock_weight

    # 99% 투자 (1% 현금 버퍼)
    total = sum(result.values())
    if total > 0:
        factor = 0.99 / total
        result = {k: v * factor for k, v in result.items()}

    return result
