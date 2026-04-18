from __future__ import annotations

from pathlib import Path

import pandas as pd


# ============================================================
# 이 파일은 2021~2025 마스터 결과물의 품질을 점검합니다.
#
# 예를 들어 아래 질문에 답하는 용도입니다.
# - corp_code가 비어 있는 행은 몇 개인가?
# - 핵심 재무지표가 비어 있는 행은 얼마나 되는가?
# - 어느 연도나 섹터의 데이터 커버리지가 약한가?
# - 이상치처럼 보이는 값이 있는가?
#
# 최종 결과물:
#   master_table_validation_2021_2025.md
# ============================================================


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "etl" / "wics_dart" / "output"
MASTER_PATH = OUTPUT_DIR / "company_year_master_2021_2025.csv"
SECTOR_PATH = OUTPUT_DIR / "sector_benchmark_wics_large_2021_2025.csv"
REPORT_PATH = OUTPUT_DIR / "master_table_validation_2021_2025.md"


def load_csv(path: Path) -> pd.DataFrame:
    """output 폴더의 CSV 파일을 읽습니다."""
    return pd.read_csv(path)


def rate_text(part: int, whole: int) -> str:
    """개수를 백분율 문자열로 바꿉니다."""
    if whole == 0:
        return "0.00%"
    return f"{part / whole:.2%}"


def build_missing_summary(master: pd.DataFrame) -> pd.DataFrame:
    """가장 중요한 컬럼들의 결측 현황을 요약합니다."""
    key_columns = [
        "corp_code",
        "wics_large",
        "revenue",
        "revenue_prev",
        "operating_income",
        "net_income",
        "total_assets",
        "total_liabilities",
        "total_equity",
        "operating_cash_flow",
        "revenue_growth_yoy",
        "operating_margin",
        "roe",
        "debt_ratio",
        "current_ratio",
        "ocf_to_revenue",
    ]

    total_rows = len(master)
    rows: list[dict[str, object]] = []
    for column in key_columns:
        missing_count = int(master[column].isna().sum())
        available_count = total_rows - missing_count
        rows.append(
            {
                "column_name": column,
                "missing_count": missing_count,
                "available_count": available_count,
                "missing_rate": rate_text(missing_count, total_rows),
                "available_rate": rate_text(available_count, total_rows),
            }
        )
    return pd.DataFrame(rows)


def build_year_summary(master: pd.DataFrame) -> pd.DataFrame:
    """연도별 커버리지 요약표를 만듭니다."""
    rows: list[dict[str, object]] = []

    for fiscal_year, group in master.groupby("fiscal_year", dropna=False):
        rows.append(
            {
                "fiscal_year": fiscal_year,
                "company_rows": len(group),
                "corp_code_available": int(group["corp_code"].notna().sum()),
                "revenue_available": int(group["revenue"].notna().sum()),
                "operating_margin_available": int(group["operating_margin"].notna().sum()),
                "roe_available": int(group["roe"].notna().sum()),
                "debt_ratio_available": int(group["debt_ratio"].notna().sum()),
            }
        )

    return pd.DataFrame(rows).sort_values("fiscal_year")


def build_sector_summary(master: pd.DataFrame) -> pd.DataFrame:
    """연도별·WICS 대분류별 커버리지 요약표를 만듭니다."""
    rows: list[dict[str, object]] = []

    for (fiscal_year, sector_name), group in master.groupby(["fiscal_year", "wics_large"], dropna=False):
        rows.append(
            {
                "fiscal_year": fiscal_year,
                "wics_large": sector_name,
                "company_rows": len(group),
                "corp_code_available": int(group["corp_code"].notna().sum()),
                "revenue_available": int(group["revenue"].notna().sum()),
                "operating_margin_available": int(group["operating_margin"].notna().sum()),
                "roe_available": int(group["roe"].notna().sum()),
                "debt_ratio_available": int(group["debt_ratio"].notna().sum()),
            }
        )

    return pd.DataFrame(rows).sort_values(["fiscal_year", "wics_large"], na_position="last")


def build_outlier_summary(master: pd.DataFrame) -> dict[str, int]:
    """추가 확인이 필요한 값들의 개수를 셉니다."""
    return {
        "negative_or_zero_equity_rows": int((master["total_equity"].fillna(0) <= 0).sum()),
        "debt_ratio_over_3_rows": int((master["debt_ratio"].fillna(-1) > 3).sum()),
        "operating_margin_below_minus_1_rows": int((master["operating_margin"].fillna(0) < -1).sum()),
        "roe_below_minus_1_rows": int((master["roe"].fillna(0) < -1).sum()),
    }


def markdown_table(df: pd.DataFrame) -> str:
    """데이터프레임을 간단한 Markdown 표로 바꿉니다."""
    if df.empty:
        return "_none_"

    headers = "| " + " | ".join(df.columns) + " |"
    divider = "| " + " | ".join(["---"] * len(df.columns)) + " |"
    rows = [
        "| " + " | ".join("" if pd.isna(value) else str(value) for value in row) + " |"
        for row in df.itertuples(index=False, name=None)
    ]
    return "\n".join([headers, divider, *rows])


def build_report(master: pd.DataFrame, sector: pd.DataFrame) -> str:
    """전체 검증 리포트를 Markdown 형식으로 만듭니다."""
    total_rows = len(master)
    sector_rows = len(sector)
    missing_corp_code = int(master["corp_code"].isna().sum())

    missing_summary = build_missing_summary(master)
    year_summary = build_year_summary(master)
    sector_summary = build_sector_summary(master)
    outlier_summary = build_outlier_summary(master)

    join_missing_examples = master.loc[
        master["corp_code"].isna(),
        ["fiscal_year", "company_name", "stock_code", "wics_large"],
    ].head(20)

    return f"""# Master Table Validation 2021-2025

## 1. Summary

- Master rows: {total_rows}
- Sector benchmark rows: {sector_rows}
- Missing `corp_code` rows: {missing_corp_code}
- `corp_code` coverage: {rate_text(total_rows - missing_corp_code, total_rows)}

## 2. Column Coverage

{markdown_table(missing_summary)}

## 3. Year Coverage

{markdown_table(year_summary)}

## 4. Sector Coverage

{markdown_table(sector_summary)}

## 5. Join Missing Examples

{markdown_table(join_missing_examples)}

## 6. Outlier Checks

- Negative or zero equity rows: {outlier_summary["negative_or_zero_equity_rows"]}
- Debt ratio greater than 3 rows: {outlier_summary["debt_ratio_over_3_rows"]}
- Operating margin below -1 rows: {outlier_summary["operating_margin_below_minus_1_rows"]}
- ROE below -1 rows: {outlier_summary["roe_below_minus_1_rows"]}
"""


def main() -> None:
    """2021~2025 결과물에 대한 검증 단계를 실행합니다."""
    master = load_csv(MASTER_PATH)
    sector = load_csv(SECTOR_PATH)
    report = build_report(master, sector)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Saved validation report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
