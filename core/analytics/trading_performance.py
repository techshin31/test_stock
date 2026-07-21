"""Auditable end-of-day performance reports for trading-mode promotion.

PAPER/REAL performance is measured from a manually certified, account-scoped
baseline.  The generator never activates capital; it only writes evidence used
by :mod:`core.analytics.trading_kpis` and the BAT launch gates.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from core.analytics.trading_kpis import (
    PromotionDecision,
    TradingKpiSnapshot,
    evaluate_promotion_gate,
    snapshot_from_operational_log,
)
from core.constant.values import TradingCostParam
from storage.postgres.connection import PostgreDB


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASELINE_CONFIRMATION = "CLEAN_PAPER_BASELINE"
REAL_BASELINE_CONFIRMATION = "CLEAN_REAL_BASELINE"
RESET_CONFIRMATION = "RESET_CLEAN_BASELINE"
BENCHMARK_SYMBOL = "^KS11"
KRX_CLOSE_TIME = dt.time(15, 30)


def _default_benchmark_loader(start: str, end: str) -> pd.Series:
    # Keep heavy market-data dependencies out of baseline checks and DRY reports.
    from data.loaders.kospi_data import download_kospi_index

    return download_kospi_index(start, end)


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _parse_timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone(dt.timedelta(hours=9)))
    return parsed


def load_account_snapshots(
    path: Path,
    *,
    mode: str,
    through_date: dt.date,
) -> list[dict]:
    """Load strict, account-scoped observations from the append-only JSONL."""
    if not path.exists():
        raise FileNotFoundError(f"scoped account snapshot log not found: {path}")
    rows: list[dict] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            timestamp = _parse_timestamp(str(row["timestamp"]))
            total_asset = float(row["total_asset"])
            cash = float(row["cash"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"invalid account snapshot record at line {line_number}"
            ) from exc
        if str(row.get("mode", "")).upper() != mode.upper():
            continue
        if timestamp.date() > through_date:
            continue
        if not math.isfinite(total_asset) or total_asset <= 0 or not math.isfinite(cash):
            raise ValueError(f"invalid account value at line {line_number}")
        account_scope = str(row.get("account_scope") or "UNKNOWN")
        strategy = str(row.get("strategy") or "UNKNOWN")
        if account_scope == "UNKNOWN" or strategy == "UNKNOWN":
            raise ValueError(f"unscoped account snapshot at line {line_number}")
        rows.append({
            **row,
            "timestamp": timestamp,
            "total_asset": total_asset,
            "cash": cash,
            "account_scope": account_scope,
            "strategy": strategy,
        })
    if not rows:
        raise ValueError(f"no {mode.upper()} account snapshots through {through_date}")
    rows.sort(key=lambda row: row["timestamp"])
    return rows


def _last_snapshot_by_date(rows: Iterable[dict]) -> list[dict]:
    by_date: dict[dt.date, dict] = {}
    for row in rows:
        day = row["timestamp"].date()
        if day not in by_date or row["timestamp"] > by_date[day]["timestamp"]:
            by_date[day] = row
    return [by_date[day] for day in sorted(by_date)]


def _benchmark_closes(
    loader: Callable[[str, str], pd.Series],
    start_date: dt.date,
    end_date: dt.date,
) -> dict[dt.date, float]:
    series = loader(
        start_date.isoformat(),
        (end_date + dt.timedelta(days=1)).isoformat(),
    )
    closes: dict[dt.date, float] = {}
    for index, value in series.dropna().items():
        closes[pd.Timestamp(index).date()] = float(value)
    return closes


def _benchmark_cutoff_date(snapshot_timestamp: dt.datetime) -> dt.date:
    local = snapshot_timestamp.astimezone(dt.timezone(dt.timedelta(hours=9)))
    if local.time().replace(tzinfo=None) < KRX_CLOSE_TIME:
        return local.date() - dt.timedelta(days=1)
    return local.date()


def _benchmark_anchor(
    loader: Callable[[str, str], pd.Series],
    snapshot_timestamp: dt.datetime,
) -> tuple[dt.date, float]:
    cutoff = _benchmark_cutoff_date(snapshot_timestamp)
    closes = _benchmark_closes(loader, cutoff - dt.timedelta(days=14), cutoff)
    eligible = [day for day in closes if day <= cutoff]
    if not eligible:
        raise ValueError(f"KOSPI close unavailable through baseline cutoff {cutoff}")
    anchor_date = max(eligible)
    return anchor_date, closes[anchor_date]


def _benchmark_anchor_freshness(
    baseline: dict,
    closes: dict[dt.date, float],
) -> tuple[bool, str]:
    certified = dt.date.fromisoformat(str(baseline["benchmark_date"]))
    baseline_timestamp = _parse_timestamp(str(baseline["baseline_timestamp"]))
    cutoff = _benchmark_cutoff_date(baseline_timestamp)
    eligible = [day for day in closes if day <= cutoff]
    expected = max(eligible) if eligible else None
    detail = (
        f"certified={certified}, expected={expected}, "
        f"snapshot={baseline_timestamp.isoformat()}"
    )
    return expected == certified, detail


def _load_cash_flows(path: Path, baseline: dict) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    if not path.exists():
        return [], [f"cash-flow ledger not found: {path}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = list(payload.get("entries") or [])
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return [], [f"invalid cash-flow ledger: {exc}"]
    if payload.get("account_scope") != baseline.get("account_scope"):
        errors.append("cash-flow ledger account_scope does not match baseline")
    normalized = []
    for index, entry in enumerate(entries, 1):
        try:
            flow_date = dt.date.fromisoformat(str(entry["date"]))
            amount = float(entry["amount"])
            reason = str(entry["reason"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"invalid cash-flow entry {index}: {exc}")
            continue
        if not reason or not math.isfinite(amount):
            errors.append(f"invalid cash-flow entry {index}")
            continue
        normalized.append({"date": flow_date, "amount": amount, "reason": reason})
    return normalized, errors


def calculate_performance(
    daily_snapshots: list[dict],
    *,
    baseline: dict,
    benchmark_closes: dict[dt.date, float],
    cash_flows: list[dict],
    total_costs: float,
) -> tuple[dict, list[dict], list[str]]:
    """Calculate flow-adjusted time-weighted NAV return and benchmark return."""
    errors: list[str] = []
    baseline_timestamp = _parse_timestamp(str(baseline["baseline_timestamp"]))
    baseline_asset = float(baseline["baseline_total_asset"])
    baseline_benchmark_date = dt.date.fromisoformat(str(baseline["benchmark_date"]))
    baseline_benchmark_close = float(baseline["benchmark_close"])
    rows = [row for row in daily_snapshots if row["timestamp"] >= baseline_timestamp]
    if not rows:
        return {}, [], ["no account snapshots at or after the certified baseline"]
    if rows[0]["account_scope"] != baseline.get("account_scope"):
        errors.append("account_scope changed after baseline")
    if any(row["account_scope"] != baseline.get("account_scope") for row in rows):
        errors.append("mixed account_scope values in performance window")
    if any(row["strategy"] != baseline.get("strategy") for row in rows):
        errors.append("mixed strategy values in performance window")

    daily = _last_snapshot_by_date(rows)
    flow_by_date: Counter = Counter()
    for entry in cash_flows:
        if entry["date"] >= baseline_timestamp.date():
            flow_by_date[entry["date"]] += entry["amount"]

    wealth = 1.0
    peak = 1.0
    max_drawdown = 0.0
    previous_asset = baseline_asset
    trend: list[dict] = []
    for row in daily:
        day = row["timestamp"].date()
        external_flow = float(flow_by_date.get(day, 0.0))
        daily_return = (
            (row["total_asset"] - external_flow) / previous_asset - 1.0
            if previous_asset
            else 0.0
        )
        wealth *= 1.0 + daily_return
        peak = max(peak, wealth)
        drawdown = wealth / peak - 1.0
        max_drawdown = min(max_drawdown, drawdown)
        benchmark_close = benchmark_closes.get(day)
        benchmark_return = (
            benchmark_close / baseline_benchmark_close - 1.0
            if benchmark_close is not None and baseline_benchmark_close
            else None
        )
        trend.append({
            "date": day.isoformat(),
            "total_asset": row["total_asset"],
            "external_cash_flow": external_flow,
            "daily_return": daily_return,
            "cumulative_return": wealth - 1.0,
            "drawdown": drawdown,
            "benchmark_return": benchmark_return,
        })
        previous_asset = row["total_asset"]

    latest_date = daily[-1]["timestamp"].date()
    latest_benchmark = benchmark_closes.get(latest_date)
    if baseline_benchmark_date not in benchmark_closes:
        errors.append(f"benchmark baseline close missing for {baseline_benchmark_date}")
    if latest_benchmark is None:
        errors.append(f"benchmark close missing for latest NAV date {latest_date}")
    benchmark_return = (
        latest_benchmark / baseline_benchmark_close - 1.0
        if latest_benchmark is not None and baseline_benchmark_close
        else None
    )
    daily_returns = [row["daily_return"] for row in trend]
    volatility = (
        float(pd.Series(daily_returns).std(ddof=1) * math.sqrt(252))
        if len(daily_returns) >= 2
        else None
    )
    metrics = {
        "baseline_date": baseline_timestamp.date().isoformat(),
        "through_date": latest_date.isoformat(),
        "performance_days": len(trend),
        "baseline_total_asset": baseline_asset,
        "ending_total_asset": daily[-1]["total_asset"],
        "net_return": wealth - 1.0,
        "benchmark_return": benchmark_return,
        "excess_return": (
            wealth - 1.0 - benchmark_return if benchmark_return is not None else None
        ),
        "max_drawdown": max_drawdown,
        "annualized_volatility": volatility,
        "total_costs": float(total_costs),
        "cost_drag": float(total_costs) / baseline_asset if baseline_asset else None,
        "benchmark_symbol": BENCHMARK_SYMBOL,
    }
    return metrics, trend, errors


def _db_from_environment() -> PostgreDB:
    password = os.getenv("POSTGRES_PASSWORD", "")
    if not password:
        raise ValueError("POSTGRES_PASSWORD environment variable is required")
    return PostgreDB({
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5433")),
        "user": os.getenv("POSTGRES_USER", "admin"),
        "password": password,
        "database": os.getenv("POSTGRES_DB", "quantpilot_db"),
    })


def fetch_trading_metrics(db, baseline: dict, through_date: dt.date) -> dict:
    """Fetch account/venue-scoped orders and executions from PostgreSQL."""
    params = (
        baseline["strategy"], baseline["mode"], baseline["account_scope"],
        baseline["baseline_timestamp"], through_date + dt.timedelta(days=1),
    )
    order_rows = db.fetch_all(
        """SELECT o.order_status_code, COUNT(*) AS count
           FROM orders o
           JOIN strategies s ON s.id = o.strategy_id
           WHERE s.name = %s
             AND o.execution_venue_code = %s
             AND o.account_scope = %s
             AND o.created_at >= %s::timestamptz
             AND o.created_at < %s::date
           GROUP BY o.order_status_code""",
        params,
    )
    execution_rows = db.fetch_all(
        """SELECT e.order_side_code, e.amount, e.commission, e.tax, e.slippage
           FROM executions e
           JOIN orders o ON o.id = e.order_id
           JOIN strategies s ON s.id = o.strategy_id
           WHERE s.name = %s
             AND o.execution_venue_code = %s
             AND o.account_scope = %s
             AND e.executed_at >= %s::timestamptz
             AND e.executed_at < %s::date""",
        params,
    )
    statuses = {str(row["order_status_code"]): int(row["count"]) for row in order_rows}
    commission = 0.0
    tax = 0.0
    slippage = 0.0
    modeled_commission_count = 0
    modeled_tax_count = 0
    for row in execution_rows:
        amount = abs(float(row.get("amount") or 0.0))
        recorded_commission = float(row.get("commission") or 0.0)
        recorded_tax = float(row.get("tax") or 0.0)
        if recorded_commission:
            commission += recorded_commission
        else:
            commission += amount * TradingCostParam.COMMISSION_BUY.rate()
            modeled_commission_count += 1
        if str(row.get("order_side_code")) == "SELL":
            if recorded_tax:
                tax += recorded_tax
            else:
                tax += amount * TradingCostParam.TAX_KOSPI.rate()
                modeled_tax_count += 1
        slippage += float(row.get("slippage") or 0.0)
    total_costs = max(commission + tax + slippage, 0.0)
    terminal = sum(statuses.get(status, 0) for status in ("FILLED", "REJECTED", "CANCELLED"))
    order_count = sum(statuses.values())
    return {
        "order_count": order_count,
        "terminal_order_count": terminal,
        "open_order_count": order_count - terminal,
        "execution_count": len(execution_rows),
        "order_status_counts": statuses,
        "commission": commission,
        "tax": tax,
        "slippage": slippage,
        "total_costs": total_costs,
        "modeled_commission_execution_count": modeled_commission_count,
        "modeled_tax_execution_count": modeled_tax_count,
        "cost_method": "recorded when non-zero; otherwise configured KOSPI model",
    }


def _decision_dict(decision: PromotionDecision) -> dict:
    return {
        "target_mode": decision.target_mode,
        "ready": decision.ready,
        "manual_approval_required": decision.manual_approval_required,
        "blockers": list(decision.blockers),
    }


def _unavailable_snapshot(report_date: dt.date) -> TradingKpiSnapshot:
    return TradingKpiSnapshot(
        as_of=report_date,
        observed_trading_days=0,
        scan_count=0,
        fresh_scan_count=0,
        risk_checks_total=0,
        risk_checks_completed=0,
        submitted_orders=0,
        reconciled_orders=0,
        critical_incidents=1,
    )


def build_end_of_day_report(
    *,
    mode: str,
    report_date: dt.date,
    log_dir: Path,
    promotion_dir: Path,
    benchmark_loader: Callable[[str, str], pd.Series] = _default_benchmark_loader,
    db=None,
    as_of: dt.datetime | None = None,
) -> dict:
    mode = mode.upper()
    if mode not in {"DRY_RUN", "PAPER", "REAL"}:
        raise ValueError("mode must be DRY_RUN, PAPER, or REAL")
    target_mode = "PAPER" if mode == "DRY_RUN" else "REAL"
    validation_checks: list[dict] = []
    validation_errors: list[str] = []
    performance: dict = {}
    trend: list[dict] = []
    trading: dict = {}
    sources = [str(log_dir / "operational_health.jsonl")]
    kst = dt.timezone(dt.timedelta(hours=9))
    as_of = as_of or dt.datetime.now(kst)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=kst)
    local_as_of = as_of.astimezone(kst)
    if report_date > local_as_of.date():
        report_status = "INVALID_FUTURE_DATE"
        validation_errors.append("report_date is in the future")
    elif report_date == local_as_of.date() and local_as_of.time() < dt.time(15, 30):
        report_status = "PRELIMINARY_INTRADAY"
        if mode in {"PAPER", "REAL"}:
            validation_errors.append("market close is not complete (15:30 KST required)")
    else:
        report_status = "FINAL"

    try:
        operational = snapshot_from_operational_log(
            log_dir / "operational_health.jsonl", through_date=report_date
        )
        validation_checks.append({
            "name": "operational_log", "passed": True,
            "detail": f"{operational.scan_count} completed scans",
        })
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        operational = _unavailable_snapshot(report_date)
        validation_errors.append(str(exc))
        validation_checks.append({
            "name": "operational_log", "passed": False, "detail": str(exc),
        })

    if mode in {"PAPER", "REAL"}:
        baseline_path = promotion_dir / mode.lower() / "baseline.json"
        ledger_path = promotion_dir / mode.lower() / "cash_flows.json"
        snapshot_path = log_dir / "account_snapshots.jsonl"
        sources.extend([str(snapshot_path), str(baseline_path), str(ledger_path)])
        baseline = None
        try:
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            required = {
                "baseline_timestamp", "baseline_total_asset", "benchmark_date",
                "benchmark_close", "mode", "strategy", "account_scope",
            }
            missing = sorted(required - set(baseline))
            if missing:
                raise ValueError(f"baseline missing fields: {', '.join(missing)}")
            if baseline["mode"] != mode:
                raise ValueError("baseline mode does not match report mode")
            validation_checks.append({
                "name": "certified_baseline", "passed": True,
                "detail": baseline["baseline_timestamp"],
            })
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            validation_errors.append(f"baseline unavailable: {exc}")
            validation_checks.append({
                "name": "certified_baseline", "passed": False, "detail": str(exc),
            })

        if baseline is not None:
            try:
                account_rows = load_account_snapshots(
                    snapshot_path, mode=mode, through_date=report_date
                )
                latest_date = account_rows[-1]["timestamp"].date()
                if latest_date != report_date:
                    raise ValueError(
                        f"latest account snapshot {latest_date} != report date {report_date}"
                    )
                validation_checks.append({
                    "name": "account_snapshot_freshness", "passed": True,
                    "detail": account_rows[-1]["timestamp"].isoformat(),
                })
            except (FileNotFoundError, ValueError) as exc:
                account_rows = []
                validation_errors.append(str(exc))
                validation_checks.append({
                    "name": "account_snapshot_freshness", "passed": False,
                    "detail": str(exc),
                })

            cash_flows, flow_errors = _load_cash_flows(ledger_path, baseline)
            validation_errors.extend(flow_errors)
            validation_checks.append({
                "name": "cash_flow_ledger", "passed": not flow_errors,
                "detail": f"{len(cash_flows)} declared external flows"
                if not flow_errors else "; ".join(flow_errors),
            })
            try:
                benchmark_start = dt.date.fromisoformat(str(baseline["benchmark_date"]))
                closes = _benchmark_closes(
                    benchmark_loader, benchmark_start, report_date
                )
                validation_checks.append({
                    "name": "benchmark_download", "passed": True,
                    "detail": f"{len(closes)} KOSPI closes",
                })
                sources.append(f"Yahoo Finance {BENCHMARK_SYMBOL} via data loader")
                anchor_is_fresh, anchor_detail = _benchmark_anchor_freshness(
                    baseline, closes
                )
                validation_checks.append({
                    "name": "benchmark_anchor_freshness",
                    "passed": anchor_is_fresh,
                    "detail": anchor_detail,
                })
                if not anchor_is_fresh:
                    validation_errors.append(
                        f"stale benchmark baseline anchor: {anchor_detail}"
                    )
            except Exception as exc:
                closes = {}
                validation_errors.append(f"benchmark unavailable: {exc}")
                validation_checks.append({
                    "name": "benchmark_download", "passed": False,
                    "detail": str(exc),
                })

            try:
                active_db = db or _db_from_environment()
                trading = fetch_trading_metrics(active_db, baseline, report_date)
                validation_checks.append({
                    "name": "scoped_order_execution_data", "passed": True,
                    "detail": (
                        f"{trading['order_count']} orders / "
                        f"{trading['execution_count']} executions"
                    ),
                })
                sources.append("PostgreSQL orders + executions (strategy/venue/account scoped)")
            except Exception as exc:
                trading = {}
                validation_errors.append(f"order/execution metrics unavailable: {exc}")
                validation_checks.append({
                    "name": "scoped_order_execution_data", "passed": False,
                    "detail": str(exc),
                })

            if account_rows:
                calculated, trend, calculation_errors = calculate_performance(
                    account_rows,
                    baseline=baseline,
                    benchmark_closes=closes,
                    cash_flows=cash_flows,
                    total_costs=float(trading.get("total_costs") or 0.0),
                )
                performance.update(calculated)
                validation_errors.extend(calculation_errors)
                validation_checks.append({
                    "name": "performance_calculation",
                    "passed": not calculation_errors,
                    "detail": (
                        f"{len(trend)} daily NAV observations"
                        if not calculation_errors else "; ".join(calculation_errors)
                    ),
                })

    validation_status = "READY" if not validation_errors else "BLOCKED"
    if mode == "DRY_RUN":
        validation_status = "NOT_APPLICABLE"
    performance["validation_status"] = validation_status
    promotion_snapshot = TradingKpiSnapshot(
        **{
            key: value
            for key, value in operational.__dict__.items()
            if key not in {
                "net_return", "benchmark_return", "max_drawdown", "cost_drag",
                "performance_validation_status",
            }
        },
        net_return=performance.get("net_return"),
        benchmark_return=performance.get("benchmark_return"),
        max_drawdown=performance.get("max_drawdown"),
        cost_drag=performance.get("cost_drag"),
        performance_validation_status=performance.get("validation_status"),
    )
    decision = evaluate_promotion_gate(promotion_snapshot, target_mode)
    headline = (
        f"{target_mode} 승격 조건을 충족했습니다. 단, 수동 승인이 필요합니다."
        if decision.ready
        else f"{target_mode} 승격은 {len(decision.blockers)}개 조건 때문에 차단됩니다."
    )
    return {
        "schema_version": 1,
        "report_date": report_date.isoformat(),
        "generated_at": local_as_of.isoformat(timespec="seconds"),
        "report_status": report_status,
        "mode": mode,
        "executive_summary": headline,
        "performance": performance,
        "performance_trend": trend,
        "operations": promotion_snapshot.to_dict(),
        "trading": trading,
        "validation": {
            "status": validation_status,
            "checks": validation_checks,
            "errors": validation_errors,
        },
        "promotion": _decision_dict(decision),
        "sources": sources,
        "caveats": [
            "수익률은 인증 기준선 이후 계좌 NAV의 시간가중수익률이며 현금흐름은 cash_flows.json 선언값으로 조정합니다.",
            "수수료·세금이 체결 원장에 0으로 기록되면 설정된 KOSPI 비용률로 추정합니다.",
            "슬리피지는 예상가 대비 체결가 차이로 계산되며 음수는 가격개선입니다.",
            "이 보고서는 승격 근거만 생성하며 PAPER/REAL 모드를 자동으로 켜지 않습니다.",
        ],
    }


def _format_rate(value) -> str:
    return "-" if value is None else f"{float(value):.2%}"


def _markdown(report: dict) -> str:
    perf = report["performance"]
    ops = report["operations"]
    promotion = report["promotion"]
    lines = [
        f"# 자동매매 EOD 성과·운영 보고서 — {report['report_date']}",
        "",
        "## Executive Summary",
        "",
        report["executive_summary"],
        "",
        "## KPI Snapshot",
        "",
        "| 지표 | 값 |",
        "|---|---:|",
        f"| 실행 모드 | {report['mode']} |",
        f"| 보고서 상태 | {report['report_status']} |",
        f"| 관측 거래일 | {ops['observed_trading_days']}일 |",
        f"| 데이터 신선도 | {_format_rate(ops['data_freshness_rate'])} |",
        f"| 위험점검 커버리지 | {_format_rate(ops['risk_check_coverage'])} |",
        f"| 주문 정산률 | {_format_rate(ops['order_reconciliation_rate'])} |",
        f"| 전략 순수익률 | {_format_rate(perf.get('net_return'))} |",
        f"| KOSPI 수익률 | {_format_rate(perf.get('benchmark_return'))} |",
        f"| 초과수익률 | {_format_rate(perf.get('excess_return'))} |",
        f"| 최대 낙폭 | {_format_rate(perf.get('max_drawdown'))} |",
        f"| 비용 드래그 | {_format_rate(perf.get('cost_drag'))} |",
        f"| 성과 검증 | {perf.get('validation_status', '-')} |",
        f"| {promotion['target_mode']} 준비도 | {'READY' if promotion['ready'] else 'BLOCKED'} |",
        "",
        "## Performance Trend",
        "",
        "| 날짜 | 총자산 | 일수익률 | 누적수익률 | KOSPI | 낙폭 | 외부현금흐름 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    if report["performance_trend"]:
        for row in report["performance_trend"][-20:]:
            lines.append(
                f"| {row['date']} | {row['total_asset']:,.0f} | "
                f"{_format_rate(row['daily_return'])} | "
                f"{_format_rate(row['cumulative_return'])} | "
                f"{_format_rate(row['benchmark_return'])} | "
                f"{_format_rate(row['drawdown'])} | "
                f"{row['external_cash_flow']:,.0f} |"
            )
    else:
        lines.append("| - | - | - | - | - | - | - |")
    lines.extend([
        "",
        "## Key Findings",
        "",
        f"- {report['executive_summary']}",
        f"- 완료 스캔 {ops['scan_count']}회 중 신선 데이터 스캔은 {ops['fresh_scan_count']}회입니다.",
        f"- 제출 주문 {ops['submitted_orders']}건 중 {ops['reconciled_orders']}건이 종결 상태로 정산되었습니다.",
        "",
        "## Next Steps",
        "",
    ])
    if promotion["blockers"]:
        lines.extend(f"- [ ] {blocker}" for blocker in promotion["blockers"])
    else:
        lines.append("- [ ] 자본 활성화 전 사람이 최종 승인하고 계좌·한도·킬스위치를 재확인합니다.")
    lines.extend([
        "",
        "## Further Questions",
        "",
        "- 외부 입출금이 있었다면 cash_flows.json에 금액과 사유가 모두 기록되었는가?",
        "- 비용 추정치와 증권사 정산 내역의 차이는 허용 범위 안인가?",
        "- 초과수익이 특정 소수 종목이나 짧은 구간에 집중되어 있지 않은가?",
        "",
        "## Validation and Caveats",
        "",
    ])
    lines.extend(
        f"- [{'x' if check['passed'] else ' '}] {check['name']}: {check['detail']}"
        for check in report["validation"]["checks"]
    )
    lines.extend(["", "### Caveats", ""])
    lines.extend(f"- {item}" for item in report["caveats"])
    lines.extend(["", "### Sources", ""])
    lines.extend(f"- `{source}`" for source in report["sources"])
    return "\n".join(lines) + "\n"


def write_end_of_day_report(
    *,
    mode: str,
    report_date: dt.date,
    log_dir: Path,
    promotion_dir: Path,
    benchmark_loader: Callable[[str, str], pd.Series] = _default_benchmark_loader,
    db=None,
    as_of: dt.datetime | None = None,
) -> dict:
    report = build_end_of_day_report(
        mode=mode,
        report_date=report_date,
        log_dir=log_dir,
        promotion_dir=promotion_dir,
        benchmark_loader=benchmark_loader,
        db=db,
        as_of=as_of,
    )
    output_dir = promotion_dir / mode.lower()
    daily_dir = output_dir / "daily"
    _atomic_json(daily_dir / f"{report_date}.json", report)
    _atomic_text(daily_dir / f"{report_date}.md", _markdown(report))
    _atomic_json(output_dir / "latest.json", report)
    if mode.upper() == "PAPER":
        readiness = {
            **report["performance"],
            "as_of": report["report_date"],
            "generated_at": report["generated_at"],
            "mode": "PAPER",
            "promotion": report["promotion"],
            "source_report": str(daily_dir / f"{report_date}.json"),
        }
        _atomic_json(promotion_dir / "real_readiness.json", readiness)
    return report


def initialize_baseline(
    *,
    mode: str,
    report_date: dt.date,
    log_dir: Path,
    promotion_dir: Path,
    confirmation: str,
    replace: bool = False,
    benchmark_loader: Callable[[str, str], pd.Series] = _default_benchmark_loader,
) -> dict:
    mode = mode.upper()
    expected = (
        RESET_CONFIRMATION if replace
        else REAL_BASELINE_CONFIRMATION if mode == "REAL"
        else BASELINE_CONFIRMATION
    )
    if confirmation != expected:
        raise PermissionError(f"baseline confirmation must be {expected}")
    if mode not in {"PAPER", "REAL"}:
        raise ValueError("certified baseline supports PAPER or REAL only")
    baseline_path = promotion_dir / mode.lower() / "baseline.json"
    if baseline_path.exists() and not replace:
        raise FileExistsError(
            f"baseline already exists: {baseline_path}; use --replace-baseline explicitly"
        )
    snapshots = load_account_snapshots(
        log_dir / "account_snapshots.jsonl", mode=mode, through_date=report_date
    )
    latest = snapshots[-1]
    if latest["timestamp"].date() != report_date:
        raise ValueError(
            "baseline requires a same-day --snapshot-only observation before PAPER orders"
        )
    from core.utils.trading_calendar import is_krx_trading_day

    if not is_krx_trading_day(report_date.isoformat()):
        raise ValueError("baseline must be initialized on a KRX trading day")
    benchmark_date, benchmark_close = _benchmark_anchor(
        benchmark_loader, latest["timestamp"]
    )
    baseline = {
        "schema_version": 1,
        "mode": mode,
        "strategy": latest["strategy"],
        "account_scope": latest["account_scope"],
        "baseline_timestamp": latest["timestamp"].isoformat(),
        "baseline_total_asset": latest["total_asset"],
        "baseline_cash": latest["cash"],
        "baseline_position_count": int(latest.get("position_count") or 0),
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "benchmark_date": benchmark_date.isoformat(),
        "benchmark_close": benchmark_close,
        "benchmark_anchor_policy": "LATEST_CLOSED_SESSION_AT_SNAPSHOT",
        "cash_flow_policy": "Declare every deposit/withdrawal in cash_flows.json",
        "initialized_at": dt.datetime.now(
            dt.timezone(dt.timedelta(hours=9))
        ).isoformat(timespec="seconds"),
    }
    _atomic_json(baseline_path, baseline)
    _atomic_json(
        promotion_dir / mode.lower() / "cash_flows.json",
        {
            "schema_version": 1,
            "mode": mode,
            "account_scope": latest["account_scope"],
            "entries": [],
            "instructions": "Add every external cash flow as {date, amount, reason}; deposits are positive.",
        },
    )
    return baseline


def check_baseline(
    mode: str,
    promotion_dir: Path,
    *,
    log_dir: Path | None = None,
    through_date: dt.date | None = None,
    require_latest_snapshot: bool = False,
) -> dict:
    path = promotion_dir / mode.lower() / "baseline.json"
    if not path.exists():
        raise FileNotFoundError(f"certified baseline not found: {path}")
    baseline = json.loads(path.read_text(encoding="utf-8"))
    if baseline.get("mode") != mode.upper():
        raise ValueError("baseline mode mismatch")
    if baseline.get("account_scope") in {None, "", "UNKNOWN"}:
        raise ValueError("baseline account_scope is not certified")
    required = {
        "baseline_timestamp", "baseline_total_asset", "strategy",
        "benchmark_date", "benchmark_close",
    }
    missing = sorted(required - set(baseline))
    if missing:
        raise ValueError(f"baseline missing fields: {', '.join(missing)}")
    ledger_path = promotion_dir / mode.lower() / "cash_flows.json"
    if not ledger_path.exists():
        raise FileNotFoundError(f"cash-flow ledger not found: {ledger_path}")
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if ledger.get("account_scope") != baseline.get("account_scope"):
        raise ValueError("cash-flow ledger account_scope mismatch")
    if require_latest_snapshot:
        if log_dir is None or through_date is None:
            raise ValueError("latest snapshot validation requires log_dir and date")
        snapshots = load_account_snapshots(
            log_dir / "account_snapshots.jsonl",
            mode=mode,
            through_date=through_date,
        )
        latest = snapshots[-1]
        if latest["timestamp"].date() != through_date:
            raise ValueError("latest account snapshot is not from today")
        if latest["account_scope"] != baseline["account_scope"]:
            raise ValueError("current account_scope does not match certified baseline")
        if latest["strategy"] != baseline["strategy"]:
            raise ValueError("current strategy does not match certified baseline")
    return baseline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate trading EOD KPI reports")
    parser.add_argument("--mode", required=True, choices=["DRY_RUN", "PAPER", "REAL"])
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--log-dir")
    parser.add_argument("--promotion-dir", default=str(PROJECT_ROOT / "reports" / "promotion"))
    parser.add_argument("--initialize-baseline", action="store_true")
    parser.add_argument("--replace-baseline", action="store_true")
    parser.add_argument("--confirm-baseline")
    parser.add_argument("--check-baseline", action="store_true")
    parser.add_argument("--check-latest-snapshot", action="store_true")
    args = parser.parse_args(argv)
    report_date = dt.date.fromisoformat(args.date)
    mode = args.mode.upper()
    log_dir = Path(args.log_dir) if args.log_dir else PROJECT_ROOT / "logs" / mode.lower()
    promotion_dir = Path(args.promotion_dir)
    try:
        if args.check_baseline:
            result = check_baseline(
                mode,
                promotion_dir,
                log_dir=log_dir,
                through_date=report_date,
                require_latest_snapshot=args.check_latest_snapshot,
            )
        elif args.initialize_baseline or args.replace_baseline:
            result = initialize_baseline(
                mode=mode,
                report_date=report_date,
                log_dir=log_dir,
                promotion_dir=promotion_dir,
                confirmation=args.confirm_baseline or "",
                replace=args.replace_baseline,
            )
        else:
            result = write_end_of_day_report(
                mode=mode,
                report_date=report_date,
                log_dir=log_dir,
                promotion_dir=promotion_dir,
            )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
