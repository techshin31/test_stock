"""
오픈 DART — 단일회사 전체 재무제표(fnlttSinglAcntAll) 조회.

재무 숫자(대차·손익·현금흐름 등)는 개발가이드의 「정기보고서 재무정보」에 해당하며,
공시정보(DS001) 메뉴의 고유번호 API로 얻은 corp_code와 함께 사용한다.

문서: https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS003
"""

from __future__ import annotations

import os
import requests
import pandas as pd
import time
from tqdm.auto import tqdm

DART_API_BASE = "https://opendart.fss.or.kr/api"

# reprt_code: 11011 사업보고서, 11012 반기, 11013 1분기, 11014 3분기
# fs_div: CFS(연결), OFS(별도)


def fetch_financial_statements(
    corp_code: str,
    bsns_year: str | int,
    *,
    crtfc_key: str | None = None,
    reprt_code: str = "11011",
    fs_div: str = "CFS",
    timeout: float = 60,
) -> pd.DataFrame:
    """
    단일회사 전체 재무제표를 DataFrame으로 반환한다.

    응답 행의 sj_div로 구분: BS(대차대조표), IS/CIS(손익·포괄손익), CF(현금흐름표) 등.
    """
    key = crtfc_key or os.environ.get("DART_API_KEY")
    if not key:
        raise ValueError("crtfc_key 또는 환경변수 DART_API_KEY가 필요합니다.")

    url = f"{DART_API_BASE}/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": key,
        "corp_code": corp_code,
        "bsns_year": str(bsns_year),
        "reprt_code": reprt_code,
        "fs_div": fs_div,
    }
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "000":
        raise RuntimeError(data.get("message", str(data)))
    rows = data.get("list") or []
    return pd.DataFrame(rows)


def split_by_statement_type(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """sj_div 기준으로 대차·손익·현금흐름 등으로 나눈다."""
    out = {
        "balance_sheet": pd.DataFrame(),
        "income_statement": pd.DataFrame(),
        "cash_flow": pd.DataFrame(),
    }
    if df.empty or "sj_div" not in df.columns:
        return out

    u = df["sj_div"].astype(str).str.upper()
    out["balance_sheet"] = df[u == "BS"].copy()
    out["income_statement"] = df[u.isin(["IS", "CIS"])].copy()
    out["cash_flow"] = df[u == "CF"].copy()
    return out


def save_financial_statements_by_year(df_com: pd.DataFrame, bsns_year: str | int):
    balance_sheet = pd.DataFrame() # 대차대조표 (sj_div == BS)
    income_statement = pd.DataFrame() # 손익·포괄손익 (IS, CIS)
    cash_flow = pd.DataFrame() # 현금흐름표 (CF)

    for dart_cd in tqdm(df_com['DART_CD'].to_list(), desc="dart..", leave=True):
        time.sleep(0.5)
        try:
            # 단일회사 전체 재무제표
            df_all = fetch_financial_statements(
                dart_cd,
                bsns_year,
                crtfc_key=os.getenv("DART_API_KEY"),
                reprt_code="11011", # # reprt_code: 11011 사업보고서, 11012 반기, 11013 1분기, 11014 3분기
                fs_div="CFS"  # CFS: 연결, OFS: 별도
            )
            # 종류별 분리
            tables = split_by_statement_type(df_all)
            balance_sheet = pd.concat([balance_sheet, tables["balance_sheet"]], axis=0)
            income_statement = pd.concat([income_statement, tables["income_statement"]], axis=0)
            cash_flow = pd.concat([cash_flow, tables["cash_flow"]], axis=0)
        except Exception as e:
            # print(e)
            continue

    balance_sheet['bsns_year'] = bsns_year
    income_statement['bsns_year'] = bsns_year
    cash_flow['bsns_year'] = bsns_year

    balance_sheet.to_csv(f'./data/balance_sheet_{bsns_year}.csv', index=False, encoding='utf-8', header=True)
    income_statement.to_csv(f'./data/income_statement_{bsns_year}.csv', index=False, encoding='utf-8', header=True)
    cash_flow.to_csv(f'./data/cash_flow_{bsns_year}.csv', index=False, encoding='utf-8', header=True)
    print(f"Saved {bsns_year} financial statements")
    
    return balance_sheet, income_statement, cash_flow