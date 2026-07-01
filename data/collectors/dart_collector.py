"""DART Open API raw data collector."""
from __future__ import annotations

import io
import os
import re
import time
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd
import requests


_DART_API_BASE = "https://opendart.fss.or.kr/api"

# B타입(주요사항보고서) 분류 규칙
_EVENT_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    ("SHAREHOLDER_RETURN", "CASH_DIVIDEND",            ("현금배당", "현금ㆍ현물배당", "주식배당")),
    ("SHAREHOLDER_RETURN", "BUYBACK",                  ("자기주식취득", "자기주식 취득 신탁계약 체결")),
    ("SHAREHOLDER_RETURN", "TREASURY_DISPOSAL",        ("자기주식처분결정",)),
    ("SHAREHOLDER_RETURN", "SHARE_CANCELLATION",       ("주식소각결정",)),
    ("CAPITAL_CHANGE",     "PAID_IN_CAPITAL_INCREASE", ("유상증자결정",)),
    ("CAPITAL_CHANGE",     "BONUS_ISSUE",              ("무상증자결정",)),
    ("CAPITAL_CHANGE",     "CONVERTIBLE_BOND",         ("전환사채권발행결정",)),
    ("CAPITAL_CHANGE",     "BOND_WITH_WARRANT",        ("신주인수권부사채권발행결정",)),
    ("CAPITAL_CHANGE",     "EXCHANGE_BOND",            ("교환사채권발행결정",)),
    ("PIPELINE_EVENT",     "CLINICAL_TRIAL",           ("임상", "임상시험")),
    ("PIPELINE_EVENT",     "APPROVAL",                 ("품목허가", "허가", "허가승인")),
    ("PIPELINE_EVENT",     "TECHNOLOGY_TRANSFER",      ("기술이전", "기술수출", "라이선스아웃", "license-out")),
    ("BUSINESS_EVENT",     "MAJOR_CONTRACT",           ("단일판매ㆍ공급계약체결", "대규모계약", "판매계약")),
    ("BUSINESS_EVENT",     "INVESTMENT_DECISION",      ("타법인 주식 및 출자증권취득결정",)),
]

# A타입(정기공시) 분류 규칙
_REGULAR_REPORT_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    ("REGULAR_REPORT", "ANNUAL_REPORT",      ("사업보고서",)),
    ("REGULAR_REPORT", "SEMI_ANNUAL_REPORT", ("반기보고서",)),
    ("REGULAR_REPORT", "Q1_REPORT",          ("1분기보고서",)),
    ("REGULAR_REPORT", "Q3_REPORT",          ("3분기보고서",)),
]


def _get_dart_key() -> str:
    key = os.environ.get("DART_API_KEY")
    if not key:
        raise ValueError("환경변수 DART_API_KEY가 필요합니다.")
    return key


def fetch_corp_codes() -> dict[str, dict]:
    """DART corpCode.xml ZIP을 다운로드해 상장사 매핑을 반환한다.

    Returns
    -------
    dict[str, dict]
        {stock_code: {"corp_code": str, "company_name": str}}
        stock_code가 없는 비상장사는 제외.
    """
    r = requests.get(
        f"{_DART_API_BASE}/corpCode.xml",
        params={"crtfc_key": _get_dart_key()},
        timeout=60,
    )
    r.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        with z.open("CORPCODE.xml") as f:
            root = ET.parse(f).getroot()

    result: dict[str, dict] = {}
    for item in root.findall("list"):
        stock_code = (item.findtext("stock_code") or "").strip()
        if not stock_code:
            continue
        result[stock_code] = {
            "corp_code":    (item.findtext("corp_code")  or "").strip(),
            "company_name": (item.findtext("corp_name")  or "").strip(),
        }
    return result


def fetch_company_detail(corp_code: str, *, timeout: float = 30) -> dict | None:
    """DART company.json에서 기업 기본정보를 반환한다.

    Parameters
    ----------
    corp_code : str
        DART 고유번호 8자리

    Returns
    -------
    dict or None
        {"acc_mt": int, ...} — 조회 실패 시 None
    """
    r = requests.get(
        f"{_DART_API_BASE}/company.json",
        params={"crtfc_key": _get_dart_key(), "corp_code": corp_code},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "000":
        return None
    acc_mt_raw = data.get("acc_mt")
    if acc_mt_raw is None:
        return None
    try:
        return {"acc_mt": int(acc_mt_raw)}
    except (ValueError, TypeError):
        return None


def fetch_financial_statements(
    corp_code: str,
    bsns_year: str | int,
    *,
    reprt_code: str = "11011",
    fs_div: str = "CFS",
    timeout: float = 60,
) -> pd.DataFrame:
    """DART API에서 단일회사 전체 재무제표를 DataFrame으로 반환한다.

    Parameters
    ----------
    corp_code : str
        DART 고유번호 8자리
    bsns_year : str or int
        사업연도 (예: 2023)
    reprt_code : str
        보고서 코드 — 11011=사업보고서, 11012=반기, 11013=1분기, 11014=3분기
    fs_div : str
        CFS=연결재무제표, OFS=별도재무제표

    Returns
    -------
    pd.DataFrame
        DART API 원본 응답의 list 항목들. 빈 DataFrame이면 데이터 없음.
    """
    params = {
        "crtfc_key": _get_dart_key(),
        "corp_code": corp_code,
        "bsns_year": str(bsns_year),
        "reprt_code": reprt_code,
        "fs_div": fs_div,
    }
    r = requests.get(
        f"{_DART_API_BASE}/fnlttSinglAcntAll.json",
        params=params,
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "000":
        return pd.DataFrame()
    rows = data.get("list") or []
    return pd.DataFrame(rows)


def split_by_statement_type(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """sj_div 컬럼 기준으로 재무상태표·손익계산서·현금흐름표를 분리한다.

    Returns
    -------
    dict with keys: "BS", "IS", "CF"
    """
    out: dict[str, pd.DataFrame] = {"BS": pd.DataFrame(), "IS": pd.DataFrame(), "CF": pd.DataFrame()}
    if df.empty or "sj_div" not in df.columns:
        return out
    u = df["sj_div"].astype(str).str.upper()
    out["BS"] = df[u == "BS"].copy()
    out["IS"] = df[u.isin(["IS", "CIS"])].copy()
    out["CF"] = df[u == "CF"].copy()
    return out


def classify_dart_event(report_name: str) -> tuple[str, str]:
    """B타입 공시명으로 이벤트 대분류·세부유형 코드를 반환한다.

    분류 불가 시 ("OTHER", "UNCLASSIFIED") 반환.
    """
    text = str(report_name or "")
    for category, subtype, keywords in _EVENT_RULES:
        if any(kw in text for kw in keywords):
            return category, subtype
    return "OTHER", "UNCLASSIFIED"


def _classify_regular_report(report_name: str) -> tuple[str, str]:
    """A타입 공시명으로 정기공시 세부유형 코드를 반환한다.

    분류 불가 시 ("OTHER", "UNCLASSIFIED") 반환.
    """
    text = str(report_name or "")
    if "분기보고서" in text:
        match = re.search(r"\((?:\d{4})\.(\d{2})\)", text)
        if match and match.group(1) == "03":
            return "REGULAR_REPORT", "Q1_REPORT"
        if match and match.group(1) == "09":
            return "REGULAR_REPORT", "Q3_REPORT"
    for category, subtype, keywords in _REGULAR_REPORT_RULES:
        if any(kw in text for kw in keywords):
            return category, subtype
    return "OTHER", "UNCLASSIFIED"


def fetch_dart_events(
    corp_code: str,
    start_date: str,
    end_date: str,
    *,
    sleep_seconds: float = 0.2,
    timeout: float = 60,
) -> pd.DataFrame:
    """DART에서 기간 내 공시 목록(A·B 타입)을 가져와 이벤트 분류 후 반환한다.

    Parameters
    ----------
    corp_code : str
        DART 고유번호 8자리
    start_date, end_date : str
        조회 기간 (YYYYMMDD)

    Returns
    -------
    pd.DataFrame
        columns: rcept_no, rcept_dt, report_nm, pblntf_ty,
                 event_category_code, event_subtype_code, flr_nm, corp_cls, rm
        OTHER 분류는 제외하고 반환.
    """
    _FETCH_TARGETS = [
        ("A", _classify_regular_report),
        ("B", classify_dart_event),
    ]
    keep = ["rcept_no", "rcept_dt", "report_nm", "pblntf_ty",
            "event_category_code", "event_subtype_code", "flr_nm", "corp_cls", "rm"]

    parts: list[pd.DataFrame] = []
    for pblntf_ty, classify_fn in _FETCH_TARGETS:
        rows: list[dict] = []
        page_no = 1
        while True:
            time.sleep(sleep_seconds)
            r = requests.get(
                f"{_DART_API_BASE}/list.json",
                params={
                    "crtfc_key":     _get_dart_key(),
                    "corp_code":     corp_code,
                    "bgn_de":        start_date,
                    "end_de":        end_date,
                    "last_reprt_at": "N",
                    "pblntf_ty":     pblntf_ty,
                    "page_no":       page_no,
                    "page_count":    100,
                },
                timeout=timeout,
            )
            r.raise_for_status()
            data = r.json()
            if data.get("status") not in ("000", "013"):
                break
            rows.extend(data.get("list") or [])
            total_page = int(data.get("total_page") or 1)
            if page_no >= total_page:
                break
            page_no += 1
        if not rows:
            continue

        df = pd.DataFrame(rows)
        classified = df["report_nm"].apply(classify_fn)
        df["event_category_code"] = classified.str[0]
        df["event_subtype_code"]  = classified.str[1]
        df["pblntf_ty"]           = pblntf_ty
        df["rcept_dt"] = pd.to_datetime(df["rcept_dt"], format="%Y%m%d", errors="coerce").dt.date

        relevant = df[df["event_category_code"] != "OTHER"]
        for col in keep:
            if col not in relevant.columns:
                relevant = relevant.copy()
                relevant[col] = None
        parts.append(relevant[keep])

    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)
