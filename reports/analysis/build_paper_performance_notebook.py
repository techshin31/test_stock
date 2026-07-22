"""Build the reproducible PAPER performance diagnostic notebook."""

from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "reports" / "analysis" / "paper_performance_diagnostic_2026-07-22.ipynb"


def code(source: str):
    return nbf.v4.new_code_cell(source.strip())


def markdown(source: str):
    return nbf.v4.new_markdown_cell(source.strip())


nb = nbf.v4.new_notebook()
nb["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3"},
}
nb["cells"] = [
    markdown(
        """
# PAPER 수익률·손실 진단 — 2026-07-22

## TL;DR

- 최초 원금이 5억 원이고 입출금이 없었다면, 현재 손실은 약 6%로 짧은 운용기간을 감안할 때 위험 신호다.
- 공식 PAPER 기준선은 2026-07-20에 463,025,590원으로 늦게 생성되어, 그 이전 손실 약 36,974,410원을 공식 수익률에서 제외한다.
- 현재 보유 종목의 미실현 손익은 순이익이므로 총손실의 주된 원인은 과거 청산손익·초기 평가손실·비용 구간에 있다.
- 2026-07-09에는 주문 240건, 체결금액 약 19.5억 원, 거절 192건이 기록됐다. 수익률을 높이기 전에 회전율과 주문 신뢰성을 먼저 통제해야 한다.
"""
    ),
    markdown(
        """
## Context & Methods

분석 범위는 PAPER 계좌 `***9904-01`, aggressive 전략이다. 로컬 계좌 시계열·공식 기준선·현재 대시보드 상태를 대사하고, PostgreSQL의 주문/체결 이력을 일자별로 집계한다. 사용자가 제공한 최초 원금 500,000,000원은 입출금이 없다는 가정 아래 사용한다.
"""
    ),
    code(
        """
from pathlib import Path
from datetime import datetime
import csv, json, os

import pandas as pd
import psycopg
from dotenv import load_dotenv

ROOT = Path.cwd()
if not (ROOT / "logs" / "paper").exists():
    ROOT = Path.cwd().parents[1]

STARTING_CAPITAL = 500_000_000.0
ACCOUNT_SCOPE = "***9904-01"
STRATEGY = "aggressive"

state = json.loads((ROOT / "logs/paper/dashboard_state.json").read_text(encoding="utf-8"))
baseline = json.loads((ROOT / "reports/promotion/paper/baseline.json").read_text(encoding="utf-8"))
history = pd.read_csv(ROOT / "logs/paper/account_history.csv")
history["date"] = history["timestamp"].map(lambda value: datetime.fromisoformat(str(value)).date())

analysis_timestamp = state["updated_at"]
current_total = float(state["total_eval"])
baseline_total = float(baseline["baseline_total_asset"])

summary = pd.DataFrame([
    {"metric": "최초 원금", "value_krw": STARTING_CAPITAL, "return_vs_start": 0.0},
    {"metric": "공식 PAPER 기준선", "value_krw": baseline_total, "return_vs_start": baseline_total / STARTING_CAPITAL - 1},
    {"metric": "현재 평가액", "value_krw": current_total, "return_vs_start": current_total / STARTING_CAPITAL - 1},
])
summary
"""
    ),
    markdown("## Results"),
    code(
        """
positions = pd.DataFrame(state["positions"])
positions["market_value"] = positions["qty"] * positions["current_price"]
positions["cost_basis"] = positions["qty"] * positions["avg_price"]
positions["unrealized_pnl"] = positions["market_value"] - positions["cost_basis"]
positions["weight"] = positions["market_value"] / current_total

assert abs(positions["market_value"].sum() + float(state["cash"]) - current_total) < 2
assert abs(positions["unrealized_pnl"].sum() - float(state["unrealized_pnl"])) < 2

implied_realized_and_other = current_total - STARTING_CAPITAL - positions["unrealized_pnl"].sum()
capital_bridge = pd.DataFrame([
    {"component": "최초 원금", "amount_krw": STARTING_CAPITAL},
    {"component": "기준선 이전 차이", "amount_krw": baseline_total - STARTING_CAPITAL},
    {"component": "기준선 이후 변화", "amount_krw": current_total - baseline_total},
    {"component": "현재 평가액", "amount_krw": current_total},
])

print(f"분석 시각: {analysis_timestamp} KST")
print(f"5억 대비: {current_total - STARTING_CAPITAL:,.0f}원 ({current_total / STARTING_CAPITAL - 1:.2%})")
print(f"공식 기준선 대비: {current_total - baseline_total:,.0f}원 ({current_total / baseline_total - 1:.2%})")
print(f"현재 미실현 손익: {positions['unrealized_pnl'].sum():,.0f}원")
print(f"암시된 과거 청산손익·비용·초기차이: {implied_realized_and_other:,.0f}원")
capital_bridge
"""
    ),
    code(
        """
name_map = {
    "021240.KS": "코웨이",
    "161390.KS": "한국타이어앤테크놀로지",
    "383220.KS": "F&F",
    "483650.KS": "달바글로벌",
}
positions["name"] = positions["ticker"].map(name_map).fillna(positions["ticker"])
positions[["name", "ticker", "qty", "avg_price", "current_price", "market_value", "weight", "unrealized_pnl", "profit_rate"]].sort_values("unrealized_pnl")
"""
    ),
    code(
        """
daily = history.groupby("date", as_index=False).agg(
    first_total=("total_asset", "first"),
    last_total=("total_asset", "last"),
    low_total=("total_asset", "min"),
    high_total=("total_asset", "max"),
    observations=("total_asset", "size"),
)
daily["close_change"] = daily["last_total"].pct_change()
daily["return_vs_500m"] = daily["last_total"] / STARTING_CAPITAL - 1
daily
"""
    ),
    code(
        """
load_dotenv(ROOT / ".env")
conn = psycopg.connect(
    host=os.getenv("POSTGRES_HOST"),
    port=os.getenv("POSTGRES_PORT"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD"),
    dbname=os.getenv("POSTGRES_DB"),
)

order_sql = '''
SELECT (o.created_at AT TIME ZONE 'Asia/Seoul')::date AS trade_date,
       COUNT(*) AS orders,
       COUNT(*) FILTER (WHERE o.order_status_code = 'FILLED') AS filled,
       COUNT(*) FILTER (WHERE o.order_status_code = 'REJECTED') AS rejected,
       COUNT(*) FILTER (WHERE o.order_status_code = 'CANCELLED') AS cancelled,
       SUM(COALESCE(o.filled_qty, 0) * COALESCE(o.avg_fill_price, 0)) AS filled_notional,
       COUNT(DISTINCT REPLACE(o.symbol, '.KS', '')) AS symbols
FROM orders o
JOIN strategies s ON s.id = o.strategy_id
WHERE s.name = %s
GROUP BY 1
ORDER BY 1
'''

with conn, conn.cursor() as cur:
    cur.execute(order_sql, (STRATEGY,))
    order_rows = cur.fetchall()

orders_daily = pd.DataFrame(order_rows, columns=[
    "trade_date", "orders", "filled", "rejected", "cancelled", "filled_notional", "symbols"
])
orders_daily["filled_notional"] = orders_daily["filled_notional"].astype(float)
orders_daily["turnover_vs_start"] = orders_daily["filled_notional"] / STARTING_CAPITAL
orders_daily
"""
    ),
    markdown(
        """
## Key Findings

1. **리포트 기준선 왜곡:** 공식 기준선은 최초 원금보다 약 3,697만 원 낮다. 따라서 공식 플러스 수익률과 최초 원금 대비 손실은 동시에 성립한다.
2. **현재 종목이 총손실의 주범은 아님:** 현재 4종목의 미실현 손익 합계는 플러스다. 총손실 중 더 큰 부분은 기준선 이전·청산된 포지션·비용 구간에 있다.
3. **주문 회전율이 과도했음:** 7월 9일 체결금액은 원금의 약 3.9배였고 주문 거절도 192건이었다. 이 정도 주문 밀도는 전략 신호보다 실행 오류와 잦은 리밸런싱의 영향을 키운다.
4. **위험 한도가 운용기간 대비 느슨함:** 현재 종목당 최대 15%, 손절 10%, 트레일링 8%, 일손실 3%다. 짧은 기간에 누적 6% 손실을 허용하는 조합으로는 원금 방어가 늦다.
5. **현재도 청산 신뢰성 문제가 있음:** F&F 트레일링 스톱 주문이 모의 API 오류 뒤 거절 처리되어, 위험 신호가 실제 포지션 축소로 이어지지 않았다.
"""
    ),
    markdown(
        """
## Recommendations

1. **수익 극대화보다 신규 진입 일시정지를 우선:** 매도·위험청산은 유지하고 신규 매수만 멈춘 상태에서 과거 손익을 복원한다.
2. **성과 기준을 이중화:** 인증된 PAPER 기준선은 보존하되, 별도로 `최초 원금 5억` 기준 누적손익·MDD를 모든 일일 리포트에 추가한다.
3. **주문 예산을 제한:** 동일 종목 당일 재주문 횟수, 일일 총 체결금액/원금 비율, 리밸런싱 최소 괴리폭을 둔다. 주문 API 불명 결과는 청산 우선 경로로 재조회한다.
4. **위험 파라미터 후보를 먼저 검증:** 종목당 8~10%, 일손실 1~1.5%, 포트폴리오 고점 대비 5% 신규진입 중지 후보를 워크포워드로 비교한다. 손절·트레일링 수치는 종목 변동성에 맞춘다.
5. **전략 변경 승인 기준:** 거래비용 포함, 분리된 검증구간, 최소 표본 길이, PBO/Deflated Sharpe를 통과한 후보만 PAPER에 반영한다.

백테스트 후보를 많이 시험한 뒤 최고 결과만 고르면 과최적화 가능성이 커진다. 참고: [Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/Papers.cfm?abstract_id=2326253), [Deflated Sharpe Ratio](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551).
"""
    ),
    markdown(
        """
## Further Questions

- 최초 5억 원 이후 입출금·수동 주문이 전혀 없었는가?
- 7월 9일 이전 계좌 원장과 체결 원본을 받을 수 있는가?
- 허용 가능한 PAPER 최대낙폭과 일손실 한도는 얼마인가?
"""
    ),
    markdown(
        """
## Caveats & Assumptions

- 5억 원은 사용자 제공값이며, 입출금이 없다고 가정했다.
- 신뢰 가능한 파일 시계열은 7월 13일부터, 인증 기준선은 7월 20일부터다. 7월 9~10일 DB 기록에는 과거 스코프 마이그레이션 전 `UNKNOWN` 값과 일부 0원 잔고가 섞여 있다.
- DB의 수수료·세금은 0으로 기록되어 실제 비용 귀속을 확정할 수 없다.
- 현재 평가는 장중 스냅샷이며 가격에 따라 변한다.
"""
    ),
]

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
NotebookClient(
    nb,
    timeout=120,
    kernel_name="python3",
    resources={"metadata": {"path": str(ROOT)}},
).execute()
nbf.write(nb, OUTPUT)
print(OUTPUT)
