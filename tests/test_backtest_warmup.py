from datetime import date
import numpy as np
import pandas as pd
import pytest
from core.backtest.config import BacktestConfig
from core.backtest.engine import run_backtest
from core.constant.types import Market,StockCap
from core.strategy.fa_ta_momentum import FaTaMomentumStrategy


def inputs():
    dates=pd.bdate_range('2024-01-01',periods=300)
    close=pd.Series(np.linspace(100,250,300),index=dates)
    frame=pd.DataFrame({'open':close,'high':close+1,'low':close-1,'close':close,'volume':1000,'fa_score':80.,'is_eligible':True,'debt_ratio':.5,'score_confidence':1.,'fa_is_stale':False})
    cfg=BacktestConfig(strategy=FaTaMomentumStrategy({}),start_date=dates[280].date(),end_date=dates[289].date(),initial_capital=10_000_000,initial_universe=['005930.KS'],market=Market.KOSPI,cap=StockCap.LARGE,market_index=close,min_history_days=252,use_prestart_history=True)
    return frame,cfg


def test_short_evaluation_uses_prior_indicators_without_prestart_positions(monkeypatch):
    monkeypatch.setattr('core.backtest.engine.run_walk_forward',lambda **kwargs:[])
    frame,cfg=inputs()
    result=run_backtest(cfg,{'005930.KS':frame.loc[:str(cfg.end_date)]})
    assert len(result.equity_curve)==10
    assert result.equity_curve.index.min().date()==cfg.start_date
    assert not result.excluded_tickers
    metadata=result.signal_metadata['005930.KS']
    assert metadata.iloc[0]['signal_reason'].startswith('DYNAMIC_ENTRY')
    assert result.signals['005930.KS'].iloc[0]>0
    assert not result.lookahead_warnings


def test_future_bars_never_count_toward_minimum_history(monkeypatch):
    monkeypatch.setattr('core.backtest.engine.run_walk_forward',lambda **kwargs:[])
    frame,cfg=inputs();cfg.start_date=frame.index[20].date();cfg.end_date=frame.index[30].date()
    with pytest.raises(ValueError,match='no OHLCV rows'):run_backtest(cfg,{'005930.KS':frame})
