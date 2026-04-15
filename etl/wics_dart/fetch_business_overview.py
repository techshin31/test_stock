from __future__ import annotations

import os
from pathlib import Path

import OpenDartReader
import pandas as pd

from etl.company.dart_api import fetch_business_overview


# ============================================================
# 이 파일은 DART에서 사업개요 텍스트를 수집합니다.
#
# 앞선 스크립트와 다르게 이 단계는 아래 조건이 필요합니다.
# - DART_API_KEY 환경변수
# - 인터넷 연결
# - OpenDartReader 설치
#
# 입력:
#   text_targets_latest.csv
#
# 출력:
#   business_overview_text_latest.csv
#
# 이 단계는 현재 로컬 데이터 파이프라인에서 선택 단계입니다.
# 정량 점수 위에 정성 텍스트 설명을 얹고 싶을 때 사용합니다.
# ============================================================


ROOT = Path(__file__).resolve().parents[2]
TARGET_PATH = ROOT / "etl" / "wics_dart" / "output" / "text_targets_latest.csv"
OUTPUT_PATH = ROOT / "etl" / "wics_dart" / "output" / "business_overview_text_latest.csv"


def load_targets() -> pd.DataFrame:
    """텍스트 수집 대상으로 선정된 기업 목록을 읽습니다."""
    if not TARGET_PATH.exists():
        raise FileNotFoundError(f"Target file not found: {TARGET_PATH}")
    return pd.read_csv(TARGET_PATH, dtype=str)


def get_dart_client() -> OpenDartReader.OpenDartReader:
    """
    DART API 클라이언트를 만듭니다.

    API 키는 DART_API_KEY 환경변수에 들어 있어야 합니다.
    """
    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        raise ValueError("DART_API_KEY environment variable is required")
    return OpenDartReader(api_key)


def build_text_rows(targets: pd.DataFrame) -> list[dict[str, str | None]]:
    """
    대상 기업별로 사업개요 텍스트를 수집합니다.

    각 출력 행에는 아래 정보가 함께 들어갑니다.
    - 기존 랭킹 정보
    - 수집된 사업개요 텍스트
    """
    dart = get_dart_client()
    rows: list[dict[str, str | None]] = []

    for target in targets.to_dict(orient="records"):
        corp_code = target["corp_code"]
        fiscal_year = int(target["fiscal_year"])
        text = fetch_business_overview(dart, corp_code, fiscal_year)

        rows.append(
            {
                "company_name": target["company_name"],
                "stock_code": target["stock_code"],
                "corp_code": corp_code,
                "fiscal_year": target["fiscal_year"],
                "wics_large": target["wics_large"],
                "overall_score": target["overall_score"],
                "overall_bucket": target["overall_bucket"],
                "business_overview_text": text,
            }
        )

    return rows


def main() -> None:
    """
    DART 텍스트 수집 단계를 실행합니다.

    입력:
    - text_targets_latest.csv

    출력:
    - business_overview_text_latest.csv
    """
    targets = load_targets()
    rows = build_text_rows(targets)
    pd.DataFrame(rows).to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"Saved business overview text: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
