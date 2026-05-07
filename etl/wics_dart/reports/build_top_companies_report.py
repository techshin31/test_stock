from __future__ import annotations

from pathlib import Path

import pandas as pd


# ============================================================
# 이 파일은 다개년 랭킹 CSV를 사람이 읽기 쉬운
# Markdown 보고서로 바꿉니다.
#
# 현재 보고서 규칙:
# - 연도별로 기업 수가 많은 상위 5개 섹터를 선택합니다.
# - 각 섹터 안에서 overall_score 상위 5개 기업을 보여줍니다.
#
# 최종 결과물:
#   top_companies_report_2021_2025.md
# ============================================================


ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = ROOT / "etl" / "wics_dart" / "output"
RANKING_PATH = OUTPUT_DIR / "company_sector_rankings_2021_2025.csv"
REPORT_PATH = OUTPUT_DIR / "top_companies_report_2021_2025.md"


def load_rankings() -> pd.DataFrame:
    """기업-섹터 랭킹 테이블을 읽습니다."""
    return pd.read_csv(RANKING_PATH)


def format_number(value: float | int | None) -> str:
    """숫자 점수를 보고서용 문자열로 바꿉니다."""
    if pd.isna(value):
        return "-"
    return f"{value:.3f}"


def format_percent(value: float | None) -> str:
    """0~1 점수를 백분율 문자열로 바꿉니다."""
    if pd.isna(value):
        return "-"
    return f"{value:.1%}"


def top_sectors_for_year(rankings: pd.DataFrame, fiscal_year: str, top_n: int = 5) -> list[str]:
    """특정 연도에서 기업 수가 가장 많은 섹터를 찾습니다."""
    year_rows = rankings.loc[rankings["fiscal_year"].astype(str) == str(fiscal_year)]
    return (
        year_rows.groupby("wics_large", dropna=False)
        .size()
        .sort_values(ascending=False)
        .head(top_n)
        .index.tolist()
    )


def build_sector_section(rankings: pd.DataFrame, fiscal_year: str, sector: str) -> str:
    """하나의 연도·섹터 그룹에 대한 Markdown 섹션을 만듭니다."""
    sector_rows = rankings.loc[
        (rankings["fiscal_year"].astype(str) == str(fiscal_year))
        & (rankings["wics_large"] == sector)
        & rankings["overall_score"].notna()
    ].sort_values(
        ["overall_score", "company_name"],
        ascending=[False, True],
        na_position="last",
    ).head(5)

    lines = [
        f"### {sector}",
        "",
        "| company_name | overall_bucket | overall_score | growth_score | profitability_score | stability_score |",
        "|---|---|---:|---:|---:|---:|",
    ]

    for _, row in sector_rows.iterrows():
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["company_name"]),
                    str(row["overall_bucket"]),
                    format_number(row["overall_score"]),
                    format_percent(row["growth_score"]),
                    format_percent(row["profitability_score"]),
                    format_percent(row["stability_score"]),
                ]
            )
            + " |"
        )

    return "\n".join(lines)


def build_year_section(rankings: pd.DataFrame, fiscal_year: str) -> str:
    """특정 연도에 대한 보고서 섹션을 만듭니다."""
    sectors = top_sectors_for_year(rankings, fiscal_year, top_n=5)
    sector_sections = [build_sector_section(rankings, fiscal_year, sector) for sector in sectors]
    return "\n\n".join([f"## {fiscal_year}", *sector_sections])


def build_report(rankings: pd.DataFrame) -> str:
    """다개년 전체 Markdown 보고서를 만듭니다."""
    years = sorted(rankings["fiscal_year"].astype(str).dropna().unique().tolist())
    year_sections = [build_year_section(rankings, year) for year in years]

    return "\n".join(
        [
            "# Top Companies Report 2021-2025",
            "",
            "## 1. Purpose",
            "",
            "Summarize top companies by WICS large sector for each year using `company_sector_rankings_2021_2025.csv`.",
            "",
            "## 2. Selection Rules",
            "",
            "- Analysis years: 2021 to 2025",
            "- Source: `company_sector_rankings_2021_2025.csv`",
            "- Sector choice: top 5 sectors by company count in each year",
            "- Company choice: top 5 companies by `overall_score` inside each selected year-sector group",
            "",
            "## 3. Year-by-Year Leaders",
            "",
            "\n\n".join(year_sections),
            "",
            "## 4. Reading Guide",
            "",
            "- `growth_score` shows relative growth strength inside the same year and sector.",
            "- `profitability_score` shows relative profitability and capital efficiency inside the same year and sector.",
            "- `stability_score` shows relative balance-sheet and cash-flow strength inside the same year and sector.",
            "- `overall_bucket` is a quick label that groups companies into broad score bands.",
        ]
    )


def main() -> None:
    """다개년 상위 기업 보고서 생성 단계를 실행합니다."""
    rankings = load_rankings()
    report = build_report(rankings)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Saved top companies report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
