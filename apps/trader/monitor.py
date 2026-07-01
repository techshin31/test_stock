from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.trade_monitor_repo import (
    fetch_daily_execution_summary,
    fetch_daily_plan_counts,
)


@dataclass
class ServiceStatus:
    strategy_name: str
    plan_date: date
    last_cycle_at: datetime | None = None
    total_plans: int = 0
    done_plans: int = 0
    skipped_plans: int = 0
    pending_plans: int = 0
    total_filled_qty: int = 0
    daily_net: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def completion_rate(self) -> float:
        if self.total_plans == 0:
            return 0.0
        return self.done_plans / self.total_plans


def fetch_status(
    db: PostgreDB,
    strategy_name: str,
    plan_date: date,
) -> ServiceStatus:
    """현재 트레이딩 진행 상태를 DB에서 조회한다."""
    status = ServiceStatus(strategy_name=strategy_name, plan_date=plan_date)

    plans_row = fetch_daily_plan_counts(db, strategy_name, plan_date)
    if plans_row:
        status.total_plans = int(plans_row.get("total", 0) or 0)
        status.done_plans = int(plans_row.get("done", 0) or 0)
        status.skipped_plans = int(plans_row.get("skipped", 0) or 0)
        status.pending_plans = int(plans_row.get("pending", 0) or 0)

    fill_row = fetch_daily_execution_summary(db, strategy_name, plan_date)
    if fill_row:
        status.total_filled_qty = int(fill_row["total_filled_qty"] or 0)
        status.daily_net = float(fill_row["daily_net"] or 0)

    status.last_cycle_at = datetime.now(timezone.utc)
    return status


def print_status(status: ServiceStatus) -> None:
    sign = "+" if status.daily_net >= 0 else ""
    print(
        f"[STATUS] {status.plan_date} | "
        f"계획 {status.total_plans}개 | "
        f"DONE {status.done_plans}개 | "
        f"SKIPPED {status.skipped_plans}개 | "
        f"PENDING/ORDERED {status.pending_plans}개 | "
        f"체결 {status.total_filled_qty:,}주 | "
        f"당일 손익 {sign}{status.daily_net:,.0f}원"
    )


def notify_slack(webhook_url: str, message: str) -> None:
    """Slack Incoming Webhook으로 알림을 전송한다.

    SLACK_WEBHOOK_URL 환경 변수로 URL을 주입한다.
    실패해도 예외를 전파하지 않는다.
    """
    try:
        data = json.dumps({"text": message}).encode()
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as exc:
        print(f"[MONITOR] Slack 알림 실패: {exc}")
