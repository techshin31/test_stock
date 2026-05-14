"""
vbt_backtest — vectorbt 기반 백테스팅 패키지

빠른 시작
---------
# yfinance 데이터로 백테스트
from vbt_backtest.data import load_close
from vbt_backtest.strategies import golden_cross
from vbt_backtest.optimizer import grid_search

close = load_close('AAPL', start='2018-01-01', end='2023-12-31')
pf = golden_cross.run_backtest(close)

# 사용자 CSV 데이터로 백테스트
from vbt_backtest.data import load_csv
close = load_csv('data/samsung.csv')
pf = golden_cross.run_backtest(close)

# 파라미터 최적화
result = grid_search(
    close,
    golden_cross.run_backtest,
    param_grid={"fast_window": [5, 10, 20], "slow_window": [60, 90]},
)
"""

from .optimizer import grid_search
from . import strategies
from . import data
from . import portfolio_backtest
from . import config
