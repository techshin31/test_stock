import argparse
import traceback
import logging
import os
from logging.handlers import RotatingFileHandler

from core.execution.trader import LiveTrader
from core.utils.telegram_bot import TelegramBot

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

def main():
    parser = argparse.ArgumentParser(description="FA+TA Momentum Live Trader")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--live", action="store_true", help="실계좌 사용(이중 잠금 필요)")
    mode_group.add_argument("--mock", action="store_true", help="모의투자 계좌 사용(기본값)")
    mode_group.add_argument("--simulate", action="store_true", help="로컬 가상 계좌와 즉시 체결 엔진 사용")
    parser.add_argument("--dry-run", action="store_true", help="주문 실행 없이 시그널만 계산")
    parser.add_argument("--premarket", action="store_true", help="장 시작 전 FA 필터링(관심종목 추출) 1회 실행")
    parser.add_argument("--liquidate", action="store_true", help="보유 중인 모든 종목을 즉시 전량 시장가 매도하여 현금화")
    parser.add_argument(
        "--confirm-liquidate", choices=["LIQUIDATE"],
        help="전체 청산 확인 문자열. --liquidate와 함께 LIQUIDATE를 입력해야 함",
    )
    args = parser.parse_args()
    requested_mode = (
        "DRY_RUN" if args.dry_run
        else "SIMULATE" if args.simulate
        else "REAL" if args.live
        else "PAPER"
    )
    configure_logging(requested_mode)
    
    bot = TelegramBot()
    
    try:
        if args.dry_run:
            bot.send_message("🚀 <b>[DRY RUN] 실전 매매 스크립트 가동</b>\n주문을 실행하지 않고 시그널만 분석합니다.")
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
            mock=not args.live, simulate=args.simulate, dry_run=args.dry_run
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
        if not orders:
            msg = "✅ <b>금일 매매 내역 없음</b>\n기존 포지션을 유지하거나 신규 진입 시그널이 없습니다."
        else:
            msg = "✅ <b>금일 매매 완료</b>\n\n"
            for o in execution_results:
                action_kr = "🔴매도" if o['type'] == "SELL" else "🟢매수"
                status = o.get('status', 'DRY_RUN')
                msg += f"• {action_kr} {o['ticker']} ({o['qty']}주) [{status}]\n  사유: {o['reason']}\n"
                
        logging.info("\n=== [실행 결과 요약] ===")
        logging.info(msg)
        logging.info("======================\n")
        bot.send_message(msg)
        
    except Exception as e:
        err_msg = traceback.format_exc()
        logging.error(err_msg)
        try:
            bot.send_message(f"🚨 <b>자동매매 스크립트 에러 발생</b>\n<pre>{str(e)}</pre>")
        finally:
            raise SystemExit(1)

if __name__ == "__main__":
    main()
