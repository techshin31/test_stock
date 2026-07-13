from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m apps.worker",
        description="QuantPilot 데이터 워커",
    )
    subparsers = parser.add_subparsers(dest="category", required=True)

    # ── collect ────────────────────────────────────────────────────────────
    collect_p = subparsers.add_parser("collect", help="데이터 수집")
    collect_p.add_argument(
        "target",
        choices=["macro", "wics", "company", "all"],
        help=(
            "macro: 매크로 시그널 | "
            "wics: WICS 섹터 구성종목 | "
            "company: 재무제표·공시 이벤트 | "
            "all: 전체"
        ),
    )
    collect_p.add_argument("--start", metavar="YYYY-MM-DD", help="수집 시작일")
    collect_p.add_argument("--end",   metavar="YYYY-MM-DD", help="수집 종료일")
    collect_p.add_argument(
        "--years", nargs="+", type=int, metavar="YEAR",
        help="재무제표 수집 연도 (예: --years 2022 2023 2024)",
    )
    collect_p.add_argument(
        "--no-progress", action="store_true",
        help="tqdm 진행바 비활성화 (cron 환경 등)",
    )
    collect_p.add_argument(
        "--check-readiness", action="store_true",
        help="수집 후 cutoff 기준 Analyzer 입력 준비도 리포트 출력 (all 전용)",
    )
    collect_p.add_argument(
        "--wics-snapshot-frequency",
        choices=["weekly", "daily"],
        default="weekly",
        help="WICS 기간 수집 간격 (기본: weekly)",
    )
    collect_p.add_argument(
        "--company-size",
        choices=["LARGE", "MID", "SMALL"],
        action="append",
        help="기업 수집 WICS 규모 필터 (미입력: 전체)",
    )
    collect_p.add_argument(
        "--force-refresh",
        action="store_true",
        help="기수집 WICS 스냅샷도 다시 조회해 교정 (wics 전용)",
    )

    # ── analyze ────────────────────────────────────────────────────────────
    analyze_p = subparsers.add_parser("analyze", help="FA 분석")
    analyze_p.add_argument(
        "target",
        choices=["macro", "sector", "company", "all"],
        help=(
            "macro: 매크로 시그널 분석 | "
            "sector: WICS 섹터 순환 분석 | "
            "company: 재무지표 스크리닝 | "
            "all: 전체"
        ),
    )
    analyze_p.add_argument("--analysis-month", metavar="YYYY-MM")
    analyze_p.add_argument("--cutoff", metavar="YYYY-MM-DD")
    analyze_p.add_argument("--effective-date", metavar="YYYY-MM-DD")
    analyze_p.add_argument("--publish", action="store_true")
    analyze_p.add_argument("--force", action="store_true")
    analyze_p.add_argument("--no-progress", action="store_true")
    analyze_p.add_argument(
        "--reuse-quarter-scores", action="store_true",
        help="역사 리플레이에서 기존 포인트인타임 분기 FA 점수를 재사용",
    )

    subparsers.add_parser("audit", help="FA 시점 안전성과 운영 상태 감사")

    return parser.parse_args()


def _init():
    from apps.worker.config import build_db_config, load_config
    from storage.postgres.connection import PostgreDB

    cfg = load_config()
    db = PostgreDB(build_db_config())
    return cfg, db


def _today_kst() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _wics_date_list(
    start: str | None,
    end: str | None,
    frequency: str = "weekly",
) -> list[str] | None:
    """--start/--end를 YYYYMMDD 날짜 목록으로 변환한다.

    둘 다 미입력이면 None 반환 → wics_job 기본값(오늘)을 사용한다.
    """
    if start is None and end is None:
        return None

    start_d = date.fromisoformat(start) if start else _today_kst()
    end_d   = date.fromisoformat(end)   if end   else _today_kst()

    dates: list[date] = []
    cur = start_d
    while cur <= end_d:
        dates.append(cur)
        cur += timedelta(days=1)
    if frequency == "daily":
        return [item.strftime("%Y%m%d") for item in dates]

    from core.utils.trading_calendar import is_krx_trading_day

    weekly_last_sessions: dict[tuple[int, int], date] = {}
    for item in dates:
        if is_krx_trading_day(item.isoformat()):
            iso_year, iso_week, _ = item.isocalendar()
            weekly_last_sessions[(iso_year, iso_week)] = item
    return [
        item.strftime("%Y%m%d")
        for item in weekly_last_sessions.values()
    ]


def _resolve_collect_start(
    target: str,
    start: str | None,
    end: str | None,
    *,
    today: date | None = None,
) -> str | None:
    if start is not None or target != "all":
        return start
    if end is not None:
        base_date = date.fromisoformat(end)
    else:
        base_date = today or _today_kst()
    return (base_date - timedelta(days=1)).isoformat()


def _resolve_collect_end(
    target: str,
    end: str | None,
    *,
    today: date | None = None,
) -> str | None:
    if end is not None or target != "all":
        return end
    base_date = today or _today_kst()
    return (base_date - timedelta(days=1)).isoformat()


def run_collect(args: argparse.Namespace) -> None:
    from apps.worker.collector import company_job, macro_job, wics_job

    cfg, db = _init()
    show = not args.no_progress
    collect_start = _resolve_collect_start(args.target, args.start, args.end)
    collect_end = _resolve_collect_end(args.target, args.end)

    try:
        if args.target in ("macro", "all"):
            macro_job.run(
                db,
                start=collect_start,
                end=collect_end,
                fred_api_key=cfg.fred_api_key,
                kto_api_key=cfg.kto_api_key,
                show_progress=show,
            )

        if args.target in ("wics", "all"):
            # collect all: companies 테이블이 아직 없으므로 가격 수집을 건너뛴다.
            # 가격은 company_job 이후에 별도로 수집한다.
            wics_job.run(
                db,
                date_list=_wics_date_list(
                    collect_start, collect_end, args.wics_snapshot_frequency
                ),
                show_progress=show,
                force_refresh=args.force_refresh,
                price_start=collect_start,
                price_end=collect_end,
                collect_prices=(args.target == "wics"),
            )

        if args.target in ("company", "all"):
            if args.years:
                effective_years = args.years
            elif collect_start:
                start_year = date.fromisoformat(collect_start).year
                end_year = (
                    date.fromisoformat(collect_end).year
                    if collect_end
                    else _today_kst().year
                )
                effective_years = list(range(start_year, end_year + 1))
            else:
                effective_years = cfg.company_years

            dart_start = collect_start.replace("-", "") if collect_start else cfg.dart_start_date
            dart_end = collect_end.replace("-", "") if collect_end else None

            company_job.run(
                db,
                years=effective_years,
                dart_start_date=dart_start,
                dart_end_date=dart_end,
                show_progress=show,
                company_size_codes=args.company_size,
            )

        if args.target == "all":
            from apps.worker.collector import wics_industry_job

            wics_industry_job.run(
                db,
                start=collect_start,
                end=collect_end,
                show_progress=show,
            )

        if args.check_readiness:
            if args.target != "all":
                raise ValueError("--check-readiness is only valid with 'collect all'")
            from apps.worker.collector.readiness import run as run_readiness

            cutoff_date = date.fromisoformat(collect_end) if collect_end else date.today()
            report = run_readiness(db, cutoff_date)
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    finally:
        db.close()


def run_analyze(args: argparse.Namespace) -> None:
    from apps.worker.analyzer.config import load_config as load_analyzer_config
    from apps.worker.analyzer.pipeline import build_request, run

    _, db = _init()
    try:
        request = build_request(
            target=args.target,
            analysis_month=args.analysis_month,
            cutoff_date=args.cutoff,
            effective_date=args.effective_date,
            publish=args.publish,
            force=args.force,
            reuse_quarter_scores=args.reuse_quarter_scores,
        )
        context = run(db, request, load_analyzer_config(), show_progress=not args.no_progress)
        print()
        print(json.dumps({
            "run_id": context.run_id,
            "target": context.target,
            "analysis_month": context.analysis_month.isoformat(),
            "cutoff_date": context.cutoff_date.isoformat(),
            "effective_date": context.effective_date.isoformat(),
            "input_hash": context.input_hash,
            "model_version": context.model_version,
            "created": context.created,
        }, ensure_ascii=False, indent=2))
    finally:
        db.close()


def run_audit() -> None:
    from apps.worker.analyzer.operations import audit_operational_state

    _, db = _init()
    try:
        report = audit_operational_state(db)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        if report.status != "PASS":
            raise RuntimeError("operational audit failed")
    finally:
        db.close()


def main() -> None:
    args = _parse_args()

    if args.category == "collect":
        run_collect(args)
    elif args.category == "analyze":
        run_analyze(args)
    elif args.category == "audit":
        run_audit()


if __name__ == "__main__":
    main()
