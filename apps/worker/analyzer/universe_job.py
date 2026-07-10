"""Atomic publication of a validated FA run to the operational universe."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from apps.worker.analyzer.config import AnalyzerConfig
from core.portfolio.rotation import calc_force_exit_date
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.universe_repo import publish_fa_run


KST = ZoneInfo("Asia/Seoul")


class UniversePublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublishResult:
    run_id: int
    active_symbols: tuple[str, ...]
    sell_only_symbols: tuple[str, ...]
    already_published: bool = False


def publish(
    db: PostgreDB,
    run_id: int,
    config: AnalyzerConfig,
    *,
    now_kst: datetime | None = None,
) -> PublishResult:
    now = now_kst or datetime.now(KST)
    expected_count = (
        config.scoring.final_industry_count * config.scoring.companies_per_industry
    )
    try:
        result = publish_fa_run(
            db,
            run_id,
            strategy_name=config.strategy_name,
            enabled_market_types=list(config.scoring.enabled_market_types),
            expected_company_count=expected_count,
            publish_deadline_kst=config.scoring.publish_deadline_kst,
            force_exit_date=calc_force_exit_date(now.date(), 20),
            now_kst=now,
        )
    except ValueError as exc:
        raise UniversePublishError(str(exc)) from exc
    return PublishResult(
        run_id=result["run_id"],
        active_symbols=result["active_symbols"],
        sell_only_symbols=result["sell_only_symbols"],
        already_published=result["already_published"],
    )
