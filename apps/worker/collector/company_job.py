"""기업 데이터 수집 Job.

financial_statements / fa_metrics / dart_events 테이블을 채운다.
- DART 이벤트: 접수번호별 정기공시와 정정공시를 증분 수집
- 재무제표: 최신 미수집 접수번호의 분기 원본을 저장
"""
from __future__ import annotations

from datetime import date

from data.loaders.company_data import (
    collect_companies_from_wics,
    collect_dart_events,
    collect_financial_statements,
    sync_company_status,
)
from apps.worker.company_risk import refresh_company_risk_states
from storage.postgres.connection import PostgreDB


def run(
    db: PostgreDB,
    years: list[int] | None = None,
    dart_start_date: str = "20200101",
    dart_end_date: str | None = None,
    show_progress: bool = True,
    company_size_codes: list[str] | None = None,
) -> dict[str, int]:
    """재무제표 + DART 이벤트를 수집해 DB에 저장한다.

    Parameters
    ----------
    db : PostgreDB
    years : list[int], optional
        재무제표 수집 연도 목록. 미입력 시 올해 포함 최근 3개년.
    dart_start_date : str
        DART 이벤트 수집 시작일 (YYYYMMDD). 증분 수집이므로 실질적 하한선.
    dart_end_date : str, optional
        DART 이벤트 수집 종료일 (YYYYMMDD). 미입력 시 오늘.
    show_progress : bool
        tqdm 진행바 및 콘솔 출력 여부.

    Returns
    -------
    dict[str, int]
        {"financial_statements": 수집된 (종목·연도) 수, "dart_events": 수집된 이벤트 수}
    """
    as_of_date = (
        date.fromisoformat(f"{dart_end_date[:4]}-{dart_end_date[4:6]}-{dart_end_date[6:]}")
        if dart_end_date
        else date.today()
    )
    effective_years = years or [as_of_date.year - 2, as_of_date.year - 1, as_of_date.year]
    effective_dart_end_date = dart_end_date or as_of_date.strftime("%Y%m%d")

    collect_companies_from_wics(db, show_progress=show_progress)
    sync_company_status(db, show_progress=show_progress)

    if show_progress:
        print(f"[COMPANY] DART 이벤트 수집: {dart_start_date} ~ {effective_dart_end_date}")
    event_count = collect_dart_events(
        db, dart_start_date, effective_dart_end_date,
        show_progress=show_progress,
        company_size_codes=company_size_codes,
    )
    print(f"[COMPANY] DART 이벤트 완료: {event_count}건 저장")
    risk_state_count = refresh_company_risk_states(db, as_of_date)
    print(f"[COMPANY] 기업 위험상태 완료: {risk_state_count}개 이벤트 상태 upsert")

    if show_progress:
        print(f"[COMPANY] 분기 재무제표 수집 연도: {effective_years}")
    fs_count = collect_financial_statements(
        db,
        effective_years,
        show_progress=show_progress,
        company_size_codes=company_size_codes,
    )
    print(f"[COMPANY] 분기 재무제표 완료: {fs_count}개 보고서 버전 저장")

    return {
        "financial_statements": fs_count,
        "dart_events": event_count,
        "company_risk_states": risk_state_count,
    }
