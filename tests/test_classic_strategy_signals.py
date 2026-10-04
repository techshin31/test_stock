"""Exercise the classic strategies without mocking their indicator calculations."""
import numpy as np
import pandas as pd
import pytest

from core.strategy.aggressive import AggressiveStrategy
from core.strategy.risk_neutral import RiskNeutralStrategy
from core.strategy.state import StrategyState


@pytest.fixture
def params():
    return {
        'entry1_size': 0.4, 'entry2_size': 0.7, 'entry2_window': 60,
        'sideways_size': 0.3, 'deadcross_keep': 0.1, 'transition_keep': 0.4,
        'downtrend_position': 0.0, 'use_ma10_trigger': False,
        'benchmark': 'test', 'target_cagr': 0.08, 'warning_cagr': 0.05,
        'target_mdd': -0.3, 'warning_mdd': -0.4,
        'target_mdd_duration': 24, 'warning_mdd_duration': 36,
        'atr_period': 14, 'bb_window': 20, 'bb_std': 2.0, 'ma10_window': 10,
        'enable_news_signal': False,
    }


@pytest.fixture
def market_frames():
    dates = pd.bdate_range('2025-01-01', periods=65)
    close = pd.Series(100 + np.arange(len(dates)) * 0.2, index=dates)
    ohlcv = pd.DataFrame({
        'open': close, 'high': close + 1, 'low': close - 1,
        'close': close, 'volume': 1000,
    })
    regimes = pd.DataFrame({
        'REGIME': ['TRANSITION'] * 60 + ['UPTREND'] * 4 + ['DOWNTREND'],
        'ma_s': close.rolling(20).mean(),
        'ma_m': close.rolling(60).mean(),
    })
    return ohlcv, regimes


@pytest.mark.parametrize('strategy_type', [RiskNeutralStrategy, AggressiveStrategy])
def test_classic_strategy_entries_and_downtrend_exit(strategy_type, params, market_frames):
    ohlcv, regimes = market_frames
    params['use_ma10_trigger'] = strategy_type is AggressiveStrategy
    strategy = strategy_type(params)
    state = StrategyState('test', '005930', ohlcv.index[0].date(), 'TRANSITION', 0.0)

    signals, metadata = strategy.make_signals_with_metadata(ohlcv, regimes, state)

    expected = [0.4, 0.7, 0.0] if strategy_type is RiskNeutralStrategy else [0.7, -0.5]
    assert signals.dropna().tolist() == expected
    assert signals.iloc[:60].isna().all()
    assert metadata.index.equals(ohlcv.index)
    assert state.position == expected[-1]
    assert state.regime == 'DOWNTREND'
    assert state.trading_date == ohlcv.index[-1].date()


@pytest.mark.parametrize('strategy_type', [RiskNeutralStrategy, AggressiveStrategy])
def test_classic_strategy_atr_stop_uses_prior_day_volatility(strategy_type, params, market_frames):
    ohlcv, regimes = market_frames
    ohlcv, regimes = ohlcv.iloc[:-1].copy(), regimes.iloc[:-1].copy()
    # A drop after entry must liquidate even though the regime still says UPTREND.
    ohlcv.loc[ohlcv.index[-1], ['open', 'high', 'low', 'close']] = [90, 91, 89, 90]
    params['use_ma10_trigger'] = strategy_type is AggressiveStrategy
    strategy = strategy_type(params)

    signals, metadata = strategy.make_signals_with_metadata(ohlcv, regimes)

    assert signals.iloc[-1] == 0.0
    if strategy_type is RiskNeutralStrategy:
        assert metadata.iloc[-1]['exit_reason'] == 'ATR_STOP'
        assert metadata.iloc[-1]['prev_atr'] == pytest.approx(2.0)
