"""포트폴리오 배분용 모멘텀 계산."""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.constant.types import MarketRegime


MOMENTUM_WINDOWS: dict[str, int] = {
    MarketRegime.UPTREND.name:    126,
    MarketRegime.TRANSITION.name: 63,
    MarketRegime.SIDEWAYS.name:   21,
}


def calc_momentum(close: pd.DataFrame, window: int) -> pd.DataFrame:
    """고정 기간 모멘텀 수익률을 계산한다."""
    if window <= 0:
        raise ValueError(f"window는 1 이상이어야 합니다. >> {window}")
    return close / close.shift(window) - 1.0


def calc_regime_momentum(
    close: pd.DataFrame,
    regime: pd.Series,
    windows: dict[str, int] | None = None,
) -> pd.DataFrame:
    """국면별 윈도우를 적용한 모멘텀 점수를 계산한다.

    DOWNTREND는 신규 매수 배분에 쓰지 않으므로 0.0을 반환한다.
    """
    windows = windows or MOMENTUM_WINDOWS
    regime = regime.reindex(close.index)
    result = pd.DataFrame(np.nan, index=close.index, columns=close.columns, dtype=float)

    for regime_name, window in windows.items():
        mask = regime == regime_name
        if mask.any():
            result.loc[mask] = calc_momentum(close, window).loc[mask]

    return result.fillna(0.0).clip(lower=0.0)


def calc_universe_momentum(
    close: pd.DataFrame,
    regime_dict: dict[str, pd.DataFrame],
    tickers: list[str],
) -> dict[str, pd.DataFrame]:
    """Calculate regime-aware momentum for multiple tickers."""
    return {
        ticker: calc_regime_momentum(
            close[[ticker]],
            regime_dict[ticker]["REGIME"],
        )
        for ticker in tickers
    }
