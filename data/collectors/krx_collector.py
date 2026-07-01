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


def fetch_krx_suspended_codes(trade_date: str | None = None) -> set[str]:
    """거래정지·관리종목 종목코드 세트를 반환한다.

    FinanceDataReader는 거래정지 목록을 제공하지 않으므로 빈 세트를 반환한다.
    status_code는 ACTIVE/DELISTED 두 값만 사용되며 SUSPENDED 판별은 생략된다.

    Returns
    -------
    set[str]
        항상 빈 세트.
    """
    return set()
