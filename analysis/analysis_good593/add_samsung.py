import nbformat as nbf

with open('3. analysis_IT.ipynb', 'r', encoding='utf-8') as f:
    nb = nbf.read(f, as_version=4)

md_samsung = """## 8. 개별 기업 시계열 분석 (삼성전자)
IT 섹터의 대표주인 삼성전자(005930)의 지난 5개년(2021~2025년) 주요 재무 지표 추이를 분석합니다.
연도별 매출액, 영업이익, 영업이익률, 부채비율 변화를 확인하여 기업의 장기적인 성장성과 안정성 흐름을 파악합니다.
"""

code_samsung = """# 삼성전자 DART_CD 확인 (종목코드 005930)
samsung_cmp = '005930'
samsung_dart = dart[dart['CMP_CD'] == samsung_cmp]['DART_CD'].values[0]

years = ['2021', '2022', '2023', '2024', '2025']
samsung_data = []

for y in years:
    # 연도별 재무제표 로드
    bs_y = pd.read_csv(f'{data_dir}/balance_sheet_{y}.csv', dtype=str)
    is_y = pd.read_csv(f'{data_dir}/income_statement_{y}.csv', dtype=str)
    cf_y = pd.read_csv(f'{data_dir}/cash_flow_{y}.csv', dtype=str)
    
    # 삼성전자 데이터 필터링
    bs_s = bs_y[bs_y['corp_code'] == samsung_dart].copy()
    is_s = is_y[is_y['corp_code'] == samsung_dart].copy()
    cf_s = cf_y[cf_y['corp_code'] == samsung_dart].copy()
    
    for df in [bs_s, is_s, cf_s]:
        df['thstrm_amount'] = pd.to_numeric(df['thstrm_amount'], errors='coerce')
        
    def get_s_amount(df, acc_id):
        val = df[df['account_id'].isin(acc_id)]['thstrm_amount']
        return val.values[0] if not val.empty else np.nan
        
    # 지표 추출
    rev = get_s_amount(is_s, ['ifrs-full_Revenue', 'dart_TotalAsset'])
    op = get_s_amount(is_s, ['dart_OperatingIncomeLoss'])
    ni = get_s_amount(is_s, ['ifrs-full_ProfitLoss'])
    asset = get_s_amount(bs_s, ['ifrs-full_Assets'])
    liab = get_s_amount(bs_s, ['ifrs-full_Liabilities'])
    eq = get_s_amount(bs_s, ['ifrs-full_Equity'])
    ocf = get_s_amount(cf_s, ['ifrs-full_CashFlowsFromUsedInOperatingActivities'])
    
    samsung_data.append({
        '연도': y,
        '매출액': rev,
        '영업이익': op,
        '당기순이익': ni,
        '자산총계': asset,
        '부채총계': liab,
        '자본총계': eq,
        '영업활동현금흐름': ocf
    })

df_sec = pd.DataFrame(samsung_data)

# 추가 지표 계산
df_sec['영업이익률(%)'] = (df_sec['영업이익'] / df_sec['매출액']) * 100
df_sec['부채비율(%)'] = (df_sec['부채총계'] / df_sec['자본총계']) * 100

# 시각화 1: 매출액 및 영업이익 추이
fig, ax1 = plt.subplots(figsize=(10, 5))

# 조 단위 변환
ax1.bar(df_sec['연도'], df_sec['매출액'] / 1e12, color='lightblue', label='매출액(조 원)')
ax1.set_ylabel('매출액 (조 원)', color='royalblue')
ax1.set_ylim(0, (df_sec['매출액'].max() / 1e12) * 1.3)
ax1.legend(loc='upper left')

ax2 = ax1.twinx()
ax2.plot(df_sec['연도'], df_sec['영업이익'] / 1e12, color='darkblue', marker='o', linewidth=2, label='영업이익(조 원)')
ax2.set_ylabel('영업이익 (조 원)', color='darkblue')
if df_sec['영업이익'].max() > 0:
    ax2.set_ylim(min(0, (df_sec['영업이익'].min() / 1e12) * 1.2), (df_sec['영업이익'].max() / 1e12) * 1.5)
ax2.legend(loc='upper right')

plt.title('삼성전자 연도별 매출액 및 영업이익 추이 (2021~2025)')
plt.show()

# 시각화 2: 영업이익률 및 부채비율 추이
fig, ax1 = plt.subplots(figsize=(10, 5))

ax1.plot(df_sec['연도'], df_sec['영업이익률(%)'], color='orange', marker='s', linewidth=2, label='영업이익률(%)')
ax1.set_ylabel('영업이익률 (%)', color='darkorange')
ax1.legend(loc='upper left')

ax2 = ax1.twinx()
ax2.plot(df_sec['연도'], df_sec['부채비율(%)'], color='gray', marker='^', linestyle='--', label='부채비율(%)')
ax2.set_ylabel('부채비율 (%)', color='dimgray')
ax2.set_ylim(0, max(50, df_sec['부채비율(%)'].max() * 1.5))
ax2.legend(loc='upper right')

plt.title('삼성전자 연도별 영업이익률 및 부채비율 추이 (2021~2025)')
plt.show()

# 결과를 소수점 둘째자리까지 반올림하여 표출
df_sec[['연도', '매출액', '영업이익', '영업이익률(%)', '부채비율(%)']].round(2)
"""

md_samsung_analysis = """**💡 삼성전자 시계열 분석 결과**
- **매출액 및 이익 성장성**: 지난 5년간 글로벌 반도체/IT 사이클에 따른 매출과 영업이익의 등락이 관찰됩니다. 특히 호황기와 다운사이클에서의 이익 체력 변화를 직관적으로 확인할 수 있습니다.
- **수익성 (영업이익률)**: 매출보다 영업이익의 변동 폭이 상대적으로 큽니다. 이는 고정비 비중이 높은 반도체 산업 특성상 나타나는 전형적인 영업레버리지(Operating Leverage) 효과를 보여줍니다.
- **재무안정성**: 업황에 따른 이익 변동성에도 불구하고, 부채비율은 지속적으로 매우 낮은 수준을 유지하고 있어 외부 충격에 버틸 수 있는 막강한 재무적 완충 능력을 갖추고 있음을 알 수 있습니다.
"""

nb.cells.extend([
    nbf.v4.new_markdown_cell(md_samsung),
    nbf.v4.new_code_cell(code_samsung),
    nbf.v4.new_markdown_cell(md_samsung_analysis)
])

with open('3. analysis_IT.ipynb', 'w', encoding='utf-8') as f:
    nbf.write(nb, f)
print("Samsung analysis appended successfully.")
