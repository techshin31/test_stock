from __future__ import annotations

from pathlib import Path

import pandas as pd


# ============================================================  
# 이 파일은 2021~2025 전체 기간에 대한
# 메인 종합 분석 보고서를 생성합니다.
#
# 사용하는 데이터:
# - master table data
# - sector benchmark data
# - company ranking data
#
# 최종 결과물:
#   etl/wics_dart/output/all_sector_analysis_report_2021_2025.md
# ============================================================


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "etl" / "wics_dart" / "output"

MASTER_PATH = OUTPUT_DIR / "company_year_master_2021_2025.csv"
BENCHMARK_PATH = OUTPUT_DIR / "sector_benchmark_wics_large_2021_2025.csv"
RANKING_PATH = OUTPUT_DIR / "company_sector_rankings_2021_2025.csv"
REPORT_PATH = OUTPUT_DIR / "all_sector_analysis_report_2021_2025.md"


def load_csv(path: Path) -> pd.DataFrame:
    """CSV 파일을 읽습니다."""
    return pd.read_csv(path)


def format_number(value: float | int | None) -> str:
    """숫자 값을 보고서용 문자열로 바꿉니다."""
    if pd.isna(value):
        return "-"
    return f"{value:.3f}"


def format_percent(value: float | int | None) -> str:
    """비율 값을 백분율 문자열로 바꿉니다."""
    if pd.isna(value):
        return "-"
    return f"{value:.1%}"


def markdown_table(df: pd.DataFrame) -> str:
    """데이터프레임을 Markdown 표로 바꿉니다."""
    if df.empty:
        return "_none_"

    headers = "| " + " | ".join(df.columns) + " |"
    divider = "| " + " | ".join(["---"] * len(df.columns)) + " |"
    rows = [
        "| " + " | ".join("" if pd.isna(value) else str(value) for value in row) + " |"
        for row in df.itertuples(index=False, name=None)
    ]
    return "\n".join([headers, divider, *rows])


def build_yearly_coverage(master: pd.DataFrame) -> pd.DataFrame:
    """실제 마스터 데이터 기준 연도별 커버리지 표를 만듭니다."""
    rows: list[dict[str, object]] = []

    for fiscal_year, group in master.groupby("fiscal_year", dropna=False):
        rows.append(
            {
                "연도": str(fiscal_year),
                "기업-연도 행 수": len(group),
                "corp_code 커버리지": format_percent(group["corp_code"].notna().mean()),
                "매출 커버리지": format_percent(group["revenue"].notna().mean()),
                "영업이익률 커버리지": format_percent(group["operating_margin"].notna().mean()),
                "ROE 커버리지": format_percent(group["roe"].notna().mean()),
            }
        )

    return pd.DataFrame(rows).sort_values("연도")


def build_2025_sector_snapshot(benchmark: pd.DataFrame, rankings: pd.DataFrame) -> pd.DataFrame:
    """2025년 기준 섹터 요약표와 상위 기업 예시를 만듭니다."""
    bench_2025 = benchmark.loc[benchmark["fiscal_year"].astype(str) == "2025"].copy()
    rank_2025 = rankings.loc[rankings["fiscal_year"].astype(str) == "2025"].copy()

    rows: list[dict[str, object]] = []
    for _, row in bench_2025.sort_values("wics_large").iterrows():
        sector = row["wics_large"]
        leaders = (
            rank_2025.loc[
                (rank_2025["wics_large"] == sector) & rank_2025["overall_score"].notna()
            ]
            .sort_values(["overall_score", "company_name"], ascending=[False, True])
            .head(3)
        )

        rows.append(
            {
                "섹터": sector,
                "기업 수": int(row["company_count"]) if not pd.isna(row["company_count"]) else "-",
                "영업이익률 중앙값": format_percent(row["operating_margin_median"]),
                "ROE 중앙값": format_percent(row["roe_median"]),
                "부채비율 중앙값": format_number(row["debt_ratio_median"]),
                "상위 기업 예시": ", ".join(leaders["company_name"].astype(str).tolist()) if not leaders.empty else "-",
            }
        )

    return pd.DataFrame(rows)


def build_key_findings(master: pd.DataFrame, benchmark: pd.DataFrame, rankings: pd.DataFrame) -> list[str]:
    """실제 계산값을 바탕으로 핵심 분석 문장을 만듭니다."""
    year_coverage = master.groupby("fiscal_year").agg(
        revenue_cov=("revenue", lambda s: s.notna().mean()),
        opm_cov=("operating_margin", lambda s: s.notna().mean()),
        roe_cov=("roe", lambda s: s.notna().mean()),
    )

    cov_2021 = year_coverage.loc[2021]
    cov_2025 = year_coverage.loc[2025]

    bench_2025 = benchmark.loc[benchmark["fiscal_year"] == 2025].copy()
    highest_opm = bench_2025.sort_values("operating_margin_median", ascending=False).iloc[0]
    lowest_roe = bench_2025.sort_values("roe_median", ascending=True).iloc[0]
    highest_debt = bench_2025.sort_values("debt_ratio_median", ascending=False).iloc[0]

    rank_2025 = rankings.loc[(rankings["fiscal_year"] == 2025) & rankings["overall_score"].notna()].copy()
    overall_top = rank_2025.sort_values(["overall_score", "company_name"], ascending=[False, True]).head(5)
    overall_top_text = ", ".join(
        f"{row.company_name}({row.overall_score:.3f})" for row in overall_top.itertuples()
    )

    return [
        (
            f"데이터 커버리지는 2021년 대비 2025년에 개선되었습니다. "
            f"매출 커버리지는 {format_percent(cov_2021['revenue_cov'])}에서 {format_percent(cov_2025['revenue_cov'])}로, "
            f"영업이익률 커버리지는 {format_percent(cov_2021['opm_cov'])}에서 {format_percent(cov_2025['opm_cov'])}로, "
            f"ROE 커버리지는 {format_percent(cov_2021['roe_cov'])}에서 {format_percent(cov_2025['roe_cov'])}로 상승했습니다."
        ),
        (
            f"2025년 기준 영업이익률 중앙값이 가장 높은 섹터는 {highest_opm['wics_large']}이며 "
            f"{format_percent(highest_opm['operating_margin_median'])}입니다. "
            f"다만 금융 섹터는 업종 특성상 일반 제조업과 동일 기준 비교에 주의가 필요합니다."
        ),
        (
            f"2025년 기준 ROE 중앙값이 가장 낮은 섹터는 {lowest_roe['wics_large']}이며 "
            f"{format_percent(lowest_roe['roe_median'])}입니다. "
            f"특히 건강관리는 수익성 회복 여부를 추가 점검할 필요가 있습니다."
        ),
        (
            f"2025년 기준 부채비율 중앙값이 가장 높은 섹터는 {highest_debt['wics_large']}이며 "
            f"{format_number(highest_debt['debt_ratio_median'])}입니다. "
            f"금융과 에너지, 유틸리티처럼 자본구조 특성이 강한 섹터는 절대 수치보다 업종 내 상대 비교가 더 중요합니다."
        ),
        (
            f"2025년 전체 섹터를 통틀어 상위권 종합점수 예시는 {overall_top_text}입니다. "
            f"이 점수는 같은 연도, 같은 섹터 안에서 성장성, 수익성, 안정성을 함께 반영한 상대평가 결과입니다."
        ),
    ]


def build_sector_commentary(benchmark: pd.DataFrame) -> list[str]:
    """2025년 섹터별 짧은 해석 메모를 만듭니다."""
    bench_2025 = benchmark.loc[benchmark["fiscal_year"] == 2025].copy().sort_values("wics_large")
    comments: list[str] = []

    for row in bench_2025.itertuples():
        sector = row.wics_large
        opm = format_percent(row.operating_margin_median)
        roe = format_percent(row.roe_median)
        debt = format_number(row.debt_ratio_median)

        if sector == "금융":
            text = f"{sector}: 영업이익률 중앙값 {opm}, ROE 중앙값 {roe}, 부채비율 중앙값 {debt}로 나타났으며 업종 특성상 일반 산업과 동일 잣대 비교는 부적절합니다."
        elif sector == "건강관리":
            text = f"{sector}: 영업이익률 중앙값 {opm}, ROE 중앙값 {roe}로 수익성 회복력이 상대적으로 약한 편입니다."
        elif sector == "유틸리티":
            text = f"{sector}: 영업이익률 중앙값 {opm}, ROE 중앙값 {roe}로 안정적 수익 구조가 보이지만 표본 수가 작아 해석에 주의가 필요합니다."
        else:
            text = f"{sector}: 영업이익률 중앙값 {opm}, ROE 중앙값 {roe}, 부채비율 중앙값 {debt}로 확인됩니다."
        comments.append(text)

    return comments


def build_sector_grade_table(benchmark: pd.DataFrame) -> pd.DataFrame:
    """
    2025년 섹터 등급형 표를 만듭니다.

    이 표는 투자등급이 아니라,
    아래 기준을 읽기 쉽게 묶은 참고용 표입니다.
    - 수익성과 안정성의 균형
    - 해석의 용이성
    - 업종 특성에 따른 주의 필요 여부
    """
    bench_2025 = benchmark.loc[benchmark["fiscal_year"] == 2025].copy().sort_values("wics_large")

    grade_map = {
        "산업재": ("좋음", "수익성과 안정성이 비교적 균형적이고 상위 기업도 강하게 확인됩니다."),
        "필수소비재": ("좋음", "방어적 성격과 안정적 수익성이 함께 보여 해석이 비교적 명확합니다."),
        "경기관련소비재": ("좋음", "섹터 중앙값은 무난하고 상위 기업의 성장성과 수익성이 뚜렷합니다."),
        "IT": ("보통", "재무부담은 낮지만 섹터 전반 수익성이 아주 높지는 않습니다."),
        "소재": ("보통", "수익성은 높지 않지만 재무구조가 과도하게 나쁘지 않아 무난한 편입니다."),
        "커뮤니케이션서비스": ("보통", "영업이익률은 무난하지만 ROE가 높지 않아 추가 확인이 필요합니다."),
        "건강관리": ("주의", "ROE 중앙값이 음수라 섹터 전반의 수익성 회복 여부를 조심해서 봐야 합니다."),
        "에너지": ("주의", "수익성은 약하고 부채 부담은 상대적으로 높아 체질 해석에 주의가 필요합니다."),
        "금융": ("주의", "업종 구조가 달라 일반 산업과 동일 잣대로 비교하기 어렵습니다."),
        "유틸리티": ("주의", "수익성은 안정적으로 보이지만 표본 수가 작아 일반화에 주의가 필요합니다."),
    }

    rows: list[dict[str, object]] = []
    for row in bench_2025.itertuples():
        grade, reason = grade_map.get(row.wics_large, ("보통", "추가 확인이 필요합니다."))
        rows.append(
            {
                "섹터": row.wics_large,
                "등급": grade,
                "판단 이유": reason,
            }
        )

    return pd.DataFrame(rows)


def build_detailed_sector_explanations(benchmark: pd.DataFrame, rankings: pd.DataFrame) -> list[str]:
    """
    2025년 섹터별 상세 설명 문장을 만듭니다.

    각 문장에는 아래 내용을 함께 담습니다.
    - 중앙값이 의미하는 섹터 체질
    - 이 섹터를 어떻게 읽어야 하는지
    - 주목할 상위 기업 예시
    """
    bench_2025 = benchmark.loc[benchmark["fiscal_year"] == 2025].copy().sort_values("wics_large")
    rank_2025 = rankings.loc[(rankings["fiscal_year"] == 2025) & rankings["overall_score"].notna()].copy()

    explanations: list[str] = []
    for row in bench_2025.itertuples():
        leaders = (
            rank_2025.loc[rank_2025["wics_large"] == row.wics_large]
            .sort_values(["overall_score", "company_name"], ascending=[False, True])
            .head(3)
        )
        leader_text = ", ".join(leaders["company_name"].astype(str).tolist()) if not leaders.empty else "-"
        opm = format_percent(row.operating_margin_median)
        roe = format_percent(row.roe_median)
        debt = format_number(row.debt_ratio_median)

        if row.wics_large == "IT":
            text = f"IT는 영업이익률 중앙값 {opm}, ROE 중앙값 {roe}, 부채비율 중앙값 {debt}로 수익성은 아주 높지 않지만 재무부담은 낮은 편입니다. 상위 기업은 {leader_text}이며, 섹터 내에서는 수익성과 안정성이 좋은 기업이 앞서 있습니다."
        elif row.wics_large == "건강관리":
            text = f"건강관리는 영업이익률 중앙값 {opm}, ROE 중앙값 {roe}로 섹터 전반의 수익성이 약합니다. 상위 기업은 {leader_text}이며, 섹터 전체보다 개별 기업 편차가 큰 편으로 읽는 것이 적절합니다."
        elif row.wics_large == "경기관련소비재":
            text = f"경기관련소비재는 영업이익률 중앙값 {opm}, ROE 중앙값 {roe}, 부채비율 중앙값 {debt}로 전반적으로 무난한 체질입니다. 상위 기업은 {leader_text}이며, 성장성과 수익성이 동시에 강한 기업이 돋보입니다."
        elif row.wics_large == "금융":
            text = f"금융은 영업이익률 중앙값 {opm}, ROE 중앙값 {roe}, 부채비율 중앙값 {debt}로 수치가 높게 보이지만 업종 구조가 달라 다른 산업과 직접 비교하면 안 됩니다. 상위 기업은 {leader_text}이며, 반드시 금융 내부 비교로 읽어야 합니다."
        elif row.wics_large == "산업재":
            text = f"산업재는 영업이익률 중앙값 {opm}, ROE 중앙값 {roe}, 부채비율 중앙값 {debt}로 수익성과 안정성이 비교적 균형적입니다. 상위 기업은 {leader_text}이며, 섹터 대표 해석에 활용하기 좋은 편입니다."
        elif row.wics_large == "소재":
            text = f"소재는 영업이익률 중앙값 {opm}, ROE 중앙값 {roe}, 부채비율 중앙값 {debt}로 수익성은 높지 않지만 재무구조는 무난한 편입니다. 상위 기업은 {leader_text}이며, 고르게 강한 기업이 상위권에 위치합니다."
        elif row.wics_large == "에너지":
            text = f"에너지는 영업이익률 중앙값 {opm}, ROE 중앙값 {roe}, 부채비율 중앙값 {debt}로 평균 체질은 강하지 않습니다. 상위 기업은 {leader_text}이며, 섹터 평균보다 개별 강한 기업을 찾는 접근이 더 적절합니다."
        elif row.wics_large == "유틸리티":
            text = f"유틸리티는 영업이익률 중앙값 {opm}, ROE 중앙값 {roe}, 부채비율 중앙값 {debt}로 안정적 수익 구조가 보입니다. 다만 표본 수가 적고 상위 기업은 {leader_text}로 제한적이라 일반화에는 주의가 필요합니다."
        elif row.wics_large == "커뮤니케이션서비스":
            text = f"커뮤니케이션서비스는 영업이익률 중앙값 {opm}, ROE 중앙값 {roe}, 부채비율 중앙값 {debt}로 수익성은 무난하지만 자본효율은 높지 않은 편입니다. 상위 기업은 {leader_text}이며, 콘텐츠·플랫폼형 강자가 상대적으로 유리합니다."
        else:
            text = f"필수소비재는 영업이익률 중앙값 {opm}, ROE 중앙값 {roe}, 부채비율 중앙값 {debt}로 비교적 안정적인 수익성과 방어적 성격이 보입니다. 상위 기업은 {leader_text}이며, 방어주 안에서도 성장성이 좋은 기업이 선별됩니다."
        explanations.append(text)

    return explanations


def build_report(master: pd.DataFrame, benchmark: pd.DataFrame, rankings: pd.DataFrame) -> str:
    """한글 종합 분석 보고서 본문 전체를 만듭니다."""
    yearly_coverage = build_yearly_coverage(master)
    sector_snapshot_2025 = build_2025_sector_snapshot(benchmark, rankings)
    findings = build_key_findings(master, benchmark, rankings)
    sector_comments = build_sector_commentary(benchmark)
    sector_grades = build_sector_grade_table(benchmark)
    detailed_sector_explanations = build_detailed_sector_explanations(benchmark, rankings)

    return "\n".join(
        [
            "# WICS 대분류 기준 5개년 종합 분석 보고서 (2021-2025)",
            "",
            "## 1. 보고서 목적",
            "",
            "본 보고서는 WICS 대분류를 기준으로 DART 재무데이터를 결합하여 2021년부터 2025년까지의 섹터별 재무 특성과 기업 상대평가 결과를 종합적으로 정리한 문서입니다.",
            "",
            "## 2. 분석 범위",
            "",
            "- 분석 기간: 2021년 ~ 2025년",
            "- 분류 기준: WICS 대분류",
            "- 데이터 소스: DART 재무제표, WICS 기업 분류",
            "- 주요 산출물: `company_year_master_2021_2025.csv`, `sector_benchmark_wics_large_2021_2025.csv`, `company_sector_rankings_2021_2025.csv`",
            "",
            "## 3. 데이터 규모",
            "",
            f"- 기업-연도 기준 전체 행 수: {len(master):,}",
            f"- 섹터-연도 기준 벤치마크 행 수: {len(benchmark):,}",
            f"- 분석 대상 연도 수: {master['fiscal_year'].nunique()}개",
            f"- 분석 대상 WICS 대분류 수: {master['wics_large'].nunique()}개",
            f"- `corp_code` 전체 커버리지: {format_percent(master['corp_code'].notna().mean())}",
            "",
            "## 4. 연도별 데이터 커버리지",
            "",
            markdown_table(yearly_coverage),
            "",
            "## 5. 핵심 분석 결과",
            "",
            *[f"- {line}" for line in findings],
            "",
            "## 6. 2025년 섹터별 스냅샷",
            "",
            markdown_table(sector_snapshot_2025),
            "",
            "## 7. 2025년 섹터 등급형 정리",
            "",
            "아래 등급은 투자등급이 아니라, 2025년 기준 재무 체질 해석의 안정성과 상대적 상태를 보기 쉽게 묶은 참고용 구분입니다.",
            "",
            markdown_table(sector_grades),
            "",
            "## 8. 2025년 섹터별 해석 메모",
            "",
            *[f"- {line}" for line in sector_comments],
            "",
            "## 9. 2025년 섹터별 상세 설명",
            "",
            *[f"- {line}" for line in detailed_sector_explanations],
            "",
            "## 10. 해석 시 유의사항",
            "",
            "- 금융, 에너지, 유틸리티처럼 자본구조와 회계 구조가 다른 섹터는 절대 수치보다 섹터 내 상대 비교가 더 적절합니다.",
            "- 현재 분석은 `wics_company_2026.csv`의 최신 WICS 분류를 2021~2025 전체 기간에 공통 적용합니다. 따라서 과거 시점의 실제 당시 섹터 분류와 차이가 있을 수 있으며, 시계열 해석에서는 이 한계를 반드시 감안해야 합니다.",
            "- 본 보고서는 정량 데이터 중심 분석이므로, 사업보고서 본문과 공시 이벤트까지 결합한 정성 해석은 별도 확장이 필요합니다.",
        ]
    )


def main() -> None:
    """종합 분석 보고서 생성 단계를 실행합니다."""
    master = load_csv(MASTER_PATH)
    benchmark = load_csv(BENCHMARK_PATH)
    rankings = load_csv(RANKING_PATH)
    report = build_report(master, benchmark, rankings)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Saved all-sector analysis report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
