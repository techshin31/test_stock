from __future__ import annotations

from pathlib import Path
import subprocess
import sys


# ============================================================
# 이 파일은 로컬 데이터 파이프라인을 한 번에 실행할 때
# 가장 먼저 보면 되는 진입점입니다.
#
# 뒤 단계는 앞 단계 결과물을 사용하므로,
# 스크립트를 정해진 순서대로 실행합니다.
#
# 현재 파이프라인 순서:
# 1. build_master_table.py
# 2. validate_master_table.py
# 3. build_sector_rankings.py
# 4. build_top_companies_report.py
# 5. prepare_text_targets.py
# 6. build_all_sector_analysis_report.py
#
# 텍스트 수집은 여기 포함하지 않았습니다.
# 그 단계는 아래 조건이 추가로 필요하기 때문입니다.
# - DART_API_KEY
# - network access
# - extra package setup
# ============================================================


ROOT = Path(__file__).resolve().parent


def run_step(script_name: str) -> None:
    """각 파이프라인 스크립트를 별도 Python 프로세스로 실행합니다."""
    script_path = ROOT / script_name
    print(f"[RUN] {script_path.name}")
    subprocess.run([sys.executable, str(script_path)], check=True)


def main() -> None:
    """2021~2025 로컬 데이터 분석 파이프라인을 순서대로 실행합니다."""
    steps = [
        "build_master_table.py",
        "validate_master_table.py",
        "build_sector_rankings.py",
        "build_top_companies_report.py",
        "prepare_text_targets.py",
        "build_all_sector_analysis_report.py",
    ]

    for step in steps:
        run_step(step)

    print("[DONE] Pipeline finished successfully.")


if __name__ == "__main__":
    main()
