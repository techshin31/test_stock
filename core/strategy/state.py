"""
트레이딩 전용 전략 상태 모델
=============================

[역할]

  매일 장 마감 후 전략이 어떤 상태인지를 담는 데이터 모델.
  트레이딩 앱(apps/trader/)이 다음날 make_signals() 호출 시
  이전 거래일 상태를 이어받기 위해 사용한다.

  백테스팅에서는 make_signals()가 전체 OHLCV로 자체 상태를 계산하므로
  StrategyState가 필요 없다.

  이 모델은 순수 데이터 구조만 정의한다 (DB 접근 없음). DB에 저장하지
  않고, 매 호출마다 OHLCV 전체 기간을 백테스트 모드로 재계산해 사용한다.

─────────────────────────────────────────────────────────────────
entry1_days_elapsed 설계 근거
─────────────────────────────────────────────────────────────────

  "entry1 후 60거래일 이내" 조건을 처리하기 위해
  entry1_date가 아닌 경과 거래일 수(entry1_days_elapsed)를 추적한다.

  이유:
    entry1_date가 OHLCV 윈도우 바깥(이전 분기)에 있을 경우,
    make_signals() 안에서 날짜 인덱스로 경과 거래일을 역산하면
    KeyError가 발생하거나 캘린더 날짜와 거래일 수가 불일치한다.
    → 거래일 카운터를 직접 보존하면 이 문제를 피할 수 있다.

  값 규칙:
    entry1 발생일  : entry1_days_elapsed = 0
    다음 거래일    : entry1_days_elapsed = 1
    60거래일 후    : entry1_days_elapsed = 60  (2차 매수 마지막 가능일)
    61거래일 후    : entry1_days_elapsed = 61  (2차 매수 창 종료)
    포지션 청산 시 : entry1_date = None, entry1_days_elapsed = None
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class StrategyState:
    """단일 종목의 전략 상태 스냅샷.

    Attributes
    ----------
    strategy_type : str
        InvestmentType.name 값 (예: "RISK_NEUTRAL", "AGGRESSIVE").
        RDB PK의 일부.
    ticker : str
        종목코드 (예: "005930").
        RDB PK의 일부.
    trading_date : date
        이 상태가 기록된 거래일 (마지막 갱신일).
    regime : str
        직전 국면. MarketRegime.name 값
        (예: "UPTREND", "DOWNTREND", "SIDEWAYS", "TRANSITION").
        make_signals() 루프에서 prev_regime으로 사용된다.
    position : float
        현재 보유 비중.
        0.0 ~ 1.0: 롱 포지션 / -1.0: 인버스 ETF (적극투자형 DOWNTREND).
    entry1_date : date | None
        1차 매수 발생일. 포지션 미보유 또는 청산 시 None.
    entry1_days_elapsed : int | None
        entry1 발생 후 경과 거래일 수.
        entry1_date가 None이면 반드시 None.
        entry1_date가 있으면 0 이상의 정수.

    Notes
    -----
    make_signals(state=state) 호출 후 state는 in-place로 갱신된다.
    갱신 후 repo.save(state)를 호출해 RDB에 반영해야 한다.

    Examples
    --------
    신규 종목 첫 거래일 (포지션 없음)::

        state = StrategyState(
            strategy_type       = "RISK_NEUTRAL",
            ticker              = "005930",
            trading_date        = date.today(),
            regime              = "TRANSITION",
            position            = 0.0,
            entry1_date         = None,
            entry1_days_elapsed = None,
        )

    1차 매수 후 다음날 상태::

        state = StrategyState(
            strategy_type       = "RISK_NEUTRAL",
            ticker              = "005930",
            trading_date        = date(2025, 3, 5),
            regime              = "UPTREND",
            position            = 0.4,
            entry1_date         = date(2025, 3, 4),
            entry1_days_elapsed = 1,
        )
    """
    strategy_type:       str
    ticker:              str
    trading_date:        date
    regime:              str
    position:            float
    entry1_date:         date | None = field(default=None)
    entry1_days_elapsed: int  | None = field(default=None)

    def reset_entry(self) -> None:
        """포지션 청산 시 entry 관련 상태를 초기화한다."""
        self.entry1_date         = None
        self.entry1_days_elapsed = None

    def open_entry1(self, trading_date: date) -> None:
        """1차 매수 발생 시 entry 상태를 기록한다."""
        self.entry1_date         = trading_date
        self.entry1_days_elapsed = 0

    def tick_entry1(self) -> None:
        """거래일 경과 시 entry1_days_elapsed를 1 증가시킨다.

        루프 내 매일 장 마감 후 호출한다.
        entry1_date가 None이면 아무것도 하지 않는다.
        """
        if self.entry1_days_elapsed is not None:
            self.entry1_days_elapsed += 1

    def is_entry2_available(self, entry2_window: int) -> bool:
        """2차 매수 창(entry2_window 거래일) 이내인지 확인한다.

        Parameters
        ----------
        entry2_window : int
            2차 매수 허용 거래일 수 (예: 60).

        Returns
        -------
        bool
            entry1_date가 있고 entry1_days_elapsed <= entry2_window이면 True.
        """
        return (
            self.entry1_date         is not None
            and self.entry1_days_elapsed is not None
            and self.entry1_days_elapsed <= entry2_window
        )
