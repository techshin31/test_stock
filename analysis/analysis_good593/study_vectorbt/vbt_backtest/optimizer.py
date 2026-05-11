"""파라미터 그리드 서치 — 전략과 독립적인 최적화 유틸리티"""

import itertools
from typing import Callable

import pandas as pd
import vectorbt as vbt


def grid_search(
    close: pd.Series,
    strategy_fn: Callable[..., vbt.Portfolio],
    param_grid: dict[str, list],
    fees: float = 0.001,
) -> pd.DataFrame:
    """
    전략 파라미터 그리드 서치

    Parameters
    ----------
    close       : 종가 시계열
    strategy_fn : run_backtest 형태의 함수 (close, **params, fees=...) -> Portfolio
    param_grid  : 파라미터명 → 후보 값 목록
                  예) {"fast_window": [5, 10, 20], "slow_window": [60, 90]}
    fees        : 수수료

    Returns
    -------
    DataFrame : 파라미터 조합 + total_return, sharpe_ratio, max_drawdown, win_rate, trade_count
                샤프비율 내림차순 정렬

    Examples
    --------
    >>> from vbt_backtest.strategies import golden_cross
    >>> from vbt_backtest.optimizer import grid_search
    >>> result = grid_search(
    ...     close,
    ...     golden_cross.run_backtest,
    ...     param_grid={"fast_window": [5, 10, 20], "slow_window": [60, 90]},
    ... )
    """
    keys = list(param_grid.keys())
    values = list(param_grid.values())

    results = []
    for combo in itertools.product(*values):
        params = dict(zip(keys, combo))
        try:
            pf = strategy_fn(close, **params, fees=fees)
            results.append(
                {
                    **params,
                    "total_return": pf.total_return(),
                    "sharpe_ratio": pf.sharpe_ratio(),
                    "max_drawdown": pf.max_drawdown(),
                    "win_rate": pf.trades.win_rate(),
                    "trade_count": pf.trades.count(),
                }
            )
        except Exception:
            continue

    return pd.DataFrame(results).sort_values("sharpe_ratio", ascending=False)
