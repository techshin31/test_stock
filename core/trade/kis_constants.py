from __future__ import annotations

from enum import Enum, IntEnum


class KisEnv(str, Enum):
    PAPER = "paper"
    REAL  = "real"


class BaseUrl(str, Enum):
    PAPER    = "https://openapivts.koreainvestment.com:29443"
    REAL     = "https://openapi.koreainvestment.com:9443"
    WS_PAPER = "ws://ops.koreainvestment.com:31000"
    WS_REAL  = "ws://ops.koreainvestment.com:21000"


class TrId(str, Enum):
    # 잔고 조회
    BALANCE_PAPER = "VTTC8434R"
    BALANCE_REAL  = "TTTC8434R"
    # 현재가 조회
    PRICE = "FHKST01010100"
    # 호가 조회
    ORDERBOOK = "FHKST01010200"
    # 매수 주문
    BUY_PAPER = "VTTC0012U"
    BUY_REAL  = "TTTC0012U"
    # 매도 주문
    SELL_PAPER = "VTTC0011U"
    SELL_REAL  = "TTTC0011U"
    # 정정/취소 주문
    REVISE_CANCEL_PAPER = "VTTC0013U"
    REVISE_CANCEL_REAL  = "TTTC0013U"
    # 주문 내역 조회
    ORDER_HISTORY_PAPER = "VTTC0081R"
    ORDER_HISTORY_REAL  = "TTTC0081R"
    # 매수가능금액 조회
    BUYABLE_PAPER = "VTTC8908R"
    BUYABLE_REAL  = "TTTC8908R"
    # 실시간 WebSocket
    WS_EXECUTION = "H0STCNT0"   # 실시간 체결
    WS_ORDERBOOK = "H0STASP0"   # 실시간 호가


class OrdDvsn(str, Enum):
    LIMIT  = "00"   # 지정가
    MARKET = "01"   # 시장가


class SllBuyDvsnCd(str, Enum):
    ALL  = "00"   # 전체
    SELL = "01"   # 매도
    BUY  = "02"   # 매수


class CcldDvsn(str, Enum):
    ALL     = "00"   # 전체
    FILLED  = "01"   # 체결
    PENDING = "02"   # 미체결


class RvseCnclDvsnCd(str, Enum):
    MODIFY = "01"   # 정정
    CANCEL = "02"   # 취소


class MrktDivCode(str, Enum):
    STOCK = "J"   # 국내 주식


class PriceSign(str, Enum):
    UPPER_LIMIT = "1"   # 상한
    RISE        = "2"   # 상승
    FLAT        = "3"   # 보합
    FALL        = "4"   # 하락
    LOWER_LIMIT = "5"   # 하한

    @property
    def label(self) -> str:
        _map = {"1": "↑↑", "2": "↑ ", "3": "- ", "4": "↓ ", "5": "↓↓"}
        return _map[self.value]

    @classmethod
    def to_label(cls, code: str) -> str:
        try:
            return cls(code).label
        except ValueError:
            return "- "


class ExecType(str, Enum):
    BUY  = "1"   # 매수 체결
    SELL = "5"   # 매도 체결


class WsTrType(str, Enum):
    SUBSCRIBE   = "1"   # 구독 등록
    UNSUBSCRIBE = "2"   # 구독 해제


class CustType(str, Enum):
    INDIVIDUAL = "P"   # 개인
    CORPORATE  = "B"   # 법인


class H0stcnt0Field(IntEnum):
    """H0STCNT0(실시간 체결) WebSocket 응답 필드 인덱스."""
    STOCK_CODE  = 0
    TIME        = 1
    PRICE       = 2
    SIGN        = 3    # 전일대비부호
    CHANGE      = 4    # 전일대비 (원)
    CHANGE_RATE = 5    # 전일대비율 (%)
    OPEN        = 7    # 시가
    HIGH        = 8    # 고가
    LOW         = 9    # 저가
    ASK1        = 10   # 매도호가1
    BID1        = 11   # 매수호가1
    VOLUME      = 12   # 체결거래량
    ACC_VOLUME  = 13   # 누적거래량
    ACC_AMOUNT  = 14   # 누적거래대금
    EXEC_TYPE   = 21   # 체결구분 (ExecType 참조)


class TaxRate(str, Enum):
    COMMISSION     = "0.00015"   # HTS 온라인 약 0.015%
    SECURITIES_TAX = "0.0020"    # 증권거래세 0.2% (KOSPI/KOSDAQ 공통, 2024~)

    @property
    def rate(self) -> float:
        return float(self)
