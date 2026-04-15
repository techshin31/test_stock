from __future__ import annotations

from pathlib import Path

import pandas as pd


# ============================================================
# 이 파일은 사업보고서 본문을 직접 수집하지 않습니다.
#
# 역할은 나중에 텍스트 수집 대상으로 삼을 기업을
# 미리 고르는 것입니다.
#
# 현재 규칙:
# 1. 랭킹 파일에서 가장 최신 연도만 봅니다.
# 2. 기업 수가 많은 상위 5개 섹터를 찾습니다.
# 3. 각 섹터에서 overall_score 상위 5개 기업을 고릅니다.
#
# 최종 결과물:
#   text_targets_latest.csv
# ============================================================


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "etl" / "wics_dart" / "output"
RANKING_PATH = OUTPUT_DIR / "company_sector_rankings_2021_2025.csv"
TARGET_PATH = OUTPUT_DIR / "text_targets_latest.csv"


def load_rankings() -> pd.DataFrame:
    """섹터 랭킹 테이블을 읽습니다."""
    return pd.read_csv(RANKING_PATH)


def latest_year(rankings: pd.DataFrame) -> str:
    """랭킹 파일에서 가장 최신 연도를 찾습니다."""
    return max(rankings["fiscal_year"].astype(str).dropna().unique().tolist())


def find_priority_sectors(rankings: pd.DataFrame, fiscal_year: str, top_n: int = 5) -> list[str]:
    """특정 연도에서 행 수가 많은 섹터를 찾습니다."""
    year_rows = rankings.loc[rankings["fiscal_year"].astype(str) == str(fiscal_year)]
    return (
        year_rows.groupby("wics_large", dropna=False)
        .size()
        .sort_values(ascending=False)
        .head(top_n)
        .index.tolist()
    )


def build_targets(rankings: pd.DataFrame) -> pd.DataFrame:
    """최신 연도 랭킹을 기준으로 텍스트 수집 대상 목록을 만듭니다."""
    target_year = latest_year(rankings)
    priority_sectors = find_priority_sectors(rankings, target_year, top_n=5)
    target_frames: list[pd.DataFrame] = []

    for sector in priority_sectors:
        sector_rows = rankings.loc[
            (rankings["fiscal_year"].astype(str) == str(target_year))
            & (rankings["wics_large"] == sector)
            & rankings["corp_code"].notna()
            & rankings["overall_score"].notna()
        ].copy()

        sector_rows = sector_rows.sort_values(
            ["overall_score", "company_name"],
            ascending=[False, True],
            na_position="last",
        ).head(5)

        target_frames.append(
            sector_rows[
                [
                    "company_name",
                    "stock_code",
                    "corp_code",
                    "fiscal_year",
                    "wics_large",
                    "overall_score",
                    "overall_bucket",
                ]
            ]
        )

    if not target_frames:
        return pd.DataFrame(
            columns=[
                "company_name",
                "stock_code",
                "corp_code",
                "fiscal_year",
                "wics_large",
                "overall_score",
                "overall_bucket",
            ]
        )

    return pd.concat(target_frames, ignore_index=True)


def main() -> None:
    """텍스트 수집 대상 선정 단계를 실행합니다."""
    rankings = load_rankings()
    targets = build_targets(rankings)
    targets.to_csv(TARGET_PATH, index=False, encoding="utf-8-sig")
    print(f"Saved text target list: {TARGET_PATH}")


if __name__ == "__main__":
    main()
