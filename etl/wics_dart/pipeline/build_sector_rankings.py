from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

WICS_DART_DIR = Path(__file__).resolve().parents[1]
if str(WICS_DART_DIR) not in sys.path:
    sys.path.insert(0, str(WICS_DART_DIR))

from core.scoring import build_event_features, build_rankings, empty_event_features


# ============================================================
# 이 파일은 2021~2025 각 연도마다 같은 WICS 대분류 안에서
# 기업들을 상대평가하는 파이프라인 진입점입니다.
#
# 실제 점수 기준과 계산식은 core/scoring.py에 모아두었습니다.
#
# 최종 결과물:
#   company_sector_rankings_2021_2025.csv
# ============================================================


ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = ROOT / "etl" / "wics_dart" / "output"
COMPANY_DATA_DIR = ROOT / "etl" / "company" / "data"
MASTER_PATH = OUTPUT_DIR / "company_year_master_2021_2025.csv"
RANKING_PATH = OUTPUT_DIR / "company_sector_rankings_2021_2025.csv"


def load_master() -> pd.DataFrame:
    """다개년 마스터 테이블을 읽습니다."""
    master = pd.read_csv(MASTER_PATH)
    master["stock_code"] = master["stock_code"].astype(str).str.split(".").str[0].str.zfill(6)
    master["fiscal_year"] = pd.to_numeric(master["fiscal_year"], errors="coerce").astype("Int64")
    return master


def latest_event_path() -> Path | None:
    candidates = list(COMPANY_DATA_DIR.glob("dart_reference_events_*.csv"))
    return max(candidates, key=lambda path: (path.stat().st_size, path.stat().st_mtime)) if candidates else None


def load_event_features() -> pd.DataFrame:
    """DART 이벤트 공시를 기업-연도 단위 특징으로 집계합니다."""
    event_path = latest_event_path()
    if event_path is None:
        return empty_event_features()

    events = pd.read_csv(
        event_path,
        dtype={"stock_code": str, "rcept_dt": str, "event_category": str, "event_subtype": str},
    )
    return build_event_features(events)


def main() -> None:
    """다개년 섹터 랭킹 계산 단계를 실행합니다."""
    master = load_master()
    event_features = load_event_features()
    ranking = build_rankings(master, event_features)
    ranking.to_csv(RANKING_PATH, index=False, encoding="utf-8-sig")
    print(f"Saved sector ranking table: {RANKING_PATH}")


if __name__ == "__main__":
    main()
