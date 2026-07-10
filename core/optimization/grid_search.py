"""
ADX 파라미터 Grid Search + IS score 산출
=========================================

[위험중립형 전략 — Walk-Forward 최적화 Step 1: 종목별 파라미터 탐색]

IS(In-Sample) 구간 데이터를 받아 ADX 파라미터 조합을 탐색하고
각 조합의 Calmar Ratio를 산출한 뒤 최고 점수를 IS score로 확정한다.

─────────────────────────────────────────────────────────────────────
탐색 파라미터 그리드
─────────────────────────────────────────────────────────────────────

  adx_threshold [15·20·25·30]  — 추세 확인 강도 기준
  adx_sideways  [10·15·20]     — 횡보 판별 기준
  → adx_sideways < adx_threshold 조합만 유효 (최대 9가지)

─────────────────────────────────────────────────────────────────────
IS score 결정 규칙
─────────────────────────────────────────────────────────────────────

  IS score = 유효 조합 중 최고 Calmar Ratio

  IS score > 0  → ADX 모드 활성 (추세 강도 신뢰 가능)
  IS score ≤ 0  → MA+KOSPI 모드 전환 (ADX 신뢰 불가)

─────────────────────────────────────────────────────────────────────
position_map — 투자성향별 국면-포지션 매핑
─────────────────────────────────────────────────────────────────────

  Grid Search의 IS 평가 기준은 OOS 실행 전략과 반드시 일치해야 한다.
  (IS-OOS 불일치 시 Walk-Forward 최적화가 의미를 잃음)

  따라서 포지션 값을 grid_search 내부에 하드코딩하지 않고,
  strategy 레이어(core/strategy/)가 자신의 position_map을 주입한다.

  position_map 형식:
    {
        "UPTREND":    float,   # 상승추세 포지션 (예: 1.0 = 풀롱, 1.5 = 레버리지)
        "DOWNTREND":  float,   # 하락추세 포지션 (예: 0.0 = 현금,  -1.0 = 숏)
        "SIDEWAYS":   float,   # 횡보 포지션     (예: 0.0 = 현금)
        "TRANSITION": float,   # 전환 포지션     (예: 0.0 = 현금)
    }

  DEFAULT_POSITION_MAP (위험중립형 기본값):
    UPTREND=1.0, DOWNTREND·SIDEWAYS·TRANSITION=0.0 (현금·단기채 보유)

  투자성향별 예시:
    - 위험중립형: DOWNTREND=0.0  (현금 보유)
    - 공격형:     DOWNTREND=-1.0 (숏 베팅)
    - 보수형:     UPTREND=0.5    (절반 진입)

  → core/strategy/ 구현 시 각 전략 클래스가 position_map을 정의하고
    run_grid_search()에 전달하는 방식으로 연결한다.
"""
import itertools
import numpy as np
import pandas as pd

from ..constant.values import MarketRegimeParam, ADXGridParam
from ..constant.types import StockCap, Market
from ..analytics.metrics import calc_calmar
from ..risk.cost import calc_transaction_cost
from ..signal.market_regime import calc_regime


def __calc_adx_returns(
    ohlcv:         pd.DataFrame,
    market_index:  pd.Series,
    position_map:  dict[str, float],
    adx_threshold: float,
    adx_sideways:  float,
    adx_window:    int      = MarketRegimeParam.ADX_WINDOW.value,
    cap:           StockCap = StockCap.LARGE,
    market:        Market   = Market.KOSPI,
) -> pd.Series:
    """IS 조합 평가용 일별 전략 수익률 계산.

    실전과 동일하게 calc_regime()으로 국면을 판별하고,
    주입받은 position_map으로 포지션을 결정한다.
    (IS 평가 로직 = OOS 실행 로직 → Walk-Forward 유효성 보장)
    """
    close = ohlcv["close"]

    # ── 국면 판별 (실전과 동일한 로직) ──────────────────────────────────
    regime_df = calc_regime(
        close         = close,
        high          = ohlcv["high"],
        low           = ohlcv["low"],
        market_index  = market_index,
        is_score      = 1.0,            # Grid Search는 항상 ADX 모드로 평가
        adx_threshold = adx_threshold,
        adx_sideways  = adx_sideways,
        adx_window    = adx_window,
    )

    # ── 포지션 결정 — position_map으로 국면 → 포지션 변환 ───────────────
    # strategy 레이어가 주입한 position_map을 그대로 사용한다.
    # 하드코딩 제거로 IS 평가 기준 = OOS 실행 전략이 자동 보장된다.
    position = regime_df["REGIME"].map(position_map).fillna(0.0)

    # ── 기본 수익률 (전일 포지션 × 당일 수익률, 미래 정보 사용 없음) ────────
    daily_ret     = close.pct_change().fillna(0)
    position_prev = position.shift(1).fillna(0)
    strategy_ret  = position_prev * daily_ret

    # ── 거래 비용 차감 ────────────────────────────────────────────────────
    strategy_ret = strategy_ret - calc_transaction_cost(
        market, cap, position, position_prev)

    return strategy_ret


def run_grid_search(
    ohlcv:        pd.DataFrame,
    market_index: pd.Series,
    position_map: dict[str, float] | None = None,
    cap:          StockCap = StockCap.LARGE,
    market:       Market   = Market.KOSPI,
    adx_window:   int      = MarketRegimeParam.ADX_WINDOW.value,
) -> dict:
    """IS 구간 OHLCV를 받아 ADX 파라미터를 전수 탐색하고 IS score + best_params를 반환한다.

    Parameters
    ----------
    ohlcv : pd.DataFrame
        IS 구간 OHLCV DataFrame (columns: open·high·low·close·volume).
    market_index : pd.Series
        IS 구간 시장지수 시리즈 (KOSPI·KOSDAQ 등).
    position_map : dict[str, float] | None, optional
        국면별 포지션 크기 매핑. None이면 DEFAULT_POSITION_MAP(위험중립형) 사용.

        strategy 레이어(core/strategy/)가 자신의 투자성향에 맞는 값을 주입한다.
        IS 평가 기준과 OOS 실행 전략이 반드시 일치해야 Walk-Forward가 유효하다.

        예시::

            # 위험중립형 (기본값)
            {"UPTREND": 1.0, "DOWNTREND": 0.0, "SIDEWAYS": 0.0, "TRANSITION": 0.0}

            # 공격형 (숏 포함)
            {"UPTREND": 1.5, "DOWNTREND": -1.0, "SIDEWAYS": 0.0, "TRANSITION": 0.5}

    cap : StockCap, optional
        슬리피지 계산용 종목 규모 (LARGE·MID·SMALL).
    market : Market, optional
        세금 계산용 시장 구분 (KOSPI·KOSDAQ).
    adx_window : int, optional
        ADX 계산 창 (Wilder 표준 = 14).

    Returns
    -------
    dict
        is_score : float
            유효 조합 중 최고 Calmar Ratio.
        best_params : dict | None
            {"adx_threshold": float, "adx_sideways": float}.
            IS score ≤ 0 이면 None (MA+시장지수 모드 전환).
    """
    if position_map is None:
        raise Exception(f"position_map(전략)이 올바르지 않음 >> {position_map}")

    best_score:  float       = -np.inf
    best_params: dict | None = None

    # ── 탐색 그리드 ──────────────────────────────────────────────────────
    for threshold, sideways in itertools.product(
        ADXGridParam.get_thresholds(),
        ADXGridParam.get_sideways()
    ):
        if sideways >= threshold:           # 논리적 제약: 횡보 기준 < 추세 기준
            continue

        _returns = __calc_adx_returns(
            ohlcv,
            market_index  = market_index,
            position_map  = position_map,
            adx_threshold = threshold,
            adx_sideways  = sideways,
            adx_window    = adx_window,
            cap           = cap,
            market        = market,
        )
        _score = calc_calmar((1 + _returns).cumprod())

        if _score > best_score:
            best_score  = _score
            best_params = {
                "adx_threshold": float(threshold),   # ADXGridParam(float) → 순수 float
                "adx_sideways":  float(sideways),
            }

    return {
        "is_score":   best_score,
        "best_params": best_params if best_score > 0 else None,
    }
