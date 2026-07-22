import json
import os
import subprocess
from collections import defaultdict
from pathlib import Path
import re
from datetime import datetime

def check_docker_db_health() -> str:
    """Checks the status of the postgres-db docker container."""
    try:
        # Run docker ps to get status of postgres-db
        result = subprocess.run(
            ["docker", "ps", "-f", "name=postgres-db", "--format", "{{.Status}}"],
            capture_output=True, text=True, check=True
        )
        status = result.stdout.strip()
        if status:
            return f"🟢 UP ({status})"
        else:
            return "🔴 DOWN (Container not found)"
    except Exception as e:
        return f"🔴 ERROR ({e})"

def parse_live_trader_log(date_str: str, log_file: Path):
    """Extracts interesting events and errors from live_trader.log for a specific date."""
    events = []
    errors = []
    
    if not log_file.exists():
        return events, errors
        
    date_prefix = date_str.replace("-", "-") # 2026-07-07
    
    # Simple regex to match start of log lines
    line_pattern = re.compile(rf"^{date_prefix} (\d{{2}}:\d{{2}}:\d{{2}}).*?\[(INFO|ERROR|WARNING)\] (.*)")
    
    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            match = line_pattern.match(line)
            if match:
                time_str, level, msg = match.groups()
                if level == "ERROR":
                    errors.append(f"[{time_str}] {msg[:200]}") # Truncate long errors
                elif level == "INFO" and ("발굴" in msg or "매수" in msg or "차단" in msg or "호재" in msg or "악재" in msg):
                    events.append(f"[{time_str}] {msg}")
                    
    return events, errors

def generate_premium_reports():
    """Parses all logs and generates premium markdown reports."""
    base_dir = Path(r'c:\dev\project\Service_Stock_Analysis')
    audit_log = base_dir / 'logs' / 'trader_audit.jsonl'
    trader_log = base_dir / 'logs' / 'live_trader.log'
    out_dir = base_dir / 'reports' / 'eod_report'
    
    out_dir.mkdir(parents=True, exist_ok=True)
    
    if not audit_log.exists():
        print("Audit log not found. Cannot generate reports.")
        return

    daily_data = defaultdict(lambda: {
        'cycles': 0, 'orders': [], 'errors': [], 'strategy': set(), 'final_balance': None
    })

    # Parse audit JSONL
    with open(audit_log, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip(): continue
            try:
                record = json.loads(line)
                ts_str = record.get('ts', '')
                if not ts_str: continue
                date_str = ts_str.split('T')[0]
                event = record.get('event')
                day_stats = daily_data[date_str]
                
                if event == 'STARTUP':
                    strat = record.get('strategy_name')
                    if strat: day_stats['strategy'].add(strat)
                elif event == 'CYCLE_DONE':
                    day_stats['cycles'] += 1
                elif event == 'ORDER_PLACED':
                    day_stats['orders'].append({
                        'ticker': record.get('symbol', ''),
                        'side': record.get('side', ''),
                        'qty': record.get('qty', 0),
                        'price': record.get('price', 0)
                    })
                elif event == 'BALANCE_SYNC':
                    day_stats['final_balance'] = record.get('total_balance_krw')
                elif event == 'ERROR' or 'error' in record:
                    day_stats['errors'].append(record.get('error_msg', str(record)))
            except: pass

    # Fetch Docker Health
    db_health = check_docker_db_health()

    # Generate Markdown for each date
    for date, stats in daily_data.items():
        # Get live_trader events for this date
        trader_events, trader_errors = parse_live_trader_log(date, trader_log)
        
        # Merge errors
        all_errors = stats['errors'] + trader_errors
        
        md = [
            f"# 📊 QuantPilot EOD 운영 보고서 ({date})",
            "",
            "> 본 리포트는 거래 감사 로그(`trader_audit.jsonl`) 및 트레이더 로그(`live_trader.log`), Docker 컨테이너 상태를 종합하여 자동 생성된 프리미엄 운영 보고서입니다.",
            "",
            "## 1. ⚙️ 시스템 Health Check",
            "",
            "| 컴포넌트 | 상태 | 비고 |",
            "|---|---|---|",
            f"| **트레이딩 봇** | 🟢 UP | {stats['cycles']} cycles completed |",
            f"| **PostgreSQL DB** | {db_health} | Docker Container `postgres-db` |",
            f"| **운영 에러** | {'🔴 발생' if all_errors else '🟢 정상'} | {len(all_errors)} issues detected |",
            "",
            "## 2. 📈 일간 성과 요약 (Summary)",
            ""
        ]
        
        strats = ', '.join(stats['strategy']) if stats['strategy'] else 'N/A'
        bal_val = stats["final_balance"]
        bal = f'{bal_val:,} 원' if bal_val is not None else '데이터 없음'
        
        md.append(f"- **적용 전략:** `{strats}`")
        md.append(f"- **추정 총자산:** `{bal}`")
        md.append(f"- **총 발생 주문:** `{len(stats['orders'])}` 건")
        
        md.append("\n## 3. 🛒 매매 체결 내역 (Orders)")
        if stats['orders']:
            md.append("| 종목코드 | 구분 | 수량 | 체결단가 |")
            md.append("|---|:---:|---:|---:|")
            for o in stats['orders']:
                side = o["side"]
                side_icon = "🔴 매도" if "sell" in side.lower() else "🟢 매수"
                price_val = o["price"]
                p = f'{price_val:,}' if isinstance(price_val, (int, float)) else price_val
                md.append(f"| `{o['ticker']}` | {side_icon} | {o['qty']} 주 | ₩{p} |")
        else:
            md.append("> 해당 일자에 체결된 매매 내역이 없습니다.")
            
        md.append("\n## 4. ⏱️ 주요 이벤트 타임라인 (Timeline)")
        if trader_events:
            for ev in trader_events[-10:]: # Show last 10
                md.append(f"- `{ev[:10]}` {ev[11:]}")
        else:
            md.append("> 특이 이벤트 기록 없음")
            
        if all_errors:
            md.append("\n> [!CAUTION]")
            md.append(f"> **시스템 경고 및 에러 로그 ({len(all_errors)}건)**")
            for e in all_errors[:5]:
                md.append(f"> - `{e}`")
            if len(all_errors) > 5:
                md.append("> - *...and more (Check server logs for details)*")
                
        out_path = out_dir / f'{date}_eod_report.md'
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(md))
            
    print(f"Generated premium EOD reports for {len(daily_data)} days.")

if __name__ == "__main__":
    generate_premium_reports()
