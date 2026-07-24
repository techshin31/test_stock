"""Operational and performance gates for automated-trading promotion.

The gate reports readiness only.  It deliberately cannot switch the runtime to
PAPER or REAL; production capital activation always requires explicit approval.
All rates use decimal units (0.01 == 1%).
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.utils.trading_calendar import is_krx_trading_day, previous_krx_trading_day


def _safe_rate(numerator: int, denominator: int) -> float:
    return float(numerator) / denominator if denominator else 1.0


@dataclass(frozen=True)
class TradingKpiSnapshot:
    as_of: date
    observed_trading_days: int
    scan_count: int
    fresh_scan_count: int
    risk_checks_total: int
    risk_checks_completed: int
    submitted_orders: int
    reconciled_orders: int
    critical_incidents: int
    net_return: float | None = None
    benchmark_return: float | None = None
    max_drawdown: float | None = None
    cost_drag: float | None = None
    performance_validation_status: str | None = None

    @property
    def data_freshness_rate(self) -> float:
        return _safe_rate(self.fresh_scan_count, self.scan_count)

    @property
    def risk_check_coverage(self) -> float:
        return _safe_rate(self.risk_checks_completed, self.risk_checks_total)

    @property
    def order_reconciliation_rate(self) -> float:
        return _safe_rate(self.reconciled_orders, self.submitted_orders)

    @property
    def operational_integrity(self) -> float:
        return min(
            self.data_freshness_rate,
            self.risk_check_coverage,
            self.order_reconciliation_rate,
        )

    @property
    def excess_return(self) -> float | None:
        if self.net_return is None or self.benchmark_return is None:
            return None
        return self.net_return - self.benchmark_return

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload.update({
            "as_of": self.as_of.isoformat(),
            "data_freshness_rate": self.data_freshness_rate,
            "risk_check_coverage": self.risk_check_coverage,
            "order_reconciliation_rate": self.order_reconciliation_rate,
            "operational_integrity": self.operational_integrity,
            "excess_return": self.excess_return,
        })
        return payload


@dataclass(frozen=True)
class PromotionPolicy:
    dry_run_days: int = 1
    paper_days: int = 60
    minimum_data_freshness_rate: float = 0.995
    minimum_risk_check_coverage: float = 1.0
    minimum_order_reconciliation_rate: float = 1.0
    minimum_paper_orders: int = 10
    maximum_critical_incidents: int = 0
    maximum_drawdown_floor: float = -0.15
    maximum_cost_drag: float = 0.015
    minimum_excess_return: float = 0.0


@dataclass(frozen=True)
class PromotionDecision:
    target_mode: str
    ready: bool
    manual_approval_required: bool
    blockers: tuple[str, ...]


def validate_paper_readiness_report(
    payload: dict,
    *,
    now: datetime | None = None,
) -> tuple[str, ...]:
    """Require the latest completed DRY_RUN EOD report before PAPER bootstrap."""
    blockers: list[str] = []
    if payload.get("mode") != "DRY_RUN":
        blockers.append("readiness report mode must be DRY_RUN")
    if payload.get("report_status") != "FINAL":
        blockers.append("DRY_RUN EOD report_status must be FINAL")
    promotion = payload.get("promotion") or {}
    if promotion.get("target_mode") != "PAPER" or promotion.get("ready") is not True:
        blockers.append("DRY_RUN EOD report is not ready for PAPER")
    try:
        report_date = date.fromisoformat(str(payload["report_date"]))
    except (KeyError, TypeError, ValueError):
        blockers.append("DRY_RUN EOD report_date is invalid")
        return tuple(blockers)

    now = now or datetime.now(ZoneInfo("Asia/Seoul"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    local_now = now.astimezone(ZoneInfo("Asia/Seoul"))
    today = local_now.date()
    expected_date = (
        today
        if is_krx_trading_day(today.isoformat()) and local_now.time() >= datetime.min.time().replace(hour=15, minute=30)
        else previous_krx_trading_day(today)
    )
    if report_date != expected_date:
        blockers.append(
            f"DRY_RUN EOD report_date {report_date} != latest completed session {expected_date}"
        )
    return tuple(blockers)


def snapshot_from_operational_log(
    log_path: str | Path,
    *,
    performance: dict | None = None,
    through_date: date | None = None,
) -> TradingKpiSnapshot:
    """Build a promotion snapshot from append-only operational observations."""
    path = Path(log_path)
    if not path.exists():
        raise FileNotFoundError(f"operational log not found: {path}")

    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            timestamp = datetime.fromisoformat(row["timestamp"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid operational log record at line {line_number}") from exc
        if (
            row.get("operational_status") != "SCANNING"
            and (through_date is None or timestamp.date() <= through_date)
        ):
            records.append((timestamp, row))
    if not records:
        raise ValueError("operational log has no completed observations")

    fresh_scans = 0
    risk_total = 0
    risk_completed = 0
    critical_incidents = 0
    active_critical_status = None
    critical_statuses = {
        "ERROR",
        "DEGRADED_RISK_UNCHECKED",
        "ENTRY_CIRCUIT_BREAKER",
        "ORDER_RECONCILIATION",
        "ORDER_SUPPRESSION",
    }
    last_by_day: dict[date, tuple[datetime, dict]] = {}
    for timestamp, row in sorted(records, key=lambda item: item[0]):
        health = row.get("data_health") or {}
        expected = int(health.get("expected_count") or 0)
        fresh = int(health.get("fresh_count") or 0)
        if (
            expected == fresh
            and not int(health.get("stale_count") or 0)
            and not int(health.get("missing_count") or 0)
        ):
            fresh_scans += 1
        risk_total += int(health.get("risk_checks_total") or 0)
        risk_completed += int(health.get("risk_checks_completed") or 0)
        status = row.get("operational_status")
        if status in critical_statuses:
            if status != active_critical_status:
                critical_incidents += 1
            active_critical_status = status
        else:
            active_critical_status = None
        day = timestamp.date()
        if day not in last_by_day or timestamp > last_by_day[day][0]:
            last_by_day[day] = (timestamp, row)

    submitted_orders = 0
    reconciled_orders = 0
    for _, row in last_by_day.values():
        actual = row.get("actual_orders") or {}
        buy_filled = int(actual.get("buy_filled") or 0)
        sell_filled = int(actual.get("sell_filled") or 0)
        rejected = int(actual.get("rejected") or 0)
        open_orders = int(actual.get("open") or 0)
        submitted_orders += buy_filled + sell_filled + rejected + open_orders
        reconciled_orders += buy_filled + sell_filled + rejected

    performance = performance or {}
    return TradingKpiSnapshot(
        as_of=max(timestamp for timestamp, _ in records).date(),
        observed_trading_days=len(last_by_day),
        scan_count=len(records),
        fresh_scan_count=fresh_scans,
        risk_checks_total=risk_total,
        risk_checks_completed=risk_completed,
        submitted_orders=submitted_orders,
        reconciled_orders=reconciled_orders,
        critical_incidents=critical_incidents,
        net_return=performance.get("net_return"),
        benchmark_return=performance.get("benchmark_return"),
        max_drawdown=performance.get("max_drawdown"),
        cost_drag=performance.get("cost_drag"),
        performance_validation_status=performance.get("validation_status"),
    )


def extract_critical_incidents(
    path: Path,
    through_date: date | None = None,
) -> list[dict]:
    """Extract chronological critical incident details from operational health log."""
    if not path.exists():
        return []

    records = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            timestamp = datetime.fromisoformat(row["timestamp"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if through_date is None or timestamp.date() <= through_date:
            records.append((timestamp, row))

    critical_statuses = {
        "ERROR",
        "DEGRADED_RISK_UNCHECKED",
        "ENTRY_CIRCUIT_BREAKER",
        "ORDER_RECONCILIATION",
        "ORDER_SUPPRESSION",
    }

    STATUS_NAMES = {
        "ORDER_SUPPRESSION": "주문 안전 차단",
        "ORDER_RECONCILIATION": "주문 정산 대기",
        "ERROR": "증권사 통신/API 오류",
        "ENTRY_CIRCUIT_BREAKER": "시장지수 서킷브레이커",
        "DEGRADED_RISK_UNCHECKED": "위험점검 미완료",
    }

    incidents = []
    active_status = None

    for timestamp, row in sorted(records, key=lambda item: item[0]):
        status = row.get("operational_status")
        if status in critical_statuses:
            if status != active_status:
                health = row.get("data_health") or {}
                last_err = row.get("last_error")
                suppressions = health.get("order_suppressions") or row.get("order_suppressions") or {}
                breaker = health.get("entry_circuit_breaker") or row.get("entry_circuit_breaker")

                detail_parts = []
                if last_err:
                    detail_parts.append(str(last_err))
                if isinstance(suppressions, dict) and suppressions.get("by_reason"):
                    reasons = [f"{k}: {v}건" for k, v in suppressions["by_reason"].items()]
                    detail_parts.append(f"차단사유 ({', '.join(reasons)})")
                elif isinstance(suppressions, dict) and suppressions.get("total"):
                    detail_parts.append(f"차단 {suppressions['total']}건")
                if breaker:
                    detail_parts.append(f"서킷브레이커 ({breaker})")

                summary = " | ".join(detail_parts) if detail_parts else STATUS_NAMES.get(status, status)

                incidents.append({
                    "timestamp": timestamp.isoformat(timespec="seconds"),
                    "date": timestamp.date().isoformat(),
                    "time": timestamp.strftime("%H:%M:%S"),
                    "status": status,
                    "status_name": STATUS_NAMES.get(status, status),
                    "summary": summary,
                    "last_error": last_err,
                })
            active_status = status
        else:
            active_status = None

    return incidents


def evaluate_promotion_gate(
    snapshot: TradingKpiSnapshot,
    target_mode: str,
    policy: PromotionPolicy | None = None,
) -> PromotionDecision:
    """Evaluate DRY_RUN→PAPER or PAPER→REAL readiness."""
    policy = policy or PromotionPolicy()
    mode = target_mode.upper()
    if mode not in {"PAPER", "REAL"}:
        raise ValueError("target_mode must be PAPER or REAL")

    blockers: list[str] = []
    minimum_days = policy.dry_run_days if mode == "PAPER" else policy.paper_days
    if snapshot.observed_trading_days < minimum_days:
        blockers.append(
            f"observed_trading_days {snapshot.observed_trading_days} < {minimum_days}"
        )
    if snapshot.scan_count <= 0:
        blockers.append("no operational scans were observed")
    if snapshot.data_freshness_rate < policy.minimum_data_freshness_rate:
        blockers.append(
            f"data_freshness_rate {snapshot.data_freshness_rate:.4f} "
            f"< {policy.minimum_data_freshness_rate:.4f}"
        )
    if snapshot.risk_check_coverage < policy.minimum_risk_check_coverage:
        blockers.append(
            f"risk_check_coverage {snapshot.risk_check_coverage:.4f} "
            f"< {policy.minimum_risk_check_coverage:.4f}"
        )
    if snapshot.order_reconciliation_rate < policy.minimum_order_reconciliation_rate:
        blockers.append(
            f"order_reconciliation_rate {snapshot.order_reconciliation_rate:.4f} "
            f"< {policy.minimum_order_reconciliation_rate:.4f}"
        )
    if snapshot.critical_incidents > policy.maximum_critical_incidents:
        blockers.append(
            f"critical_incidents {snapshot.critical_incidents} "
            f"> {policy.maximum_critical_incidents}"
        )

    if mode == "REAL":
        if snapshot.performance_validation_status != "READY":
            blockers.append(
                "performance_validation_status "
                f"{snapshot.performance_validation_status or 'MISSING'} != READY"
            )
        if snapshot.submitted_orders < policy.minimum_paper_orders:
            blockers.append(
                f"submitted_orders {snapshot.submitted_orders} "
                f"< {policy.minimum_paper_orders}"
            )
        if snapshot.excess_return is None:
            blockers.append("net_return and benchmark_return are required")
        elif snapshot.excess_return <= policy.minimum_excess_return:
            blockers.append(
                f"excess_return {snapshot.excess_return:.4f} "
                f"<= {policy.minimum_excess_return:.4f}"
            )
        if snapshot.max_drawdown is None:
            blockers.append("max_drawdown is required")
        elif snapshot.max_drawdown < policy.maximum_drawdown_floor:
            blockers.append(
                f"max_drawdown {snapshot.max_drawdown:.4f} "
                f"< {policy.maximum_drawdown_floor:.4f}"
            )
        if snapshot.cost_drag is None:
            blockers.append("cost_drag is required")
        elif snapshot.cost_drag > policy.maximum_cost_drag:
            blockers.append(
                f"cost_drag {snapshot.cost_drag:.4f} > {policy.maximum_cost_drag:.4f}"
            )

    return PromotionDecision(
        target_mode=mode,
        ready=not blockers,
        manual_approval_required=True,
        blockers=tuple(blockers),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate trading-mode promotion readiness")
    parser.add_argument("--target", required=True, choices=["PAPER", "REAL"])
    parser.add_argument("--operational-log", required=True)
    parser.add_argument("--performance-json")
    parser.add_argument("--readiness-json")
    args = parser.parse_args(argv)

    performance = None
    if args.performance_json:
        performance_path = Path(args.performance_json)
        if not performance_path.exists():
            print(json.dumps({
                "ready": False,
                "blockers": [f"performance snapshot not found: {performance_path}"],
            }, ensure_ascii=False))
            return 2
        performance = json.loads(performance_path.read_text(encoding="utf-8"))

    try:
        snapshot = snapshot_from_operational_log(
            args.operational_log,
            performance=performance,
        )
        decision = evaluate_promotion_gate(snapshot, args.target)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ready": False, "blockers": [str(exc)]}, ensure_ascii=False))
        return 2

    readiness_blockers: tuple[str, ...] = ()
    if args.readiness_json:
        try:
            readiness_payload = json.loads(
                Path(args.readiness_json).read_text(encoding="utf-8")
            )
            readiness_blockers = validate_paper_readiness_report(readiness_payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            readiness_blockers = (f"readiness report unavailable: {exc}",)
    combined_blockers = tuple(readiness_blockers) + decision.blockers
    decision = PromotionDecision(
        target_mode=decision.target_mode,
        ready=not combined_blockers,
        manual_approval_required=True,
        blockers=combined_blockers,
    )

    print(json.dumps({
        "snapshot": snapshot.to_dict(),
        "decision": {
            "target_mode": decision.target_mode,
            "ready": decision.ready,
            "manual_approval_required": decision.manual_approval_required,
            "blockers": list(decision.blockers),
        },
    }, ensure_ascii=False, indent=2))
    return 0 if decision.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
