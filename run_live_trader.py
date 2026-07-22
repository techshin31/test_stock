import argparse
import atexit
import datetime
import hashlib
import json
import logging
import os
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.execution.trader import LiveTrader
from core.utils.telegram_bot import TelegramBot
from core.utils.process_lock import ProcessAlreadyRunning, ProcessInstanceLock


PROJECT_ROOT = Path(__file__).resolve().parent


def _assert_real_system_ready(project_root: Path = PROJECT_ROOT) -> dict:
    """Fail closed before any ordinary REAL broker/order path is initialized."""
    from core.analytics.system_readiness import audit_system_readiness

    result = audit_system_readiness(project_root, environ={})
    if result.get("full_system_complete") is not True:
        blockers = "; ".join(result.get("blockers") or ["completion unavailable"])
        raise PermissionError(
            "REAL activation requires complete PAPER system evidence: " + blockers
        )
    return result

def configure_logging(mode: str) -> None:
    log_dir = os.path.join("logs", mode.lower())
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            RotatingFileHandler(
                os.path.join(log_dir, "trader.log"),
                maxBytes=5 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            ),
            logging.StreamHandler(),
        ],
        force=True,
    )


def build_result_message(
    orders, execution_results, suppressions=None, global_pause=None
):
    suppressions = list(suppressions or [])
    if global_pause:
        return (
            "⛔ <b>미정산 주문 보호 작동</b>\n"
            "모든 신규 주문을 일시 중지했습니다. 브로커 정산 확인 후 자동 해제됩니다.\n"
            f"상세: {global_pause}"
        )
    reason_labels = {
        "AMBIGUOUS_RESULT_SAME_DAY": "브로커 응답 불확실로 당일 재시도 금지",
        "OPEN_ORDER_TODAY": "오늘 열린 주문과 중복 방지",
        "FILLED_ORDER_TODAY": "오늘 체결 주문과 중복 방지",
        "PRICE_GUARD_COOLDOWN": "가격 편차 보호 대기",
        "RETRY_LIMIT": "당일 주문 재시도 한도",
    }
    suppression_detail = None
    if suppressions:
        symbols = ", ".join(sorted({row["ticker"] for row in suppressions}))
        reasons = ", ".join(sorted({
            reason_labels.get(row.get("reason"), row.get("reason", "UNKNOWN"))
            for row in suppressions
        }))
        suppression_detail = f"대상: {symbols}\n사유: {reasons}"
    if not orders and suppression_detail:
        return (
            "🛡️ <b>주문 후보 안전 차단</b>\n"
            f"{suppression_detail}\n"
            "전역 신규주문 중지가 아니라 해당 후보만 이번 사이클에서 제외했습니다."
        )
    if not orders:
        return (
            "✅ <b>금일 매매 내역 없음</b>\n"
            "기존 포지션을 유지하거나 신규 진입 시그널이 없습니다."
        )

    message = "✅ <b>금일 매매 완료</b>\n\n"
    for order in execution_results:
        action_kr = "🔴매도" if order["type"] == "SELL" else "🟢매수"
        status = order.get("status", "DRY_RUN")
        message += (
            f"• {action_kr} {order['ticker']} ({order['qty']}주) [{status}]\n"
            f"  사유: {order['reason']}\n"
        )
    if suppression_detail:
        message += (
            "\n🛡️ <b>별도 주문 후보 안전 차단</b>\n"
            f"{suppression_detail}\n"
            "전역 신규주문 중지가 아니라 해당 후보만 제외했습니다."
        )
    return message


def send_intraday_notification_once(
    bot,
    message,
    orders,
    execution_results,
    suppressions,
    global_pause,
    state_path,
    *,
    today=None,
):
    """Deliver each state-changing intraday alert once after confirmed send."""
    payload = {
        "orders": list(orders or []),
        "results": list(execution_results or []),
        "suppressions": list(suppressions or []),
        "global_pause": global_pause,
    }
    if not any(payload.values()):
        return False
    signature = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()
    path = Path(state_path)
    day = (today or datetime.date.today()).isoformat()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        state = {}
    delivered_keys = (
        list(state.get("delivered_keys", [])) if state.get("date") == day else []
    )
    if signature in delivered_keys:
        return False
    if not bot.send_message(message):
        return False
    delivered_keys.append(signature)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(
                {"date": day, "delivered_keys": delivered_keys[-100:]}, indent=2
            ),
            encoding="utf-8",
        )
        temp_path.replace(path)
    except OSError as exc:
        logging.warning("알림 중복 방지 상태 저장 실패: %s", exc)
    return True

def main():
    parser = argparse.ArgumentParser(description="FA+TA Momentum Live Trader")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--live", action="store_true", help="실계좌 사용(이중 잠금 필요)")
    mode_group.add_argument("--mock", action="store_true", help="모의투자 계좌 사용(기본값)")
    mode_group.add_argument("--simulate", action="store_true", help="로컬 가상 계좌와 즉시 체결 엔진 사용")
    parser.add_argument("--dry-run", action="store_true", help="주문 실행 없이 시그널만 계산")
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument(
        "--premarket", action="store_true",
        help="장 시작 전 FA 필터링(관심종목 추출) 1회 실행",
    )
    action_group.add_argument(
        "--snapshot-only", action="store_true",
        help="주문·시그널 계산 없이 현재 계좌 잔고 기준선용 스냅샷만 저장",
    )
    action_group.add_argument(
        "--liquidate", action="store_true",
        help="보유 중인 모든 종목을 즉시 전량 시장가 매도하여 현금화",
    )
    parser.add_argument(
        "--confirm-liquidate", choices=["LIQUIDATE"],
        help="전체 청산 확인 문자열. --liquidate와 함께 LIQUIDATE를 입력해야 함",
    )
    args = parser.parse_args()
    if args.live and args.dry_run:
        parser.error("--live and --dry-run cannot be combined; DRY_RUN always uses mock")
    if args.liquidate and args.dry_run:
        parser.error("--liquidate and --dry-run cannot be combined")
    requested_mode = (
        "DRY_RUN" if args.dry_run
        else "SIMULATE" if args.simulate
        else "REAL" if args.live
        else "PAPER"
    )
    if args.live and not args.snapshot_only and not args.liquidate:
        _assert_real_system_ready()
    configure_logging(requested_mode)
    cycle_lock = None
    if not args.snapshot_only:
        cycle_lock = ProcessInstanceLock(
            os.path.join("logs", "trader.cycle.lock"),
            requested_mode,
            label="trader cycle",
        )
        try:
            cycle_lock.acquire()
        except ProcessAlreadyRunning as exc:
            logging.warning("[BLOCKED] %s", exc)
            raise SystemExit(2)
        atexit.register(cycle_lock.release)
    
    bot = TelegramBot()
    
    trader = None
    try:
        if args.dry_run:
            logging.info("[DRY RUN] 주문 없이 시그널을 분석합니다.")
        elif args.premarket:
            bot.send_message("🚀 <b>장 시작 전 준비 스크립트 가동</b>\n오늘의 FA/TA 타겟 유니버스를 필터링합니다.")
        elif args.liquidate:
            mode = "실전투자" if args.live else "모의투자"
            bot.send_message(f"🚨 <b>[{mode}] 전체 포지션 청산 실행</b>\n보유 중인 모든 주식을 전량 시장가 매도합니다.")
        else:
            mode = "실전투자" if args.live else "모의투자"
            bot.send_message(f"🚀 <b>[{mode}] 실전 매매 스크립트 가동</b>\nFA+TA 모멘텀 배치 작업을 시작합니다.")
            
        # 트레이더 초기화
        # 주의: dry_run이면 무조건 mock API를 바라보게 하거나 주문 전송 단계에서 막음
        trader = LiveTrader(
            mock=args.dry_run or not args.live,
            simulate=args.simulate,
            dry_run=args.dry_run,
        )
        runtime_mode = (
            "DRY_RUN" if args.dry_run
            else "SIMULATE" if args.simulate
            else "PAPER" if trader.broker.is_mock
            else "REAL"
        )
        logging.info(
            "[TRADER] mode=%s account=%s",
            runtime_mode,
            trader.broker.masked_account,
        )
        
        # 만약 dry_run이면 내부에서 주문이 나가지 않도록 _execute_orders를 패치 (간이 구현)
        if getattr(args, 'dry_run', False): # argparse는 하이픈을 언더스코어로 바꿈
            def mock_execute(orders):
                print("[DRY RUN] 다음 주문들이 실행될 예정입니다:")
                for o in orders:
                    print(f" -> {o['type']} {o['ticker']} 수량: {o['qty']}")
            trader._execute_orders = mock_execute
            
        if args.liquidate:
            if args.confirm_liquidate != "LIQUIDATE":
                raise PermissionError(
                    "전체 청산은 --confirm-liquidate LIQUIDATE 확인이 필요합니다."
                )
            balance_info = trader.broker.get_balance()
            positions = balance_info.get('positions', {})
            if not positions:
                msg = "✅ 보유 중인 포지션이 없습니다."
                logging.info(msg)
                bot.send_message(msg)
                return
            
            sell_orders = []
            for ticker, pos in positions.items():
                sell_orders.append({
                    "type": "SELL",
                    "ticker": ticker,
                    "qty": pos['qty'],
                    "reason": "USER_REQUESTED_LIQUIDATION"
                })
            
            results = trader._execute_orders(sell_orders)
            trader.append_trade_history(results or [])
            if results is None:  # dry-run monkey patch
                results = [{**order, "status": "DRY_RUN"} for order in sell_orders]
            
            # DB 동기화를 위해 잔고 다시 읽어서 zero out
            # 실제 잔량이 0이 될 때까지 확인한다.
            if not getattr(args, 'dry_run', False):
                import time
                for _ in range(10):
                    balance_info = trader.broker.get_balance()
                    if not balance_info['positions']:
                        break
                    time.sleep(1)
                if balance_info['positions']:
                    remaining = ", ".join(
                        f"{ticker}:{pos['qty']}주"
                        for ticker, pos in balance_info['positions'].items()
                    )
                    raise RuntimeError(f"전체 청산 미완료. 잔여 포지션: {remaining}")
                cash = balance_info['cash']
                # 평가금액 재계산
                total_eval = cash + sum(p['qty'] * p['current_price'] for p in balance_info['positions'].values())
                trader._sync_balance_and_positions(balance_info, total_eval)
                
            msg = f"✅ <b>전체 포지션 청산 완료</b>\n{len(results)}개 종목의 잔량 0을 확인했습니다."
            logging.info(msg)
            bot.send_message(msg)
            return
            
        if args.snapshot_only:
            snapshot = trader.capture_account_snapshot()
            msg = (
                "✅ <b>계좌 기준선용 스냅샷 저장 완료</b>\n"
                f"모드: {snapshot['mode']} / 총자산: {snapshot['total_asset']:,.0f}원 / "
                f"보유종목: {snapshot['position_count']}개\n"
                "주문은 전송하지 않았습니다."
            )
            logging.info(msg)
            bot.send_message(msg)
            return
        if args.premarket:
            trader.run_premarket_batch()
            orders = None
            msg = "✅ <b>프리마켓(8시 30분) 준비 완료!</b>\nFA 데이터 필터링을 성공적으로 마치고 관심 종목을 저장했습니다."
            bot.send_message(msg)
            return
        else:
            orders = trader.run_daily_batch()
            # dry_run이 아닌 경우에만 실제 주문 제출
            if not getattr(args, 'dry_run', False) and orders:
                execution_results = trader._execute_orders(orders)
            else:
                execution_results = orders or []
            trader.update_intraday_dashboard(execution_results)
            if not getattr(args, 'dry_run', False):
                trader.append_trade_history(execution_results)
        
        # 결과 메시지 조립
        msg = build_result_message(
            orders,
            execution_results,
            getattr(trader, "last_order_suppressions", []),
            getattr(trader, "last_global_order_pause", None),
        )
                
        logging.info("\n=== [실행 결과 요약] ===")
        logging.info(msg)
        logging.info("======================\n")
        send_intraday_notification_once(
            bot,
            msg,
            orders,
            execution_results,
            getattr(trader, "last_order_suppressions", []),
            getattr(trader, "last_global_order_pause", None),
            Path("logs") / requested_mode.lower() / "notification_state.json",
        )
        
    except Exception as e:
        err_msg = traceback.format_exc()
        logging.error(err_msg)
        try:
            if trader is not None:
                trader.record_operational_error(e)
            bot.send_message(f"🚨 <b>자동매매 스크립트 에러 발생</b>\n<pre>{str(e)}</pre>")
        finally:
            raise SystemExit(1)

if __name__ == "__main__":
    main()
