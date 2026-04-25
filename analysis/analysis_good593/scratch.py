import pandas as pd
import glob
import os

data_dir = './data/재무제표'

wics = pd.read_csv(f'{data_dir}/wics_company_2026.csv', dtype=str)
dart = pd.read_csv(f'{data_dir}/dart_company_2026.csv', dtype=str)

it_wics = wics[wics['SEC_CD'] == 'G45']
print(f"IT companies count: {len(it_wics)}")

if len(it_wics) > 0:
    it_cmp_cds = it_wics['CMP_CD'].unique()
    it_dart = dart[dart['CMP_CD'].isin(it_cmp_cds)]
    it_corp_codes = it_dart['DART_CD'].unique()
    print(f"Mapped to DART codes: {len(it_corp_codes)}")

    # Sample reading one year
    is_2025 = pd.read_csv(f'{data_dir}/income_statement_2025.csv', dtype=str)
    it_is_2025 = is_2025[is_2025['corp_code'].isin(it_corp_codes)]
    print(f"IS 2025 rows for IT: {len(it_is_2025)}")
    
    print("IS Account IDs:")
    print(it_is_2025['account_id'].value_counts().head(10))
    print("IS Account Names:")
    print(it_is_2025['account_nm'].value_counts().head(10))
