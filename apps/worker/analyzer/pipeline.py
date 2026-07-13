"""Monthly analyzer orchestration skeleton."""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from apps.worker.analyzer.config import AnalyzerConfig
from apps.worker.analyzer.company_job import (
    refresh_quarterly_scores,
    run as run_company_selection,
)
from apps.worker.analyzer.macro_job import run as run_macro_analysis
from apps.worker.analyzer.sector_job import run as run_sector_analysis
from apps.worker.analyzer.models import AnalysisRunContext, RunStatus
from apps.worker.analyzer.validation import validate_run, validate_source_readiness
from apps.worker.analyzer.universe_job import publish as publish_universe
from apps.worker.fa_contract import (
    ANALYZE_TARGET_STEPS,
    REQUIRED_MACRO_CODES,
)
from tqdm import tqdm
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.fa_analysis_repo import (
    fail_stale_analysis_runs,
    get_or_create_analysis_run,
    update_analysis_run_status,
)
from storage.postgres.repositories.strategy_repo import fetch_active_strategy

KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class AnalysisRequest:
    target: str
    analysis_month: date
    cutoff_date: date
    effective_date: date
    publish: bool = False
    force: bool = False
    reuse_quarter_scores: bool = False

    def validate(self) -> None:
        if self.target not in ANALYZE_TARGET_STEPS:
            raise ValueError(f"unsupported analyzer target: {self.target}")
        if self.analysis_month.day != 1:
            raise ValueError("analysis_month must be the first day of a month")
        if self.cutoff_date > self.effective_date:
            raise ValueError("cutoff_date must not be later than effective_date")
        if self.publish and self.target != "all":
            raise ValueError("--publish is only valid for analyze all")


def _today_kst() -> date:
    return datetime.now(KST).date()


def build_request(
    *,
    target: str,
    analysis_month: str | date | None = None,
    cutoff_date: str | date | None = None,
    effective_date: str | date | None = None,
    publish: bool = False,
    force: bool = False,
    reuse_quarter_scores: bool = False,
) -> AnalysisRequest:
    today = _today_kst()
    cutoff = date.fromisoformat(cutoff_date) if isinstance(cutoff_date, str) else cutoff_date
    effective = (
        date.fromisoformat(effective_date)
        if isinstance(effective_date, str) else effective_date
    )
    cutoff = cutoff or today
    effective = effective or cutoff
    if analysis_month is None:
        month = effective.replace(day=1)
    elif isinstance(analysis_month, str):
        month = date.fromisoformat(
            f"{analysis_month}-01" if len(analysis_month) == 7 else analysis_month
        ).replace(day=1)
    else:
        month = analysis_month.replace(day=1)
    request = AnalysisRequest(
        target=target,
        analysis_month=month,
        cutoff_date=cutoff,
        effective_date=effective,
        publish=publish,
        force=force,
        reuse_quarter_scores=reuse_quarter_scores,
    )
    request.validate()
    return request


def _analysis_input_hash(
    readiness_hash: str,
    config_fingerprint: str,
    target: str,
    request: AnalysisRequest,
) -> str:
    payload = ":".join((
        readiness_hash,
        config_fingerprint,
        target,
        request.analysis_month.isoformat(),
        request.cutoff_date.isoformat(),
        request.effective_date.isoformat(),
        str(request.reuse_quarter_scores),
    ))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _macro_quality_summary(macro_results) -> dict:
    used = sorted(result.signal_name_code for result in macro_results)
    missing = sorted(set(REQUIRED_MACRO_CODES) - set(used))
    return {
        "used_macro_signals": used,
        "missing_macro_signals": missing,
        "macro_result_count": len(used),
        "required_macro_count": len(REQUIRED_MACRO_CODES),
    }


def _status_with_quality(base_status: str, input_quality: dict, macro_quality: dict) -> str:
    if base_status == RunStatus.FAIL.value:
        return base_status
    has_input_warning = input_quality.get("status") == "WARNING"
    has_missing_macros = bool(macro_quality.get("missing_macro_signals"))
    if has_input_warning or has_missing_macros or base_status == RunStatus.WARNING.value:
        return RunStatus.WARNING.value
    return RunStatus.PASS.value


def _run_stage(
    db: PostgreDB,
    context: AnalysisRunContext,
    phase: int,
    operation,
):
    try:
        return operation()
    except Exception as exc:
        update_analysis_run_status(
            db,
            context.run_id,
            RunStatus.FAIL.value,
            validation_summary={"phase": phase, "target": context.target},
            failure_reason=f"{type(exc).__name__}:{exc}"[:1000],
        )
        raise


def prepare_run(
    db: PostgreDB,
    request: AnalysisRequest,
    config: AnalyzerConfig,
) -> AnalysisRunContext:
    request.validate()
    config.validate()
    readiness = validate_source_readiness(db, request.cutoff_date)
    strategy = fetch_active_strategy(db, config.strategy_name)
    fail_stale_analysis_runs(db, strategy["id"], request.analysis_month)
    input_hash = _analysis_input_hash(
        readiness.input_hash, config.fingerprint, request.target, request
    )
    row, created = get_or_create_analysis_run(
        db,
        strategy_id=strategy["id"],
        analysis_month=request.analysis_month,
        cutoff_date=request.cutoff_date,
        effective_date=request.effective_date,
        model_version=config.model_version,
        input_hash=input_hash,
        force=request.force,
    )
    return AnalysisRunContext(
        run_id=row["id"],
        target=request.target,
        strategy_id=strategy["id"],
        analysis_month=request.analysis_month,
        cutoff_date=request.cutoff_date,
        effective_date=request.effective_date,
        input_hash=input_hash,
        model_version=config.model_version,
        created=created,
        input_quality=readiness.to_dict(),
    )


def run(
    db: PostgreDB,
    request: AnalysisRequest,
    config: AnalyzerConfig,
    *,
    show_progress: bool = True,
) -> AnalysisRunContext:
    # prepare(1) + quarter_fa(1) + macro(1) + sector? + company? + validation? + publish?
    _BASE_STEPS = {"macro": 3, "sector": 4, "company": 5, "all": 6}
    total = _BASE_STEPS[request.target] + (1 if request.target == "all" and request.publish else 0)

    pbar = tqdm(
        total=total,
        desc="준비 중",
        unit="단계",
        disable=not show_progress,
        file=sys.stdout,
        dynamic_ncols=True,
    )

    def _w(msg: str) -> None:
        tqdm.write(msg, file=sys.stdout)

    # ── 준비 ──────────────────────────────────────────────────────────────
    context = prepare_run(db, request, config)
    pbar.set_description("준비")
    pbar.update(1)
    _w(f"  run_id={context.run_id}  {'[신규]' if context.created else '[캐시 히트]'}")
    _w(f"  분석월={context.analysis_month}  기준일={context.cutoff_date}  시행일={context.effective_date}")

    if not context.created:
        publish_cached = request.publish and request.target == "all"
        pbar.total = 1 + (1 if publish_cached else 0)
        pbar.refresh()
        if publish_cached:
            pbar.set_description("발행")
            publish_universe(db, context.run_id, config)
            pbar.update(1)
        pbar.close()
        return context

    # ── 분기 FA ────────────────────────────────────────────────────────────
    pbar.set_description("분기 FA")
    quarter_rows = (
        0
        if request.reuse_quarter_scores
        else _run_stage(
            db, context, 7,
            lambda: refresh_quarterly_scores(db, request.cutoff_date, config),
        )
    )
    pbar.update(1)
    _w(
        "  분기 FA 스코어: 기존 포인트인타임 점수 재사용"
        if request.reuse_quarter_scores
        else f"  분기 FA 스코어: {quarter_rows:,}건 갱신"
    )

    # ── 매크로 분석 ────────────────────────────────────────────────────────
    pbar.set_description("매크로 분석")
    macro_results = _run_stage(
        db, context, 7,
        lambda: run_macro_analysis(db, context.run_id, request.cutoff_date, config),
    )
    pbar.update(1)
    for r in macro_results:
        _w(f"  {r.signal_name_code:<8}  {r.direction_code.value:<4}  trend={r.trend_raw:+.3f}  conf={r.confidence:.2f}")
    macro_quality = _macro_quality_summary(macro_results)

    if request.target == "macro":
        status = _status_with_quality(
            RunStatus.PASS.value, context.input_quality, macro_quality
        )
        update_analysis_run_status(
            db,
            context.run_id,
            status,
            validation_summary={
                "phase": 7,
                "target": request.target,
                "company_quarter_fa_rows": quarter_rows,
                **macro_quality,
                "input_quality": context.input_quality,
            },
        )
        pbar.close()
        return context

    # ── 섹터 분석 ──────────────────────────────────────────────────────────
    pbar.set_description("섹터 분석")
    sector_results = _run_stage(
        db, context, 8,
        lambda: run_sector_analysis(
            db, context.run_id, request.cutoff_date, macro_results, config
        ),
    )
    pbar.update(1)
    n_selected = sum(r["is_selected"] for r in sector_results)
    _w(f"  선택 {n_selected}개")
    for r in sorted(sector_results, key=lambda x: x.get("final_rank") or 99):
        if r["is_selected"]:
            _w(f"  [{r['final_rank']}] {r['industry_code']}  score={r['sector_score']:.1f}  eligible_large={r['eligible_large_count']}")
        elif r.get("reason_code") == "INSUFFICIENT_LARGE":
            _w(f"  [skip] {r['industry_code']}  {r.get('reason_code')}  score={r['sector_score']:.1f}")

    if request.target == "sector":
        selected = sum(row["is_selected"] for row in sector_results)
        base_status = (
            RunStatus.PASS.value
            if selected >= 0
            else RunStatus.WARNING.value
        )
        status = _status_with_quality(
            base_status, context.input_quality, macro_quality
        )
        update_analysis_run_status(
            db, context.run_id, status,
            selected_industry_count=selected,
            validation_summary={
                "phase": 8, "target": request.target,
                **macro_quality,
                "selected_industry_count": selected,
                "input_quality": context.input_quality,
            },
        )
        pbar.close()
        return context

    # ── 기업 선택 ──────────────────────────────────────────────────────────
    pbar.set_description("기업 선택")
    company_results = _run_stage(
        db, context, 9,
        lambda: run_company_selection(
            db, context.run_id, request.cutoff_date, config
        ),
    )
    pbar.update(1)
    selected_companies = [r for r in company_results if r["is_selected"]]
    by_industry: dict[str, list[str]] = {}
    for r in selected_companies:
        by_industry.setdefault(r["industry_code"], []).append(r["stock_code"])
    _w(f"  선택 기업 {len(selected_companies)}개 (산업 {len(by_industry)}개)")
    for ind_code, stocks in sorted(by_industry.items()):
        _w(f"  {ind_code}: {', '.join(stocks)}")

    if request.target == "company":
        within_selection_limits = len(selected_companies) == len(
            {row["stock_code"] for row in selected_companies}
        )
        base_status = (
            RunStatus.PASS.value if within_selection_limits else RunStatus.WARNING.value
        )
        status = _status_with_quality(
            base_status, context.input_quality, macro_quality
        )
        update_analysis_run_status(
            db, context.run_id, status,
            selected_industry_count=len(selected_industries),
            selected_company_count=len(selected_companies),
            validation_summary={
                "phase": 9, "target": request.target,
                **macro_quality,
                "selected_industry_count": len(selected_industries),
                "selected_company_count": len(selected_companies),
                "company_risk_source": "company_risk_states",
                "input_quality": context.input_quality,
            },
        )
        pbar.close()
        return context

    # ── 결과 검증 ──────────────────────────────────────────────────────────
    pbar.set_description("결과 검증")
    validation = _run_stage(
        db, context, 10,
        lambda: validate_run(db, context.run_id, config),
    )
    pbar.update(1)
    _w(f"  검증: {validation.status}")
    for check in validation.checks:
        mark = "O" if check.passed else "X"
        _w(f"  [{mark}] {check.name}: {check.detail}")

    final_status = _status_with_quality(
        validation.status, context.input_quality, macro_quality
    )
    update_analysis_run_status(
        db, context.run_id, final_status,
        selected_industry_count=sum(row["is_selected"] for row in sector_results),
        selected_company_count=sum(row["is_selected"] for row in company_results),
        validation_summary={
            **validation.summary,
            "phase": 10,
            "target": request.target,
            **macro_quality,
            "input_quality": context.input_quality,
        },
        failure_reason=(
            "RUN_VALIDATION_FAILED"
            if final_status == RunStatus.FAIL.value
            else None
        ),
    )

    # 경고 상태는 결과를 보존하되 실거래 유니버스로 발행하지 않는다.
    publishable_statuses = {RunStatus.PASS.value}
    if request.publish and final_status in publishable_statuses:
        pbar.set_description("유니버스 발행")
        publish_universe(db, context.run_id, config)
        pbar.update(1)
        _w(f"  유니버스 발행 완료 (검증 상태: {final_status})")

    pbar.close()
    return context
