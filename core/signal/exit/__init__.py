"""매도·청산 신호 판별 함수 묶음.

NaN 처리 규약:
  - 모든 float 파라미터는 math.isnan()으로 검사한다.
  - 인디케이터가 NaN(워밍업 미완료)이면 신호 없음(False)을 반환한다.
  - strategy 레이어는 별도 NaN 확인 없이 반환값만 사용한다.
"""
from .atr_stop   import check_atr_stop
from .regime     import check_downtrend_exit
from .bollinger  import check_bb_upper_breakdown
from .deadcross  import check_deadcross
from .transition import check_transition_exit

__all__ = [
    "check_atr_stop",
    "check_downtrend_exit",
    "check_bb_upper_breakdown",
    "check_deadcross",
    "check_transition_exit",
]
