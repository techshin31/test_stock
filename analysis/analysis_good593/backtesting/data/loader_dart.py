"""data/재무제표/ DART 재무제표 로더 — FA 7지표 추출 (공시 지연 반영)"""
import pandas as pd
from pathlib import Path
from datetime import timedelta

_DART_ROOT = Path(__file__).parent.parent.parent / "data" / "재무제표"

# DART 공시 지연: 결산기말 기준 +60일 이후부터 사용
_PUBLISH_DELAY_DAYS = 60

# reprt_code → 결산기말 월/일
_PERIOD_END = {
    "11011": (12, 31),  # 연간
    "11012": (3, 31),   # Q1
    "11013": (6, 30),   # 반기
    "11014": (9, 30),   # Q3
}

# FA 계산에 사용할 account_id (우선순위 순)
_ACCOUNT_IDS = {
    "revenue":       ["ifrs-full_Revenue"],
    "op_income":     ["dart_OperatingIncomeLoss"],
    "net_income":    ["ifrs-full_ProfitLoss"],
    "total_liab":    ["ifrs-full_Liabilities"],
    "total_equity":  ["ifrs-full_Equity"],
    "op_cf":         ["ifrs-full_CashFlowsFromUsedInOperatingActivities"],
}


def _load_company_map() -> pd.DataFrame:
    path = _DART_ROOT / "dart_company_2026.csv"
    df = pd.read_csv(path, dtype=str)
    df["CMP_CD"] = df["CMP_CD"].str.zfill(6)
    df["DART_CD"] = df["DART_CD"].str.zfill(8)
    return df[["CMP_CD", "CMP_KOR", "DART_CD"]]


def _load_statements(stmt_type: str, years: list[int]) -> pd.DataFrame:
    dfs = []
    for year in years:
        path = _DART_ROOT / f"{stmt_type}_{year}.csv"
        if path.exists():
            dfs.append(pd.read_csv(path, dtype={"corp_code": str, "reprt_code": str}))
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


def _extract_amount(df: pd.DataFrame, account_ids: list[str]) -> pd.DataFrame:
    """account_id 우선순위로 회사당 1개 값만 추출."""
    for aid in account_ids:
        sub = df[df["account_id"] == aid][
            ["corp_code", "bsns_year", "reprt_code", "thstrm_amount"]
        ].copy()
        sub = sub.dropna(subset=["thstrm_amount"])
        sub["thstrm_amount"] = pd.to_numeric(sub["thstrm_amount"], errors="coerce")
        sub = sub.dropna(subset=["thstrm_amount"])
        if not sub.empty:
            # 같은 (corp, year, reprt)에 중복이 있으면 최초 행 사용
            return sub.drop_duplicates(subset=["corp_code", "bsns_year", "reprt_code"])
    return pd.DataFrame(columns=["corp_code", "bsns_year", "reprt_code", "thstrm_amount"])


def _available_date(reprt_code: str, bsns_year: int) -> pd.Timestamp:
    month, day = _PERIOD_END[reprt_code]
    period_end = pd.Timestamp(year=bsns_year, month=month, day=day)
    return period_end + timedelta(days=_PUBLISH_DELAY_DAYS)


def load_fa_data(years: list[int]) -> pd.DataFrame:
    """FA 7지표 계산을 위한 재무 원자료 반환.

    반환 컬럼:
        CMP_CD, bsns_year, reprt_code, available_date,
        revenue, op_income, net_income, total_liab, total_equity, op_cf
    """
    company_map = _load_company_map()

    # 연간 + 분기 모두 로드 (전년도 비교를 위해 years-1 도 포함)
    load_years = sorted(set(years) | {min(years) - 1})

    is_df = _load_statements("income_statement", load_years)
    bs_df = _load_statements("balance_sheet", load_years)
    cf_df = _load_statements("cash_flow", load_years)

    # 각 지표 추출
    metrics = {
        "revenue":      _extract_amount(is_df, _ACCOUNT_IDS["revenue"]),
        "op_income":    _extract_amount(is_df, _ACCOUNT_IDS["op_income"]),
        "net_income":   _extract_amount(is_df, _ACCOUNT_IDS["net_income"]),
        "total_liab":   _extract_amount(bs_df, _ACCOUNT_IDS["total_liab"]),
        "total_equity": _extract_amount(bs_df, _ACCOUNT_IDS["total_equity"]),
        "op_cf":        _extract_amount(cf_df, _ACCOUNT_IDS["op_cf"]),
    }

    # 기준 컬럼으로 merge
    base = metrics["revenue"].rename(columns={"thstrm_amount": "revenue"})
    for name, m_df in metrics.items():
        if name == "revenue":
            continue
        renamed = m_df.rename(columns={"thstrm_amount": name})
        base = base.merge(renamed, on=["corp_code", "bsns_year", "reprt_code"], how="left")

    # corp_code → CMP_CD 매핑
    base["corp_code"] = base["corp_code"].str.zfill(8)
    base = base.merge(
        company_map.rename(columns={"DART_CD": "corp_code"}),
        on="corp_code",
        how="inner",
    )

    # 공시 가능일 계산
    base["bsns_year"] = base["bsns_year"].astype(int)
    base["available_date"] = base.apply(
        lambda r: _available_date(r["reprt_code"], r["bsns_year"]), axis=1
    )

    cols = [
        "CMP_CD", "CMP_KOR", "bsns_year", "reprt_code", "available_date",
        "revenue", "op_income", "net_income", "total_liab", "total_equity", "op_cf",
    ]
    return base[cols].sort_values(["CMP_CD", "available_date"]).reset_index(drop=True)


def get_latest_financials(fa_df: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """특정 날짜 기준으로 각 종목의 가장 최근 공시 재무 데이터 반환."""
    available = fa_df[fa_df["available_date"] <= as_of]
    # 종목별 가장 최근 available_date 행만 유지
    idx = available.groupby("CMP_CD")["available_date"].idxmax()
    return available.loc[idx].reset_index(drop=True)
