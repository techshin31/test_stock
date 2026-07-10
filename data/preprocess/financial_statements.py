"""FA 지표 계산 — financial_statements EAV 데이터에서 fa_metrics 컬럼형 지표를 산출한다."""
from __future__ import annotations

import calendar
from datetime import date

import pandas as pd


def _calc_fiscal_year_end(bsns_year: int, acc_mt: int) -> date:
    """사업연도와 결산월로 회계연도 종료일을 계산한다."""
    last_day = calendar.monthrange(bsns_year, acc_mt)[1]
    return date(bsns_year, acc_mt, last_day)


# DART account_id 기준 우선 탐색, 없으면 account_nm 키워드로 폴백
_ACCOUNT_MAP: dict[str, tuple[list[str], list[str]]] = {
    # metric_key: (account_id_candidates, account_nm_keywords)
    "total_assets":          (["ifrs_Assets", "ifrs-full_Assets"],                          ["자산총계"]),
    "total_liabilities":     (["ifrs_Liabilities", "ifrs-full_Liabilities"],               ["부채총계"]),
    "total_equity":          (["ifrs_Equity", "ifrs-full_Equity"],                          ["자본총계"]),
    "current_assets":        (["ifrs-full_CurrentAssets"],                                  ["유동자산"]),
    "current_liabilities":   (["ifrs-full_CurrentLiabilities"],                             ["유동부채"]),
    "net_income":            (["ifrs_ProfitLoss", "ifrs-full_ProfitLoss"],                  ["당기순이익"]),
    "revenue":               (["ifrs_Revenue", "ifrs-full_Revenue"],                        ["매출액", "수익(매출액)"]),
    "operating_income":      (["dart_OperatingIncomeLoss"],                                 ["영업이익"]),
    "operating_cash_flow":   (["ifrs-full_CashFlowsFromUsedInOperatingActivities",
                                "ifrs-full_CashFlowsFromOperatingActivities"],              ["영업활동현금흐름", "영업활동으로인한현금흐름"]),
    "capex":                 (["ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                                "ifrs-full_AcquisitionOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
                                                                                             ["유형자산의 취득", "유형자산취득"]),
}


def _extract_amount(df: pd.DataFrame, account_ids: list[str], keywords: list[str]) -> float | None:
    """account_id → account_nm 순으로 계정과목 금액을 탐색한다."""
    if df.empty:
        return None

    # 1차: account_id 정확 일치
    if "account_id" in df.columns:
        for aid in account_ids:
            match = df[df["account_id"] == aid]
            if not match.empty:
                val = pd.to_numeric(match.iloc[0]["thstrm_amount"], errors="coerce")
                return None if pd.isna(val) else float(val)

    # 2차: account_nm 키워드 포함
    if "account_nm" in df.columns:
        for kw in keywords:
            match = df[df["account_nm"].astype(str).str.contains(kw, na=False, regex=False)]
            if not match.empty:
                val = pd.to_numeric(match.iloc[0]["thstrm_amount"], errors="coerce")
                return None if pd.isna(val) else float(val)

    return None


def _safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def calc_fa_metrics(
    bs: pd.DataFrame,
    is_: pd.DataFrame,
    cf: pd.DataFrame,
) -> dict[str, float | None]:
    """재무제표 3종(BS·IS·CF)에서 FA 지표를 계산한다.

    Parameters
    ----------
    bs : pd.DataFrame
        재무상태표 (sj_div == BS)
    is_ : pd.DataFrame
        손익계산서 (sj_div == IS or CIS)
    cf : pd.DataFrame
        현금흐름표 (sj_div == CF)

    Returns
    -------
    dict
        keys: roe, roa, operating_margin, debt_ratio, current_ratio, fcf
        계산 불가 지표는 None.
    """
    def get(key: str) -> float | None:
        ids, kws = _ACCOUNT_MAP[key]
        src = bs if key in ("total_assets", "total_liabilities", "total_equity",
                             "current_assets", "current_liabilities") else (
              cf if key in ("operating_cash_flow", "capex") else is_)
        return _extract_amount(src, ids, kws)

    total_assets       = get("total_assets")
    total_liabilities  = get("total_liabilities")
    total_equity       = get("total_equity")
    current_assets     = get("current_assets")
    current_liabilities = get("current_liabilities")
    net_income         = get("net_income")
    revenue            = get("revenue")
    operating_income   = get("operating_income")
    operating_cash_flow = get("operating_cash_flow")
    capex              = get("capex")

    # capex는 현금흐름표에서 음수(-) 또는 양수(+)로 기록될 수 있음
    # FCF = 영업활동현금흐름 - |capex|
    fcf: float | None = None
    if operating_cash_flow is not None and capex is not None:
        fcf = operating_cash_flow - abs(capex)

    return {
        "roe":              _safe_div(net_income, total_equity),
        "roa":              _safe_div(net_income, total_assets),
        "operating_margin": _safe_div(operating_income, revenue),
        "debt_ratio":       _safe_div(total_liabilities, total_equity),
        "current_ratio":    _safe_div(current_assets, current_liabilities),
        "fcf":              int(fcf) if fcf is not None else None,
    }


def calc_fa_metrics_from_db_rows(
    rows: list[dict],
    stock_code: str,
    bsns_year: int,
    fs_div: str = "CFS",
    acc_mt: int | None = None,
) -> dict:
    """financial_statements DB 행 목록에서 fa_metrics 딕셔너리를 생성한다.

    Parameters
    ----------
    rows : list[dict]
        financial_repo.fetch_financial_statements() 반환값
    stock_code, bsns_year, fs_div : str / int / str
        메타 정보 (fa_metrics 테이블 저장 시 사용)
    acc_mt : int, optional
        결산월 (1~12). 전달 시 fiscal_year_end 계산.

    Returns
    -------
    dict
        fa_metrics 테이블 upsert에 사용할 딕셔너리
    """
    if not rows:
        return {}

    df = pd.DataFrame(rows)
    bs  = df[df["sj_div"] == "BS"].copy()
    is_ = df[df["sj_div"].isin(["IS", "CIS"])].copy()
    cf  = df[df["sj_div"] == "CF"].copy()

    metrics = calc_fa_metrics(bs, is_, cf)
    if acc_mt:
        fiscal_year_end = _calc_fiscal_year_end(bsns_year, acc_mt)
    else:
        period_end = rows[0].get("period_end")
        fiscal_year_end = pd.Timestamp(period_end).date() if period_end else None
    return {
        "stock_code":      stock_code,
        "bsns_year":       bsns_year,
        "fs_div":          fs_div,
        "fiscal_year_end": fiscal_year_end,
        "source_rcept_no": rows[0].get("source_rcept_no"),
        "available_date":  rows[0].get("available_date"),
        "model_version":   "annual-fa-v2.0.0",
        **metrics,
    }
