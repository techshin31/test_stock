import enum 

class InsufficientHistoryPolicy(enum.Enum):
    """백테스팅 시, 충분한 과거 데이터가 없는 경우의 처리 정책을 정의하는 열거형입니다."""
    
    RAISE = "raise"  # 충분한 과거 데이터가 없는 경우 예외를 발생시킨다 (백테스트 실패)
    ALLOW = "allow"  # 충분한 과거 데이터가 없어도 백테스트를 허용한다 (해당 종목/기간은 수익률 계산에서 제외하지만, 백테스트 전체는 계속 진행)
    EXCLUDE = "exclude"  # 해당 종목/기간을 완전히 제외한다 (백테스트에서 아예 고려하지 않음)

