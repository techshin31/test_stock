import os
import requests
import pandas as pd
import time
from tqdm.auto import tqdm
import io
import re

import OpenDartReader
import pandas as pd
import requests
from bs4 import BeautifulSoup
from OpenDartReader import dart_utils


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



def find_business_report_rcp_no(dart, corp_code: str, bsns_year: int):
    """사업연도(bsns_year)에 해당하는 최종 사업보고서 접수번호(rcept_no)."""
    y = int(bsns_year)
    windows = [
        (f"{y + 1}0101", f"{y + 1}1231"),
        (f"{y}0101", f"{y + 1}0630"),
    ]
    for start, end in windows:
        lst = dart.list(corp_code, start=start, end=end, kind="A", final=True)
        if lst.empty:
            continue
        m = lst["report_nm"].astype(str).str.contains("사업보고서", na=False)
        cand = lst.loc[m]
        if cand.empty:
            continue
        m2 = cand["report_nm"].astype(str).str.contains(str(y), na=False)
        prefer = cand.loc[m2] if m2.any() else cand
        row = prefer.sort_values("rcept_dt", ascending=False).iloc[0]
        return str(row["rcept_no"]), row
    return None, None


def fetch_viewer_text(url: str, timeout: float = 60.0) -> str:
    r = requests.get(url, headers={"User-Agent": dart_utils.USER_AGENT}, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    return soup.get_text("\n", strip=True)


def fetch_business_overview(dart, corp_code: str, bsns_year: int):
    rcp, _ = find_business_report_rcp_no(dart, corp_code, bsns_year)
    if not rcp:
        return None
    toc = dart.sub_docs(rcp, match="1. 사업의 개요")
    if toc.empty:
        toc = dart.sub_docs(rcp, match="사업의 개요")
    if toc.empty:
        return None
    return fetch_viewer_text(toc.iloc[0]["url"])


def fetch_segment_sales_tables(dart, corp_code: str, bsns_year: int) -> list:
    """사업보고서 HTML 표 중 부문/매출 형태의 표를 골라 반환."""
    rcp, _ = find_business_report_rcp_no(dart, corp_code, bsns_year)
    if not rcp:
        return []
    for match in ("매출 및 수주상황", "사업부문별 요약", "사업부문", "부문별"):
        toc = dart.sub_docs(rcp, match=match)
        if toc.empty:
            continue
        url = toc.iloc[0]["url"]
        r = requests.get(url, headers={"User-Agent": dart_utils.USER_AGENT}, timeout=60)
        r.raise_for_status()
        try:
            tables = pd.read_html(io.StringIO(r.text))
        except ValueError:
            continue
        out = []
        for t in tables:
            if t.shape[1] < 3 or t.shape[0] < 2:
                continue
            flat = t.to_string()
            if re.search(r"부\s*문|부문별|매출유형|세그먼트", flat):
                out.append(t)
        if out:
            return out
    return []









