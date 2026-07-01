from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from storage.postgres.repositories.balance_repo import fetch_latest_total_value

if TYPE_CHECKING:
    from storage.postgres.connection import PostgreDB


class LiveOrderBlocked(RuntimeError):
    """실주문 게이트가 차단했을 때 발생한다."""


@dataclass(frozen=True)
class GateStatus:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class DailyLossLimit:
    amount: float
    label: str


def _resolve_daily_loss_limit(loss_limit: float, reference_total_value: float) -> DailyLossLimit:
    raw_limit = abs(float(loss_limit))
    if 0 < raw_limit <= 1:
        return DailyLossLimit(
            amount=reference_total_value * raw_limit,
            label=f"전일자산의 {raw_limit:.1%}",
        )
    return DailyLossLimit(amount=raw_limit, label="고정 원화")


def check_live_order_gate(
    kis_env: str | None = None,
    allow_live_order: str | None = None,
) -> GateStatus:
    """KIS_ENV=real + ALLOW_LIVE_ORDER=true 이중 잠금을 검증한다.

    두 조건이 모두 충족돼야 실주문이 허용된다.
    paper 환경에서는 게이트를 통과시킨다.
    """
    env = kis_env if kis_env is not None else os.getenv("KIS_ENV", "paper")
    allow = allow_live_order if allow_live_order is not None else os.getenv("ALLOW_LIVE_ORDER", "false")

    if env != "real":
        return GateStatus(allowed=True, reason=f"paper mode ({env}); gate skipped")
    if allow.lower() != "true":
        return GateStatus(
            allowed=False,
            reason="KIS_ENV=real이지만 ALLOW_LIVE_ORDER=true가 설정되지 않았습니다",
        )
    return GateStatus(allowed=True, reason="live order gate passed")


def assert_live_order_allowed(
    kis_env: str | None = None,
    allow_live_order: str | None = None,
) -> None:
    """실주문 실행 전 게이트를 검증한다. 통과 못하면 LiveOrderBlocked를 발생시킨다."""
    status = check_live_order_gate(kis_env, allow_live_order)
    if not status.allowed:
        raise LiveOrderBlocked(status.reason)


def check_daily_loss_limit(
    db: "PostgreDB",
    strategy_name: str,
    loss_limit: float,
    current_total_value: float,
) -> GateStatus:
    """전일 마감 자산 대비 현재 자산의 손익이 한도를 초과했는지 확인한다.

    당일 체결 현금흐름(매수=-, 매도=+) 합으로는 매수만 해도 "손실"로
    잘못 잡히고 보유 종목의 평가손익은 반영되지 않는다. 대신 실무에서
    쓰는 방식대로 "전일 장마감 총자산(balance_history) 대비 현재
    총자산(broker 잔고)의 변화"를 손익으로 본다 — 매수는 현금이 주식으로
    형태만 바뀌므로 손익에 영향이 없고, 미실현 평가손익도 즉시 반영된다.

    Parameters
    ----------
    loss_limit : float
        0보다 크고 1 이하이면 전일 마감 총자산 대비 비율로 해석한다.
        예: 0.10 → 전일 마감 총자산의 10%를 초과하는 손실이면 차단.
        1보다 크면 고정 원화 한도로 해석한다.
        예: 500_000 → 당일 손익이 -500,000원 미만이면 차단.
    current_total_value : float
        현재 총자산(broker balance의 tot_evlu_amt 등). 호출 시점에 직접 조회해 전달한다.
    """
    prev_total_value = fetch_latest_total_value(db, strategy_name)
    if prev_total_value is None:
        return GateStatus(
            allowed=True,
            reason="전일 balance_history 스냅샷이 없어 손실 한도 체크를 건너뜁니다",
        )

    prev_total = prev_total_value
    daily_net = current_total_value - prev_total
    limit = _resolve_daily_loss_limit(loss_limit, prev_total)
    limit_text = f"-{limit.amount:,.0f}원 ({limit.label})"
    if daily_net < -limit.amount:
        return GateStatus(
            allowed=False,
            reason=(
                f"일일 손실 한도 초과: {daily_net:,.0f}원 "
                f"(전일자산 {prev_total:,.0f}원 → 현재 {current_total_value:,.0f}원, 한도: {limit_text})"
            ),
        )
    return GateStatus(
        allowed=True,
        reason=f"일일 손익 {daily_net:,.0f}원 (한도: {limit_text})",
    )
