from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd


# ============================================================
# 이 파일은 2021~2025 전체 기간을 대상으로
# WICS-DART 분석의 기초 데이터셋을 생성합니다.
#
# 결과물 1:
#   company_year_master_2021_2025.csv
#   한 행은 "기업 1개 + 연도 1개"를 뜻합니다.
#
# 결과물 2:
#   sector_benchmark_wics_large_2021_2025.csv
#   한 행은 "WICS 대분류 1개 + 연도 1개"를 뜻합니다.
#
# 전체 흐름:
# 1. WICS 기업 분류 데이터를 읽습니다.
# 2. WICS 기업코드와 DART 기업코드를 연결합니다.
# 3. 2021년부터 2025년까지 재무제표를 읽습니다.
# 4. 주요 재무비율을 계산합니다.
# 5. 기업 기준 결과와 섹터 기준 결과를 저장합니다.
# ============================================================


ROOT = Path(__file__).resolve().parents[2]
COMPANY_DATA_DIR = ROOT / "etl" / "company" / "data"
WICS_PATH = ROOT / "etl" / "wics" / "data" / "csv" / "wics_company_2026.csv"
DART_COMPANY_PATH = COMPANY_DATA_DIR / "dart_company_2026.csv"
OUTPUT_DIR = ROOT / "etl" / "wics_dart" / "output"
MASTER_OUTPUT_PATH = OUTPUT_DIR / "company_year_master_2021_2025.csv"
SECTOR_OUTPUT_PATH = OUTPUT_DIR / "sector_benchmark_wics_large_2021_2025.csv"

START_YEAR = 2021
END_YEAR = 2025
YEARS = list(range(START_YEAR, END_YEAR + 1))


FINANCIAL_ACCOUNT_MAP = {
    "revenue": "ifrs-full_Revenue",
    "operating_income": "dart_OperatingIncomeLoss",
    "net_income": "ifrs-full_ProfitLoss",
    "total_assets": "ifrs-full_Assets",
    "total_liabilities": "ifrs-full_Liabilities",
    "total_equity": "ifrs-full_Equity",
    "current_assets": "ifrs-full_CurrentAssets",
    "current_liabilities": "ifrs-full_CurrentLiabilities",
    "operating_cash_flow": "ifrs-full_CashFlowsFromUsedInOperatingActivities",
    "investing_cash_flow": "ifrs-full_CashFlowsFromUsedInInvestingActivities",
    "financing_cash_flow": "ifrs-full_CashFlowsFromUsedInFinancingActivities",
}


def load_csv(path: Path) -> pd.DataFrame:
    """원본 값이 흔들리지 않도록 CSV를 먼저 문자열 기준으로 읽습니다."""
    return pd.read_csv(path, dtype=str)


def dedupe_wics(df: pd.DataFrame) -> pd.DataFrame:
    """
    같은 종목코드에 대해 가장 최신 WICS 행만 남깁니다.

    WICS 파일에는 같은 기업이 여러 날짜로 들어 있을 수 있으므로
    현재 분석에서는 가장 최근 행을 대표 분류로 사용합니다.
    """
    wics = df.loc[:, ["CMP_CD", "CMP_KOR", "SEC_CD", "SEC_NM_KOR", "IDX_CD", "IDX_NM_KOR", "DATE"]].copy()
    wics["DATE"] = pd.to_datetime(wics["DATE"], format="%Y%m%d", errors="coerce")
    wics = wics.sort_values(["CMP_CD", "DATE"], ascending=[True, False])
    return wics.drop_duplicates(subset=["CMP_CD"], keep="first")


def build_company_bridge() -> pd.DataFrame:
    """
    stock_code와 corp_code를 연결하는 브리지 테이블을 만듭니다.

    이 테이블은 아래 두 데이터를 연결하는 핵심 중간층입니다.
    - WICS 기업 정보
    - DART 기업 정보
    """
    wics = dedupe_wics(load_csv(WICS_PATH)).rename(
        columns={
            "CMP_CD": "stock_code",
            "CMP_KOR": "company_name_wics",
            "SEC_CD": "wics_large_code",
            "SEC_NM_KOR": "wics_large",
            "IDX_CD": "wics_index_code",
            "IDX_NM_KOR": "wics_index_name",
            "DATE": "wics_date",
        }
    )
    dart = load_csv(DART_COMPANY_PATH).rename(
        columns={
            "CMP_CD": "stock_code",
            "CMP_KOR": "company_name",
            "DART_CD": "corp_code",
        }
    )

    bridge = wics.merge(dart, on="stock_code", how="left", validate="one_to_one")
    bridge["company_name"] = bridge["company_name"].fillna(bridge["company_name_wics"])

    return bridge[
        [
            "company_name",
            "company_name_wics",
            "stock_code",
            "corp_code",
            "wics_large_code",
            "wics_large",
            "wics_index_code",
            "wics_index_name",
            "wics_date",
        ]
    ]


def prepare_statement(df: pd.DataFrame, *, year: int, account_columns: dict[str, str]) -> pd.DataFrame:
    """
    세로형 재무제표 데이터를 가로형 기업 테이블로 바꿉니다.

    입력 예시:
    - corp_code / account_id / thstrm_amount

    출력 예시:
    - corp_code / revenue / operating_income / net_income
    """
    filtered = df.loc[df["bsns_year"] == str(year), ["corp_code", "account_id", "thstrm_amount"]].copy()
    filtered["thstrm_amount"] = pd.to_numeric(filtered["thstrm_amount"], errors="coerce")
    filtered = filtered.loc[filtered["account_id"].isin(account_columns.values())]
    filtered = filtered.drop_duplicates(subset=["corp_code", "account_id"], keep="first")

    wide = filtered.pivot(index="corp_code", columns="account_id", values="thstrm_amount").reset_index()
    rename_map = {value: key for key, value in account_columns.items()}
    return wide.rename(columns=rename_map)


def add_missing_columns(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """필요한 계정 열이 없으면 빈 열을 추가합니다."""
    for column in columns:
        if column not in df.columns:
            df[column] = pd.NA
    return df


def file_path(statement_type: str, year: int) -> Path:
    """연도별 재무제표 파일 경로를 만듭니다."""
    return COMPANY_DATA_DIR / f"{statement_type}_{year}.csv"


def build_financials_for_year(year: int) -> pd.DataFrame:
    """
    특정 연도의 재무값 테이블을 만듭니다.

    매출 성장률을 계산하려면 전년도 매출도 필요하므로
    함께 불러와 `revenue_prev`로 붙입니다.
    """
    income_current = prepare_statement(
        load_csv(file_path("income_statement", year)),
        year=year,
        account_columns={
            key: value
            for key, value in FINANCIAL_ACCOUNT_MAP.items()
            if key in {"revenue", "operating_income", "net_income"}
        },
    )

    if year - 1 >= START_YEAR:
        income_prev = prepare_statement(
            load_csv(file_path("income_statement", year - 1)),
            year=year - 1,
            account_columns={"revenue_prev": FINANCIAL_ACCOUNT_MAP["revenue"]},
        )
    else:
        income_prev = pd.DataFrame(columns=["corp_code", "revenue_prev"])

    balance = prepare_statement(
        load_csv(file_path("balance_sheet", year)),
        year=year,
        account_columns={
            key: value
            for key, value in FINANCIAL_ACCOUNT_MAP.items()
            if key in {"total_assets", "total_liabilities", "total_equity", "current_assets", "current_liabilities"}
        },
    )
    cash_flow = prepare_statement(
        load_csv(file_path("cash_flow", year)),
        year=year,
        account_columns={
            key: value
            for key, value in FINANCIAL_ACCOUNT_MAP.items()
            if key in {"operating_cash_flow", "investing_cash_flow", "financing_cash_flow"}
        },
    )

    merged = income_current.merge(income_prev, on="corp_code", how="left")
    merged = merged.merge(balance, on="corp_code", how="outer")
    merged = merged.merge(cash_flow, on="corp_code", how="outer")
    merged["fiscal_year"] = str(year)

    return add_missing_columns(
        merged,
        [
            "revenue",
            "revenue_prev",
            "operating_income",
            "net_income",
            "total_assets",
            "total_liabilities",
            "total_equity",
            "current_assets",
            "current_liabilities",
            "operating_cash_flow",
            "investing_cash_flow",
            "financing_cash_flow",
        ],
    )


def safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """분모가 0이거나 결측인 경우를 피해서 안전하게 비율을 계산합니다."""
    numerator = numerator.astype("float64")
    denominator = denominator.astype("float64")
    result = numerator / denominator
    return result.where(denominator.notna() & (denominator != 0))


def build_master_table() -> pd.DataFrame:
    """전체 분석 연도에 대한 기업-연도 마스터 테이블을 만듭니다."""
    base = build_company_bridge()
    year_frames: list[pd.DataFrame] = []

    for year in YEARS:
        year_financials = build_financials_for_year(year)
        year_base = base.copy()
        year_base["fiscal_year"] = str(year)

        master_year = year_base.merge(year_financials, on=["corp_code", "fiscal_year"], how="left")
        master_year["revenue_growth_yoy"] = safe_ratio(
            master_year["revenue"] - master_year["revenue_prev"],
            master_year["revenue_prev"],
        )
        master_year["operating_margin"] = safe_ratio(master_year["operating_income"], master_year["revenue"])
        master_year["roe"] = safe_ratio(master_year["net_income"], master_year["total_equity"])
        master_year["debt_ratio"] = safe_ratio(master_year["total_liabilities"], master_year["total_equity"])
        master_year["current_ratio"] = safe_ratio(master_year["current_assets"], master_year["current_liabilities"])
        master_year["ocf_to_revenue"] = safe_ratio(master_year["operating_cash_flow"], master_year["revenue"])
        year_frames.append(master_year)

    master = pd.concat(year_frames, ignore_index=True)

    ordered_columns = [
        "company_name",
        "company_name_wics",
        "stock_code",
        "corp_code",
        "fiscal_year",
        "wics_large_code",
        "wics_large",
        "wics_index_code",
        "wics_index_name",
        "wics_date",
        "revenue",
        "revenue_prev",
        "operating_income",
        "net_income",
        "total_assets",
        "total_liabilities",
        "total_equity",
        "current_assets",
        "current_liabilities",
        "operating_cash_flow",
        "investing_cash_flow",
        "financing_cash_flow",
        "revenue_growth_yoy",
        "operating_margin",
        "roe",
        "debt_ratio",
        "current_ratio",
        "ocf_to_revenue",
    ]
    return master[ordered_columns].sort_values(["fiscal_year", "wics_large", "company_name"], na_position="last")


def build_sector_benchmark(master: pd.DataFrame) -> pd.DataFrame:
    """연도별·섹터별 벤치마크 테이블을 만듭니다."""
    metrics = [
        "revenue_growth_yoy",
        "operating_margin",
        "roe",
        "debt_ratio",
        "current_ratio",
        "ocf_to_revenue",
    ]
    grouped = master.groupby(["fiscal_year", "wics_large"], dropna=False)

    benchmark = grouped.agg(
        company_count=("corp_code", "count"),
        revenue_median=("revenue", "median"),
        operating_margin_median=("operating_margin", "median"),
        roe_median=("roe", "median"),
        debt_ratio_median=("debt_ratio", "median"),
    ).reset_index()

    for metric in metrics:
        percentiles = grouped[metric].quantile([0.25, 0.5, 0.75]).unstack()
        percentiles = percentiles.rename(
            columns={
                0.25: f"{metric}_p25",
                0.5: f"{metric}_p50",
                0.75: f"{metric}_p75",
            }
        ).reset_index()
        benchmark = benchmark.merge(percentiles, on=["fiscal_year", "wics_large"], how="left")

    return benchmark.sort_values(["fiscal_year", "wics_large"], na_position="last")


def main() -> None:
    """마스터 테이블 생성 단계를 실행합니다."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    master = build_master_table()
    benchmark = build_sector_benchmark(master)

    master.to_csv(MASTER_OUTPUT_PATH, index=False, encoding="utf-8-sig")
    benchmark.to_csv(SECTOR_OUTPUT_PATH, index=False, encoding="utf-8-sig")

    print(f"Saved master table: {MASTER_OUTPUT_PATH}")
    print(f"Saved sector benchmark: {SECTOR_OUTPUT_PATH}")
    print(f"Master rows: {len(master)}")
    print(f"Benchmark rows: {len(benchmark)}")


if __name__ == "__main__":
    main()
