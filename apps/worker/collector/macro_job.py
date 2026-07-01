"""매크로 시그널 수집 Job.

macro_signals 테이블에 FA 계약 매크로 시그널을 증분 저장한다.
auto_start=True이므로 시그널별 마지막 저장일 다음 날부터만 수집한다.
"""
from __future__ import annotations

from datetime import date

from storage.postgres.connection import PostgreDB


def run(
    db: PostgreDB,
    start: str | None = None,
    end: str | None = None,
    fred_api_key: str | None = None,
    kto_api_key: str | None = None,
    show_progress: bool = True,
) -> dict[str, int]:
    """매크로 시그널 전체를 수집해 DB에 저장한다.

    Parameters
    ----------
    db : PostgreDB
    start : str, optional
        수집 시작일 (YYYY-MM-DD). auto_start=True이면 DB 최신일 이후 날짜를 우선 사용.
    end : str, optional
        수집 종료일 (YYYY-MM-DD). 미입력 시 오늘.
    fred_api_key : str, optional
        FRED API 키 (CPI 수집). 미입력 시 환경변수 FRED_API_KEY 참조.
    kto_api_key : str, optional
        KTO API 키 (외국인 관광객 수집). 미입력 시 환경변수 KTO_API_KEY 참조.
    show_progress : bool
        진행 상황 콘솔 출력 여부.

    Returns
    -------
    dict[str, int]
        signal_name_code → 저장된 행 수.
    """
    from data.preprocess.macro_signals import collect_and_save

    effective_start = start or "2010-01-01"
    effective_end = end or date.today().isoformat()

    if show_progress:
        print(f"[MACRO] 수집 기간: {effective_start} ~ {effective_end}")

    result = collect_and_save(
        db,
        start=effective_start,
        end=effective_end,
        fred_api_key=fred_api_key,
        kto_api_key=kto_api_key,
        source_release_collected_date=date.fromisoformat(effective_end),
        auto_start=True,
    )

    total = sum(result.values())
    print(f"[MACRO] 완료: {len(result)}개 시그널, 총 {total}건 저장")
    return result
