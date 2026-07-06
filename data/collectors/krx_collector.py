"""KRX 상장 종목 데이터 수집 — FinanceDataReader 기반."""
from __future__ import annotations

import FinanceDataReader as fdr


_MARKETS = [
    ("KOSPI",  "KOSPI"),
    ("KOSDAQ", "KOSDAQ"),
]


def fetch_krx_market_map(trade_date: str | None = None) -> dict[str, str]:
    """KOSPI/KOSDAQ 상장 종목 → 거래소 코드 매핑을 반환한다.

    Parameters
    ----------
    trade_date : str, optional
        사용하지 않음 (FinanceDataReader는 현재 시점 상장 종목만 제공).

    Returns
    -------
    dict[str, str]
        {stock_code(6자리): "KOSPI" | "KOSDAQ"}
        조회 실패 시 빈 dict 반환.
    """
    result: dict[str, str] = {}
    for listing_key, market_code in _MARKETS:
        try:
            df = fdr.StockListing(listing_key)
            for code in df["Code"].dropna():
                code = str(code).strip().zfill(6)
                if code:
                    result[code] = market_code
        except Exception as e:
            print(f"[WARN] KRX {market_code} 조회 실패: {e}")
    return result


import requests
from bs4 import BeautifulSoup

def fetch_krx_suspended_codes(trade_date: str | None = None) -> set[str]:
    """네이버 금융을 크롤링하여 거래정지 및 관리종목 종목코드 세트를 반환한다.

    Returns
    -------
    set[str]
        거래정지 또는 관리종목 코드 6자리 세트
    """
    bad_codes = set()
    
    # 1. 거래정지 종목
    halt_url = "https://finance.naver.com/sise/trading_halt.naver"
    try:
        res = requests.get(halt_url, timeout=10)
        soup = BeautifulSoup(res.content, "html.parser")
        for a in soup.find_all("a", href=True):
            if "/item/main.naver?code=" in a["href"]:
                code = a["href"].split("code=")[1][:6]
                if code.isdigit():
                    bad_codes.add(code)
    except Exception as e:
        print(f"[WARN] 거래정지 종목 수집 실패: {e}")
        
    # 2. 관리종목
    mgmt_url = "https://finance.naver.com/sise/management.naver"
    try:
        res = requests.get(mgmt_url, timeout=10)
        soup = BeautifulSoup(res.content, "html.parser")
        for a in soup.find_all("a", href=True):
            if "/item/main.naver?code=" in a["href"]:
                code = a["href"].split("code=")[1][:6]
                if code.isdigit():
                    bad_codes.add(code)
    except Exception as e:
        print(f"[WARN] 관리종목 수집 실패: {e}")
        
    return bad_codes
