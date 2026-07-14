from datetime import date

import numpy as np
import pandas as pd
import pytest

from core.execution.trader import LiveTrader
from core.strategy.fa_ta_momentum import FaTaMomentumStrategy
from data.loaders.fa_ta_loader import enrich_ohlcv_with_fa


class FaDB:
    def __init__(self, rows):
        self.rows = rows
        self.query = ""

    def fetch_all(self, query, params=None):
        self.query = query
        return self.rows


def test_fa_merge_is_deterministic_and_blocks_stale_scores():
    rows = [{
        "stock_code": "005930", "available_date": date(2026, 1, 2),
        "period_end": date(2025, 12, 31), "source_rcept_no": "R2",
        "fa_score": 75.0, "is_eligible": True, "score_confidence": 0.9,
        "score_model_code": "GENERAL_V1", "per_proxy": 10.0,
        "pbr_proxy": 1.0, "roe": 0.1, "debt_ratio": 0.5,
        "operating_income_growth_yoy": 0.1,
    }]
    db = FaDB(rows)
    index = pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-05"])
    store = {"005930.KS": pd.DataFrame({"close": [100, 101, 102]}, index=index)}
    enriched = enrich_ohlcv_with_fa(
        db, store, "2026-01-05", max_age_days=1, min_score_confidence=0.5
    )["005930.KS"]

    assert "DISTINCT ON (stock_code, available_date)" in db.query
    assert "period_end DESC, source_rcept_no DESC, id DESC" in db.query
    assert bool(enriched.iloc[0]["is_eligible"]) is True
    assert bool(enriched.iloc[-1]["is_eligible"]) is False
    assert bool(enriched.iloc[-1]["fa_is_stale"]) is True


def _strategy_frame(confidence=0.9, debt_ratio=0.5):
    index = pd.date_range("2026-01-01", periods=80, freq="B")
    close = np.linspace(100, 180, len(index))
    return pd.DataFrame({
        "close": close, "fa_score": 75.0, "is_eligible": True,
        "score_confidence": confidence, "debt_ratio": debt_ratio,
    }, index=index)


def test_live_ta_uses_actual_position_and_latest_regime_only():
    strategy = FaTaMomentumStrategy({"ma_window": 20, "ma_window_fast": 5})
    frame = _strategy_frame()

    target, metadata = strategy.evaluate_latest(
        frame, "UPTREND", current_position=0.17
    )
    assert target == 0.17
    assert metadata["signal_reason"] == "HOLD"

    target, metadata = strategy.evaluate_latest(
        frame, "DOWNTREND", current_position=0.17
    )
    assert target == 0.0
    assert metadata["signal_reason"] == "MARKET_DOWNTREND"


def test_live_ta_rejects_missing_or_low_confidence_fundamentals():
    strategy = FaTaMomentumStrategy({"ma_window": 20, "ma_window_fast": 5})
    for frame in (_strategy_frame(confidence=0.2), _strategy_frame(debt_ratio=np.nan)):
        target, _ = strategy.evaluate_latest(frame, "UPTREND", current_position=0.0)
        assert target == 0.0


def test_live_strategy_hard_stop_precedes_hold_signal():
    strategy = FaTaMomentumStrategy({"ma_window": 20, "ma_window_fast": 5})
    target, metadata = strategy.evaluate_latest(
        _strategy_frame(), "UPTREND", current_position=0.12,
        average_price=100, current_price=89, peak_price=110,
    )
    assert target == 0.0
    assert metadata["signal_reason"] == "HARD_STOP_LOSS"


def test_live_strategy_trailing_stop_protects_gains():
    strategy = FaTaMomentumStrategy({"ma_window": 20, "ma_window_fast": 5})
    target, metadata = strategy.evaluate_latest(
        _strategy_frame(), "UPTREND", current_position=0.12,
        average_price=100, current_price=109, peak_price=120,
    )
    assert target == 0.0
    assert metadata["signal_reason"] == "TRAILING_STOP"


def test_portfolio_limit_keeps_all_eligible_positions_without_upscaling():
    trader = object.__new__(LiveTrader)
    targets = {f"{i:06d}.KS": 0.15 for i in range(6)}
    details = {
        ticker: {"fa_score": 60 + i, "momentum": i / 100}
        for i, ticker in enumerate(targets)
    }
    positions = {"000000.KS": {}, "000001.KS": {}}
    limited = trader._apply_portfolio_limits(targets, details, positions)

    active = {ticker for ticker, weight in limited.items() if weight > 0}
    assert active == set(targets)
    assert sum(limited.values()) == pytest.approx(0.90)
    assert all(weight == pytest.approx(0.15) for weight in limited.values())


class PublishedDB:
    def __init__(self):
        self.queries = []

    def fetch_one(self, query, params=None):
        self.queries.append(query)
        return {"id": 9}

    def fetch_all(self, query, params=None):
        self.queries.append(query)
        return [{
            "fa_company_result_id": 1, "stock_code": "005930",
            "fa_score": 80.0, "score_confidence": 0.9,
            "latest_available_date": date(2026, 6, 1),
            "debt_ratio": 0.5, "is_eligible": True,
            "score_model_code": "GENERAL_V1",
        }]


def test_live_candidates_require_published_pass_run():
    trader = object.__new__(LiveTrader)
    trader.db = PublishedDB()
    trader.strategy_name = "aggressive"
    trader.allow_warning_fa_run = False
    run, rows = trader._load_published_fa_candidates(date(2026, 7, 1))
    assert run["id"] == 9 and rows[0]["stock_code"] == "005930"
    assert "validation_summary->>'status'" in trader.db.queries[0]
    assert "s.name = %s" in trader.db.queries[0]
    assert "c.is_selected = TRUE" in trader.db.queries[1]


def test_universe_sync_fails_before_db_write_when_broker_is_unavailable():
    class BrokenBroker:
        def get_balance(self):
            raise TimeoutError("broker timeout")

    class NoWriteDB:
        def transaction(self):
            raise AssertionError("DB transaction must not start without broker state")

    trader = object.__new__(LiveTrader)
    trader.broker = BrokenBroker()
    trader.db = NoWriteDB()
    trader.strategy_name = "aggressive"

    with pytest.raises(RuntimeError, match="universe .*broker timeout"):
        trader._sync_universe_to_db([], {})
