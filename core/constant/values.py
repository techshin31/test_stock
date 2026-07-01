"""
숫자/문자열 리터럴 (수수료, 운영시간 등)

슬리피지 — 호가 스프레드로 인한 예상가 vs 체결가 차이
수수료 — 매수/매도 시 증권사 수수료 (보통 0.015~0.05%)
세금 — 매도 시 증권거래세 (코스피 0.18%, 코스닥 0.18%), 금융소득세
"""
import enum
from .types import StockCap

class MarketRegimeParam(enum.IntEnum):
    """시장 국면 판별 고정 파라미터 (WF 최적화 대상 제외)"""
    MA_SHORT   = 20    # 단기 이동평균
    MA_MID     = 60    # 중기 이동평균
    MA_LONG    = 120   # 장기 이동평균
    ADX_WINDOW = 14    # ADX 계산 창 (Wilder 표준)
    KOSPI_MA   = 60    # KOSPI 필터 이동평균 (KOSPI_MA60)

    @classmethod
    def get_ma_windows(cls) -> tuple:
        """MA 창 튜플 반환 (calc_regime의 ma_windows 인자에 직접 전달)"""
        return (cls.MA_SHORT.value, cls.MA_MID.value, cls.MA_LONG.value)

class TradingCostParam(enum.IntEnum):
    """
    명시적 비용 (Explicit)  : 수수료, 세금
    거래 비용 고정 파라미터 — 단위: 1/100_000 (소수점 회피)
    실제 비율로 쓸 때는 .rate() 사용

    예) TradingCostParam.COMMISSION_BUY.rate()  → 0.00015
    """
    COMMISSION_BUY      = 15    # 매수 수수료  0.015%
    COMMISSION_SELL     = 15    # 매도 수수료  0.015%
    TAX_KOSPI           = 180   # 코스피 증권거래세  0.18%
    TAX_KOSDAQ          = 180   # 코스닥 증권거래세  0.18%

    def rate(self) -> float:
        """1/100_000 단위 정수 → 소수 비율로 변환"""
        return self.value / 100_000

class SlippageParam(enum.IntEnum):
    """
    암묵적 비용 (Implicit)  : 슬리피지, 시장 충격
    슬리피지 추정 파라미터 — 단위: 1/100_000 (소수점 회피)
    실제 비율로 쓸 때는 .rate() 사용

    슬리피지 원인
        - 호가 스프레드   : 매수호가/매도호가 간 갭
        - 시장 충격       : 대량 주문이 가격을 밀어내는 효과
        - 체결 지연       : 신호 발생 → 실제 체결 사이의 가격 변동
    """
    SPREAD_LARGE_CAP    = 5     # 대형주 호가 스프레드  0.005%
    SPREAD_MID_CAP      = 10    # 중형주 호가 스프레드  0.010%
    SPREAD_SMALL_CAP    = 30    # 소형주 호가 스프레드  0.030%
    MARKET_IMPACT       = 10    # 시장 충격 (기본 추정) 0.010%
    EXECUTION_DELAY     = 5     # 체결 지연 슬리피지    0.005%

    def rate(self) -> float:
        """1/100_000 단위 정수 → 소수 비율로 변환"""
        return self.value / 100_000

    @classmethod
    def total_slippage_rate(cls, cap: StockCap) -> float:
        """
        단방향(매수 or 매도) 1회 총 슬리피지 비율 반환
        cap: 'LARGE' | 'MID' | 'SMALL'
        """
        spread = cls[f"SPREAD_{cap.name}_CAP"]
        return spread.rate() + cls.MARKET_IMPACT.rate() + cls.EXECUTION_DELAY.rate()

class WalkForwardParam(enum.IntEnum):
    """
    Walk-Forward 최적화 고정 구간 파라미터

    IS 12개월 고정 근거:
      MA120 신뢰도 확보에 최소 6개월 이상 데이터가 필요하다.
      12개월(≈252 거래일)은 MA120 워밍업 + 충분한 평가 구간을 확보한다.

    OOS 3개월 고정 근거:
      분기 실적 발표 주기(3·6·9·12월)와 통일해 관리 포인트를 단일화한다.
    """
    IS_MONTHS  = 12   # IS 구간 (학습) — MA120 워밍업 + 평가 구간 확보
    OOS_MONTHS = 3    # OOS 구간 (검증) — 분기 실적 발표 주기와 통일


class ADXGridParam(float, enum.Enum):
    """
    ADX Grid Search 탐색 파라미터
    WF 최적화 대상 — IS 구간에서 조합 탐색

    adx_threshold : 추세 확인 강도 기준  [15.0·20.0·25.0·30.0]
    adx_sideways  : 횡보 판별 기준       [10.0·15.0·20.0]
    → 4 × 3 = 12가지 조합

    float 상속 이유:
      ADX 기준값은 pd.Series(float)와 직접 비교하는 값이므로
      처음부터 float으로 정의해 암묵적 형변환 없이 사용한다.
      (IntEnum으로 정의하면 외부에서 float() 변환이 필요해짐)
    """
    THRESHOLD_1 = 15.0   # 추세 확인 강도 기준 1
    THRESHOLD_2 = 20.0   # 추세 확인 강도 기준 2
    THRESHOLD_3 = 25.0   # 추세 확인 강도 기준 3
    THRESHOLD_4 = 30.0   # 추세 확인 강도 기준 4

    SIDEWAYS_1  = 10.0   # 횡보 판별 기준 1
    SIDEWAYS_2  = 15.0   # 횡보 판별 기준 2
    SIDEWAYS_3  = 20.0   # 횡보 판별 기준 3

    @classmethod
    def get_thresholds(cls) -> list[float]:
        """adx_threshold 후보 리스트 반환"""
        return [cls.THRESHOLD_1, cls.THRESHOLD_2, cls.THRESHOLD_3, cls.THRESHOLD_4]

    @classmethod
    def get_sideways(cls) -> list[float]:
        """adx_sideways 후보 리스트 반환"""
        return [cls.SIDEWAYS_1, cls.SIDEWAYS_2, cls.SIDEWAYS_3]


