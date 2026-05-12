"""파라미터 그리드 서치 + Walk-Forward Optimization — 전략과 독립적인 최적화 유틸리티"""

import itertools
from typing import Callable

import numpy as np
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


def walk_forward(
    close: pd.Series,
    strategy_fn: Callable,
    param_grid: dict[str, list],
    train_months: int = 12,
    test_months: int = 6,
    fees: float = 0.0015,
    slippage: float = 0.001,
    metric: str = "sharpe_ratio",
    warmup_days: int = 150,
    **data_kwargs,
) -> dict:
    """
    Walk-Forward Optimization

    학습 구간에서 최적 파라미터 탐색 → 검증 구간에서 해당 파라미터로 백테스트 → 슬라이딩 반복

    Parameters
    ----------
    close         : 종가 시계열
    strategy_fn   : (close, **data_kwargs, **params, fees, slippage) -> vbt.Portfolio
    param_grid    : 최적화할 파라미터 후보 {'adx_threshold': [15, 20, 25, 30]}
    train_months  : 학습 구간 길이 (월)
    test_months   : 검증 구간 길이 (월)
    metric        : 최적화 기준 ('sharpe_ratio' | 'total_return' | 'calmar_ratio')
    warmup_days   : 검증 시 지표 warm-up용 버퍼 일수 (MA120 기준 150 권장)
    **data_kwargs : 추가 데이터 (high=, low=, volume=)

    Returns
    -------
    dict:
      'windows'      : 구간별 결과 리스트 (train/test 기간, 최적 파라미터, 검증 포트폴리오)
      'equity_curve' : 검증 구간을 이어붙인 누적 자산 곡선 (정규화, 시작=1.0)
      'n_windows'    : 총 윈도우 수
    """
    idx = close.index
    windows = []
    period_start = idx[0]

    while True:
        train_end = period_start + pd.DateOffset(months=train_months)
        test_end  = train_end   + pd.DateOffset(months=test_months)

        if test_end > idx[-1] + pd.Timedelta(days=1):
            break

        train_mask = (idx >= period_start) & (idx < train_end)
        test_mask  = (idx >= train_end)    & (idx < test_end)

        if train_mask.sum() < 130 or test_mask.sum() < 5:
            period_start += pd.DateOffset(months=test_months)
            continue

        # ── 1. 학습: 그리드 서치로 최적 파라미터 탐색 ────────────────────────
        tr_close = close[train_mask]
        tr_data  = {k: v[train_mask] for k, v in data_kwargs.items()}

        keys   = list(param_grid.keys())
        combos = list(itertools.product(*param_grid.values()))

        best_score  = -np.inf
        best_params = None   # None = 유효한 최적값 없음
        scan_rows   = []

        for combo in combos:
            params = dict(zip(keys, combo))
            try:
                pf    = strategy_fn(tr_close, **tr_data, **params, fees=fees, slippage=slippage)
                score = getattr(pf, metric)()
                # NaN: 거래 없음(정의 불가) / -inf: 수학적 발산 — 둘 다 NaN으로 통일해 저장
                display_score = score if np.isfinite(score) else np.nan
                scan_rows.append({**params, metric: display_score})
                if np.isfinite(score) and score > best_score:
                    best_score  = score
                    best_params = params
            except Exception:
                continue

        # 유효한 score가 하나도 없으면 이전 윈도우 최적값 재사용 (하락장 대응)
        if best_params is None:
            if windows:
                best_params = windows[-1]["best_params"]
            else:
                best_params = {k: vals[len(vals) // 2] for k, vals in param_grid.items()}

        # ── 2. 검증: warm-up 버퍼 포함 슬라이스로 백테스트 후 검증 구간만 추출 ─
        warmup_start = train_end - pd.Timedelta(days=int(warmup_days * 1.5))
        warmup_start = max(warmup_start, idx[0])

        wu_mask  = (idx >= warmup_start) & (idx < test_end)
        ts_close = close[wu_mask]
        ts_data  = {k: v[wu_mask] for k, v in data_kwargs.items()}

        test_value = None
        try:
            pf        = strategy_fn(ts_close, **ts_data, **best_params, fees=fees, slippage=slippage)
            pf_value  = pf.value()
            test_dates = close[test_mask].index
            test_value = pf_value.reindex(test_dates, method="nearest")
        except Exception:
            period_start += pd.DateOffset(months=test_months)
            continue

        windows.append({
            "train_start": period_start,
            "train_end":   train_end,
            "test_start":  close[test_mask].index[0],
            "test_end":    close[test_mask].index[-1],
            "best_params": best_params,
            "best_score":  round(best_score, 4),
            "scan":        pd.DataFrame(scan_rows).sort_values(metric, ascending=False).reset_index(drop=True),
            "test_value":  test_value,
        })

        period_start += pd.DateOffset(months=test_months)

    # ── 검증 구간 자산 곡선 이어붙이기 ───────────────────────────────────────
    parts      = []
    multiplier = 1.0
    for w in windows:
        tv = w["test_value"]
        if tv is None or len(tv) == 0:
            continue
        normalized  = tv / tv.iloc[0] * multiplier
        multiplier  = normalized.iloc[-1]
        parts.append(normalized)

    equity_curve = pd.concat(parts) if parts else pd.Series(dtype=float)

    return {
        "windows":      windows,
        "equity_curve": equity_curve,
        "n_windows":    len(windows),
    }
