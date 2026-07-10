"""매수 신호 판별 함수 묶음.

NaN 처리 규약:
  - 모든 float 파라미터는 math.isnan()으로 검사한다.
  - 인디케이터가 NaN(워밍업 미완료)이면 신호 없음(False)을 반환한다.
  - strategy 레이어는 별도 NaN 확인 없이 반환값만 사용한다.
"""
from .uptrend import check_uptrend_entry1, check_uptrend_entry2, check_ma10_trigger
from .sideways import check_bb_lower_breakout

__all__ = [
    "check_uptrend_entry1",
    "check_uptrend_entry2",
    "check_ma10_trigger",
    "check_bb_lower_breakout",
]
