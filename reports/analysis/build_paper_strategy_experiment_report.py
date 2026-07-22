"""Build the canonical Data Analytics report artifact for PAPER experiments."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
EXP_ROOT = ROOT / "reports" / "analysis" / "paper_strategy_experiments"
OUTPUT = ROOT / "reports" / "analysis" / "paper_strategy_experiment_artifact_2026-07-22.json"

full = json.loads((EXP_ROOT / "full" / "metrics.json").read_text(encoding="utf-8"))
recent = json.loads((EXP_ROOT / "pass_only" / "metrics.json").read_text(encoding="utf-8"))
returns = pd.read_csv(EXP_ROOT / "full" / "daily_returns.csv", index_col=0, parse_dates=True)
events = pd.read_csv(EXP_ROOT / "full" / "events.csv")
events["date"] = pd.to_datetime(events["date"])
labels = {row["code"]: row["label"] for row in full["metadata"]["variant_definitions"]}

display_codes = [
    "A0_LEGACY",
    "X_CAP15_ONLY",
    "A_CURRENT",
    "X_COOLDOWN5",
    "B_EQUAL",
    "C_CAP10",
    "C_CAP08",
    "D_BAND20",
    "E_VOL_RISK",
]

candidate_rows = []
for code in display_codes:
    full_row = full["summary"][code]
    recent_row = recent["summary"][code]
    candidate_rows.append(
        {
            "variant": code,
            "candidate": labels[code],
            "full_total_return": full_row["total_return"],
            "full_cagr": full_row["cagr"],
            "full_mdd": full_row["max_drawdown"],
            "full_sharpe": full_row["sharpe_zero_rf"],
            "full_cost": full_row["total_cost_ratio"],
            "annual_turnover": full_row["annualized_turnover"],
            "average_exposure": full_row["average_exposure"],
            "recent_total_return": recent_row["total_return"],
            "recent_mdd": recent_row["max_drawdown"],
            "recent_sharpe": recent_row["sharpe_zero_rf"],
        }
    )

equity = (1 + returns).cumprod()
weekly = equity[["A0_LEGACY", "A_CURRENT", "C_CAP10", "C_CAP08"]].resample("W-FRI").last()
equity_rows = []
for date, row in weekly.iterrows():
    for code in weekly.columns:
        equity_rows.append(
            {
                "date": date.date().isoformat(),
                "variant": code,
                "candidate": labels[code],
                "equity_multiple": float(row[code]),
            }
        )

risk_rows = [
    {
        "variant": row["variant"],
        "candidate": row["candidate"],
        "mdd_abs": abs(row["full_mdd"]),
        "cagr": row["full_cagr"],
        "average_exposure": row["average_exposure"],
    }
    for row in candidate_rows
    if row["variant"] != "A0_LEGACY"
]

stop_rows = []
for code in ["A_CURRENT", "X_COOLDOWN5", "B_EQUAL", "C_CAP10", "C_CAP08", "D_BAND20", "E_VOL_RISK"]:
    frame = events[events["variant"].eq(code)].sort_values(["ticker", "date"])
    stops = frame[frame["reason"].isin(["HARD_STOP", "TRAILING_STOP"])]
    gaps = []
    for _, stop in stops.iterrows():
        next_entry = frame[
            frame["ticker"].eq(stop["ticker"])
            & frame["date"].gt(stop["date"])
            & frame["reason"].eq("ENTRY")
        ]
        if not next_entry.empty:
            gaps.append((next_entry.iloc[0]["date"] - stop["date"]).days)
    stop_rows.append(
        {
            "variant": code,
            "candidate": labels[code],
            "stops": int(len(stops)),
            "reentry_within_5d": int(sum(gap <= 5 for gap in gaps)),
            "median_reentry_days": float(pd.Series(gaps).median()) if gaps else None,
            "annual_turnover": full["summary"][code]["annualized_turnover"],
            "total_cost": full["summary"][code]["total_cost_ratio"],
        }
    )

current = full["summary"]["A_CURRENT"]
current_recent = recent["summary"]["A_CURRENT"]
headline = [
    {
        "full_cagr": current["cagr"],
        "full_mdd": current["max_drawdown"],
        "recent_return": current_recent["total_return"],
        "cost_ratio": current["total_cost_ratio"],
        "pbo": full["robustness"]["cscv"]["pbo"],
        "dsr_probability": full["robustness"]["deflated_sharpe_probability"]["A_CURRENT"],
    }
]

source_sql = """WITH ranked AS (
  SELECT r.*, ROW_NUMBER() OVER (
    PARTITION BY r.analysis_month
    ORDER BY CASE r.status_code WHEN 'PUBLISHED' THEN 0 WHEN 'PASS' THEN 1 ELSE 2 END,
             r.run_version DESC, r.id DESC
  ) AS rn
  FROM fa_analysis_runs r
  JOIN strategies s ON s.id = r.strategy_id
  WHERE s.name = 'aggressive'
    AND r.status_code IN ('PASS', 'WARNING', 'PUBLISHED')
)
SELECT r.id AS run_id, r.analysis_month, r.cutoff_date, r.effective_date,
       r.status_code, c.stock_code, c.fa_score
FROM ranked r
JOIN fa_company_results c ON c.run_id = r.id
WHERE r.rn = 1 AND c.is_selected = TRUE AND c.is_eligible = TRUE
ORDER BY r.effective_date, c.stock_code;

SELECT stock_code, price_date, close
FROM wics_constituent_prices
WHERE close > 0
ORDER BY price_date, stock_code;"""

sources = [
    {
        "id": "experiment_combined",
        "label": "PAPER 전략 후보 전체·최근 구간 분석 노트북",
        "path": "reports/analysis/paper_strategy_experiments_2026-07-22.ipynb",
        "query": {
            "engine": "PostgreSQL",
            "language": "sql",
            "description": "동일한 FA 선택·KOSPI/TA 조건·거래비용으로 전체 및 PASS/PUBLISHED 후보를 비교",
            "sql": source_sql,
            "executed_at": full["metadata"]["generated_at"],
            "tables_used": [
                "reports/analysis/paper_strategy_experiments/full/metrics.json",
                "reports/analysis/paper_strategy_experiments/pass_only/metrics.json",
                "reports/analysis/paper_strategy_experiments/full/daily_returns.csv",
                "reports/analysis/paper_strategy_experiments/full/events.csv",
            ],
            "filters": [
                "strategy=aggressive",
                "full window=2023-05-31..2026-07-09",
                "recent window=PASS/PUBLISHED selections only, 2026-01-30..2026-07-09",
                "REAL excluded",
            ],
            "metric_definitions": [
                "총수익률 = 일별 비용 차감 수익률의 기하 누적 - 1",
                "MDD = 누적 자산의 직전 고점 대비 최대 하락률",
                "연환산 회전율 = 일평균 절대 비중 매매량 × 252",
                "비용률 = 매수 0.115%, 매도 0.295%를 일별 비중 변화에 적용한 누적값",
            ],
        },
    },
    {
        "id": "experiment_full",
        "label": "PAPER 전략 후보 전체 구간 리플레이",
        "path": "reports/analysis/paper_strategy_experiments/full/metrics.json",
        "query": {
            "engine": "PostgreSQL",
            "language": "sql",
            "description": "WARNING를 포함한 39개 월별 선택 실행과 757거래일 가격을 사용한 후보 리플레이",
            "sql": source_sql,
            "executed_at": full["metadata"]["generated_at"],
            "tables_used": [
                "fa_analysis_runs",
                "fa_company_results",
                "wics_constituent_prices",
            ],
            "filters": [
                "strategy=aggressive",
                "status in PASS, WARNING, PUBLISHED",
                "period=2023-05-31..2026-07-09",
            ],
            "metric_definitions": [
                "주간 누적 자산 배수 = 일별 비용 차감 수익률을 기하 누적한 뒤 금요일 기준 마지막 값",
                "후보별 수익과 위험은 동일한 데이터·비용 가정으로 계산",
            ],
        },
    },
    {
        "id": "paper_actual",
        "label": "PAPER 5억 원금 성과 진단",
        "path": "reports/analysis/paper_performance_diagnostic_2026-07-22.ipynb",
    },
]

artifact = {
    "surface": "report",
    "manifest": {
        "version": 1,
        "surface": "report",
        "title": "PAPER 전략 수정 후보 실험 결과",
        "description": "전체·최근 구간의 수익, 낙폭, 비용, 회전율과 과최적화 위험을 비교한 의사결정 보고서",
        "generatedAt": full["metadata"]["generated_at"],
        "sources": sources,
        "cards": [
            {
                "id": "full_cagr",
                "dataset": "headline",
                "description": "현재 규칙 근사의 전체 757거래일 연복리 수익률",
                "sourceId": "experiment_full",
                "metrics": [
                    {"label": "전체 CAGR", "field": "full_cagr", "format": "percent"},
                    {"label": "DSR 확률", "field": "dsr_probability", "format": "percent"},
                ],
            },
            {
                "id": "full_mdd",
                "dataset": "headline",
                "description": "현재 규칙 근사의 전체 구간 최대낙폭",
                "sourceId": "experiment_full",
                "metrics": [
                    {"label": "전체 MDD", "field": "full_mdd", "format": "percent", "signed": True},
                    {"label": "PBO", "field": "pbo", "format": "percent"},
                ],
            },
            {
                "id": "recent_return",
                "dataset": "headline",
                "description": "PASS/PUBLISHED 107거래일에서 현재 규칙 근사의 총수익률",
                "sourceId": "experiment_combined",
                "metrics": [
                    {"label": "최근 총수익률", "field": "recent_return", "format": "percent", "signed": True},
                ],
            },
            {
                "id": "cost_ratio",
                "dataset": "headline",
                "description": "전체 구간의 고정 비용 가정 누적값",
                "sourceId": "experiment_full",
                "metrics": [
                    {"label": "누적 비용률", "field": "cost_ratio", "format": "percent"},
                ],
            },
        ],
        "charts": [
            {
                "id": "equity_curve",
                "title": "후보별 누적 자산 배수",
                "subtitle": "2023년 5월 31일~2026년 7월 9일, 주간 마지막 값",
                "type": "line",
                "intent": "trend",
                "dataset": "equity_curve",
                "sourceId": "experiment_full",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "날짜"},
                    "y": {"field": "equity_multiple", "type": "quantitative", "label": "누적 자산 배수", "format": "number"},
                    "color": {"field": "candidate", "type": "nominal", "label": "후보"},
                    "tooltip": [
                        {"field": "candidate", "type": "text", "label": "후보"},
                        {"field": "equity_multiple", "type": "quantitative", "label": "자산 배수", "format": "number"},
                    ],
                },
                "valueFormat": "number",
                "layout": "full",
                "settings": {"legend": "bottom", "valueLabels": "none"},
                "palette": {"kind": "categorical"},
            },
            {
                "id": "risk_return",
                "title": "연복리 수익률과 최대낙폭",
                "subtitle": "원 크기는 평균 투자비중, 기존 연구 A0는 제외",
                "type": "scatter",
                "intent": "relationship",
                "dataset": "risk_return",
                "sourceId": "experiment_full",
                "encodings": {
                    "x": {"field": "mdd_abs", "type": "quantitative", "label": "MDD 절대값", "format": "percent"},
                    "y": {"field": "cagr", "type": "quantitative", "label": "CAGR", "format": "percent"},
                    "size": {"field": "average_exposure", "type": "quantitative", "label": "평균 투자비중", "format": "percent"},
                    "tooltip": [
                        {"field": "candidate", "type": "text", "label": "후보"},
                        {"field": "average_exposure", "type": "quantitative", "label": "평균 투자비중", "format": "percent"},
                    ],
                },
                "layout": "full",
                "settings": {"valueLabels": "none"},
                "palette": {"kind": "categorical"},
            },
        ],
        "tables": [
            {
                "id": "candidate_table",
                "title": "후보별 전체·최근 성과",
                "subtitle": "전체 757거래일과 PASS/PUBLISHED 107거래일 비교",
                "dataset": "candidate_summary",
                "sourceId": "experiment_combined",
                "defaultSort": {"field": "full_sharpe", "direction": "desc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "candidate", "label": "후보", "type": "text"},
                    {"field": "full_total_return", "label": "전체 수익", "format": "percent", "movement": True},
                    {"field": "full_mdd", "label": "전체 MDD", "format": "percent", "movement": True},
                    {"field": "full_sharpe", "label": "전체 Sharpe", "format": "number"},
                    {"field": "full_cost", "label": "비용률", "format": "percent"},
                    {"field": "annual_turnover", "label": "연회전", "format": "number", "unit": "x"},
                    {"field": "average_exposure", "label": "평균 투자", "format": "percent"},
                    {"field": "recent_total_return", "label": "최근 수익", "format": "percent", "movement": True},
                    {"field": "recent_mdd", "label": "최근 MDD", "format": "percent", "movement": True},
                ],
            },
            {
                "id": "stop_table",
                "title": "손절·재진입과 회전율",
                "subtitle": "전체 구간, 동일 종목의 다음 진입까지 달력일 기준",
                "dataset": "stop_reentry",
                "sourceId": "experiment_full",
                "defaultSort": {"field": "stops", "direction": "desc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "candidate", "label": "후보", "type": "text"},
                    {"field": "stops", "label": "손절", "format": "number"},
                    {"field": "reentry_within_5d", "label": "5일 내 재진입", "format": "number"},
                    {"field": "median_reentry_days", "label": "재진입 중앙값", "format": "number", "unit": "일"},
                    {"field": "annual_turnover", "label": "연회전", "format": "number", "unit": "x"},
                    {"field": "total_cost", "label": "비용률", "format": "percent"},
                ],
            },
        ],
        "blocks": [
            {"id": "title", "type": "markdown", "body": "# PAPER 전략 수정 후보 실험 결과"},
            {
                "id": "executive_summary",
                "type": "markdown",
                "body": "## Executive Summary\n\n- **지금 PAPER 설정을 변경할 후보는 없습니다.** 현재 규칙 근사는 전체 구간에서 +22.31%였지만 최근 107거래일에서 -1.75%였고, 모든 운영 가능 후보가 최근 구간에서 손실이었습니다.\n- **8~10% 종목 상한은 낙폭을 줄이지만 수익 개선은 아닙니다.** 전체 MDD가 -16.73%와 -13.66%로 줄었지만 평균 투자비중도 33.7%와 27.3%로 낮아졌습니다.\n- **비용의 핵심은 리밸런싱 밴드보다 손절·재진입 반복입니다.** 현재 근사 규칙은 123회 손절 중 92회가 5일 안에 다시 진입했고 누적 비용률은 13.16%였습니다.\n- **결론의 신뢰도는 제한적입니다.** 전체 선택 실행의 82.1%가 WARNING이고 가격은 7월 9일에서 끝나며, 현재 규칙의 DSR 확률은 60.4%, 후보군 PBO는 37.1%입니다.",
            },
            {"id": "headline_metrics", "type": "metric-strip", "cardIds": ["full_cagr", "full_mdd", "recent_return", "cost_ratio"]},
            {
                "id": "scope",
                "type": "markdown",
                "body": "## 비교 기준과 데이터 범위\n\n모든 후보는 동일한 월별 FA 선택, 일별 KOSPI/TA 조건, 매수 0.115%·매도 0.295% 비용 가정으로 비교했습니다. A0는 기존 연구 재현용이며 종목 상한과 가격 손절이 없어 운영 후보가 아닙니다. 전체 구간은 방향성 연구용, PASS/PUBLISHED 107거래일은 최근 스트레스 확인용입니다.",
                "sourceId": "experiment_combined",
            },
            {
                "id": "equity_interpretation",
                "type": "markdown",
                "body": "## 높은 과거수익 후보는 운영 규칙을 빠뜨렸습니다\n\n기존 연구 A0가 가장 높지만 실제 운영의 15% 종목 상한과 가격 손절을 반영하지 않습니다. 15% 상한만 적용한 진단 후보는 현재 규칙보다 비용과 수익이 좋았지만 MDD와 최악의 날 손실이 악화됐습니다. 이는 현재 손절 경로가 성과를 훼손한다는 증거이지 손절 제거의 근거는 아닙니다.",
                "sourceId": "experiment_full",
            },
            {"id": "equity_chart_block", "type": "chart", "chartId": "equity_curve"},
            {
                "id": "risk_interpretation",
                "type": "markdown",
                "body": "## 작은 종목 상한은 알파보다 현금 효과가 큽니다\n\n10%와 8% 상한은 전체 MDD를 낮췄지만 평균 투자비중도 크게 낮췄습니다. 위험 예산을 줄이는 수단으로는 유효하지만, 동일 위험에서 더 나은 수익을 만드는 전략 개선으로 해석하면 안 됩니다.",
                "sourceId": "experiment_full",
            },
            {"id": "risk_chart_block", "type": "chart", "chartId": "risk_return"},
            {
                "id": "churn_interpretation",
                "type": "markdown",
                "body": "## 손절 뒤 빠른 재진입이 비용을 지배합니다\n\n20% 밴드는 연환산 회전율을 21.4배에서 20.6배로만 낮췄습니다. 현재 근사 규칙의 손절 뒤 재진입 간격 중앙값은 1일이었습니다. 단순 5거래일 쿨다운은 회전율을 줄였지만 전체·최근 성과를 개선하지 못했고, 더 강한 손절도 최근 -7.27%로 악화됐습니다.",
                "sourceId": "experiment_combined",
            },
            {"id": "stop_table_block", "type": "table", "tableId": "stop_table"},
            {
                "id": "candidate_interpretation",
                "type": "markdown",
                "body": "## 최근 구간에서는 모든 운영 후보가 탈락합니다\n\n동일 비중과 넓은 밴드는 현재 규칙과 사실상 같았고, 작은 상한은 낙폭만 줄였습니다. 최근 PASS/PUBLISHED 구간에서 운영 가능 후보가 모두 손실이므로, 현재 데이터로 최고 후보를 고르는 대신 잘못된 후보를 제거하는 데 결과를 사용해야 합니다.",
                "sourceId": "experiment_combined",
            },
            {"id": "candidate_table_block", "type": "table", "tableId": "candidate_table"},
            {
                "id": "recommendations",
                "type": "markdown",
                "body": "## Recommended Next Steps\n\n1. **PAPER 파라미터는 유지합니다.** REAL은 계속 제외합니다.\n2. **최신 가격과 운영 체결 규칙을 리플레이에 넣습니다.** 정수 주식, 장중 고점, 부분체결, 거절, 모호한 주문 결과를 포함해야 합니다.\n3. **다음 손절 실험은 히스테리시스 방식으로 제한합니다.** 손절 뒤 기존 진입 조건보다 강한 재확인 조건을 요구하고 단순 쿨다운·손절 강화는 제외합니다.\n4. **8~10% 상한은 위험 예산 시나리오로만 유지합니다.** 목표 MDD와 허용 수익 저하를 먼저 정한 뒤 판단합니다.\n5. **5억 원금 손익 원장을 복원합니다.** 백테스트는 현재 -5.95% 손실의 실제 주문·종목별 원인을 대신 설명하지 못합니다.",
            },
            {
                "id": "questions",
                "type": "markdown",
                "body": "## Further Questions\n\n- 최신 가격과 실제 PAPER 주문 상태를 반영하면 손절·재진입 횟수가 얼마나 달라지는가?\n- 현재 -5.95% 손실 중 종목 선택, 청산, 거절·재주문, 비용이 각각 얼마인가?\n- 허용 가능한 PAPER MDD와 평균 투자비중 하한을 얼마로 정할 것인가?",
            },
            {
                "id": "caveats",
                "type": "markdown",
                "body": "## Caveats & Assumptions\n\n- 전체 구간 데이터 품질은 LOW이고 최근 구간은 짧은 표본 때문에 MEDIUM입니다.\n- 일별 종가와 비례 비중은 장중·정수주식·부분체결을 근사할 뿐입니다.\n- 고정 비용률은 실제 세금 누락과 주문 실패 비용을 완전히 반영하지 못합니다.\n- 이 보고서는 PAPER 분석용이며 REAL 실행 근거가 아닙니다.",
            },
        ],
    },
    "snapshot": {
        "version": 1,
        "generatedAt": full["metadata"]["generated_at"],
        "status": "partial",
        "accessIssues": [
            {
                "id": "stale_prices",
                "scope": "strategy experiment",
                "sourceId": "experiment_full",
                "dataset": "candidate_summary",
                "message": "구성종목 가격 이력이 2026-07-09에서 끝나 2026-07-22 현재 PAPER 상태까지 검증하지 못했습니다.",
            },
            {
                "id": "execution_parity_gap",
                "scope": "execution replay",
                "sourceId": "experiment_combined",
                "dataset": "stop_reentry",
                "message": "장중 손절, 정수 주식, 부분체결, 거절과 모호한 주문 결과를 일별 비중 리플레이가 완전히 재현하지 못합니다.",
            },
        ],
        "datasets": {
            "headline": headline,
            "candidate_summary": candidate_rows,
            "equity_curve": equity_rows,
            "risk_return": risk_rows,
            "stop_reentry": stop_rows,
        },
    },
    "sources": sources,
}

OUTPUT.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
print(OUTPUT)
