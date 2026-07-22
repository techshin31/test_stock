"""Build and execute the PAPER ledger/reentry decision notebook."""

from pathlib import Path

import nbformat as nbf
from nbclient import NotebookClient


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "reports" / "analysis" / "paper_ledger_reentry_2026-07-22.ipynb"


def markdown(source: str):
    return nbf.v4.new_markdown_cell(source.strip())


def code(source: str):
    return nbf.v4.new_code_cell(source.strip())


nb = nbf.v4.new_notebook()
nb["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3"},
}
nb["cells"] = [
    markdown(
        """
# PAPER 원장 복원·주문결과 리플레이·재진입 실험

## 결론

- 5억원 대비 손실은 컷오프 총평가액으로 직접 확인되는 실제 손실이다.
- 주문별 실현손익은 executions 누락, 초기 체결가 누락, 수량 불일치 때문에 완전 복원할 수 없다. 따라서 확정 손익과 미복원 조정항목을 분리한다.
- 재진입 확인 조건은 최근 구간의 손실과 회전율을 줄였지만 전체 구간 수익률을 희생했다. 즉시 운영 반영이 아니라 PAPER shadow 비교가 적절하다.
"""
    ),
    code(
        """
from pathlib import Path
import json

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path.cwd()
LEDGER = ROOT / 'reports' / 'analysis' / 'paper_ledger_2026-07-22'
REENTRY = ROOT / 'reports' / 'analysis' / 'paper_reentry_experiments'

ledger = json.loads((LEDGER / 'summary.json').read_text(encoding='utf-8'))
pnl = pd.read_csv(LEDGER / 'pnl_attribution.csv')
orders = pd.read_csv(LEDGER / 'order_lifecycle.csv')
positions = pd.read_csv(LEDGER / 'position_reconciliation.csv')
daily_nav = pd.read_csv(LEDGER / 'daily_nav.csv')
full = json.loads((REENTRY / 'full' / 'metrics.json').read_text(encoding='utf-8'))
recent = json.loads((REENTRY / 'pass_only' / 'metrics.json').read_text(encoding='utf-8'))

print('Cutoff:', ledger['metadata']['cutoff'])
print('Mode:', ledger['metadata']['mode'])
print('Data quality:', ledger['data_quality']['overall_grade'])
"""
    ),
    markdown("## 5억원 기준 원장"),
    code(
        """
endpoint = pd.DataFrame([
    {'metric': '시작자금', 'value': ledger['metadata']['starting_capital']},
    {'metric': '컷오프 총평가액', 'value': ledger['endpoint']['total_asset']},
    {'metric': '총손익', 'value': ledger['endpoint']['total_pnl']},
    {'metric': '총수익률', 'value': ledger['endpoint']['total_return']},
    {'metric': '기준선 이후 손익', 'value': ledger['endpoint']['post_baseline_pnl']},
    {'metric': '기준선 이후 수익률', 'value': ledger['endpoint']['post_baseline_return']},
])
endpoint
"""
    ),
    code(
        """
fig, ax = plt.subplots(figsize=(10, 4.8))
colors = ['#2f6fed' if c != 'UNRESOLVED_BALANCING_ITEM' else '#d97706' for c in pnl['classification']]
ax.barh(pnl['component'], pnl['amount'] / 1_000_000, color=colors)
ax.axvline(0, color='black', linewidth=0.8)
ax.set_xlabel('백만원')
ax.set_title('5억원 대비 손익 구성: 미복원 조정항목을 별도 표시')
ax.grid(axis='x', alpha=0.2)
plt.tight_layout()
plt.show()
"""
    ),
    markdown(
        """
현재 보유 평가손익과 일부 매칭된 실현손익만으로는 전체 손실을 설명할 수 없다. 잔여분은 초기 보유, 누락 체결, 실제 수수료·세금, 외부 변동이 섞인 조정항목이며 임의 거래로 만들지 않는다.
"""
    ),
    markdown("## 주문결과 리플레이와 데이터 품질"),
    code(
        """
status = orders['status'].value_counts().rename_axis('status').reset_index(name='orders')
fig, ax = plt.subplots(figsize=(8, 4.5))
ax.bar(status['status'], status['orders'], color=['#dc2626', '#16a34a', '#64748b'][:len(status)])
ax.set_ylabel('주문 수')
ax.set_title('실제 주문 최종 상태')
ax.grid(axis='y', alpha=0.2)
plt.tight_layout()
plt.show()
status
"""
    ),
    code(
        """
quality = pd.DataFrame([
    {'check': '체결가 보유율', 'value': ledger['data_quality']['fill_price_coverage']},
    {'check': 'executions 연결률', 'value': ledger['data_quality']['execution_table_coverage_of_filled_orders']},
    {'check': '기록 수수료·세금 0 비율', 'value': ledger['data_quality']['zero_recorded_commission_tax_rate']},
    {'check': '현재 보유수량 정확 일치율', 'value': ledger['reconciliation']['endpoint_held_position_match_rate']},
])
quality.style.format({'value': '{:.1%}'})
"""
    ),
    code(
        """
positions.loc[
    (positions['actual_endpoint_qty'] != 0) | (positions['qty_gap_balancing_entry'] != 0),
    ['stock_name', 'symbol', 'known_fill_net_qty', 'actual_endpoint_qty', 'qty_gap_balancing_entry', 'exact_qty_match']
].sort_values(['actual_endpoint_qty', 'stock_name'], ascending=[False, True])
"""
    ),
    markdown(
        """
종목 표기는 코드만 노출하지 않고 DB의 한글 종목명과 코드를 함께 사용한다. 현재 보유 4종목 중 알려진 체결만으로 수량이 일치하는 종목은 2개다.
"""
    ),
    markdown("## 재진입 확인 조건 실험"),
    code(
        """
labels = {row['code']: row['label'] for row in full['metadata']['variant_definitions']}
variants = ['A_CURRENT', 'X_COOLDOWN5', 'R_EXIT_RECOVERY', 'R_TREND_REARM', 'C_CAP10', 'C_CAP08']
rows = []
for variant in variants:
    f = full['summary'][variant]
    r = recent['summary'][variant]
    rows.append({
        'variant': variant,
        'label': labels[variant],
        'full_return': f['total_return'],
        'full_mdd': f['max_drawdown'],
        'full_turnover': f['annualized_turnover'],
        'recent_return': r['total_return'],
        'recent_mdd': r['max_drawdown'],
        'recent_turnover': r['annualized_turnover'],
        'blocked_sessions': r['reentry_blocked_sessions'],
        'confirmed_reentries': r['confirmed_reentries'],
    })
comparison = pd.DataFrame(rows).set_index('variant')
comparison.style.format({
    'full_return': '{:.2%}', 'full_mdd': '{:.2%}', 'full_turnover': '{:.1f}x',
    'recent_return': '{:.2%}', 'recent_mdd': '{:.2%}', 'recent_turnover': '{:.1f}x',
})
"""
    ),
    code(
        """
fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
x = range(len(variants))
axes[0].bar(x, comparison.loc[variants, 'full_return'], color='#2f6fed')
axes[0].set_title('전체 구간 수익률')
axes[1].bar(x, comparison.loc[variants, 'recent_return'], color='#16a34a')
axes[1].set_title('PASS/PUBLISHED 최근 구간 수익률')
for ax in axes:
    ax.axhline(0, color='black', linewidth=0.8)
    ax.set_xticks(list(x), [labels[v] for v in variants], rotation=35, ha='right')
    ax.yaxis.set_major_formatter(lambda value, pos: f'{value:.0%}')
    ax.grid(axis='y', alpha=0.2)
plt.tight_layout()
plt.show()
"""
    ),
    markdown(
        """
추세 재무장 3일 확인은 최근 구간에서 현재 규칙의 -1.75%를 -0.03%로 줄이고, MDD를 -19.06%에서 -17.16%, 연환산 회전율을 45.8배에서 23.7배로 낮췄다. 그러나 전체 구간 수익률은 +22.31%에서 +10.87%로 낮아지고 MDD는 -23.19%에서 -27.06%로 나빠졌다. 따라서 전면 적용 근거가 아니라 최근 고회전 구간의 shadow 후보로 해석한다.
"""
    ),
    markdown("## 검증과 의사결정"),
    code(
        """
bridge_total = pnl.loc[pnl['classification'] != 'EXACT_ENDPOINT', 'amount'].sum()
assert ledger['metadata']['mode'] == 'PAPER'
assert abs(bridge_total - ledger['endpoint']['total_pnl']) < 1.0
assert ledger['order_result_replay']['orders'] == len(orders)
assert ledger['reconciliation']['endpoint_held_positions'] == 4
assert recent['summary']['R_TREND_REARM']['total_return'] > recent['summary']['A_CURRENT']['total_return']

checks = pd.DataFrame([
    {'check': 'PAPER 모드', 'result': 'PASS'},
    {'check': '손익 브리지 합계', 'result': 'PASS'},
    {'check': '주문 행 수 일치', 'result': 'PASS'},
    {'check': '현재 보유 4종목 확인', 'result': 'PASS'},
    {'check': '최근 구간 추세 재무장 개선', 'result': 'PASS'},
])
checks
"""
    ),
    markdown(
        """
1. 운영 전략은 즉시 변경하지 않는다.
2. 현재 규칙과 `R_TREND_REARM`을 10거래일 PAPER shadow로 병렬 기록한다.
3. 일별 리포트에 주문 최종상태, 체결 연결률, 수량 조정항목, 회전율, 비용을 필수 지표로 추가한다.
4. shadow 기간 동안 최근 수익률·MDD·회전율이 모두 개선되고 수량 불일치가 해소될 때만 승격을 재검토한다.
"""
    ),
]

client = NotebookClient(nb, timeout=600, kernel_name="python3", resources={"metadata": {"path": str(ROOT)}})
client.execute()
nbf.write(nb, OUTPUT)
print(OUTPUT)
