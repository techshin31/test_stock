from __future__ import annotations

import argparse
from datetime import date
import json
import math
import re
from pathlib import Path
import time
import signal

from core.utils.io import write_json


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="QuantPilot 진단·데이터 준비·자동매매 실행")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="설정 존재 여부·DB·데이터 준비도 읽기 전용 점검")
    doctor.add_argument("--cutoff", type=date.fromisoformat)
    doctor.add_argument("--require-data", action="store_true")
    doctor.add_argument("--output", type=Path)
    local = commands.add_parser("local-check", help="격리된 가상계좌에서 전략·체결·재시작 검증")
    local.add_argument("--output", type=Path)
    paper = commands.add_parser("paper-check", help="KIS 모의투자 인증·잔고 조회만 검증 (주문 없음)")
    paper.add_argument("--output", type=Path)
    quality = commands.add_parser("data-quality", help="재무 분기 수·제외 사유·공개 공시 수집 최신성 조회")
    quality.add_argument("--cutoff", type=date.fromisoformat)
    quality.add_argument("--output", type=Path)
    research = commands.add_parser("strategy-review", help="기존 백테스트의 기간별 성과·비용·집중도 진단")
    research.add_argument("--directory", type=Path, required=True)
    research.add_argument("--benchmark", type=Path, required=True)
    research.add_argument("--output", type=Path)
    backup = commands.add_parser("backup", help="DB와 선택적 공개 원본 캐시 백업")
    backup.add_argument("--directory", type=Path, required=True)
    backup.add_argument("--source-cache", type=Path)
    backup.add_argument("--output", type=Path)
    restore = commands.add_parser("restore", help="체크섬 검증 후 새 격리 DB에만 복원")
    restore.add_argument("--directory", type=Path, required=True)
    restore.add_argument("--database", help="quantpilot_restore_ 접두사의 새 DB 이름")
    restore.add_argument("--output", type=Path)
    prepare = commands.add_parser("prepare", help="완료된 거래일 자료 검증·FA 분석·PASS 결과 발행")
    prepare.add_argument("--effective-date", type=date.fromisoformat)
    prepare.add_argument("--collect", action="store_true", help="분석 전 일상 증분 수집 실행")
    prepare.add_argument("--output", type=Path, default=Path("logs/system/preparation.json"))
    cycle = commands.add_parser("run", help="KRX 시간에 준비·장전 후보·매매 주기 실행 (기본 DRY_RUN)")
    cycle.add_argument("--mode", choices=["dry-run", "simulate", "paper"], default="dry-run")
    cycle.add_argument("--collect", action="store_true", help="거래일마다 첫 준비 성공까지 증분 수집 실행")
    cycle.add_argument("--watch", action="store_true", help="중단할 때까지 실행, 미지정 시 1회")
    cycle.add_argument("--paper-policy", action="store_true", help="DRY_RUN/SIMULATE에서 PAPER 정책 재현")
    cycle.add_argument("--supervise", action="store_true", help="진행 정체 감지·최대 3회 복구하며 반복 실행")
    cycle.add_argument("--interval", type=float, default=300)
    cycle.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command in {"prepare", "run"}:
        from apps.system.workflow import prepare as prepare_session, run_cycle, WorkflowBlocked, PROJECT_ROOT
        from core.utils.process_lock import ProcessAlreadyRunning, ProcessHeartbeat, ProcessInstanceLock
        if args.command == "run" and (not math.isfinite(args.interval) or args.interval < 30):
            parser.error("--interval must be finite and at least 30 seconds")
        watch_lock = heartbeat = None
        scheduler_lock = scheduler_heartbeat = None
        if args.command == "run" and args.supervise:
            from apps.system.supervisor import supervise
            arguments = ["--mode", args.mode, "--interval", str(args.interval)]
            if args.collect:
                arguments.append("--collect")
            if args.paper_policy:
                arguments.append("--paper-policy")
            if args.output:
                parser.error("--supervise uses the canonical cycle output; omit --output")
            return supervise(arguments, mode=args.mode)
        previous_signal = signal.getsignal(signal.SIGTERM)
        def terminate(_signum, _frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, terminate)
        try:
            if args.command == "run" and args.watch:
                from apps.system.workflow import MODES
                scheduler_lock = ProcessInstanceLock(PROJECT_ROOT / "logs/scheduler.instance.lock", MODES[args.mode],
                                                       label="scheduler").acquire()
                scheduler_heartbeat = ProcessHeartbeat(PROJECT_ROOT / "logs" / MODES[args.mode].lower() /
                                                        "scheduler_runtime.json", MODES[args.mode], label="scheduler").start()
                watch_lock = ProcessInstanceLock(PROJECT_ROOT / "logs/system/watch.lock", args.mode,
                                                 label="automated trading watcher").acquire()
                heartbeat = ProcessHeartbeat(PROJECT_ROOT / "logs/system/watch.heartbeat.json", args.mode,
                                             label="automated trading watcher").start()
            while True:
                try:
                    result = (prepare_session(effective_date=args.effective_date, collect=args.collect,
                                              output=args.output) if args.command == "prepare" else
                              run_cycle(mode=args.mode, collect=args.collect, output=args.output,
                                        paper_policy=args.paper_policy))
                    code = 0
                except (WorkflowBlocked, ProcessAlreadyRunning) as exc:
                    result = {"status": "BLOCKED", "reason": str(exc)}
                    code = 2
                print(json.dumps(result, ensure_ascii=False, indent=2, default=str), flush=True)
                if args.command != "run" or not args.watch:
                    return code
                time.sleep(args.interval)
        except ProcessAlreadyRunning as exc:
            print(json.dumps({"status": "BLOCKED", "reason": str(exc)}))
            return 2
        except KeyboardInterrupt:
            return 130
        finally:
            signal.signal(signal.SIGTERM, previous_signal)
            if heartbeat:
                heartbeat.stop()
            if watch_lock:
                watch_lock.release()
            if scheduler_heartbeat:
                scheduler_heartbeat.stop()
            if scheduler_lock:
                scheduler_lock.release()
    if args.command in {"data-quality", "strategy-review", "backup", "restore"}:
        try:
            if args.command == "data-quality":
                from apps.system.quality import check_quality
                result = check_quality(args.cutoff)
            elif args.command == "strategy-review":
                from apps.system.strategy_review import review
                result = review(args.directory, args.benchmark)
            else:
                from apps.system import recovery
                result = (recovery.backup(args.directory, args.source_cache) if args.command == "backup"
                          else recovery.restore(args.directory, args.database))
        except Exception as exc:
            # DB and HTTP exception text can include credentials.
            message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else ""
            result = {"status": "BLOCKED", "error_type": type(exc).__name__,
                      "reason": message if re.fullmatch(r"[A-Z][A-Z0-9_]+", message) else "DEPENDENCY_FAILED"}
        passed = result["status"] == "PASS"
    elif args.command == "doctor":
        from apps.system.diagnostics import diagnose

        result = diagnose(args.cutoff)
        passed = result["development_ready"] and (not args.require_data or result["data_ready"])
    elif args.command == "paper-check":
        from apps.system.paper import check_paper
        result = check_paper()
        passed = result["status"] == "PASS"
    else:
        from apps.system.local_check import run_local_check

        result = run_local_check()
        passed = result["status"] == "PASS"
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
