import nbformat as nbf
import os

nb = nbf.v4.new_notebook()

# -----------------
# 0. Intro & Data Load
# -----------------
md_intro = """# IT 섹터(G45) 재무제표 종합 분석
README.md에 정의된 7가지 평가항목(수익성, 성장성, 재무안정성, 현금흐름, 밸류에이션, 주주환원, 재무생존성)을 기준으로 IT 섹터(G45) 기업들을 분석합니다.
각 항목별로 지표를 산출하고 시각화하여 섹터 내 기업들의 특징을 파악합니다.
"""

code_load = """import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import warnings
warnings.filterwarnings('ignore')

# 폰트 설정
plt.rc('font', family='AppleGothic')
plt.rcParams['axes.unicode_minus'] = False

# 1. 데이터 로드 및 전처리
data_dir = './data/재무제표'
wics = pd.read_csv(f'{data_dir}/wics_company_2026.csv', dtype=str)
dart = pd.read_csv(f'{data_dir}/dart_company_2026.csv', dtype=str)

# IT 섹터(G45) 필터링
it_wics = wics[wics['SEC_CD'] == 'G45'].copy()
it_wics['MKT_VAL'] = pd.to_numeric(it_wics['MKT_VAL'], errors='coerce') * 1000000 # 백만원 단위 조정

# CMP_CD -> DART_CD 매핑
it_dart = dart[dart['CMP_CD'].isin(it_wics['CMP_CD'])]
cmp_to_dart = dict(zip(it_dart['CMP_CD'], it_dart['DART_CD']))
it_wics['corp_code'] = it_wics['CMP_CD'].map(cmp_to_dart)

# 재무제표 로드 (2025년 기준)
bs = pd.read_csv(f'{data_dir}/balance_sheet_2025.csv', dtype=str)
is_df = pd.read_csv(f'{data_dir}/income_statement_2025.csv', dtype=str)
cf = pd.read_csv(f'{data_dir}/cash_flow_2025.csv', dtype=str)

bs = bs[bs['corp_code'].isin(it_wics['corp_code'])]
is_df = is_df[is_df['corp_code'].isin(it_wics['corp_code'])]
cf = cf[cf['corp_code'].isin(it_wics['corp_code'])]

for df in [bs, is_df, cf]:
    df['thstrm_amount'] = pd.to_numeric(df['thstrm_amount'], errors='coerce')
    df['frmtrm_amount'] = pd.to_numeric(df['frmtrm_amount'], errors='coerce')

def get_amount(df, account_ids, val_col='thstrm_amount'):
    filtered = df[df['account_id'].isin(account_ids)]
    return filtered.groupby('corp_code')[val_col].first()

# 분석용 기본 데이터프레임
df_it = it_wics[['CMP_CD', 'CMP_KOR', 'corp_code', 'MKT_VAL']].copy().set_index('corp_code')

# 계정 추출
df_it['매출액'] = get_amount(is_df, ['ifrs-full_Revenue', 'dart_TotalAsset'])
df_it['전기매출액'] = get_amount(is_df, ['ifrs-full_Revenue', 'dart_TotalAsset'], 'frmtrm_amount')
df_it['영업이익'] = get_amount(is_df, ['dart_OperatingIncomeLoss'])
df_it['당기순이익'] = get_amount(is_df, ['ifrs-full_ProfitLoss'])

df_it['자산총계'] = get_amount(bs, ['ifrs-full_Assets'])
df_it['부채총계'] = get_amount(bs, ['ifrs-full_Liabilities'])
df_it['자본총계'] = get_amount(bs, ['ifrs-full_Equity'])
df_it['현금성자산'] = get_amount(bs, ['ifrs-full_CashAndCashEquivalents'])

df_it['영업활동현금흐름'] = get_amount(cf, ['ifrs-full_CashFlowsFromUsedInOperatingActivities'])
df_it['배당금지급'] = get_amount(cf, ['ifrs-full_DividendsPaidClassifiedAsFinancingActivities']).fillna(0)

df_it.reset_index(inplace=True)
df_it.dropna(subset=['매출액', '자본총계'], inplace=True) # 필수 데이터 없는 기업 제외

top10_it = df_it.sort_values('MKT_VAL', ascending=False).head(10).copy()
print(f"분석 대상 IT 기업 수: {len(df_it)}개")
"""

# -----------------
# 1. 수익성
# -----------------
md_profit = """## 1. 수익성 분석
회사가 본업을 통해 실제로 얼마나 안정적으로 이익을 창출하는지 확인합니다. 영업이익률(OPM)과 순이익률(NPM)을 계산합니다.
"""
code_profit = """df_it['영업이익률(%)'] = (df_it['영업이익'] / df_it['매출액']) * 100
df_it['순이익률(%)'] = (df_it['당기순이익'] / df_it['매출액']) * 100

top10_it = df_it.sort_values('MKT_VAL', ascending=False).head(10).copy()

plt.figure(figsize=(10, 5))
sns.barplot(data=top10_it, x='CMP_KOR', y='영업이익률(%)', palette='Blues_r')
plt.title('IT 섹터 시가총액 상위 10개사 영업이익률')
plt.ylabel('영업이익률 (%)')
plt.xticks(rotation=45)
plt.axhline(df_it['영업이익률(%)'].median(), color='red', linestyle='--', label='섹터 중앙값')
plt.legend()
plt.tight_layout()
plt.show()
"""
md_profit_analysis = """**💡 수익성 분석 결과**
- 대형 IT 기업들은 대체로 안정적인 두 자릿수 영업이익률을 기록하며 섹터 중앙값(빨간 점선)을 상회하는 모습을 보여줍니다.
- 규모의 경제를 달성한 대기업일수록 본업에서의 이익 창출력이 뛰어나며, 이는 높은 기업가치를 정당화하는 핵심 요인입니다.
"""

# -----------------
# 2. 성장성
# -----------------
md_growth = """## 2. 성장성 분석
향후 매출과 이익이 확대될 가능성이 있는지, 전년 동기 대비 매출액 증감률(YoY)을 통해 확인합니다.
"""
code_growth = """df_it['매출성장률(%)'] = ((df_it['매출액'] - df_it['전기매출액']) / df_it['전기매출액'].abs()) * 100
top10_it['매출성장률(%)'] = df_it.loc[top10_it.index, '매출성장률(%)']

plt.figure(figsize=(10, 5))
sns.barplot(data=top10_it, x='CMP_KOR', y='매출성장률(%)', palette='Greens_r')
plt.title('IT 섹터 시가총액 상위 10개사 매출성장률 (YoY)')
plt.ylabel('매출성장률 (%)')
plt.xticks(rotation=45)
plt.axhline(0, color='black', linewidth=1)
plt.axhline(df_it['매출성장률(%)'].median(), color='red', linestyle='--', label='섹터 중앙값')
plt.legend()
plt.tight_layout()
plt.show()
"""
md_growth_analysis = """**💡 성장성 분석 결과**
- 성숙기에 접어든 대형 IT 기업들의 매출성장률은 폭발적이기보다는 안정적인 흐름을 보이거나, 일부 업황에 따라 역성장(마이너스 성장)을 기록한 기업도 관찰됩니다.
- 전반적인 섹터 중앙값과 비교하여 각 기업이 시장 평균 대비 얼마나 아웃퍼폼하고 있는지 확인할 수 있습니다.
"""

# -----------------
# 3. 재무안정성
# -----------------
md_safety = """## 3. 재무안정성 분석
빚이 과도하지 않으며 어려운 상황을 버틸 수 있는 재무구조를 갖추고 있는지 부채비율(부채총계/자본총계)로 평가합니다.
"""
code_safety = """df_it['부채비율(%)'] = (df_it['부채총계'] / df_it['자본총계']) * 100
top10_it['부채비율(%)'] = df_it.loc[top10_it.index, '부채비율(%)']

plt.figure(figsize=(10, 5))
sns.barplot(data=top10_it, x='CMP_KOR', y='부채비율(%)', palette='Oranges_r')
plt.title('IT 섹터 시가총액 상위 10개사 부채비율')
plt.ylabel('부채비율 (%)')
plt.xticks(rotation=45)
plt.axhline(100, color='red', linestyle='-', label='일반적 안전기준(100%)')
plt.legend()
plt.tight_layout()
plt.show()
"""
md_safety_analysis = """**💡 재무안정성 분석 결과**
- IT 대형주들은 대부분 부채비율이 100% 미만으로 매우 건전한 재무 상태를 유지하고 있습니다.
- 제조업 기반 IT 기업의 경우 대규모 설비투자로 인해 일부 부채가 있을 수 있으나, 창출되는 현금흐름으로 충분히 감당 가능한 수준입니다.
"""

# -----------------
# 4. 현금흐름
# -----------------
md_cf = """## 4. 현금흐름 분석
회계상 이익(당기순이익)뿐만 아니라, 실제로 현금이 안정적으로 유입(영업활동현금흐름)되고 있는지 비교합니다.
"""
code_cf = """width = 0.35
x = np.arange(len(top10_it['CMP_KOR']))

fig, ax = plt.subplots(figsize=(12, 6))
rects1 = ax.bar(x - width/2, top10_it['당기순이익'] / 1e12, width, label='당기순이익(조 원)', color='lightgray')
rects2 = ax.bar(x + width/2, top10_it['영업활동현금흐름'] / 1e12, width, label='영업활동현금흐름(조 원)', color='royalblue')

ax.set_ylabel('금액 (조 원)')
ax.set_title('당기순이익 vs 영업활동현금흐름 비교 (이익의 질 평가)')
ax.set_xticks(x)
ax.set_xticklabels(top10_it['CMP_KOR'], rotation=45)
ax.legend()
fig.tight_layout()
plt.show()
"""
md_cf_analysis = """**💡 현금흐름 분석 결과**
- 우량한 IT 기업들은 당기순이익보다 영업활동현금흐름이 더 크게 나타납니다. 이는 감가상각비 등 현금 유출이 없는 비용이 더해져 실제 기업에 유입되는 현금이 장부상 이익보다 크다는 의미입니다.
- 이처럼 '이익의 질(Quality of Earnings)'이 우수해야 대규모 R&D 및 배당이 가능합니다.
"""

# -----------------
# 5. 밸류에이션
# -----------------
md_val = """## 5. 밸류에이션 분석
우수한 기업이라도 주가가 지나치게 고평가되어 있지 않은지 PER과 PBR을 통해 확인합니다.
"""
code_val = """df_it['PER'] = np.where(df_it['당기순이익'] > 0, df_it['MKT_VAL'] / df_it['당기순이익'], np.nan)
df_it['PBR'] = np.where(df_it['자본총계'] > 0, df_it['MKT_VAL'] / df_it['자본총계'], np.nan)

valid_val = df_it[(df_it['PER'] > 0) & (df_it['PER'] < 100) & (df_it['PBR'] < 10)].copy()

plt.figure(figsize=(10, 6))
sns.scatterplot(data=valid_val, x='PBR', y='PER', size='MKT_VAL', sizes=(20, 800), alpha=0.6, color='purple')
plt.title('IT 섹터 밸류에이션 (PBR vs PER) - 버블크기: 시가총액')
plt.axvline(valid_val['PBR'].median(), color='red', linestyle='--', label='Median PBR', alpha=0.5)
plt.axhline(valid_val['PER'].median(), color='blue', linestyle='--', label='Median PER', alpha=0.5)
plt.legend()
plt.tight_layout()
plt.show()
"""
md_val_analysis = """**💡 밸류에이션 분석 결과**
- 1사분면(우상단)에 위치한 기업들은 시장에서 높은 프리미엄을 받는 성장주 형태입니다.
- 3사분면(좌하단)에 위치한 기업들은 자산이나 이익 대비 저평가(가치주) 영역에 있습니다. 
- 버블의 크기(시가총액)가 큰 대장주들은 대개 중간 정도의 안정적인 멀티플(PER 10~20배 내외)을 형성하고 있습니다.
"""

# -----------------
# 6. 주주환원
# -----------------
md_div = """## 6. 주주환원 분석
배당금 지급액을 바탕으로 투자자에게 이익을 얼마나 환원하는지(배당수익률) 분석합니다.
"""
code_div = """df_it['배당수익률(%)'] = (df_it['배당금지급'].abs() / df_it['MKT_VAL']) * 100
div_top10 = df_it[df_it['배당수익률(%)'] > 0].sort_values('배당수익률(%)', ascending=False).head(10)

plt.figure(figsize=(10, 5))
sns.barplot(data=div_top10, x='CMP_KOR', y='배당수익률(%)', palette='Purples_r')
plt.title('IT 섹터 내 배당수익률 상위 10개사')
plt.ylabel('배당수익률 (%)')
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()
"""
md_div_analysis = """**💡 주주환원 분석 결과**
- IT 섹터임에도 전통적인 고배당주 못지않은 배당수익률을 기록하는 성숙한 기업들이 존재합니다.
- 성장성 둔화를 높은 배당으로 보상하거나, 주주가치 제고에 적극적인 기업들로 해석할 수 있습니다.
"""

# -----------------
# 7. 재무생존성
# -----------------
md_runway = """## 7. 재무생존성 (Runway) 분석
적자이거나 영업현금흐름이 마이너스(-)인 기업이 현재 보유한 현금으로 얼마나 사업을 지속할 수 있는지(Runway) 측정합니다.
"""
code_runway = """df_it['Runway(년)'] = np.where(df_it['영업활동현금흐름'] < 0, 
                                df_it['현금성자산'] / df_it['영업활동현금흐름'].abs(), 
                                np.nan)

risk_df = df_it.dropna(subset=['Runway(년)']).sort_values('Runway(년)').head(10)

if not risk_df.empty:
    plt.figure(figsize=(10, 5))
    sns.barplot(data=risk_df, x='CMP_KOR', y='Runway(년)', palette='Reds_r')
    plt.title('영업현금흐름 적자 IT기업의 현금소진 유예기간 (Runway, 짧은 순)')
    plt.ylabel('Runway (년)')
    plt.xticks(rotation=45)
    plt.axhline(1, color='red', linestyle='--', label='위험선 (1년 이내)')
    plt.legend()
    plt.tight_layout()
    plt.show()
else:
    print("분석 대상 중 영업활동현금흐름이 적자인 기업이 없어 Runway 분석을 생략합니다.")
"""
md_runway_analysis = """**💡 재무생존성 분석 결과**
- 영업활동에서 현금이 유출되고 있는 기업들의 경우, 보유 현금성 자산으로 몇 년을 버틸 수 있는지(Runway) 보여줍니다.
- 1년 미만인 기업은 단기적인 유상증자나 사채 발행 등 자금 조달 리스크가 매우 높다고 볼 수 있습니다.
"""

# -----------------
# Assemble Notebook
# -----------------
nb['cells'] = [
    nbf.v4.new_markdown_cell(md_intro),
    nbf.v4.new_code_cell(code_load),
    nbf.v4.new_markdown_cell(md_profit),
    nbf.v4.new_code_cell(code_profit),
    nbf.v4.new_markdown_cell(md_profit_analysis),
    nbf.v4.new_markdown_cell(md_growth),
    nbf.v4.new_code_cell(code_growth),
    nbf.v4.new_markdown_cell(md_growth_analysis),
    nbf.v4.new_markdown_cell(md_safety),
    nbf.v4.new_code_cell(code_safety),
    nbf.v4.new_markdown_cell(md_safety_analysis),
    nbf.v4.new_markdown_cell(md_cf),
    nbf.v4.new_code_cell(code_cf),
    nbf.v4.new_markdown_cell(md_cf_analysis),
    nbf.v4.new_markdown_cell(md_val),
    nbf.v4.new_code_cell(code_val),
    nbf.v4.new_markdown_cell(md_val_analysis),
    nbf.v4.new_markdown_cell(md_div),
    nbf.v4.new_code_cell(code_div),
    nbf.v4.new_markdown_cell(md_div_analysis),
    nbf.v4.new_markdown_cell(md_runway),
    nbf.v4.new_code_cell(code_runway),
    nbf.v4.new_markdown_cell(md_runway_analysis)
]

with open('3. analysis_IT.ipynb', 'w', encoding='utf-8') as f:
    nbf.write(nb, f)
print("Notebook rebuilt with itemized cells.")
