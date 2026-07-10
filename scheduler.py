import argparse
import datetime
import json
import os
import subprocess
import time
from pathlib import Path

from core.utils.trading_calendar import is_krx_trading_day


PROJECT_ROOT = Path(__file__).resolve().parent


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def is_trading_day(now: datetime.datetime) -> bool:
    return is_krx_trading_day(now.date().isoformat())


def draw_dashboard(last_mode, next_run_time):
    clear_screen()
    print("=======================================================================")
    print(" 🚀 FA/TA 모멘텀 라이브 트레이더 [전광판 모드]")
    print("=======================================================================")
    state = {}
    state_file = PROJECT_ROOT / "logs" / "dashboard_state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            cash = state.get("cash", 0)
            total = state.get("total_eval", 0)
            positions = state.get("positions", [])
            print(f" 🕒 최근 업데이트: {state.get('updated_at', '-')}")
            print(f" 💰 총 자산 추정치: {total:,.0f} 원")
            print(f" 💵 현재 예수금:   {cash:,.0f} 원")
            print(f" 📉 누적 슬리피지: {state.get('total_slippage', 0):,.0f} 원")
            print(f" 📊 보유 종목({len(positions)}): {', '.join(positions) if positions else '없음'}")
        except (OSError, ValueError, TypeError) as exc:
            print(f" [대시보드 데이터 오류: {exc}]")
    else:
        print(" [첫 매매 사이클 대기 중...]")

    print("-----------------------------------------------------------------------")
    print(f" 🎯 최근 실행된 작업: {last_mode or '없음'}")
    print(" 📋 [최근 작업 타임라인]")
    for event in state.get("timeline", []) or ["(아직 기록된 타임라인이 없습니다)"]:
        print(f"    {event}")

    now = datetime.datetime.now()
    print(f"\n ⏳ 현재 시간: {now:%Y-%m-%d %H:%M:%S}")
    if not is_trading_day(now):
        print(" 🛑 오늘은 KRX 휴장일입니다.")
    else:
        print(" - 거래일 08:30 : 프리마켓 FA 종목 필터링")
        print(" - 거래일 09:00 ~ 15:20 : 매 분마다 매매 스캔")
        print(f" ⏭️ 다음 자동 실행 예정: {next_run_time}")
    print("=======================================================================")


def get_next_run_time(now):
    if not is_trading_day(now):
        return "다음 KRX 거래일 08:30"
    if now.hour < 8 or (now.hour == 8 and now.minute < 30):
        return "오늘 08:30 (프리마켓 필터링)"
    if (9 <= now.hour <= 14) or (now.hour == 15 and now.minute < 20):
        return "1분 뒤 (장중 스캔)"
    return "다음 KRX 거래일 08:30"


def run_command(mode="intraday", live=False):
    print(f"\n[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] 작업 시작 ({mode})")
    cmd = ["uv", "run", "python", "run_live_trader.py", "--live" if live else "--mock"]
    if mode == "premarket":
        cmd.append("--premarket")
    result = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        env=dict(os.environ, PYTHONPATH=str(PROJECT_ROOT), PYTHONUTF8="1"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15 * 60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{mode} 하위 프로세스 실패(returncode={result.returncode})")


def check_and_run_cold_start(live=False, now=None):
    now = now or datetime.datetime.now()
    if not is_trading_day(now):
        return None
    state_file = PROJECT_ROOT / "logs" / "fa_candidates.json"
    after_premarket = now.hour > 8 or (now.hour == 8 and now.minute >= 30)
    is_fresh = state_file.exists() and datetime.datetime.fromtimestamp(
        state_file.stat().st_mtime
    ).date() == now.date()
    if after_premarket and not is_fresh:
        run_command(mode="premarket", live=live)
        return "8:30"
    return None


def main():
    parser = argparse.ArgumentParser(description="QuantPilot 거래 스케줄러")
    parser.add_argument("--live", action="store_true", help="실계좌 실행(실주문 이중 잠금 필요)")
    args = parser.parse_args()

    last_run_mark = check_and_run_cold_start(live=args.live)
    last_run_mode = "premarket" if last_run_mark else None
    while True:
        now = datetime.datetime.now()
        try:
            if is_trading_day(now):
                if now.hour == 8 and now.minute == 30 and last_run_mark != "8:30":
                    last_run_mark = "8:30"
                    run_command(mode="premarket", live=args.live)
                    last_run_mode = "premarket"
                elif (9 <= now.hour <= 14) or (now.hour == 15 and now.minute <= 20):
                    current_mark = f"{now.hour}:{now.minute}"
                    if last_run_mark != current_mark:
                        last_run_mark = current_mark
                        run_command(mode="intraday", live=args.live)
                        last_run_mode = "intraday"
        except Exception as exc:
            last_run_mode = f"ERROR: {exc}"
        draw_dashboard(last_run_mode, get_next_run_time(now))
        time.sleep(10)


if __name__ == "__main__":
    main()
