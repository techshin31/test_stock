from __future__ import annotations

from pathlib import Path

import pandas as pd


# ============================================================
# 이 파일은 2021~2025 각 연도마다 같은 WICS 대분류 안에서
# 기업들을 상대평가합니다.
#
# 예를 들면 아래 질문에 답할 수 있습니다.
# - 2023년 IT 섹터에서 어떤 기업의 성장성이 강했는가?
# - 2025년 소재 섹터에서 어떤 기업이 안정적인가?
#
# 최종 결과물:
#   company_sector_rankings_2021_2025.csv
# ============================================================


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "etl" / "wics_dart" / "output"
MASTER_PATH = OUTPUT_DIR / "company_year_master_2021_2025.csv"
RANKING_PATH = OUTPUT_DIR / "company_sector_rankings_2021_2025.csv"


def load_master() -> pd.DataFrame:
    """다개년 마스터 테이블을 읽습니다."""
    return pd.read_csv(MASTER_PATH)


def percentile_rank(series: pd.Series, *, ascending: bool) -> pd.DataFrame:
    """같은 연도·같은 섹터 안에서 순위와 percentile을 계산합니다."""
    valid = series.dropna()

    if valid.empty:
        return pd.DataFrame(index=series.index, columns=["rank", "percentile"])

    ordered = valid.sort_values(ascending=ascending)
    ranks = pd.Series(range(1, len(ordered) + 1), index=ordered.index)

    if len(ordered) == 1:
        percentiles = pd.Series(1.0, index=ordered.index)
    else:
        percentiles = (len(ordered) - ranks) / (len(ordered) - 1)

    result = pd.DataFrame(index=series.index, columns=["rank", "percentile"])
    result.loc[ranks.index, "rank"] = ranks
    result.loc[percentiles.index, "percentile"] = percentiles
    return result


def bucket_from_score(score: float | None) -> str | None:
    """종합점수를 읽기 쉬운 구간 라벨로 바꿉니다."""
    if pd.isna(score):
        return None
    if score >= 0.8:
        return "top_20%"
    if score >= 0.6:
        return "top_40%"
    if score >= 0.4:
        return "middle"
    if score >= 0.2:
        return "bottom_40%"
    return "bottom_20%"


def score_group(group: pd.DataFrame) -> pd.DataFrame:
    """하나의 연도·섹터 그룹에 대해 상대평가 점수를 계산합니다."""
    result = group.copy()

    metric_rules = {
        "revenue_growth_yoy": False,
        "operating_margin": False,
        "roe": False,
        "debt_ratio": True,
        "current_ratio": False,
        "ocf_to_revenue": False,
    }

    for metric, ascending in metric_rules.items():
        score_df = percentile_rank(result[metric], ascending=ascending)
        result[f"{metric}_rank"] = score_df["rank"]
        result[f"{metric}_percentile"] = score_df["percentile"]

    result["growth_score"] = result["revenue_growth_yoy_percentile"]
    result["profitability_score"] = result[
        ["operating_margin_percentile", "roe_percentile"]
    ].mean(axis=1, skipna=True)
    result["stability_score"] = result[
        ["debt_ratio_percentile", "current_ratio_percentile", "ocf_to_revenue_percentile"]
    ].mean(axis=1, skipna=True)
    result["overall_score"] = result[
        ["growth_score", "profitability_score", "stability_score"]
    ].mean(axis=1, skipna=True)
    result["overall_bucket"] = result["overall_score"].apply(bucket_from_score)
    return result


def build_rankings(master: pd.DataFrame) -> pd.DataFrame:
    """2021~2025 전체 기업-섹터 랭킹 테이블을 만듭니다."""
    frames: list[pd.DataFrame] = []

    for (fiscal_year, wics_large), group in master.groupby(["fiscal_year", "wics_large"], dropna=False):
        scored = score_group(group)
        scored["fiscal_year"] = fiscal_year
        scored["wics_large"] = wics_large
        frames.append(scored)

    ranking = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    ranking = ranking.sort_values(
        ["fiscal_year", "wics_large", "overall_score", "company_name"],
        ascending=[True, True, False, True],
        na_position="last",
    )
    return ranking


def main() -> None:
    """다개년 섹터 랭킹 계산 단계를 실행합니다."""
    master = load_master()
    ranking = build_rankings(master)
    ranking.to_csv(RANKING_PATH, index=False, encoding="utf-8-sig")
    print(f"Saved sector ranking table: {RANKING_PATH}")


if __name__ == "__main__":
    main()
