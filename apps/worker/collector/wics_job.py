"""WICS 섹터 구성종목 수집 Job.

wics_companies 테이블에 날짜별 WICS 스냅샷을 저장한다.
이미 수집된 날짜는 WiseIndex API를 호출하지 않는다.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from storage.postgres.connection import PostgreDB


def _today_kst() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def run(
    db: PostgreDB,
    date_list: list[str] | None = None,
    show_progress: bool = True,
    force_refresh: bool = False,
    price_start: str | None = None,
    price_end: str | None = None,
    collect_prices: bool = True,
) -> int:
    """WICS 구성종목을 수집해 DB에 저장한다.

    Parameters
    ----------
    db : PostgreDB
    date_list : list[str], optional
        수집할 날짜 목록 (YYYYMMDD). 미입력 시 오늘 날짜만 수집.
    show_progress : bool
        tqdm 진행바 및 콘솔 출력 여부.
    price_start : str, optional
        WICS 구성종목 가격 수집 시작일 (YYYY-MM-DD).
    price_end : str, optional
        WICS 구성종목 가격 수집 종료일 (YYYY-MM-DD).
    collect_prices : bool
        True면 가격 수집까지 실행. False면 구성종목 스냅샷만 저장하고 종료.
        collect all 흐름에서는 companies 테이블이 채워진 뒤 별도로 가격을 수집하므로
        False로 호출한다.

    Returns
    -------
    int
        새로 수집한 날짜 수.
    """
    from data.loaders.wics_data import collect_wics_companies

    effective_dates = (
        [_today_kst().strftime("%Y%m%d")]
        if date_list is None
        else date_list
    )

    if not effective_dates:
        if show_progress:
            print("[WICS] 수집 대상 날짜 없음")
        return 0

    if show_progress:
        print(f"[WICS] 조회 범위 {len(effective_dates)}건: {effective_dates[0]} ~ {effective_dates[-1]}")

    count = collect_wics_companies(
        db,
        effective_dates,
        show_progress=show_progress,
        force_refresh=force_refresh,
    )
    print(f"[WICS] 완료: {count}개 날짜 신규 저장 (기수집 날짜는 건너뜀)")

    if collect_prices:
        from apps.worker.collector import wics_industry_job

        wics_industry_job.run(
            db,
            start=price_start,
            end=price_end,
            show_progress=show_progress,
        )
    return count


def build_date_range(start: str, end: str | None = None) -> list[str]:
    """start ~ end 범위의 날짜 목록을 YYYYMMDD 형식으로 생성한다."""
    start_d = date.fromisoformat(start)
    end_d = date.fromisoformat(end) if end else date.today()

    dates: list[str] = []
    cur = start_d
    while cur <= end_d:
        dates.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return dates
