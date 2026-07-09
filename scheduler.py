import time
import datetime
import subprocess
import os
import json

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def draw_dashboard(last_mode, next_run_time):
    clear_screen()
    print("=======================================================================")
    print(" 🚀 FA/TA 모멘텀 라이브 트레이더 [전광판 모드]")
    print("=======================================================================")
    
    # 1. 상태 읽기
    state_file = "logs/dashboard_state.json"
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
            cash = state.get("cash", 0)
            total = state.get("total_eval", 0)
            positions = state.get("positions", [])
            updated_at = state.get("updated_at", "-")
            
            print(f" 🕒 최근 업데이트: {updated_at}")
            print(f" 💰 총 자산 추정치: {total:,.0f} 원")
            print(f" 💵 현재 예수금:   {cash:,.0f} 원")
            print(f" 📊 보유 종목({len(positions)}): {', '.join(positions) if positions else '없음'}")
        except:
            print(" [데이터 로딩 중...]")
    else:
        print(" [첫 매매 사이클 대기 중...]")
        
    print("-----------------------------------------------------------------------")
    print(f" 🎯 최근 실행된 작업: {last_mode if last_mode else '없음'}")
    print(" 📋 [최근 작업 타임라인]")
    if 'state' in locals() and state.get("timeline"):
        for event in state["timeline"]:
            print(f"    {event}")
    else:
        print("    (아직 기록된 타임라인이 없습니다)")
    
    now = datetime.datetime.now()
    print(f"\n ⏳ 현재 시간: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    if now.weekday() >= 5:
        print(" 🛑 주말은 휴장입니다. 편안한 휴일 보내세요!")
    else:
        print(" - 평일 08:30 : 프리마켓 FA 종목 필터링")
        print(" - 평일 09:00 ~ 15:20 : 매 분마다 장중 실전 매매 스캔")
        print(f" ⏭️ 다음 자동 실행 예정: {next_run_time}")
    
    print("=======================================================================")
    print(" [이 창을 켜두시면 정해진 시간에 자동으로 매매가 실행됩니다.]")

def get_next_run_time(now):
    if now.weekday() >= 5:
        return "월요일 08:30 (프리마켓)"
    
    # 오늘 시간이 8:30 이전
    if now.hour < 8 or (now.hour == 8 and now.minute < 30):
        return "오늘 08:30 (프리마켓 필터링)"
    
    # 장중 시간 (09:00 ~ 15:20)
    if (9 <= now.hour <= 14) or (now.hour == 15 and now.minute < 20):
        return "1분 뒤 (장중 매 분마다 스캔 중...)"
        
    return "내일 08:30 (프리마켓 필터링)"

def run_command(mode="intraday"):
    global last_run_mode
    last_run_mode = mode
    
    print(f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 백그라운드 작업 시작 (모드: {mode})...")
    # stdout을 NULL로 보내서 전광판이 망가지지 않게 함 (로그는 live_trader.log에 저장됨)
    cmd = ["uv", "run", "python", "run_live_trader.py"]
    if mode == "premarket":
        cmd.append("--premarket")
        
    subprocess.run(cmd, env=dict(os.environ, PYTHONPATH=os.getcwd(), PYTHONUTF8="1"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

last_run_mark = None
last_run_mode = None

while True:
    now = datetime.datetime.now()
    
    # 평일만 동작
    if now.weekday() < 5:
        # 1. 프리마켓 (08:30)
        if now.hour == 8 and now.minute == 30 and last_run_mark != "8:30":
            run_command(mode="premarket")
            last_run_mark = "8:30"
            
        # 2. 장중 (09:00 ~ 15:20 매 분마다)
        elif (9 <= now.hour <= 14) or (now.hour == 15 and now.minute <= 20):
            current_time_str = f"{now.hour}:{now.minute}"
            if last_run_mark != current_time_str:
                run_command(mode="intraday")
                last_run_mark = current_time_str
            
    # 대시보드 새로고침
    draw_dashboard(last_run_mode, get_next_run_time(now))
    time.sleep(10)
