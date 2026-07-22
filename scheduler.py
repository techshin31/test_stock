import argparse
import atexit
import datetime
import json
import os
import subprocess
import time
import traceback
from pathlib import Path

from core.broker.kis_api import redact_sensitive_text
from core.utils.trading_calendar import is_krx_trading_day
from core.utils.process_lock import ProcessAlreadyRunning, ProcessInstanceLock


PROJECT_ROOT = Path(__file__).resolve().parent

SUPPRESSION_REASON_LABELS = {
    "AMBIGUOUS_RESULT_SAME_DAY": "브로커 응답 불확실·당일 재시도 금지",
    "OPEN_ORDER_TODAY": "당일 미체결 주문 중복 방지",
    "FILLED_ORDER_TODAY": "당일 체결 주문 중복 방지",
    "PRICE_GUARD_COOLDOWN": "가격 편차 보호 대기",
    "RETRY_LIMIT": "당일 재시도 한도",
}

OPERATIONAL_STATUS_LABELS = {
    "NORMAL": "정상",
    "SCANNING": "스캔 중",
    "ORDER_SUPPRESSION": "후보별 주문 안전차단",
    "ORDER_DEDUPLICATION": "중복 주문 제거",
    "ORDER_RECONCILIATION": "미정산 주문 정산 중·전체 신규주문 일시정지",
    "ENTRY_CIRCUIT_BREAKER": "신규 진입 안전차단·매도 위험청산 허용",
    "DEGRADED_DATA_STALE": "일부 데이터 지연",
    "DEGRADED_RISK_UNCHECKED": "위험점검 미완료",
    "ERROR": "오류",
}


def operational_status_label(status: str) -> str:
    label = OPERATIONAL_STATUS_LABELS.get(status, status or "확인 중")
    return f"{label} ({status})" if status else label


SchedulerAlreadyRunning = ProcessAlreadyRunning


class SchedulerInstanceLock(ProcessInstanceLock):
    """Global lock preventing concurrent scheduler processes."""

    def __init__(self, path: Path, mode: str):
        super().__init__(path, mode, label="scheduler")


def log_error(message: str, mode: str) -> None:
    scheduler_log = PROJECT_ROOT / "logs" / mode.lower() / "scheduler.log"
    scheduler_log.parent.mkdir(parents=True, exist_ok=True)
    with scheduler_log.open("a", encoding="utf-8") as log_file:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_file.write(f"[{timestamp}] {message}\n")
        log_file.write(traceback.format_exc())
        log_file.write("\n")


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def is_trading_day(now: datetime.datetime) -> bool:
    return is_krx_trading_day(now.date().isoformat())


def draw_dashboard(last_mode, next_run_time, execution_mode):
    clear_screen()
    print("=======================================================================")
    mode_label = {
        "PAPER": "한국투자 모의투자", "REAL": "실계좌", "DRY_RUN": "주문 없는 점검",
        "SIMULATE": "로컬 시뮬레이션",
    }.get(execution_mode, execution_mode)
    print(f" 🚀 FA/TA 모멘텀 트레이더 | {mode_label}")
    print("=======================================================================")
    state = {}
    state_file = PROJECT_ROOT / "logs" / execution_mode.lower() / "dashboard_state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            cash = state.get("cash", 0)
            total = state.get("total_eval", 0)
            positions = state.get("positions", [])
            print(f" 🕒 최근 업데이트: {state.get('updated_at', '-')}")
            print(f" 💰 총 자산: {total:,.0f} 원 | 예수금: {cash:,.0f} 원")
            print(
                f" 📉 평가손익: {float(state.get('unrealized_pnl', 0)):,.0f} 원 | "
                f"당일 자산변동: {float(state.get('daily_asset_change', 0)):,.0f} 원 "
                f"({float(state.get('daily_asset_change_rate', 0)):.2f}%)"
            )
            print(f" 🧾 체결가 차이 비용(슬리피지 누계): {state.get('total_slippage', 0):,.0f} 원")
            print(f" 📊 보유 종목({len(positions)}): {', '.join(positions) if positions else '없음'}")
            daily = state.get("actual_orders", state.get("daily_orders", {}))
            print(
                " 📌 오늘 실제 주문: "
                f"매수체결 {daily.get('buy_filled', 0)} | "
                f"매도체결 {daily.get('sell_filled', 0)} | "
                f"정산대기 {daily.get('open', 0)} | 거절·취소 {daily.get('rejected', 0)}"
            )
            candidates = state.get("order_candidates", {})
            print(
                " 🧮 최근 주문 후보: "
                f"매수 {candidates.get('buy', 0)} | 매도 {candidates.get('sell', 0)} | "
                f"위험청산 {candidates.get('risk_exit', 0)}"
            )
            suppressions = state.get("order_suppressions", {})
            if int(suppressions.get("total", 0) or 0) > 0:
                reasons = ", ".join(
                    f"{SUPPRESSION_REASON_LABELS.get(reason, reason)} {count}"
                    for reason, count in suppressions.get("by_reason", {}).items()
                )
                print(
                    " 🚧 후보별 주문 안전차단: "
                    f"매수 {suppressions.get('buy', 0)} | "
                    f"매도 {suppressions.get('sell', 0)} | {reasons}"
                )
            data_health = state.get("data_health", {})
            print(
                " 🩺 데이터/위험 점검: "
                f"신선 {data_health.get('fresh_count', 0)}/"
                f"{data_health.get('expected_count', 0)} | "
                f"보유 신호데이터 이상 {len(data_health.get('held_stale_tickers', []))} | "
                f"위험점검 {data_health.get('risk_checks_completed', 0)}/"
                f"{data_health.get('risk_checks_total', 0)}"
            )
            risk = state.get("risk_controls", {})
            print(
                f" 🛡️ 위험관리: 손절 {float(risk.get('stop_loss_pct', 0)):.0%} | "
                f"트레일링 {float(risk.get('trailing_stop_pct', 0)):.0%} | "
                f"일손실한도 {float(risk.get('max_daily_loss_rate', 0)):.0%} | "
                "운영상태 "
                f"{operational_status_label(state.get('operational_status'))}"
            )
            if state.get("last_error"):
                print(f" ⚠️ 최근 오류: {state['last_error']}")
        except (OSError, ValueError, TypeError) as exc:
            print(f" [대시보드 데이터 오류: {exc}]")
    else:
        print(" [첫 매매 사이클 대기 중...]")

    fa_file = PROJECT_ROOT / "logs" / "fa_candidates.json"
    if fa_file.exists():
        try:
            fa = json.loads(fa_file.read_text(encoding="utf-8"))
            print(
                f" 🧠 FA 전략: {fa.get('signal_date', '-')} 기준 {len(fa.get('tickers', []))}종목 | "
                f"점수 ≥ {fa.get('minimum_fa_score', 50.0)} | "
                f"신뢰도 ≥ {fa.get('minimum_score_confidence', 0.70)} | "
                f"모델 {fa.get('score_model_code', 'topdown-fa-v1.0.0')}"
            )
        except (OSError, ValueError, TypeError):
            print(" [FA 후보 상태 읽기 실패]")

    report_file = PROJECT_ROOT / "reports" / "promotion" / execution_mode.lower() / "latest.json"
    if not report_file.exists():
        report_file = PROJECT_ROOT / "logs" / execution_mode.lower() / "reports" / "latest.json"
    if report_file.exists():
        try:
            report = json.loads(report_file.read_text(encoding="utf-8"))
            perf = report.get("performance", {})
            trend = report.get("performance_trend", [])
            daily_return = trend[-1].get("daily_return", 0) if trend else 0
            print(
                f" 성과 검증: {perf.get('validation_status', report.get('health', '-'))} | "
                f"일일 {float(daily_return):.2%} | "
                f"누적 {float(perf.get('net_return', perf.get('cumulative_return', 0)) or 0):.2%}"
            )
        except (OSError, ValueError, TypeError):
            print(" [일일 보고서 읽기 실패]")

    print("-----------------------------------------------------------------------")
    print(f" 🎯 최근 실행된 작업: {last_mode or '없음'} (아래는 최근 1분 단위 결과)")
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
    if now.hour == 15 and now.minute < 30:
        return "오늘 15:30 (EOD 성과·운영 보고서)"
    return "다음 KRX 거래일 08:30"


REPORT_RETRY_INTERVAL = datetime.timedelta(minutes=5)


def should_attempt_daily_report(
    completed_date,
    report_date,
    last_attempt_at,
    now,
    retry_interval=REPORT_RETRY_INTERVAL,
):
    """Return whether an EOD report may run without creating a tight retry loop."""
    if completed_date == report_date:
        return False
    if last_attempt_at is None:
        return True
    return now - last_attempt_at >= retry_interval


def pending_paper_eod_report_date(
    now: datetime.datetime,
    project_root: Path = PROJECT_ROOT,
):
    """Return the oldest completed PAPER session without a valid daily report."""
    from core.analytics.system_readiness import (
        _completed_operational_dates,
        _final_daily_report_dates,
    )

    log_path = project_root / "logs" / "paper" / "operational_health.jsonl"
    if not log_path.exists():
        return None
    completed_dates = _completed_operational_dates(log_path, now)
    valid_dates, _ = _final_daily_report_dates(
        project_root / "reports" / "promotion" / "paper" / "daily"
    )
    return next(
        (session_date for session_date in completed_dates if session_date not in valid_dates),
        None,
    )


def due_end_of_day_report_date(
    now: datetime.datetime,
    execution_mode: str,
    project_root: Path = PROJECT_ROOT,
):
    """Choose a current or missed EOD session without inventing non-trading days."""
    if execution_mode == "PAPER":
        return pending_paper_eod_report_date(now, project_root)
    if not is_trading_day(now):
        return None
    if now.hour > 15 or (now.hour == 15 and now.minute >= 30):
        return now.date()
    return None


def run_command(mode="intraday", live=False, dry_run=True, simulate=False):
    print(f"\n[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] 작업 시작 ({mode})")
    broker_flag = "--live" if live else "--simulate" if simulate else "--mock"
    cmd = ["uv", "run", "python", "run_live_trader.py", broker_flag]
    if dry_run:
        cmd.append("--dry-run")
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
    if result.returncode == 2:
        print(f"[SKIPPED] {mode} trader cycle is already running")
        return False
    if result.returncode != 0:
        raise RuntimeError(f"{mode} 하위 프로세스 실패(returncode={result.returncode})")
    return True


def run_simulation_report(report_date):
    result = subprocess.run(
        [
            "uv", "run", "python", "-m", "core.execution.simulation_report",
            "--date", report_date.isoformat(),
        ],
        cwd=PROJECT_ROOT,
        env=dict(os.environ, PYTHONPATH=str(PROJECT_ROOT), PYTHONUTF8="1"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5 * 60,
    )
    if result.returncode != 0:
        raise RuntimeError("simulation daily health report failed")


def run_end_of_day_report(report_date, execution_mode):
    result = subprocess.run(
        [
            "uv", "run", "python", "-m", "core.analytics.trading_performance",
            "--mode", execution_mode,
            "--date", report_date.isoformat(),
        ],
        cwd=PROJECT_ROOT,
        env=dict(os.environ, PYTHONPATH=str(PROJECT_ROOT), PYTHONUTF8="1"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10 * 60,
    )
    stdout = redact_sensitive_text(getattr(result, "stdout", "") or "")
    stderr = redact_sensitive_text(getattr(result, "stderr", "") or "")
    status = {
        "schema_version": 1,
        "updated_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "mode": execution_mode,
        "report_date": report_date.isoformat(),
        "status": "READY" if result.returncode == 0 else "FAILED",
        "return_code": int(result.returncode),
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
    }
    status_path = (
        PROJECT_ROOT / "logs" / execution_mode.lower() / "eod_report_status.json"
    )
    status_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = status_path.with_suffix(status_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(status_path)
    if result.returncode != 0:
        diagnostic = next(
            (
                line.strip()
                for line in reversed((stderr or stdout).splitlines())
                if line.strip()
            ),
            f"returncode={result.returncode}",
        )
        raise RuntimeError(
            f"{execution_mode} EOD performance report failed: {diagnostic}"
        )


def check_and_run_cold_start(live=False, dry_run=True, simulate=False, now=None):
    now = now or datetime.datetime.now()
    if not is_trading_day(now):
        return None
    state_file = PROJECT_ROOT / "logs" / "fa_candidates.json"
    after_premarket = now.hour > 8 or (now.hour == 8 and now.minute >= 30)
    is_fresh = state_file.exists() and datetime.datetime.fromtimestamp(
        state_file.stat().st_mtime
    ).date() == now.date()
    if after_premarket and not is_fresh:
        run_command(mode="premarket", live=live, dry_run=dry_run, simulate=simulate)
        return "8:30"
    return None


def main():
    parser = argparse.ArgumentParser(description="QuantPilot 거래 스케줄러")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--live", action="store_true", help="실계좌 실행(실주문 이중 잠금 필요)")
    mode_group.add_argument("--paper", action="store_true", help="KIS 모의투자 주문 실행")
    mode_group.add_argument("--simulate", action="store_true", help="로컬 가상 계좌 주문 실행")
    mode_group.add_argument("--dry-run", action="store_true", help="주문 없이 매매 계획만 반복 계산(기본값)")
    args = parser.parse_args()
    dry_run = args.dry_run or not (args.live or args.paper or args.simulate)
    execution_mode = (
        "DRY_RUN" if dry_run else "SIMULATE" if args.simulate
        else "REAL" if args.live else "PAPER"
    )
    instance_lock = SchedulerInstanceLock(
        PROJECT_ROOT / "logs" / "scheduler.instance.lock",
        execution_mode,
    )
    try:
        instance_lock.acquire()
    except SchedulerAlreadyRunning as exc:
        print(f"[BLOCKED] {exc}")
        return 2
    atexit.register(instance_lock.release)
    report_run_date = None
    report_last_attempt_at = None

    try:
        last_run_mark = check_and_run_cold_start(live=args.live, dry_run=dry_run, simulate=args.simulate)
        last_run_mode = "premarket" if last_run_mark else None
        cold_start_pending = False
    except Exception as exc:
        log_error(f"cold-start premarket failed: {exc}", execution_mode)
        last_run_mark = None
        last_run_mode = f"ERROR: {exc} (10초 후 재시도)"
        cold_start_pending = True
    while True:
        now = datetime.datetime.now()
        try:
            if cold_start_pending:
                last_run_mark = check_and_run_cold_start(live=args.live, dry_run=dry_run, simulate=args.simulate)
                last_run_mode = "premarket" if last_run_mark else last_run_mode
                cold_start_pending = False
            if is_trading_day(now):
                if now.hour == 8 and now.minute == 30 and last_run_mark != "8:30":
                    last_run_mark = "8:30"
                    completed = run_command(
                        mode="premarket", live=args.live,
                        dry_run=dry_run, simulate=args.simulate,
                    )
                    last_run_mode = (
                        "premarket" if completed else "premarket skipped (cycle busy)"
                    )
                elif (9 <= now.hour <= 14) or (now.hour == 15 and now.minute <= 20):
                    current_mark = f"{now.hour}:{now.minute}"
                    if last_run_mark != current_mark:
                        last_run_mark = current_mark
                        completed = run_command(
                            mode="intraday", live=args.live,
                            dry_run=dry_run, simulate=args.simulate,
                        )
                        last_run_mode = (
                            "intraday" if completed
                            else "intraday skipped (cycle busy)"
                        )
                if (
                    args.simulate
                    and (now.hour > 15 or (now.hour == 15 and now.minute >= 21))
                    and should_attempt_daily_report(
                        report_run_date, now.date(), report_last_attempt_at, now
                    )
                ):
                    report_last_attempt_at = now
                    run_simulation_report(now.date())
                    report_run_date = now.date()
                    last_run_mode = "simulation_report"
            if not args.simulate:
                pending_report_date = due_end_of_day_report_date(
                    now, execution_mode
                )
                if pending_report_date and should_attempt_daily_report(
                    report_run_date,
                    pending_report_date,
                    report_last_attempt_at,
                    now,
                ):
                    report_last_attempt_at = now
                    run_end_of_day_report(pending_report_date, execution_mode)
                    report_run_date = pending_report_date
                    last_run_mode = (
                        f"eod_performance_report:{pending_report_date}"
                    )
        except Exception as exc:
            log_error(f"scheduled job failed: {exc}", execution_mode)
            retry_note = " (10초 후 재시도)" if cold_start_pending else ""
            last_run_mode = f"ERROR: {exc}{retry_note}"
        draw_dashboard(last_run_mode, get_next_run_time(now), execution_mode)
        time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
