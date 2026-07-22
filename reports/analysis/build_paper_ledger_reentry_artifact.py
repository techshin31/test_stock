"""Build the canonical MCP report artifact for PAPER ledger/reentry analysis."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd


ROOT = Path(
    os.environ.get("PAPER_REPORT_PROJECT_ROOT", Path(__file__).resolve().parents[2])
).resolve()
LEDGER = ROOT / "reports" / "analysis" / "paper_ledger_latest"
REENTRY = ROOT / "reports" / "analysis" / "paper_reentry_experiments"
COMPAT_OUTPUT = ROOT / "reports" / "analysis" / "paper_ledger_reentry_artifact_2026-07-22.json"
SYSTEM_REPORT_DIR = ROOT / "reports" / "analysis" / "paper_system_report"
READINESS = ROOT / "reports" / "analysis" / "automated_trading_system_readiness.json"
PARITY = ROOT / "reports" / "analysis" / "paper_order_result_replay" / "latest" / "summary.json"
STRESS = ROOT / "reports" / "analysis" / "paper_execution_stress" / "latest" / "summary.json"
BROKER_HISTORY = ROOT / "reports" / "analysis" / "paper_broker_history" / "latest.json"
FINAL_DAILY = ROOT / "reports" / "promotion" / "paper" / "latest.json"

ledger = json.loads((LEDGER / "summary.json").read_text(encoding="utf-8"))
full = json.loads((REENTRY / "full" / "metrics.json").read_text(encoding="utf-8"))
recent = json.loads((REENTRY / "pass_only" / "metrics.json").read_text(encoding="utf-8"))
positions = pd.read_csv(LEDGER / "position_reconciliation.csv", dtype={"symbol": "string"})
readiness = json.loads(READINESS.read_text(encoding="utf-8"))
parity = json.loads(PARITY.read_text(encoding="utf-8"))
stress = json.loads(STRESS.read_text(encoding="utf-8"))
broker_history = json.loads(BROKER_HISTORY.read_text(encoding="utf-8"))
final_daily = json.loads(FINAL_DAILY.read_text(encoding="utf-8"))

generated_at = readiness["generated_at"]
cutoff = ledger["metadata"]["cutoff"]
current = full["summary"]["A_CURRENT"]
recent_current = recent["summary"]["A_CURRENT"]
trend = full["summary"]["R_TREND_REARM"]
recent_trend = recent["summary"]["R_TREND_REARM"]

ledger_source = {
    "id": "paper_ledger",
    "label": "PAPER 주문·손익 복원 원장",
    "path": "reports/analysis/paper_ledger_latest/summary.json",
    "query": {
        "engine": "PostgreSQL",
        "language": "sql",
        "description": "동일 PAPER 계좌의 risk_neutral→aggressive 전략 계보와 KIS 주문 감사를 컷오프까지 읽기 전용으로 결합",
        "sql": "SELECT o.*, s.name FROM orders o JOIN strategies s ON s.id=o.strategy_id WHERE s.name IN ('risk_neutral','aggressive') AND ((o.execution_venue='PAPER' AND o.account_scope=%(account_scope)s) OR o.execution_venue='UNKNOWN') AND o.created_at <= %(cutoff)s ORDER BY o.created_at;\nSELECT e.* FROM executions e JOIN orders o ON o.id=e.order_id JOIN strategies s ON s.id=o.strategy_id WHERE s.name IN ('risk_neutral','aggressive') AND ((o.execution_venue='PAPER' AND o.account_scope=%(account_scope)s) OR o.execution_venue='UNKNOWN') AND e.executed_at <= %(cutoff)s ORDER BY e.executed_at;\nSELECT bh.* FROM balance_history bh JOIN strategies s ON s.id=bh.strategy_id WHERE s.name IN ('risk_neutral','aggressive') AND ((bh.execution_venue='PAPER' AND bh.account_scope=%(account_scope)s) OR bh.execution_venue='UNKNOWN') AND bh.recorded_at <= %(cutoff)s ORDER BY bh.recorded_at;",
        "executed_at": ledger["metadata"]["generated_at"],
        "tables_used": ["orders", "executions", "balance_history", "strategies", "companies"],
        "filters": [f"cutoff={cutoff}", "strategy lineage=risk_neutral,aggressive", "PAPER account scope + UNKNOWN legacy", "REAL excluded"],
        "metric_definitions": [
            "총손익 = 컷오프 PAPER 총평가액 - 500,000,000원",
            "현금 잔차 = 500,000,000원 직접 주문결과 재생 종료현금 - 브로커 종료현금",
            "체결률 = FILLED 주문 수 / 전체 종결 주문 수",
            "수량 조정항목 = 컷오프 실제 수량 - 알려진 체결의 순수량",
        ],
    },
}

experiment_source = {
    "id": "reentry_experiments",
    "label": "재진입 확인 조건 전체·최근 구간 실험",
    "path": "reports/analysis/paper_reentry_experiments/full/metrics.json",
    "query": {
        "engine": "PostgreSQL",
        "language": "sql",
        "description": "월별 FA 선택과 일별 가격을 사용한 현재 규칙 및 청산 사유별 재진입 확인 조건 비교",
        "sql": "WITH ranked AS (SELECT r.*, ROW_NUMBER() OVER (PARTITION BY r.analysis_month ORDER BY CASE r.status_code WHEN 'PUBLISHED' THEN 0 WHEN 'PASS' THEN 1 ELSE 2 END, r.run_version DESC, r.id DESC) rn FROM fa_analysis_runs r JOIN strategies s ON s.id=r.strategy_id WHERE s.name='aggressive' AND r.status_code IN ('PASS','WARNING','PUBLISHED')) SELECT r.id run_id,r.effective_date,r.status_code,c.stock_code,c.fa_score FROM ranked r JOIN fa_company_results c ON c.run_id=r.id WHERE r.rn=1 AND c.is_selected=TRUE AND c.is_eligible=TRUE ORDER BY r.effective_date,c.stock_code;\nSELECT stock_code,price_date,close FROM wics_constituent_prices WHERE close>0 ORDER BY price_date,stock_code;",
        "executed_at": full["metadata"]["generated_at"],
        "tables_used": ["fa_analysis_runs", "fa_company_results", "wics_constituent_prices"],
        "filters": [
            "strategy=aggressive",
            "full period=2023-05-31..2026-07-09",
            "recent period=PASS/PUBLISHED only, 2026-01-30..2026-07-09",
            "REAL excluded",
        ],
        "metric_definitions": [
            "총수익률 = 일별 비용 차감 수익률의 기하 누적 - 1",
            "MDD = 누적자산의 직전 고점 대비 최대 하락률",
            "연환산 회전율 = 일평균 절대 비중 매매량 × 252",
            "매수 비용 0.115%, 매도 비용 0.295%를 적용",
        ],
    },
}

readiness_source = {
    "id": "system_readiness",
    "label": "PAPER 자동매매 시스템 준비도 감사",
    "path": "reports/analysis/automated_trading_system_readiness.json",
}

broker_source = {
    "id": "broker_history",
    "label": "KIS PAPER 주문 원장 전수 감사",
    "path": "reports/analysis/paper_broker_history/latest.json",
}

final_daily_source = {
    "id": "final_daily_report",
    "label": f"{final_daily['report_date']} PAPER FINAL·READY 일일 보고서",
    "path": f"reports/promotion/paper/daily/{final_daily['report_date']}.json",
}

pnl_rows = [
    {"component": "전체 손익", "amount_million": ledger["endpoint"]["total_pnl"] / 1_000_000, "classification": "확정"},
    {"component": "현재 평가손익", "amount_million": ledger["endpoint"]["broker_unrealized_pnl"] / 1_000_000, "classification": "브로커"},
    {"component": "부분 매칭 실현손익", "amount_million": ledger["order_result_replay"]["partially_matched_realized_gross_pnl"] / 1_000_000, "classification": "부분 추정"},
    {"component": "추정 수수료·세금", "amount_million": -ledger["order_result_replay"]["modeled_commission_and_tax"] / 1_000_000, "classification": "모형"},
    {"component": "5억원 재생 현금 잔차", "amount_million": ledger["reconciliation"]["unresolved_pnl_balancing_item"] / 1_000_000, "classification": "허용범위"},
]

order_status_rows = [
    {"status": status, "orders": count, "share": count / ledger["order_result_replay"]["orders"]}
    for status, count in ledger["order_result_replay"]["status_counts"].items()
]

variant_codes = ["A_CURRENT", "X_COOLDOWN5", "R_EXIT_RECOVERY", "R_TREND_REARM", "C_CAP10", "C_CAP08"]
labels = {row["code"]: row["label"] for row in full["metadata"]["variant_definitions"]}
reentry_rows = []
reentry_table_rows = []
for code in variant_codes:
    full_row = full["summary"][code]
    recent_row = recent["summary"][code]
    for scope, row in (("전체", full_row), ("최근", recent_row)):
        reentry_rows.append(
            {
                "variant": code,
                "candidate": labels[code],
                "scope": scope,
                "total_return": row["total_return"],
                "mdd": row["max_drawdown"],
                "annualized_turnover": row["annualized_turnover"],
                "average_exposure": row["average_exposure"],
            }
        )
    reentry_table_rows.append(
        {
            "candidate": labels[code],
            "full_return": full_row["total_return"],
            "full_mdd": full_row["max_drawdown"],
            "recent_return": recent_row["total_return"],
            "recent_mdd": recent_row["max_drawdown"],
            "recent_turnover": recent_row["annualized_turnover"],
            "confirmed_reentries": recent_row["confirmed_reentries"],
        }
    )

position_rows = positions[
    (positions["actual_endpoint_qty"] != 0) | (positions["qty_gap_balancing_entry"] != 0)
].copy()
position_rows["gap_abs"] = position_rows["qty_gap_balancing_entry"].abs()
position_rows = position_rows.sort_values("gap_abs", ascending=False).head(12)
position_dataset = position_rows[
    ["stock_name", "symbol", "known_fill_net_qty", "actual_endpoint_qty", "qty_gap_balancing_entry", "exact_qty_match", "gap_abs"]
].to_dict(orient="records")

gate_rows = [
    {
        "criterion": row["name"],
        "passed": row["passed"],
        "detail": row["detail"],
        "status_rank": 1 if row["passed"] else 0,
    }
    for row in [*readiness["safety_checks"], *readiness["completion_evidence_checks"]]
]

gate_values = ",\n        ".join(
    "(" + ", ".join([
        "'" + row["criterion"].replace("'", "''") + "'",
        "TRUE" if row["passed"] else "FALSE",
        "'" + row["detail"].replace("'", "''") + "'",
        str(row["status_rank"]),
    ]) + ")"
    for row in gate_rows
)
readiness_source["query"] = {
    "engine": "PostgreSQL",
    "language": "sql",
    "description": "준비도 JSON에서 검토한 안전검사와 완료 증거검사를 재현하는 값 테이블",
    "sql": (
        "WITH readiness_gate(criterion, passed, detail, status_rank) AS (VALUES\n        "
        + gate_values
        + "\n) SELECT criterion, passed, detail, status_rank FROM readiness_gate "
        + "ORDER BY status_rank ASC, criterion;"
    ),
    "executed_at": readiness["generated_at"],
    "tables_used": [],
    "filters": ["scope=PAPER_AUTOMATED_TRADING_SYSTEM", "REAL authorization always false"],
    "metric_definitions": [
        "안전검사 통과율 = passed 안전검사 수 / 전체 안전검사 수",
        "증거검사 통과율 = passed 완료 증거검사 수 / 전체 완료 증거검사 수",
    ],
}

implementation_result = [{
    "total_asset": ledger["endpoint"]["total_asset"],
    "return_vs_500m": ledger["endpoint"]["total_return"],
    "post_baseline_return": ledger["endpoint"]["post_baseline_return"],
    "fill_rate": ledger["order_result_replay"]["fill_rate"],
    "auditable_fill_coverage": ledger["data_quality"]["auditable_fill_evidence_coverage"],
    "held_quantity_match_rate": ledger["reconciliation"]["endpoint_held_position_match_rate"],
    "safety_checks_passed": readiness["progress"]["safety_checks"]["passed"],
    "evidence_checks_passed": readiness["progress"]["evidence_checks"]["passed"],
}]

headline = [{
    "total_pnl": ledger["endpoint"]["total_pnl"],
    "total_return": ledger["endpoint"]["total_return"],
    "post_baseline_return": ledger["endpoint"]["post_baseline_return"],
    "fill_rate": ledger["order_result_replay"]["terminal_fill_rate"],
    "held_position_match_rate": ledger["reconciliation"]["endpoint_held_position_match_rate"],
    "unresolved_pnl": ledger["reconciliation"]["unresolved_pnl_balancing_item"],
}]

sources = [
    ledger_source,
    experiment_source,
    readiness_source,
    broker_source,
    final_daily_source,
]
title = "PAPER 자동매매 원장 복원·실험·준비도 보고서"

artifact = {
    "surface": "report",
    "manifest": {
        "version": 1,
        "surface": "report",
        "title": title,
        "description": "5억원 기준 실제 PAPER 손익, 주문결과 원장 복원, 재진입 확인 조건 실험의 의사결정 보고서",
        "generatedAt": generated_at,
        "sources": sources,
        "cards": [
            {
                "id": "total_loss",
                "dataset": "headline",
                "description": "컷오프 총평가액과 5억원의 차이",
                "sourceId": "paper_ledger",
                "metrics": [
                    {"label": "5억원 대비 총손익", "field": "total_pnl", "format": "number", "unit": "원", "signed": True},
                    {"label": "총수익률", "field": "total_return", "format": "percent", "signed": True},
                ],
            },
            {
                "id": "post_baseline",
                "dataset": "headline",
                "description": "7월 20일 인증 기준선 이후 수익률",
                "sourceId": "paper_ledger",
                "metrics": [{"label": "기준선 이후", "field": "post_baseline_return", "format": "percent", "signed": True}],
            },
            {
                "id": "fill_rate",
                "dataset": "headline",
                "description": "종결 주문 중 FILLED 비중",
                "sourceId": "paper_ledger",
                "metrics": [{"label": "실제 체결률", "field": "fill_rate", "format": "percent"}],
            },
            {
                "id": "position_match",
                "dataset": "headline",
                "description": "현재 보유 4종목 중 알려진 체결 순수량과 일치한 비율",
                "sourceId": "paper_ledger",
                "metrics": [{"label": "보유수량 일치율", "field": "held_position_match_rate", "format": "percent"}],
            },
        ],
        "charts": [
            {
                "id": "pnl_bridge",
                "title": "5억원 손익 관련 금액 비교",
                "subtitle": "2026-07-22 13:10 KST 컷오프, 단위 백만원; 항목은 가산식이 아님",
                "type": "bar",
                "intent": "comparison",
                "dataset": "pnl_bridge",
                "sourceId": "paper_ledger",
                "encodings": {
                    "x": {"field": "component", "type": "nominal", "label": "구성 항목"},
                    "y": {"field": "amount_million", "type": "quantitative", "label": "백만원", "format": "number"},
                    "color": {"field": "classification", "type": "nominal", "label": "분류"},
                    "tooltip": [
                        {"field": "classification", "type": "text", "label": "분류"},
                        {"field": "amount_million", "type": "quantitative", "label": "백만원", "format": "number"},
                    ],
                },
                "layout": "full",
                "settings": {"legend": "bottom", "valueLabels": "auto"},
                "palette": {"kind": "categorical"},
            },
            {
                "id": "order_status",
                "title": "실제 주문 최종상태",
                "subtitle": f"컷오프까지 {ledger['order_result_replay']['orders']}건, 부분체결을 별도 상태로 표시",
                "type": "bar",
                "intent": "comparison",
                "dataset": "order_status",
                "sourceId": "paper_ledger",
                "encodings": {
                    "x": {"field": "status", "type": "nominal", "label": "상태"},
                    "y": {"field": "orders", "type": "quantitative", "label": "주문 수", "format": "number"},
                    "tooltip": [{"field": "share", "type": "quantitative", "label": "비중", "format": "percent"}],
                },
                "layout": "full",
                "settings": {"legend": "none", "valueLabels": "auto"},
                "palette": {"kind": "categorical"},
            },
            {
                "id": "reentry_returns",
                "title": "재진입 후보 전체·최근 수익률",
                "subtitle": "최근은 PASS/PUBLISHED 107거래일, 전체는 757거래일",
                "type": "bar",
                "intent": "comparison",
                "dataset": "reentry_results",
                "sourceId": "reentry_experiments",
                "encodings": {
                    "x": {"field": "candidate", "type": "nominal", "label": "후보"},
                    "y": {"field": "total_return", "type": "quantitative", "label": "총수익률", "format": "percent"},
                    "color": {"field": "scope", "type": "nominal", "label": "구간"},
                    "tooltip": [
                        {"field": "mdd", "type": "quantitative", "label": "MDD", "format": "percent"},
                        {"field": "annualized_turnover", "type": "quantitative", "label": "연환산 회전율", "format": "number"},
                    ],
                },
                "layout": "full",
                "settings": {"legend": "bottom", "valueLabels": "none"},
                "palette": {"kind": "categorical"},
            },
        ],
        "tables": [
            {
                "id": "position_gaps",
                "title": "보유·리플레이 수량 대사",
                "subtitle": "한글 종목명을 주표기로, 종목코드를 보조 표기로 표시",
                "dataset": "position_gaps",
                "sourceId": "paper_ledger",
                "defaultSort": {"field": "gap_abs", "direction": "desc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "stock_name", "label": "종목명", "type": "text"},
                    {"field": "symbol", "label": "코드", "type": "text"},
                    {"field": "known_fill_net_qty", "label": "알려진 순수량", "format": "number"},
                    {"field": "actual_endpoint_qty", "label": "실제 수량", "format": "number"},
                    {"field": "qty_gap_balancing_entry", "label": "조정 수량", "format": "number", "movement": True},
                    {"field": "exact_qty_match", "label": "일치", "type": "boolean"},
                    {"field": "gap_abs", "label": "절대 차이", "format": "number"},
                ],
            },
            {
                "id": "reentry_table",
                "title": "재진입 후보 성과 비교",
                "subtitle": "전체 성과와 최근 스트레스 구간을 함께 비교",
                "dataset": "reentry_table",
                "sourceId": "reentry_experiments",
                "defaultSort": {"field": "recent_return", "direction": "desc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "candidate", "label": "후보", "type": "text"},
                    {"field": "full_return", "label": "전체 수익", "format": "percent", "movement": True},
                    {"field": "full_mdd", "label": "전체 MDD", "format": "percent", "movement": True},
                    {"field": "recent_return", "label": "최근 수익", "format": "percent", "movement": True},
                    {"field": "recent_mdd", "label": "최근 MDD", "format": "percent", "movement": True},
                    {"field": "recent_turnover", "label": "최근 회전율", "format": "number"},
                    {"field": "confirmed_reentries", "label": "확인 재진입", "format": "number"},
                ],
            },
            {
                "id": "shadow_gate",
                "title": "PAPER 자동매매 전체 준비도 게이트",
                "subtitle": "안전·원장·리플레이·체결표본·shadow·60세션 근거를 함께 판정",
                "dataset": "shadow_gate",
                "sourceId": "system_readiness",
                "defaultSort": {"field": "status_rank", "direction": "asc"},
                "density": "spacious",
                "layout": "full",
                "columns": [
                    {"field": "criterion", "label": "기준", "type": "text"},
                    {"field": "passed", "label": "통과", "type": "boolean"},
                    {"field": "detail", "label": "근거", "type": "text"},
                    {"field": "status_rank", "label": "상태 순위", "format": "number"},
                ],
            },
        ],
        "blocks": [
            {"id": "title", "type": "markdown", "body": f"# {title}"},
            {
                "id": "executive_summary",
                "type": "markdown",
                "body": (
                    "## Technical Summary\n\n"
                    f"- **5억원 대비 손실은 실제입니다.** 컷오프 총평가액은 "
                    f"{ledger['endpoint']['total_asset'] / 1_000_000:.1f}백만원으로 "
                    f"총수익률은 {ledger['endpoint']['total_return']:.2%}입니다. "
                    f"다만 7월 20일 인증 기준선 이후에는 "
                    f"{ledger['endpoint']['post_baseline_return']:.2%}입니다.\n"
                    f"- **5억원 원장 대사는 운영 기준을 통과했습니다.** "
                    f"{ledger['order_result_replay']['orders']}개 주문과 "
                    f"{ledger['order_result_replay']['filled_orders']}개 실제 체결을 재생했고, "
                    f"전체 {ledger['reconciliation']['position_rows']}개 종목 수량이 모두 맞습니다. "
                    f"현금 잔차는 {abs(parity['promotion_gate']['opening_cash_difference_abs']):,.0f}원으로 "
                    f"{parity['promotion_gate']['opening_cash_tolerance']:,.0f}원 한도 안입니다.\n"
                    "- **수익개선 후보는 아직 주문 규칙으로 승격하지 않습니다.** "
                    "C_CAP10·C_CAP08은 세 스트레스 시나리오를 통과했지만, R_TREND_REARM은 보수 시나리오에서 실패했습니다.\n"
                    f"- **PAPER 런타임은 안전하지만 전체 시스템은 관측 중입니다.** 안전검사 "
                    f"{readiness['progress']['safety_checks']['passed']}/{readiness['progress']['safety_checks']['total']}, "
                    f"증거검사 {readiness['progress']['evidence_checks']['passed']}/{readiness['progress']['evidence_checks']['total']}입니다. "
                    "BUY/SELL 30건, shadow 10세션, PAPER 및 FINAL 보고서 60세션 전에는 REAL을 승인하지 않습니다."
                ),
            },
            {"id": "headline_metrics", "type": "metric-strip", "cardIds": ["total_loss", "post_baseline", "fill_rate", "position_match"]},
            {
                "id": "ledger_scope",
                "type": "markdown",
                "body": (
                    "## 종료 계좌는 대사됐지만 거래별 실현손익은 낮은 신뢰도로 남습니다\n\n"
                    "총평가액과 종료 보유수량은 브로커 PAPER 스냅샷으로 직접 관측됩니다. "
                    f"KIS 주문행 {broker_history['broker_order_rows']}건을 감사해 잘못된 DB 체결 7건과 "
                    "DB에 없던 브로커 체결 5건을 분석 원장에서 대사했습니다. 체결 가격·수량 근거와 "
                    "현재 및 전체 종목 수량은 100%입니다. 다만 과거 execution 테이블 연결률은 "
                    f"{ledger['data_quality']['execution_table_coverage_of_filled_orders']:.2%}이고 실제 수수료·세금이 "
                    "기록되지 않아 거래별 실현손익은 저신뢰 진단값입니다."
                ),
            },
            {"id": "pnl_chart_block", "type": "chart", "chartId": "pnl_bridge"},
            {
                "id": "order_results",
                "type": "markdown",
                "body": (
                    "## 높은 회전과 낮은 체결률이 손실 확대 가능성을 보여줍니다\n\n"
                    f"전체 {ledger['order_result_replay']['orders']}개 주문 중 실제 체결 이벤트는 "
                    f"{ledger['order_result_replay']['filled_orders']}개이고 체결률은 "
                    f"{ledger['order_result_replay']['terminal_fill_rate']:.2%}입니다. 누적 체결대금은 "
                    f"{ledger['order_result_replay']['fill_notional'] / 1_000_000:.1f}백만원으로 "
                    f"시작자금의 {ledger['order_result_replay']['fill_notional_multiple_of_starting_capital']:.2f}배입니다. "
                    "이 규모는 손실을 종목 선택만의 문제로 해석하기 어렵게 하며 반복 진입·거절·체결비용을 계속 감시해야 한다는 근거입니다."
                ),
                "sourceId": "paper_ledger",
            },
            {"id": "order_chart_block", "type": "chart", "chartId": "order_status"},
            {
                "id": "position_interpretation",
                "type": "markdown",
                "body": (
                    "## 한글 종목명을 복구했고 모든 종목 수량이 일치합니다\n\n"
                    "현재 보유 종목은 코웨이, 한국타이어앤테크놀로지, F&F, 달바글로벌을 주표기로 표시하고 "
                    "종목코드는 보조 표기로 유지합니다. 현재 보유 4/4종목과 전체 23/23종목의 주문결과 재생 수량이 "
                    "브로커 계좌와 일치하며, 시작재고 추정과 수량 조정항목은 0주입니다."
                ),
                "sourceId": "paper_ledger",
            },
            {"id": "position_table_block", "type": "table", "tableId": "position_gaps"},
            {
                "id": "reentry_interpretation",
                "type": "markdown",
                "body": "## 추세 재무장 조건은 최근 방어 후보지만 장기 승자는 아닙니다\n\n추세 재무장 3일 확인은 최근 107거래일 수익률을 -1.75%에서 -0.03%, MDD를 -19.06%에서 -17.16%, 회전율을 45.8배에서 23.7배로 개선했습니다. 그러나 전체 757거래일 수익률은 +22.31%에서 +10.87%로 낮아지고 MDD는 -23.19%에서 -27.06%로 악화됐습니다.",
                "sourceId": "reentry_experiments",
            },
            {"id": "reentry_chart_block", "type": "chart", "chartId": "reentry_returns"},
            {"id": "reentry_table_block", "type": "table", "tableId": "reentry_table"},
            {
                "id": "implementation_result",
                "type": "markdown",
                "body": (
                    "## REAL 사전 게이트는 현재 전체 완료를 거부합니다\n\n"
                    f"현재 준비도는 안전검사 {readiness['progress']['safety_checks']['passed']}/"
                    f"{readiness['progress']['safety_checks']['total']}, 증거검사 "
                    f"{readiness['progress']['evidence_checks']['passed']}/"
                    f"{readiness['progress']['evidence_checks']['total']}입니다. 전체 증거가 완료되기 전에는 "
                    "배치와 직접 REAL 주문 경로가 모두 브로커 초기화 전에 실패합니다."
                ),
                "sourceId": "system_readiness",
            },
            {
                "id": "eod_report_integrity",
                "type": "markdown",
                "body": (
                    "## 최근 완료 세션 보고서는 운영 무결성을 충족합니다\n\n"
                    f"{final_daily['report_date']} 최종 일별 보고서는 주문 {final_daily['trading']['order_count']}건과 "
                    f"체결 실행 {final_daily['trading']['execution_count']}건을 읽었습니다. "
                    "데이터 신선도·위험점검·주문 대사·운영 무결성이 각각 100%이고 미종결 주문은 "
                    f"{final_daily['trading']['open_order_count']}건이라 FINAL·READY 증거로 인정됩니다."
                ),
                "sourceId": "final_daily_report",
            },
            {"id": "shadow_gate_block", "type": "table", "tableId": "shadow_gate"},
            {
                "id": "recommendations",
                "type": "markdown",
                "body": (
                    "## Recommended Next Steps\n\n"
                    "1. **현재 PAPER 주문 규칙을 유지합니다.** C_CAP10·C_CAP08은 비상 위험후보로만 보존하고 주문 규칙에는 아직 반영하지 않습니다.\n"
                    f"2. **체결 표본을 자동 누적합니다.** 현재 BUY {stress['execution_samples']['BUY']['orders']}/30, "
                    f"SELL {stress['execution_samples']['SELL']['orders']}/30이며 동일 스트레스 조건으로 다시 평가합니다.\n"
                    f"3. **shadow와 운영기간을 채웁니다.** shadow {readiness['progress']['shadow_sessions']['completed']}/10, "
                    f"완료 PAPER {readiness['progress']['paper_sessions']['completed']}/60, "
                    f"FINAL·READY 보고서 {readiness['progress']['final_daily_reports']['completed']}/60을 날짜별로 대조합니다.\n"
                    "4. **매 EOD 원장과 브로커 감사를 재생성합니다.** 실패하면 성공 처리하지 않고 5분 간격 재시도 경로로 보냅니다.\n"
                    "5. **REAL은 실행하지 않습니다.** 전체 준비도, 기존 KPI, 환경 잠금, 수동 승인을 모두 통과하기 전에는 실행을 거부합니다."
                ),
            },
            {
                "id": "methodology",
                "type": "markdown",
                "body": (
                    "## 원장과 준비도는 원본을 바꾸지 않는 방식으로 계산했습니다\n\n"
                    "주문 원장은 DB 기록, KIS PAPER 일별 주문 전체 페이지, executions, 잔고 스냅샷을 날짜와 브로커 주문번호로 결합합니다. "
                    "KIS가 미체결로 확인한 DB FILLED는 분석 레이어에서만 EXPIRED_UNFILLED로 분류하며 원본 DB와 계좌는 수정하지 않습니다. "
                    "주문결과 리플레이는 관측된 체결·부분체결·거절·취소만 재생하고, 준비도는 완료 세션 날짜와 같은 날짜의 FINAL·READY 보고서를 교차 검증합니다."
                ),
            },
            {
                "id": "caveats",
                "type": "markdown",
                "body": (
                    "## Caveats & Assumptions\n\n"
                    "- 7월 22일 값은 13:10 KST 컷오프라 15:30 최종 보고서에서 달라질 수 있습니다.\n"
                    "- 총평가액과 5억원 대비 손익은 브로커 스냅샷 직접 관측값이지만 종목별 실현손익은 과거 execution 누락과 실제 비용 미기록 때문에 저신뢰입니다.\n"
                    "- 391,449원 현금 잔차는 0.10% 허용한도 안이지만 정확한 입출금·수수료 명세가 없어 원인을 특정하지 않습니다.\n"
                    "- 7월 21일 이전 UNKNOWN 범위는 전환 직전·직후 현금 연속성을 근거로 동일 PAPER 계보로 추정했습니다.\n"
                    "- 체결 스트레스 표본은 BUY 5건, SELL 4건으로 작고 전략 승격이나 REAL 승인 근거가 아닙니다.\n"
                    "- 전체 완료 판정은 실제 10 shadow 세션과 60 완료 PAPER 세션·60 FINAL 보고서가 쌓이기 전까지 유지되지 않습니다."
                ),
            },
            {
                "id": "further_questions",
                "type": "markdown",
                "body": (
                    "## Further Questions\n\n"
                    "- 391,449원 현금 잔차를 입출금·실제 수수료·평가시점 중 어느 항목으로 설명할 수 있는가?\n"
                    "- BUY/SELL 각 30건 이후에도 C_CAP10과 C_CAP08이 Wilson 하한 시나리오를 통과하는가?\n"
                    "- 10세션 shadow에서 R_TREND_REARM이 실제 재진입 후보를 만들고도 현행 규칙보다 낙폭과 회전율을 줄이는가?\n"
                    "- 60세션 동안 FINAL 보고서 연속성과 무중단 복구 증거가 유지되는가?"
                ),
            },
        ],
    },
    "snapshot": {
        "version": 1,
        "generatedAt": generated_at,
        "status": "ready",
        "datasets": {
            "headline": headline,
            "pnl_bridge": pnl_rows,
            "order_status": order_status_rows,
            "position_gaps": position_dataset,
            "reentry_results": reentry_rows,
            "reentry_table": reentry_table_rows,
            "implementation_result": implementation_result,
            "shadow_gate": gate_rows,
        },
    },
    "sources": sources,
}

def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


daily_output = SYSTEM_REPORT_DIR / "daily" / f"{final_daily['report_date']}.json"
latest_output = SYSTEM_REPORT_DIR / "latest.json"
for output in (daily_output, latest_output, COMPAT_OUTPUT):
    _atomic_write_json(output, artifact)
print(latest_output)
