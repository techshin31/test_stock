"""Step 7 — 분기 종목 교체 단위 테스트 (rotation.py)

검증 항목:
  - RotationManager: apply_plan, complete_exit, get_sell_only, get_force_close_date
  - deadline 계산: 거래일 캘린더 기반 / BDay 기반
  - build_rotated_size_df():
      sell_only 종목: 매수 신호(양수) → NaN
      sell_only 종목: 청산 신호(0.0) 유지
      force_close: 마감일 이후 첫 거래일 0.0
      비rotation 종목: 변경 없음
  - apply_rotation_to_signal(): trading 전용 후처리
  - to_json / from_json: 상태 직렬화·복원
  - rotation_plans=None: 기존 동작과 동일
"""

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stock_system.rotation import (
    RotationManager,
    RotationPlan,
    apply_rotation_to_signal,
    build_rotated_size_df,
)
from stock_system.portfolio import build_size_df


# ── RotationManager 상태 관리 ─────────────────────────────────────────────────

class TestRotationManager:
    def test_apply_plan_registers_sell_only(self):
        mgr  = RotationManager()
        plan = RotationPlan("2023-01-05", exit_stocks=["A"], deadline_days=20)
        cal  = pd.date_range("2023-01-05", periods=30, freq="B")
        mgr.apply_plan(plan, trading_calendar=cal)
        assert "A" in mgr.get_sell_only()

    def test_apply_plan_force_close_date(self):
        """review_date 이후 20번째 거래일 = future[19] = calendar[20]
        (future = review_date 초과 날짜들, 0-indexed)"""
        mgr  = RotationManager()
        plan = RotationPlan("2023-01-05", exit_stocks=["A"], deadline_days=20)
        cal  = pd.date_range("2023-01-05", periods=30, freq="B")
        mgr.apply_plan(plan, trading_calendar=cal)
        # future = cal[cal > "2023-01-05"] = cal[1:]
        # future[deadline_days - 1] = future[19] = cal[20]
        assert mgr.get_force_close_date("A") == cal[20]

    def test_apply_plan_multiple_stocks(self):
        mgr  = RotationManager()
        plan = RotationPlan("2023-01-05", exit_stocks=["A", "B", "C"])
        mgr.apply_plan(plan)
        sell_only = mgr.get_sell_only()
        assert "A" in sell_only
        assert "B" in sell_only
        assert "C" in sell_only

    def test_complete_exit_removes_stock(self):
        mgr  = RotationManager()
        plan = RotationPlan("2023-01-05", exit_stocks=["A"])
        mgr.apply_plan(plan)
        assert "A" in mgr.get_sell_only()
        mgr.complete_exit("A")
        assert "A" not in mgr.get_sell_only()

    def test_complete_exit_nonexistent_no_error(self):
        """없는 종목 complete_exit → 에러 없음"""
        mgr = RotationManager()
        mgr.complete_exit("NONEXISTENT")  # should not raise

    def test_get_force_close_date_none_for_unknown(self):
        mgr = RotationManager()
        assert mgr.get_force_close_date("UNKNOWN") is None

    def test_bday_fallback_without_calendar(self):
        """trading_calendar=None → BDay 기준 마감일 계산"""
        mgr  = RotationManager()
        plan = RotationPlan("2023-01-05", exit_stocks=["A"], deadline_days=20)
        mgr.apply_plan(plan, trading_calendar=None)
        deadline = mgr.get_force_close_date("A")
        expected = pd.Timestamp("2023-01-05") + pd.offsets.BDay(20)
        assert deadline == expected

    def test_apply_plan_deadline_at_end_of_calendar(self):
        """deadline_days가 캘린더 길이 초과 → 마지막 날"""
        mgr  = RotationManager()
        plan = RotationPlan("2023-01-05", exit_stocks=["A"], deadline_days=5)
        cal  = pd.date_range("2023-01-05", periods=3, freq="B")
        mgr.apply_plan(plan, trading_calendar=cal)
        # future는 cal 전체(3일), 5일 필요하지만 3일만 있음 → 마지막 날
        assert mgr.get_force_close_date("A") == cal[-1]


# ── JSON 직렬화 ───────────────────────────────────────────────────────────────

class TestJsonSerialization:
    def test_to_json_from_json_round_trip(self):
        mgr  = RotationManager()
        plan = RotationPlan("2023-01-05", exit_stocks=["A", "B"])
        cal  = pd.date_range("2023-01-05", periods=30, freq="B")
        mgr.apply_plan(plan, trading_calendar=cal)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        mgr.to_json(path)
        restored = RotationManager.from_json(path)
        assert restored.get_sell_only() == mgr.get_sell_only()
        assert restored.get_force_close_date("A") == mgr.get_force_close_date("A")
        assert restored.get_force_close_date("B") == mgr.get_force_close_date("B")
        Path(path).unlink()


# ── build_rotated_size_df ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def rotation_scenario(dates, uptrend_ohlc, neutral_profile):
    """A, B 두 종목 uptrend: A만 sell_only 등록"""
    close, high, low = uptrend_ohlc
    close_df = pd.DataFrame({"A": close, "B": close})
    high_df  = pd.DataFrame({"A": high,  "B": high})
    low_df   = pd.DataFrame({"A": low,   "B": low})

    # warmup 후 추세 구간(day 200~)에 deadline 설정
    deadline = dates[249]

    mgr = RotationManager()
    mgr._sell_only["A"] = deadline  # 직접 설정

    size_base, _ = build_size_df(neutral_profile, close_df, high_df, low_df)
    size_rot, _  = build_rotated_size_df(mgr, neutral_profile, close_df, high_df, low_df)

    return mgr, size_base, size_rot, deadline, close_df, high_df, low_df


class TestBuildRotatedSizeDf:
    def test_buy_signals_blocked_before_deadline(self, rotation_scenario):
        """sell_only 종목: 마감일 전 양수 size → NaN"""
        _, _, size_rot, deadline, *_ = rotation_scenario
        pre_mask = size_rot.index < deadline
        positive_before = (size_rot.loc[pre_mask, "A"] > 0).sum()
        assert positive_before == 0, "마감일 전 A의 양수 size 존재"

    def test_exit_signals_preserved_before_deadline(self, rotation_scenario):
        """sell_only 종목: 청산 신호(0.0)는 마감일 전에도 유지"""
        _, size_base, size_rot, deadline, *_ = rotation_scenario
        pre_mask = size_rot.index < deadline
        zero_in_base = size_base.loc[pre_mask, "A"] == 0.0
        if zero_in_base.sum() == 0:
            pytest.skip("마감일 전 A의 청산 신호(0.0) 없음")
        zero_idx = size_base.loc[pre_mask].index[zero_in_base]
        assert (size_rot.loc[zero_idx, "A"] == 0.0).all()

    def test_force_close_on_deadline(self, rotation_scenario):
        """마감일 이후 첫 거래일 → A = 0.0 (강제 청산)"""
        _, _, size_rot, deadline, *_ = rotation_scenario
        post_dates = size_rot.index[size_rot.index >= deadline]
        assert len(post_dates) > 0
        assert size_rot.loc[post_dates[0], "A"] == 0.0

    def test_non_rotated_stock_unchanged(self, rotation_scenario):
        """rotation 미적용 종목 B: base와 동일"""
        _, size_base, size_rot, *_ = rotation_scenario
        pd.testing.assert_series_equal(size_base["B"], size_rot["B"])

    def test_no_manager_returns_base(self, uptrend_ohlc, neutral_profile):
        """manager=None → build_size_df와 동일 결과"""
        close, high, low = uptrend_ohlc
        close_df = pd.DataFrame({"A": close})
        high_df  = pd.DataFrame({"A": high})
        low_df   = pd.DataFrame({"A": low})

        size_base, _ = build_size_df(neutral_profile, close_df, high_df, low_df)
        size_rot, _  = build_rotated_size_df(None, neutral_profile, close_df, high_df, low_df)
        pd.testing.assert_frame_equal(size_base, size_rot)

    def test_empty_sell_only_returns_base(self, uptrend_ohlc, neutral_profile):
        """sell_only 비어있는 manager → build_size_df와 동일 결과"""
        close, high, low = uptrend_ohlc
        close_df = pd.DataFrame({"A": close})
        high_df  = pd.DataFrame({"A": high})
        low_df   = pd.DataFrame({"A": low})

        size_base, _ = build_size_df(neutral_profile, close_df, high_df, low_df)
        mgr = RotationManager()  # 비어있음
        size_rot, _  = build_rotated_size_df(mgr, neutral_profile, close_df, high_df, low_df)
        pd.testing.assert_frame_equal(size_base, size_rot)


# ── apply_rotation_to_signal (trading 전용) ───────────────────────────────────

class TestApplyRotationToSignal:
    def test_blocks_buy_signal_before_deadline(self):
        """마감일 전: 양수 목표비중 → NaN"""
        mgr = RotationManager()
        mgr._sell_only["A"] = pd.Timestamp("2024-02-01")
        signal = {"A": 0.4, "B": 0.4}
        today  = pd.Timestamp("2024-01-15")  # 마감일 전
        result = apply_rotation_to_signal(mgr, signal, today)
        assert pd.isna(result["A"])
        assert result["B"] == 0.4

    def test_force_close_on_or_after_deadline(self):
        """마감일 당일 이후: 0.0 (강제 청산)"""
        mgr = RotationManager()
        mgr._sell_only["A"] = pd.Timestamp("2024-01-15")
        signal = {"A": 0.4, "B": 0.4}
        today  = pd.Timestamp("2024-01-15")  # 마감일 당일
        result = apply_rotation_to_signal(mgr, signal, today)
        assert result["A"] == 0.0

    def test_preserves_exit_signal_before_deadline(self):
        """마감일 전 청산 신호(0.0) → 그대로 0.0"""
        mgr = RotationManager()
        mgr._sell_only["A"] = pd.Timestamp("2024-02-01")
        signal = {"A": 0.0, "B": 0.4}
        today  = pd.Timestamp("2024-01-15")
        result = apply_rotation_to_signal(mgr, signal, today)
        assert result["A"] == 0.0

    def test_preserves_nan_signal_before_deadline(self):
        """마감일 전 NaN(hold) → 그대로 NaN"""
        mgr = RotationManager()
        mgr._sell_only["A"] = pd.Timestamp("2024-02-01")
        signal = {"A": float("nan"), "B": 0.4}
        today  = pd.Timestamp("2024-01-15")
        result = apply_rotation_to_signal(mgr, signal, today)
        assert pd.isna(result["A"])

    def test_no_manager_returns_unchanged(self):
        signal = {"A": 0.4, "B": 0.7}
        result = apply_rotation_to_signal(None, signal, pd.Timestamp.today())
        assert result == signal

    def test_empty_sell_only_returns_unchanged(self):
        mgr    = RotationManager()
        signal = {"A": 0.4, "B": 0.7}
        result = apply_rotation_to_signal(mgr, signal, pd.Timestamp.today())
        assert result == signal

    def test_unknown_stock_in_sell_only_ignored(self):
        """signal에 없는 종목이 sell_only에 있어도 에러 없음"""
        mgr = RotationManager()
        mgr._sell_only["UNKNOWN"] = pd.Timestamp("2024-02-01")
        signal = {"A": 0.4}
        result = apply_rotation_to_signal(mgr, signal, pd.Timestamp("2024-01-15"))
        assert result["A"] == 0.4
