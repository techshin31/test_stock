import argparse
import traceback
import logging
import os
import sys

# Ensure the project root is in the PYTHONPATH
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from core.execution.trader import LiveTrader
from core.utils.telegram_bot import TelegramBot
import datetime

# 로그 디렉토리 생성 및 로거 설정
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("logs/live_trader.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def main():
    parser = argparse.ArgumentParser(description="FA+TA Momentum Live Trader")
    parser.add_argument("--mock", action="store_true", help="모의투자 계좌 사용")
    parser.add_argument("--dry-run", action="store_true", help="주문 실행 없이 시그널만 계산")
    parser.add_argument("--premarket", action="store_true", help="장 시작 전 FA 필터링(관심종목 추출) 1회 실행")
    args = parser.parse_args()
    
    bot = TelegramBot()
    
    try:
        if args.dry_run:
            bot.send_message("🚀 <b>[DRY RUN] 실전 매매 스크립트 가동</b>\n주문을 실행하지 않고 시그널만 분석합니다.")
        elif args.premarket:
            bot.send_message(f"🚀 <b>장 시작 전 준비 스크립트 가동</b>\n오늘의 FA/TA 타겟 유니버스를 필터링합니다.")
        else:
            mode = "모의투자" if args.mock else "실전투자"
            bot.send_message(f"🚀 <b>[{mode}] 실전 매매 스크립트 가동</b>\nFA+TA 모멘텀 배치 작업을 시작합니다.")
            
        # 트레이더 초기화
        # 주의: dry_run이면 무조건 mock API를 바라보게 하거나 주문 전송 단계에서 막음
        trader = LiveTrader(mock=args.mock)
        
        # 만약 dry_run이면 내부에서 주문이 나가지 않도록 _execute_orders를 패치 (간이 구현)
        if getattr(args, 'dry_run', False): # argparse는 하이픈을 언더스코어로 바꿈
            def mock_execute(orders):
                print("[DRY RUN] 다음 주문들이 실행될 예정입니다:")
                for o in orders:
                    print(f" -> {o['type']} {o['ticker']} 수량: {o['qty']}")
            trader._execute_orders = mock_execute
            
        if args.premarket:
            trader.run_premarket_batch()
            orders = None
            msg = "✅ <b>프리마켓(8시 30분) 준비 완료!</b>\nFA 데이터 필터링을 성공적으로 마치고 관심 종목을 저장했습니다."
            bot.send_message(msg)
            return
        else:
            orders = trader.run_daily_batch()
        
        # 결과 메시지 조립
        if not orders:
            msg = "✅ <b>금일 매매 내역 없음</b>\n기존 포지션을 유지하거나 신규 진입 시그널이 없습니다."
        else:
            msg = "✅ <b>금일 매매 완료</b>\n\n"
            for o in orders:
                action_kr = "🔴매도" if o['type'] == "SELL" else "🟢매수"
                msg += f"• {action_kr} {o['ticker']} ({o['qty']}주)\n  사유: {o['reason']}\n"
                
        logging.info("\n=== [실행 결과 요약] ===")
        logging.info(msg)
        logging.info("======================\n")
        bot.send_message(msg)
        
    except Exception as e:
        err_msg = traceback.format_exc()
        logging.error(err_msg)
        bot.send_message(f"🚨 <b>자동매매 스크립트 에러 발생</b>\n<pre>{str(e)}</pre>")

if __name__ == "__main__":
    main()
