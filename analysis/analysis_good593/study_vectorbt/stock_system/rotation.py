"""분기 종목 교체 관리

공개 API:
  RotationPlan                           분기 검토 결과 1회분
  RotationManager                        종목 유니버스 상태 관리
  build_rotated_size_df(manager, ...)    portfolio.build_size_df() + rotation 후처리
  apply_rotation_to_signal(manager, ...) get_signal() 결과에 rotation 후처리 (trading 전용)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


@dataclass
class RotationPlan:
    """분기 검토 결과 1회분"""
    review_date: str                         # "2024-01-02"
    exit_stocks: List[str] = field(default_factory=list)
    entry_stocks: List[str] = field(default_factory=list)
    deadline_days: int = 20                  # 강제 청산 기한 (거래일 기준)


class RotationManager:
    """종목 유니버스 상태 관리

    편출 확정 종목을 sell_only 모드로 등록해 매수 신호를 차단하고
    deadline_days 거래일 이내 강제 청산을 보장한다.

    trading 서버에서는 to_json / from_json 으로 상태를 영속화한다.
    """

    def __init__(self):
        self._sell_only: Dict[str, pd.Timestamp] = {}  # {종목명: 강제청산일}

    def apply_plan(self, plan: RotationPlan, trading_calendar: pd.DatetimeIndex = None):
        """RotationPlan 적용 — 편출 종목을 sell_only로 등록

        Parameters
        ----------
        trading_calendar : 실제 거래일 인덱스 (backtest).
                           None 이면 영업일(BDay) 기준으로 마감일 계산 (trading).
        """
        review_dt = pd.Timestamp(plan.review_date)

        if trading_calendar is not None:
            future = trading_calendar[trading_calendar > review_dt]
            deadline = (future[plan.deadline_days - 1]
                        if len(future) >= plan.deadline_days else future[-1])
        else:
            deadline = review_dt + pd.offsets.BDay(plan.deadline_days)

        for name in plan.exit_stocks:
            self._sell_only[name] = deadline

    def complete_exit(self, name: str):
        """편출 완료 — sell_only에서 제거"""
        self._sell_only.pop(name, None)

    def get_sell_only(self) -> List[str]:
        """현재 sell_only 중인 종목 리스트"""
        return list(self._sell_only.keys())

    def get_force_close_date(self, name: str) -> Optional[pd.Timestamp]:
        """종목의 강제 청산일 반환"""
        return self._sell_only.get(name)

    def to_json(self, path: str):
        """상태 직렬화 — trading 서버 영속화용"""
        Path(path).write_text(
            json.dumps({k: str(v) for k, v in self._sell_only.items()},
                       ensure_ascii=False, indent=2)
        )

    @classmethod
    def from_json(cls, path: str) -> RotationManager:
        """상태 복원 — trading 서버 재시작 후 복구용"""
        mgr = cls()
        for name, dt in json.loads(Path(path).read_text()).items():
            mgr._sell_only[name] = pd.Timestamp(dt)
        return mgr


def build_rotated_size_df(
    manager: Optional[RotationManager],
    profile,
    close_df: pd.DataFrame,
    high_df: pd.DataFrame,
    low_df: pd.DataFrame,
    **kwargs,
) -> tuple:
    """portfolio.build_size_df() 호출 후 rotation 후처리 적용

    sell_only 종목 : 매수 신호(양수) → NaN  (ATR stop·DOWNTREND 등 청산 신호 0.0은 유지)
    force_close 종목: 강제청산일 이후 첫 거래일에 0.0 설정

    manager 가 None 이거나 sell_only 종목이 없으면 build_size_df() 결과를 그대로 반환.

    Returns
    -------
    size_df, signal_info
    """
    from .portfolio import build_size_df

    size_df, signal_info = build_size_df(
        profile, close_df, high_df, low_df, **kwargs
    )

    if manager is None or not manager.get_sell_only():
        return size_df, signal_info

    for name, deadline in manager._sell_only.items():
        if name not in size_df.columns:
            continue

        # 마감일 이전: 매수 신호(양수) → NaN
        pre_mask = size_df.index < deadline
        buy_mask = size_df[name] > 0
        size_df.loc[pre_mask & buy_mask, name] = np.nan

        # 마감일 이후 첫 거래일: 강제 청산 0.0
        post_dates = size_df.index[size_df.index >= deadline]
        if len(post_dates) > 0:
            size_df.loc[post_dates[0], name] = 0.0

    return size_df, signal_info


def apply_rotation_to_signal(
    manager: Optional[RotationManager],
    signal: dict,
    today: pd.Timestamp,
) -> dict:
    """get_signal() 결과에 rotation 후처리 적용 — trading 전용

    sell_only 종목 : 양수 목표비중 → NaN  (매수 신호 차단)
    force_close 종목: 0.0  (강제 청산)

    Returns
    -------
    dict  종목명 → 보정된 목표 비중
    """
    if manager is None or not manager.get_sell_only():
        return signal

    result = dict(signal)
    for name in manager.get_sell_only():
        if name not in result:
            continue
        deadline = manager.get_force_close_date(name)
        if deadline is not None and today >= deadline:
            result[name] = 0.0
        elif pd.notna(result[name]) and result[name] > 0:
            result[name] = float("nan")

    return result
