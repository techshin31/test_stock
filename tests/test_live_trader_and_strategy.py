import pandas as pd
import numpy as np
from core.strategy.fa_ta_momentum import FaTaMomentumStrategy
from core.execution.trader import LiveTrader

def test_fa_ta_momentum_strategy_signals():
    params = {
        "entry_size": 0.2,
        "ma_window": 10,
        "ma_window_fast": 5,
        "fa_score_min": 60.0,
        "fa_score_exit": 40.0,
        "debt_ratio_max": 2.0,
    }
    strategy = FaTaMomentumStrategy(params)
    
    # Create mock OHLCV with FA metrics
    dates = pd.date_range(start="2026-01-01", periods=20, freq="D")
    ohlcv = pd.DataFrame({
        "open": np.linspace(100, 200, 20),
        "high": np.linspace(105, 205, 20),
        "low": np.linspace(95, 195, 20),
        "close": np.linspace(100, 200, 20),  # strictly increasing
        "volume": [1000] * 20,
        "fa_score": [75.0] * 20,
        "is_eligible": [True] * 20,
        "debt_ratio": [1.2] * 20,
    }, index=dates)
    
    regime_df = pd.DataFrame({"REGIME": ["UPTREND"] * 20}, index=dates)
    
    # UPTREND regime with high fa_score and positive momentum -> BUY signal
    signals = strategy.make_signals(ohlcv, regime_df)
    non_nan_signals = signals.dropna()
    
    assert len(non_nan_signals) == 1
    assert non_nan_signals.iloc[0] > 0.0
    
    # Test exit when fa_score deteriorates below FA_SCORE_EXIT
    ohlcv_exit = ohlcv.copy()
    ohlcv_exit.loc[dates[-1], "fa_score"] = 35.0  # below 40.0
    
    state = None
    signals_exit, meta = strategy.make_signals_with_metadata(ohlcv_exit, regime_df, state)
    non_nan_exit_signals = signals_exit.dropna()
    
    # Should have a buy signal and then a sell signal (0.0)
    assert len(non_nan_exit_signals) == 2
    assert non_nan_exit_signals.iloc[-1] == 0.0
    # The last row's signal reason should reflect the exit reason
    assert meta["signal_reason"].iloc[-1] == "FA_SCORE_DETERIORATED"


def test_live_trader_calculate_orders(monkeypatch):
    # Mock KisBroker and PostgreDB to avoid connections during init
    monkeypatch.setattr("core.execution.trader.KisBroker", lambda *args, **kwargs: None)
    monkeypatch.setattr("core.execution.trader.PostgreDB", lambda *args, **kwargs: None)
    
    trader = LiveTrader(mock=True)
    
    total_eval = 10_000_000
    current_positions = {
        "005930": {"qty": 10, "avg_price": 70000, "current_price": 80000, "profit_rate": 14.28}
    }
    
    # If 005930 target weight is 0.0 -> SELL order
    # If 000660 target weight is 0.2 -> BUY order
    target_positions = {
        "005930": 0.0,
        "000660": 0.2,
    }
    
    ohlcv_store = {
        "000660": pd.DataFrame({"close": [150_000]}, index=[pd.Timestamp("2026-07-08")]),
    }
    
    orders = trader._calculate_orders(total_eval, current_positions, target_positions, ohlcv_store)
    
    sell_orders = [o for o in orders if o["type"] == "SELL"]
    buy_orders = [o for o in orders if o["type"] == "BUY"]
    
    assert len(sell_orders) == 1
    assert sell_orders[0]["ticker"] == "005930"
    assert sell_orders[0]["qty"] == 10
    
    assert len(buy_orders) == 1
    assert buy_orders[0]["ticker"] == "000660"
    # Target value: 10,000,000 * 0.2 = 2,000,000
    # Qty: 2,000,000 // 150,000 = 13
    assert buy_orders[0]["qty"] == 13
