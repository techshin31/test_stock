from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date

from core.trade.execution import ExecutionConfig, execute_plan_with_orderbook_slicing
from core.trade.gate import check_daily_loss_limit
from core.trade.kis_broker import KisBroker
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.trade_plan_repo import fetch_executable_trade_plans

from apps.trader import audit


@dataclass
class CycleResult:
    filled_count: int = 0
    error_count: int = 0
    skipped_count: int = 0
    plan_ids: list[int] = field(default_factory=list)


def run_one_cycle(
    db: PostgreDB,
    broker: KisBroker,
    strategy_name: str,
    plan_date: date,
    daily_loss_limit: float,
    exec_config: ExecutionConfig | None = None,
) -> CycleResult:
    """단일 트레이딩 사이클을 실행한다.

    개별 plan 실행 중 예외가 발생해도 해당 plan만 건너뛰고 다음 plan을 계속 실행한다.
    """
    result = CycleResult()

    balance = broker.account.balance()
    current_total_value = float((balance.get("output2") or [{}])[0].get("tot_evlu_amt", "0") or 0)

    loss_status = check_daily_loss_limit(db, strategy_name, daily_loss_limit, current_total_value)
    if not loss_status.allowed:
        audit.log_loss_limit(loss_status.reason)
        print(f"[RUNNER] 손실 한도 초과로 사이클 중단: {loss_status.reason}")
        return result

    plans = fetch_executable_trade_plans(db, plan_date, strategy_name)
    audit.log_cycle_start(str(plan_date), len(plans))

    if not plans:
        return result

    start = time.monotonic()
    for plan in plans:
        symbol = str(plan.get("symbol", ""))
        side = str(plan.get("order_side_code", ""))
        plan_id = int(plan.get("id", 0))
        result.plan_ids.append(plan_id)

        try:
            exec_result = execute_plan_with_orderbook_slicing(
                db=db,
                broker=broker,
                plan=plan,
                config=exec_config,
            )
            if exec_result.filled_qty > 0:
                result.filled_count += 1
                audit.log_order(
                    symbol=symbol,
                    side=side,
                    qty=exec_result.filled_qty,
                    price=int(exec_result.avg_fill_price) if exec_result.avg_fill_price else None,
                    status="FILLED",
                    plan_id=plan_id,
                )
            else:
                result.skipped_count += 1

        except Exception as exc:
            result.error_count += 1
            audit.log_error(f"plan_id={plan_id} symbol={symbol}", str(exc))
            print(f"[RUNNER] plan {plan_id} ({symbol}) 오류 — 다음 사이클에서 재시도: {exc}")

    elapsed = time.monotonic() - start
    audit.log_cycle_end(result.filled_count, result.error_count, elapsed)
    return result
