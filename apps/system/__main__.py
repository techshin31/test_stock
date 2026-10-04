from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path

from core.utils.io import write_json


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="QuantPilot 초기 개발 점검 (브로커 주문 없음)")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="설정 존재 여부·DB·데이터 준비도 읽기 전용 점검")
    doctor.add_argument("--cutoff", type=date.fromisoformat)
    doctor.add_argument("--require-data", action="store_true")
    doctor.add_argument("--output", type=Path)
    local = commands.add_parser("local-check", help="격리된 가상계좌에서 전략·체결·재시작 검증")
    local.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "doctor":
        from apps.system.diagnostics import diagnose

        result = diagnose(args.cutoff)
        passed = result["development_ready"] and (not args.require_data or result["data_ready"])
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
