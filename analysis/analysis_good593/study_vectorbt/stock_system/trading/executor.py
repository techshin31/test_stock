"""주문 실행 — 브로커 API 연동 (스텁)

get_today_signal() 결과를 실제 주문으로 변환한다.
브로커 SDK(한국투자증권 등) 연동 시 이 파일만 수정한다.
"""

import math


def execute_orders(
    signal: dict,
    portfolio_value: float,
    current_positions: dict = None,
    dry_run: bool = True,
) -> list:
    """목표 비중 → 주문 리스트 변환

    Parameters
    ----------
    signal            : get_today_signal() 반환값
    portfolio_value   : 현재 총 포트폴리오 가치 (원)
    current_positions : 현재 보유 {종목명: 보유금액}
    dry_run           : True이면 주문 출력만, 실제 API 호출 없음

    Returns
    -------
    list[dict]  주문 리스트 {'name', 'action', 'target_pct', 'target_amount'}
    """
    current_positions = current_positions or {}
    orders = []

    for name, target_pct in signal.items():
        import math
        if math.isnan(target_pct):
            continue  # 유지 — 주문 없음

        target_amount = portfolio_value * target_pct
        current_amount = current_positions.get(name, 0)
        diff = target_amount - current_amount

        action = "BUY" if diff > 0 else "SELL" if diff < 0 else "HOLD"

        order = {
            "name":          name,
            "action":        action,
            "target_pct":    target_pct,
            "target_amount": round(target_amount),
            "diff_amount":   round(diff),
        }
        orders.append(order)

        if dry_run:
            print(f"[DRY-RUN] {action:4s} {name:12s}  "
                  f"목표비중={target_pct:.1%}  "
                  f"목표금액={target_amount:,.0f}원  "
                  f"차이={diff:+,.0f}원")

    return orders
