from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m apps.trader",
        description="QuantPilot 트레이딩 서비스",
    )
    parser.add_argument(
        "command",
        choices=["planner", "executor", "reconciler"],
        help="planner: 장전 전략 생성 | executor: 장중 매수/매도 | reconciler: 장마감 정산",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="시간 대기 없이 즉시 실행. planner는 계획이 없으면 랜덤 생성",
    )
    return parser.parse_args()


def _mask_account(account_no: str) -> str:
    if len(account_no) >= 4:
        return f"{account_no[:2]}****{account_no[-2:]}"
    return "****"


def _init():
    """공통 초기화: config 로드 → gate 확인 → DB 연결 → 자격증명 조회 → broker 생성."""
    from apps.trader import audit
    from apps.trader.config import build_db_config, load_config
    from core.trade.gate import check_live_order_gate
    from core.trade.kis_broker import KisBroker
    from storage.postgres.connection import PostgreDB
    from storage.postgres.repositories.credential_repo import fetch_credential_by_account_type
    from storage.postgres.repositories.user_repo import fetch_user_by_email

    cfg = load_config()

    gate_status = check_live_order_gate()
    audit.log_gate(gate_status.allowed, gate_status.reason)
    if not gate_status.allowed:
        print(f"[GATE] 차단됨: {gate_status.reason}", file=sys.stderr)
        sys.exit(1)

    db = PostgreDB(build_db_config())

    user = fetch_user_by_email(db, cfg.user_email)
    if not user:
        print(f"[TRADER] 등록된 사용자가 없습니다: {cfg.user_email}", file=sys.stderr)
        print("         'python -m apps.user register'를 먼저 실행하세요.", file=sys.stderr)
        db.close()
        sys.exit(1)

    credential = fetch_credential_by_account_type(
        db,
        user_id=user["id"],
        broker_code=cfg.broker_code,
        account_type="STOCK",
        environment_code=cfg.environment_code,
    )
    if not credential:
        print(
            f"[TRADER] DB에서 주식 계좌 자격증명을 찾을 수 없습니다: "
            f"user={cfg.user_email}, broker={cfg.broker_code}, env={cfg.environment_code}",
            file=sys.stderr,
        )
        print("         'python -m apps.user register'를 먼저 실행하세요.", file=sys.stderr)
        db.close()
        sys.exit(1)

    broker = KisBroker.from_db_credential(credential)
    account_masked = _mask_account(credential["account_number"])

    audit.log_startup({
        "kis_env": cfg.kis_env,
        "strategy_name": cfg.strategy_name,
        "account": account_masked,
        "daily_loss_limit": cfg.daily_loss_limit,
    })
    print(
        f"[TRADER] KIS_ENV={cfg.kis_env} | 전략={cfg.strategy_name} | "
        f"계좌={account_masked}"
    )

    return cfg, db, broker


def run_planner(test: bool = False) -> None:
    """장전 프로세스: 포지션 동기화 + 전략 계산(STEP 4~8) → trade_plans 저장."""
    from apps.trader.monitor import fetch_status, print_status
    from apps.trader.planner import pre_market_sync, run_strategy_planning
    from apps.trader.scheduler import PRE_MARKET_START, is_trading_day, wait_until

    cfg, db, broker = _init()
    plan_date = date.today()

    if not is_trading_day():
        print("[PLANNER] 오늘은 거래일이 아닙니다.")
        db.close()
        return

    wait_until(PRE_MARKET_START)
    balance = pre_market_sync(db, broker, cfg.strategy_name)
    run_strategy_planning(db, broker, cfg.strategy_name, plan_date, test=test, balance=balance)

    print_status(fetch_status(db, cfg.strategy_name, plan_date))
    db.close()
    print("[PLANNER] 장전 프로세스 완료")


def run_executor() -> None:
    """장중 프로세스: 매수/매도 실행 루프."""
    from apps.trader.monitor import fetch_status, print_status
    from apps.trader.planner import has_executable_plans
    from apps.trader.runner import run_one_cycle
    from apps.trader.scheduler import MARKET_OPEN, is_market_hours, is_trading_day, wait_until

    cfg, db, broker = _init()
    plan_date = date.today()

    if not is_trading_day():
        print("[EXECUTOR] 오늘은 거래일이 아닙니다.")
        db.close()
        return

    if not has_executable_plans(db, cfg.strategy_name, plan_date):
        status = fetch_status(db, cfg.strategy_name, plan_date)
        print_status(status)
        if status.total_plans == 0:
            print(
                "[EXECUTOR] 실행할 trade_plans가 없습니다.\n"
                "           먼저 planner를 실행하세요: python -m apps.trader planner"
            )
        else:
            print("[EXECUTOR] PENDING/ORDERED 계획이 0개입니다. 장중 루프를 시작하지 않습니다.")
        db.close()
        return

    wait_until(MARKET_OPEN)
    print(f"[EXECUTOR] 장중 실행 루프 시작 (사이클 간격: {cfg.cycle_interval_sec}초)")

    while is_market_hours():
        cycle_start = time.monotonic()
        run_one_cycle(
            db=db,
            broker=broker,
            strategy_name=cfg.strategy_name,
            plan_date=plan_date,
            daily_loss_limit=cfg.daily_loss_limit,
        )
        status = fetch_status(db, cfg.strategy_name, plan_date)
        print_status(status)
        if status.pending_plans == 0:
            print("[EXECUTOR] PENDING/ORDERED 계획이 0개입니다. 장중 루프를 조기 종료합니다.")
            break

        elapsed = time.monotonic() - cycle_start
        sleep_sec = max(0.0, cfg.cycle_interval_sec - elapsed)
        if sleep_sec > 0:
            time.sleep(sleep_sec)

    print("[EXECUTOR] 장중 루프 종료")
    db.close()


def run_reconciler() -> None:
    """장마감 프로세스: 체결 내역 reconcile + 포지션 재동기화 + Slack 알림."""
    from apps.trader import audit
    from apps.trader.monitor import fetch_status, notify_slack, print_status
    from apps.trader.planner import pre_market_sync
    from apps.trader.scheduler import EOD_START, wait_until
    from core.trade.reconcile import reconcile_orders_from_broker_history
    from storage.postgres.repositories.balance_repo import fetch_balance_history, insert_balance_history

    cfg, db, broker = _init()
    plan_date = date.today()

    status = fetch_status(db, cfg.strategy_name, plan_date)
    if status.total_plans > 0 and status.pending_plans == 0:
        print_status(status)
        print("[RECONCILER] PENDING/ORDERED 계획이 0개입니다. 15:40 대기를 건너뜁니다.")
    else:
        wait_until(EOD_START)

    try:
        summary = reconcile_orders_from_broker_history(db, broker, plan_date)
        eod_data = {
            "broker_rows": summary.broker_rows,
            "managed_orders": summary.managed_orders,
            "inserted_executions": summary.inserted_executions,
            "updated_orders": summary.updated_orders,
        }
        audit.log_eod(eod_data)
        print(f"[RECONCILER] EOD reconcile 완료: {eod_data}")
    except Exception as exc:
        audit.log_error("eod_reconcile", str(exc))
        print(f"[RECONCILER] EOD reconcile 실패: {exc}")

    eod_balance = pre_market_sync(db, broker, cfg.strategy_name)

    if eod_balance is not None:
        from storage.postgres.repositories.universe_repo import (
            mark_empty_sell_only_removed,
        )

        removed = mark_empty_sell_only_removed(db, cfg.strategy_name)
        if removed:
            print(f"[RECONCILER] SELL_ONLY -> REMOVED: {removed}")

    # 장마감 잔고 스냅샷을 balance_history에 저장한다.
    # 다음 거래일 executor의 일일 손실 한도 체크가 "전일 마감 자산"을 기준으로
    # 손익을 계산하므로(core/trade/gate.py:check_daily_loss_limit), 이 스냅샷이
    # 없으면 그날의 손실 한도 체크가 통과 처리(skip)된다.
    if eod_balance is not None:
        summary_acct = (eod_balance.get("output2") or [{}])[0]
        total_value = float(summary_acct.get("tot_evlu_amt", "0") or 0)
        cash = float(summary_acct.get("prvs_rcdl_excc_amt", "0") or 0)
        history = fetch_balance_history(db, strategy_name=cfg.strategy_name)
        prev_total = float(history[-1]["total_value"]) if history else total_value
        daily_return = (total_value / prev_total - 1.0) if prev_total > 0 else 0.0

        insert_balance_history(db, strategy_name=cfg.strategy_name, snapshot={
            "date": plan_date,
            "cash": cash,
            "stock_value": total_value - cash,
            "total_value": total_value,
            "daily_return": daily_return,
        })
        print(
            f"[RECONCILER] balance_history 스냅샷 저장: 총자산 {total_value:,.0f}원 "
            f"(일간수익률 {daily_return*100:+.2f}%)"
        )
    else:
        audit.log_error("balance_history", "EOD 잔고 조회 실패 — 스냅샷 저장 건너뜀")
        print("[RECONCILER] EOD 잔고 조회 실패 — balance_history 스냅샷 저장 건너뜀")

    final_status = fetch_status(db, cfg.strategy_name, plan_date)
    print_status(final_status)

    slack_url = os.getenv("SLACK_WEBHOOK_URL")
    if slack_url:
        sign = "+" if final_status.daily_net >= 0 else ""
        notify_slack(
            slack_url,
            f"[QuantPilot] {plan_date} 트레이딩 완료\n"
            f"계획 {final_status.done_plans}/{final_status.total_plans} | "
            f"체결 {final_status.total_filled_qty:,}주 | "
            f"당일 손익 {sign}{final_status.daily_net:,.0f}원",
        )

    db.close()
    print("[RECONCILER] 장마감 프로세스 완료")


def main() -> None:
    args = _parse_args()

    if args.test:
        os.environ["TRADER_SKIP_WAIT"] = "true"

    if args.command == "planner":
        run_planner(test=args.test)
    elif args.command == "executor":
        run_executor()
    elif args.command == "reconciler":
        run_reconciler()


if __name__ == "__main__":
    main()
