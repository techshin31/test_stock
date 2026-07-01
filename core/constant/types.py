"""
OrderSide, OrderType, OrderStatus, TimeFrame 등
"""
import enum 

# 시장 국면 판별 — 4국면: SIDEWAYS / UPTREND / DOWNTREND / TRANSITION
class MarketRegime(enum.Enum):
    SIDEWAYS   = "횡보(방향 없이 좌우로 움직이는 장세)"
    UPTREND    = "상승(방향 있는 장세)"
    DOWNTREND  = "하락(방향 있는 장세)"
    TRANSITION = "전환(국면 전환 중인 장세)"

    @property
    def description(self) -> str:
        """국면 설명 반환"""
        return self.value
    
class StockCap(enum.Enum):
    """슬리피지 계산용 종목 규모 구분"""

    LARGE  = "대형주"
    MID    = "중형주"
    SMALL  = "소형주"

    @property
    def description(self) -> str:
        return self.value


class Market(enum.Enum):
    """세금 계산용 시장 구분"""

    KOSPI  = (".KS", "^KS11", "코스피")
    KOSDAQ = (".KQ", "^KQ11", "코스닥")

    @property
    def suffix(self) -> str:
        return self.value[0]
    
    @property
    def ticker(self) -> str:
        return self.value[1]
    
    @property
    def description(self) -> str:
        return self.value[2]
    


class UniverseStatus(enum.Enum):
    """포트폴리오 유니버스 내 종목 운용 상태"""

    ACTIVE    = "정상 매매 가능"
    SELL_ONLY = "매도 전용"
    REMOVED   = "제거됨"

    @property
    def description(self) -> str:
        return self.value


class TradingMode(enum.Enum):
    """실전 트레이딩 실행 모드"""

    DRY_RUN = "주문 계획만 생성"
    PAPER = "모의투자 주문 실행"
    LIVE = "실계좌 주문 실행"

    @property
    def description(self) -> str:
        return self.value


class OrderSide(enum.Enum):
    """주문 방향"""

    BUY = "매수"
    SELL = "매도"

    @property
    def description(self) -> str:
        return self.value


class OrderType(enum.Enum):
    """주문 유형"""

    MARKET = "시장가"
    LIMIT = "지정가"

    @property
    def description(self) -> str:
        return self.value


class OrderRequestType(enum.Enum):
    """주문 요청 유형"""

    SUBMIT = "신규 주문"
    MODIFY = "주문 정정"
    CANCEL = "주문 취소"

    @property
    def description(self) -> str:
        return self.value


class OrderStatus(enum.Enum):
    """broker 주문 상태를 QuantPilot 내부 상태로 정규화한 값 — .name이 DB ORDER_STATUS_CODE와 1:1 대응"""

    PENDING  = "대기"
    SUBMITTED = "제출됨"
    ACCEPTED = "접수됨"
    PARTIAL  = "부분 체결"
    FILLED   = "완전 체결"
    MODIFIED = "정정 완료"
    CANCELLED = "취소"
    REJECTED = "거부"
    EXPIRED  = "만료"

    @property
    def description(self) -> str:
        return self.value


class ReconciliationStatus(enum.Enum):
    """계획 대비 실제 주문/체결 비교 결과"""

    MATCHED = "계획대로 체결"
    PARTIAL = "부분 일치"
    MISMATCHED = "불일치"
    MISSING_ORDER = "계획 주문 누락"
    EXTRA_ORDER = "계획 외 주문"
    FAILED = "검증 실패"

    @property
    def description(self) -> str:
        return self.value


class ReconciliationReasonCode(enum.Enum):
    """계획과 실제 결과가 달라진 이유 코드"""

    PLANNED = "계획대로 실행"
    PARTIAL_FILL = "부분 체결"
    NOT_FILLED = "미체결"
    REJECTED = "주문 거부"
    CANCELLED = "주문 취소"
    MANUAL_ORDER = "수동 주문 또는 외부 주문"
    CASH_SHORTAGE = "현금 부족"
    SELLABLE_QUANTITY_SHORTAGE = "매도 가능 수량 부족"
    PRICE_NOT_REACHED = "지정가 미도달"
    MARKET_CLOSED = "장 운영 상태"
    API_ERROR = "API 오류"
    UNKNOWN = "원인 미상"

    @property
    def description(self) -> str:
        return self.value


class Tickers(enum.Enum):
    """티커 구분"""

    KOSPI_INDEX = ("^KS11", "코스피 지수")
    BOND_ETF = ("153130.KS", "KODEX 단기채권 ETF")
    INVERSE_ETF = ("153131.KS", "KODEX 인버스 ETF")

    @property
    def description(self) -> str:
        return self.value[1]

    @property
    def ticker(self) -> str:
        return self.value[0]
