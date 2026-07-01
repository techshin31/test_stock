from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.trade.kis_broker import KisBroker
from core.utils.parsing import parse_int
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.position_repo import (
    fetch_active_position_symbols,
    upsert_position,
    zero_out_position,
)


@dataclass
class SyncResult:
    synced: int = 0
    zeroed: int = 0
    symbols: list[str] = field(default_factory=list)
    zeroed_symbols: list[str] = field(default_factory=list)
    balance: dict[str, Any] = field(default_factory=dict)


def sync_positions_from_broker(
    db: PostgreDB,
    broker: KisBroker,
    strategy_name: str,
) -> SyncResult:
    """KIS 잔고를 positions 테이블과 전량 동기화한다.

    KIS output1에 있는 종목은 upsert하고,
    DB에 qty > 0이지만 KIS 잔고에 없는 종목은 qty=0으로 처리한다.
    노트북에 흩어진 포지션 동기화 로직을 대체한다.
    """
    balance = broker.account.balance()
    holdings: list[dict[str, Any]] = balance.get("output1") or []

    broker_symbols: set[str] = set()
    result = SyncResult(balance=balance)

    for item in holdings:
        symbol = str(item.get("pdno", "")).strip()
        if not symbol:
            continue
        qty = parse_int(item.get("hldg_qty"))
        if qty <= 0:
            continue

        avg_cost_raw = str(item.get("pchs_avg_pric", "0")).replace(",", "").strip()
        try:
            avg_cost = float(avg_cost_raw)
        except ValueError:
            avg_cost = 0.0

        broker_symbols.add(symbol)
        upsert_position(
            db,
            strategy_name=strategy_name,
            symbol=symbol,
            data={
                "qty": qty,
                "avg_cost": avg_cost,
                "market_type_code": _infer_market_type(item),
                "instrument_type_code": "STOCK",
            },
        )
        result.synced += 1
        result.symbols.append(symbol)

    zeroed_symbols = _zero_out_missing(db, strategy_name, broker_symbols)
    result.zeroed = len(zeroed_symbols)
    result.zeroed_symbols = zeroed_symbols

    return result


def get_sellable_qty(broker: KisBroker, symbol: str) -> int:
    """KIS 잔고에서 특정 종목의 주문가능수량(매도가능수량)을 조회한다.

    KIS balance output1의 ord_psbl_qty 필드를 사용한다.
    종목이 잔고에 없으면 0을 반환한다.
    """
    balance = broker.account.balance()
    holdings: list[dict[str, Any]] = balance.get("output1") or []
    for item in holdings:
        if str(item.get("pdno", "")).strip() == symbol:
            return parse_int(item.get("ord_psbl_qty"))
    return 0


def _zero_out_missing(
    db: PostgreDB,
    strategy_name: str,
    broker_symbols: set[str],
) -> list[str]:
    """DB에 있지만 KIS 잔고에 없는 종목을 qty=0으로 처리하고 종목 목록을 반환한다."""
    zeroed: list[str] = []
    for sym in fetch_active_position_symbols(db, strategy_name):
        if sym not in broker_symbols:
            zero_out_position(db, strategy_name, sym)
            zeroed.append(sym)
    return zeroed


def _infer_market_type(item: dict[str, Any]) -> str:
    """KIS prdt_type_cd로 시장 구분을 추정한다."""
    prdt_type = str(item.get("prdt_type_cd", "")).strip()
    if prdt_type.startswith("3"):
        return "KOSDAQ"
    return "KOSPI"
