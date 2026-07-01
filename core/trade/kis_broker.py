from __future__ import annotations

import os
import json as jsonlib
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
import websockets

from core.trade.kis_constants import (
    BaseUrl, CcldDvsn, CustType, ExecType, H0stcnt0Field,
    KisEnv, MrktDivCode, OrdDvsn, PriceSign, RvseCnclDvsnCd,
    SllBuyDvsnCd, TrId, WsTrType,
)
from core.utils.parsing import parse_int


TOKEN_CACHE_PATH = Path(__file__).parent / ".token_cache.json"


class KisApiError(RuntimeError):
    """Raised when the KIS API returns an unsuccessful response."""


class KisHTTPError(KisApiError):
    """HTTP 레벨 오류 (4xx/5xx). 네트워크/인증 문제 또는 서버 오류."""

    def __init__(self, status_code: int, body: Any):
        super().__init__(f"KIS HTTP {status_code}: {body}")
        self.status_code = status_code
        self.body = body


class KisBusinessError(KisApiError):
    """비즈니스 로직 오류 (rt_cd != '0'). 주문 거부, 잔량 부족 등."""

    def __init__(self, msg_cd: str, message: str, body: Any):
        super().__init__(f"KIS business error [{msg_cd}]: {message}")
        self.msg_cd = msg_cd
        self.message = message
        self.body = body


@dataclass(frozen=True)
class KisAccount:
    account_no: str
    product_code: str


@dataclass(frozen=True)
class KisConfig:
    app_key: str
    app_secret: str
    domestic_stock: KisAccount
    domestic_futures: KisAccount | None = None
    env: str = KisEnv.PAPER

    @property
    def base_url(self) -> str:
        if self.env == KisEnv.REAL:
            return BaseUrl.REAL
        if self.env == KisEnv.PAPER:
            return BaseUrl.PAPER
        raise ValueError("KIS_ENV must be 'paper' or 'real'.")

    @property
    def ws_base_url(self) -> str:
        if self.env == KisEnv.REAL:
            return BaseUrl.WS_REAL
        return BaseUrl.WS_PAPER

    @property
    def is_paper(self) -> bool:
        return self.env == KisEnv.PAPER


# ──────────────────────────────────────────────────────────────
# 1. 주문관리 (Order Management)
# ──────────────────────────────────────────────────────────────

class OrderManager:
    """매수·매도·정정·취소·체결 대기."""

    def __init__(self, broker: KisBroker):
        self._broker = broker

    @property
    def _cfg(self) -> KisConfig:
        return self._broker.config

    def buy_market(self, stock_code: str, quantity: int) -> dict[str, Any]:
        if quantity <= 0:
            raise ValueError("quantity must be greater than 0.")
        tr_id = TrId.BUY_PAPER if self._cfg.is_paper else TrId.BUY_REAL
        return self._broker._request(
            "POST",
            "/uapi/domestic-stock/v1/trading/order-cash",
            json={
                "CANO": self._cfg.domestic_stock.account_no,
                "ACNT_PRDT_CD": self._cfg.domestic_stock.product_code,
                "PDNO": stock_code,
                "ORD_DVSN": OrdDvsn.MARKET,
                "ORD_QTY": str(quantity),
                "ORD_UNPR": "0",
            },
            tr_id=tr_id,
        )

    def buy_limit(self, stock_code: str, quantity: int, price: int) -> dict[str, Any]:
        if quantity <= 0:
            raise ValueError("quantity must be greater than 0.")
        if price <= 0:
            raise ValueError("price must be greater than 0.")
        price = round_to_tick(price)
        tr_id = TrId.BUY_PAPER if self._cfg.is_paper else TrId.BUY_REAL
        return self._broker._request(
            "POST",
            "/uapi/domestic-stock/v1/trading/order-cash",
            json={
                "CANO": self._cfg.domestic_stock.account_no,
                "ACNT_PRDT_CD": self._cfg.domestic_stock.product_code,
                "PDNO": stock_code,
                "ORD_DVSN": OrdDvsn.LIMIT,
                "ORD_QTY": str(quantity),
                "ORD_UNPR": str(price),
            },
            tr_id=tr_id,
        )

    def sell_market(self, stock_code: str, quantity: int) -> dict[str, Any]:
        if quantity <= 0:
            raise ValueError("quantity must be greater than 0.")
        tr_id = TrId.SELL_PAPER if self._cfg.is_paper else TrId.SELL_REAL
        return self._broker._request(
            "POST",
            "/uapi/domestic-stock/v1/trading/order-cash",
            json={
                "CANO": self._cfg.domestic_stock.account_no,
                "ACNT_PRDT_CD": self._cfg.domestic_stock.product_code,
                "PDNO": stock_code,
                "ORD_DVSN": OrdDvsn.MARKET,
                "ORD_QTY": str(quantity),
                "ORD_UNPR": "0",
            },
            tr_id=tr_id,
        )

    def sell_limit(self, stock_code: str, quantity: int, price: int) -> dict[str, Any]:
        if quantity <= 0:
            raise ValueError("quantity must be greater than 0.")
        if price <= 0:
            raise ValueError("price must be greater than 0.")
        price = round_to_tick(price)
        tr_id = TrId.SELL_PAPER if self._cfg.is_paper else TrId.SELL_REAL
        return self._broker._request(
            "POST",
            "/uapi/domestic-stock/v1/trading/order-cash",
            json={
                "CANO": self._cfg.domestic_stock.account_no,
                "ACNT_PRDT_CD": self._cfg.domestic_stock.product_code,
                "PDNO": stock_code,
                "ORD_DVSN": OrdDvsn.LIMIT,
                "ORD_QTY": str(quantity),
                "ORD_UNPR": str(price),
            },
            tr_id=tr_id,
        )

    def cancel(
        self,
        orgn_odno: str,
        krx_fwdg_ord_orgno: str,
        qty_all_yn: str = "Y",
        ord_qty: int = 0,
    ) -> dict[str, Any]:
        tr_id = TrId.REVISE_CANCEL_PAPER if self._cfg.is_paper else TrId.REVISE_CANCEL_REAL
        return self._broker._request(
            "POST",
            "/uapi/domestic-stock/v1/trading/order-rvsecncl",
            json={
                "CANO": self._cfg.domestic_stock.account_no,
                "ACNT_PRDT_CD": self._cfg.domestic_stock.product_code,
                "KRX_FWDG_ORD_ORGNO": krx_fwdg_ord_orgno,
                "ORGN_ODNO": orgn_odno,
                "ORD_DVSN": OrdDvsn.LIMIT,
                "RVSE_CNCL_DVSN_CD": RvseCnclDvsnCd.CANCEL,
                "ORD_QTY": str(ord_qty) if qty_all_yn == "N" else "0",
                "ORD_UNPR": "0",
                "QTY_ALL_ORD_YN": qty_all_yn,
            },
            tr_id=tr_id,
        )

    def get_order_status(
        self,
        odno: str,
        date_str: str | None = None,
        request_timeout: float = 10,
    ) -> dict[str, Any] | None:
        """Return the KIS order row and parsed fill quantities for a broker order id."""
        target_date = date_str or datetime.now().strftime("%Y%m%d")
        tr_id = TrId.ORDER_HISTORY_PAPER if self._cfg.is_paper else TrId.ORDER_HISTORY_REAL
        ctx_fk = ""
        ctx_nk = ""

        while True:
            orders = self._broker._request(
                "GET",
                "/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
                params={
                    "CANO": self._cfg.domestic_stock.account_no,
                    "ACNT_PRDT_CD": self._cfg.domestic_stock.product_code,
                    "INQR_STRT_DT": target_date,
                    "INQR_END_DT": target_date,
                    "SLL_BUY_DVSN_CD": SllBuyDvsnCd.ALL,
                    "INQR_DVSN": "00",
                    "PDNO": "",
                    "ORD_GNO_BRNO": "",
                    "ODNO": odno,
                    "CCLD_DVSN": CcldDvsn.ALL,
                    "INQR_DVSN_1": "",
                    "INQR_DVSN_3": "00",
                    "EXCG_ID_DVSN_CD": "KRX",
                    "CTX_AREA_FK100": ctx_fk,
                    "CTX_AREA_NK100": ctx_nk,
                },
                tr_id=tr_id,
                _timeout=request_timeout,
            )
            for order in orders.get("output1", []):
                if order.get("odno") == odno:
                    filled_qty = parse_int(order.get("tot_ccld_qty"))
                    remaining_qty = parse_int(order.get("rmn_qty"))
                    filled_amount = parse_int(order.get("tot_ccld_amt"))
                    avg_fill_price = parse_int(order.get("avg_prvs"))
                    if avg_fill_price == 0 and filled_qty > 0:
                        avg_fill_price = filled_amount // filled_qty
                    return {
                        "order": order,
                        "filled_qty": filled_qty,
                        "remaining_qty": remaining_qty,
                        "filled_amount": filled_amount,
                        "avg_fill_price": avg_fill_price,
                        "is_cancelled": order.get("cncl_yn") == "Y",
                    }

            ctx_nk = orders.get("ctx_area_nk100", "").strip()
            if not ctx_nk:
                return None
            ctx_fk = orders.get("ctx_area_fk100", "").strip()

    def fetch_unfilled_orders(self, date_str: str | None = None) -> list[dict[str, Any]]:
        """당일 미체결 주문을 조회한다."""
        target_date = date_str or datetime.now().strftime("%Y%m%d")
        tr_id = TrId.ORDER_HISTORY_PAPER if self._cfg.is_paper else TrId.ORDER_HISTORY_REAL
        ctx_fk = ""
        ctx_nk = ""
        unfilled: list[dict[str, Any]] = []

        while True:
            orders = self._broker._request(
                "GET",
                "/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
                params={
                    "CANO": self._cfg.domestic_stock.account_no,
                    "ACNT_PRDT_CD": self._cfg.domestic_stock.product_code,
                    "INQR_STRT_DT": target_date,
                    "INQR_END_DT": target_date,
                    "SLL_BUY_DVSN_CD": SllBuyDvsnCd.ALL,
                    "INQR_DVSN": "00",
                    "PDNO": "",
                    "ORD_GNO_BRNO": "",
                    "ODNO": "",
                    "CCLD_DVSN": CcldDvsn.ALL,
                    "INQR_DVSN_1": "",
                    "INQR_DVSN_3": "00",
                    "EXCG_ID_DVSN_CD": "KRX",
                    "CTX_AREA_FK100": ctx_fk,
                    "CTX_AREA_NK100": ctx_nk,
                },
                tr_id=tr_id,
            )
            for order in orders.get("output1", []):
                remain = parse_int(order.get("rmn_qty"))
                if remain > 0 and order.get("cncl_yn") != "Y":
                    unfilled.append(order)

            ctx_nk = orders.get("ctx_area_nk100", "").strip()
            if not ctx_nk:
                break
            ctx_fk = orders.get("ctx_area_fk100", "").strip()

        return unfilled

    def modify(
        self,
        orgn_odno: str,
        krx_fwdg_ord_orgno: str,
        ord_qty: int,
        ord_unpr: int,
        qty_all_yn: str = "N",
    ) -> dict[str, Any]:
        ord_unpr = round_to_tick(ord_unpr)
        tr_id = TrId.REVISE_CANCEL_PAPER if self._cfg.is_paper else TrId.REVISE_CANCEL_REAL
        return self._broker._request(
            "POST",
            "/uapi/domestic-stock/v1/trading/order-rvsecncl",
            json={
                "CANO": self._cfg.domestic_stock.account_no,
                "ACNT_PRDT_CD": self._cfg.domestic_stock.product_code,
                "KRX_FWDG_ORD_ORGNO": krx_fwdg_ord_orgno,
                "ORGN_ODNO": orgn_odno,
                "ORD_DVSN": OrdDvsn.LIMIT,
                "RVSE_CNCL_DVSN_CD": RvseCnclDvsnCd.MODIFY,
                "ORD_QTY": str(ord_qty),
                "ORD_UNPR": str(ord_unpr),
                "QTY_ALL_ORD_YN": qty_all_yn,
            },
            tr_id=tr_id,
        )

    def wait_for_fill(self, odno: str, timeout_sec: int = 20) -> bool:
        """주문번호(odno)가 완전체결될 때까지 실제 timeout_sec 안에서 폴링한다."""
        import time

        today = datetime.now().strftime("%Y%m%d")
        started_at = time.monotonic()
        deadline = started_at + timeout_sec

        while time.monotonic() < deadline:
            time.sleep(min(1, max(0, deadline - time.monotonic())))
            remaining_sec = deadline - time.monotonic()
            if remaining_sec <= 0:
                return False
            status = self.get_order_status(
                odno,
                date_str=today,
                request_timeout=max(1, min(5, remaining_sec)),
            )
            if status is None:
                continue
            filled = status["filled_qty"]
            remain = status["remaining_qty"]
            elapsed = int(time.monotonic() - started_at)
            print(f"  [{elapsed:2d}s] 체결:{filled}주  잔량:{remain}주")
            if filled > 0 and remain == 0:
                return True
        return False


# ──────────────────────────────────────────────────────────────
# 2. 포지션 & 잔고 조회 (Account Management)
# ──────────────────────────────────────────────────────────────

class AccountManager:
    """잔고 조회·매수가능금액 조회."""

    def __init__(self, broker: KisBroker):
        self._broker = broker

    @property
    def _cfg(self) -> KisConfig:
        return self._broker.config

    def balance(self) -> dict[str, Any]:
        tr_id = TrId.BALANCE_PAPER if self._cfg.is_paper else TrId.BALANCE_REAL
        return self._broker._request(
            "GET",
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            params={
                "CANO": self._cfg.domestic_stock.account_no,
                "ACNT_PRDT_CD": self._cfg.domestic_stock.product_code,
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "00",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
            tr_id=tr_id,
        )

    def buyable_amount(
        self,
        stock_code: str,
        ord_unpr: str = "",
        ord_dvsn: str = OrdDvsn.MARKET,
    ) -> dict[str, Any]:
        tr_id = TrId.BUYABLE_PAPER if self._cfg.is_paper else TrId.BUYABLE_REAL
        return self._broker._request(
            "GET",
            "/uapi/domestic-stock/v1/trading/inquire-psbl-order",
            params={
                "CANO": self._cfg.domestic_stock.account_no,
                "ACNT_PRDT_CD": self._cfg.domestic_stock.product_code,
                "PDNO": stock_code,
                "ORD_UNPR": ord_unpr,
                "ORD_DVSN": ord_dvsn,
                "CMA_EVLU_AMT_ICLD_YN": "N",
                "OVRS_ICLD_YN": "N",
            },
            tr_id=tr_id,
        )


# ──────────────────────────────────────────────────────────────
# 3. 시세 데이터 수신 (Market Data)
# ──────────────────────────────────────────────────────────────

class MarketDataManager:
    """현재가 조회·실시간 체결 및 호가 스트리밍."""

    def __init__(self, broker: KisBroker):
        self._broker = broker

    @property
    def _cfg(self) -> KisConfig:
        return self._broker.config

    def price(self, stock_code: str) -> dict[str, Any]:
        return self._broker._request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            params={
                "FID_COND_MRKT_DIV_CODE": MrktDivCode.STOCK,
                "FID_INPUT_ISCD": stock_code,
            },
            tr_id=TrId.PRICE,
        )

    def orderbook(self, stock_code: str) -> dict[str, Any]:
        """Return a KRX orderbook snapshot for a domestic stock or ETF."""
        return self._broker._request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn",
            params={
                "FID_COND_MRKT_DIV_CODE": MrktDivCode.STOCK,
                "FID_INPUT_ISCD": stock_code,
            },
            tr_id=TrId.ORDERBOOK,
        )

    async def stream_price(self, stock_code: str, count: int = 10) -> None:
        """실시간 주식 체결(H0STCNT0)을 WebSocket으로 수신해 출력한다."""
        key = self._broker.get_websocket_approval_key()
        async with websockets.connect(self._cfg.ws_base_url) as ws:
            await ws.send(jsonlib.dumps(_ws_subscribe_msg(key, TrId.WS_EXECUTION, stock_code)))
            print(f"[{stock_code}] 실시간 현재가 구독 시작 (H0STCNT0, {count}틱)...\n")
            print(f"{'시각':^8}  {'현재가':>10}  {'등락':>4}  {'전일대비':>8}  {'비율':>7}  {'체결량':>10}  구분")
            print("-" * 65)
            received = 0
            async for raw in ws:
                parts = raw.split("|")
                if len(parts) < 4 or parts[0] != "0":
                    continue
                f = parts[3].split("^")
                tick = _parse_execution_tick(f)
                if tick is None:
                    continue
                t, price, sign, vrss, ctrt, vol, div = tick
                print(f"{t:^8}  {price:>10,}  {sign}  {vrss:>+8,}  {ctrt:>6}%  {vol:>10,}  {div}")
                received += 1
                if received >= count:
                    break

    async def stream_orderbook(self, stock_code: str, count: int = 5, levels: int = 5) -> None:
        """실시간 호가(H0STASP0)를 WebSocket으로 수신해 출력한다."""
        key = self._broker.get_websocket_approval_key()
        async with websockets.connect(self._cfg.ws_base_url) as ws:
            await ws.send(jsonlib.dumps(_ws_subscribe_msg(key, TrId.WS_ORDERBOOK, stock_code)))
            print(f"[{stock_code}] 실시간 호가창 구독 시작 (H0STASP0, {count}회 업데이트)...")
            received = 0
            async for raw in ws:
                parts = raw.split("|")
                if len(parts) < 4 or parts[0] != "0":
                    continue
                f = parts[3].split("^")
                if len(f) < 45:
                    continue
                print_orderbook(f, levels)
                received += 1
                if received >= count:
                    break

    async def stream_execution_ticks(
        self,
        stock_codes: str | list[str],
        max_events: int | None = None,
    ):
        """실시간 체결 tick을 dict로 yield한다.

        ATR stop처럼 호출부가 가격 tick을 직접 소비해야 하는 경우에 사용한다.
        """
        codes = [stock_codes] if isinstance(stock_codes, str) else list(stock_codes)
        if not codes:
            return

        key = self._broker.get_websocket_approval_key()
        async with websockets.connect(self._cfg.ws_base_url) as ws:
            for code in codes:
                await ws.send(jsonlib.dumps(_ws_subscribe_msg(key, TrId.WS_EXECUTION, code)))
            print(f"실시간 체결 구독 시작: {codes}")

            received = 0
            async for raw in ws:
                parts = raw.split("|")
                if len(parts) < 4 or parts[0] != "0" or parts[1] != TrId.WS_EXECUTION:
                    continue
                f = parts[3].split("^")
                tick = _parse_execution_tick(f)
                if tick is None:
                    continue

                t, price, sign, vrss, ctrt, vol, div = tick
                yield {
                    "code": f[H0stcnt0Field.STOCK_CODE],
                    "time": t,
                    "price": price,
                    "sign": sign,
                    "change": vrss,
                    "change_rate": ctrt,
                    "volume": vol,
                    "exec_type": div,
                }

                received += 1
                if max_events is not None and received >= max_events:
                    break

    async def stream_realtime(self, stock_code: str, max_events: int = 30) -> None:
        """실시간 체결(H0STCNT0) + 호가(H0STASP0)를 단일 WebSocket으로 동시 수신한다."""
        key = self._broker.get_websocket_approval_key()
        async with websockets.connect(self._cfg.ws_base_url) as ws:
            await ws.send(jsonlib.dumps(_ws_subscribe_msg(key, TrId.WS_EXECUTION, stock_code)))
            await ws.send(jsonlib.dumps(_ws_subscribe_msg(key, TrId.WS_ORDERBOOK, stock_code)))
            print(f"[{stock_code}] 실시간 체결(H0STCNT0) + 호가(H0STASP0) 동시 구독 시작...")
            print(f"{'─'*65}")
            count = 0
            async for raw in ws:
                parts = raw.split("|")
                if len(parts) < 4 or parts[0] != "0":
                    continue
                tr_id = parts[1]
                f = parts[3].split("^")
                if tr_id == TrId.WS_EXECUTION:
                    tick = _parse_execution_tick(f)
                    if tick is None:
                        continue
                    t, price, sign, vrss, _, vol, div = tick
                    print(f"[체결] {t}  {price:>10,}원  {sign} {vrss:>+,}  체결량:{vol:>8,}주  {div}")
                elif tr_id == TrId.WS_ORDERBOOK and len(f) >= 45:
                    hour   = f[1]
                    t      = f"{hour[:2]}:{hour[2:4]}:{hour[4:]}"
                    ask1   = int(f[3])
                    bid1   = int(f[13])
                    aq1    = int(f[23])
                    bq1    = int(f[33])
                    spread = ask1 - bid1
                    print(f"[호가] {t}  매도1:{ask1:>10,}원({aq1:,}주)  매수1:{bid1:>10,}원({bq1:,}주)  스프레드:{spread:,}원")
                count += 1
                if count >= max_events:
                    break


# ──────────────────────────────────────────────────────────────
# 4. 체결 내역 조회 (Execution History)
# ──────────────────────────────────────────────────────────────

class HistoryManager:
    """일별 체결 내역 및 기간별 거래 내역 조회."""

    def __init__(self, broker: KisBroker):
        self._broker = broker

    @property
    def _cfg(self) -> KisConfig:
        return self._broker.config

    def get(
        self,
        start_date: str,
        end_date: str,
        sll_buy_dvsn_cd: str = SllBuyDvsnCd.ALL,
        ccld_dvsn: str = CcldDvsn.ALL,
        stock_code: str = "",
    ) -> dict[str, Any]:
        tr_id = TrId.ORDER_HISTORY_PAPER if self._cfg.is_paper else TrId.ORDER_HISTORY_REAL
        return self._broker._request(
            "GET",
            "/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
            params={
                "CANO": self._cfg.domestic_stock.account_no,
                "ACNT_PRDT_CD": self._cfg.domestic_stock.product_code,
                "INQR_STRT_DT": start_date,
                "INQR_END_DT": end_date,
                "SLL_BUY_DVSN_CD": sll_buy_dvsn_cd,
                "INQR_DVSN": "00",
                "PDNO": stock_code,
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "CCLD_DVSN": ccld_dvsn,
                "INQR_DVSN_1": "",
                "INQR_DVSN_3": "00",
                "EXCG_ID_DVSN_CD": "KRX",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
            tr_id=tr_id,
        )


# ──────────────────────────────────────────────────────────────
# KisBroker — 인증·HTTP 인프라 + 4개 매니저 조합
# ──────────────────────────────────────────────────────────────

class KisBroker:
    def __init__(self, config: KisConfig):
        self.config  = config
        self._access_token: str | None = self._load_cached_access_token()
        self.orders  = OrderManager(self)
        self.account = AccountManager(self)
        self.market  = MarketDataManager(self)
        self.history = HistoryManager(self)

    @classmethod
    def from_db_credential(cls, credential: dict) -> KisBroker:
        """DB user_broker_credentials 행으로 KisBroker를 생성한다.

        api_key/api_secret은 호출 전에 이미 복호화된 상태여야 한다.
        """
        extra = credential.get("extra") or {}
        env_code = credential.get("environment_code", "PAPER")
        kis_env = KisEnv.REAL if env_code == "REAL" else KisEnv.PAPER
        config = KisConfig(
            app_key=credential["api_key"],
            app_secret=credential["api_secret"],
            domestic_stock=KisAccount(
                account_no=credential["account_number"],
                product_code=extra.get("account_product_code", "01"),
            ),
            env=kis_env,
        )
        return cls(config)

    @classmethod
    def from_env(cls, env_path=None) -> KisBroker:
        if env_path:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        config = KisConfig(
            app_key=_required_env("KIS_APP_KEY"),
            app_secret=_required_env("KIS_APP_SECRET"),
            domestic_stock=KisAccount(
                account_no=_required_env(
                    "KIS_DOMESTIC_STOCK_ACCOUNT_NO",
                    fallback="KIS_ACCOUNT_NO",
                ),
                product_code=_required_env(
                    "KIS_DOMESTIC_STOCK_ACCOUNT_PRODUCT_CODE",
                    fallback="KIS_ACCOUNT_PRODUCT_CODE",
                ),
            ),
            domestic_futures=_optional_account(
                "KIS_DOMESTIC_FUTURES_ACCOUNT_NO",
                "KIS_DOMESTIC_FUTURES_ACCOUNT_PRODUCT_CODE",
            ),
            env=_parse_env(os.getenv("KIS_ENV", KisEnv.PAPER)),
        )
        return cls(config)

    def issue_access_token(self) -> dict[str, Any]:
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
        }
        data = self._request("POST", "/oauth2/tokenP", json=payload, auth=False)
        token = data.get("access_token")
        if not token:
            raise KisApiError(f"Token response did not include access_token: {data}")
        self._access_token = token
        self._save_token_cache(data)
        return data

    def get_websocket_approval_key(self) -> str:
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.config.app_key,
            "secretkey": self.config.app_secret,
        }
        data = self._request("POST", "/oauth2/Approval", json=payload, auth=False)
        key = data.get("approval_key")
        if not key:
            raise KisApiError(f"approval_key not found in response: {data}")
        return key

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        tr_id: str | None = None,
        auth: bool = True,
        _retries: int = 3,
        _retry_delay: float = 0.5,
        _timeout: float = 10,
    ) -> dict[str, Any]:
        import time

        headers = {
            "content-type": "application/json; charset=utf-8",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
            "custtype": CustType.INDIVIDUAL,
        }
        if tr_id:
            headers["tr_id"] = tr_id
        if auth:
            headers["authorization"] = f"Bearer {self.access_token}"

        for attempt in range(_retries):
            response = requests.request(
                method,
                f"{self.config.base_url}{path}",
                headers=headers,
                params=params,
                json=json,
                timeout=_timeout,
            )

            try:
                data = response.json()
            except ValueError as exc:
                raise KisHTTPError(
                    response.status_code,
                    f"non-JSON response: {response.text}",
                ) from exc

            # 로컬 캐시가 유효해 보여도 KIS 서버가 만료로 판단할 수 있다.
            # 이 경우 exponential backoff로 토큰을 재발급하고 같은 요청을 한 번 더 보낸다.
            if auth and data.get("msg_cd") == "EGW00123":
                if attempt < _retries - 1:
                    self._refresh_token_with_backoff()
                    headers["authorization"] = f"Bearer {self.access_token}"
                    continue
                raise KisApiError(f"KIS access token expired and refresh failed: {data}")

            # 초당 거래건수 초과 → exponential backoff 후 재시도
            if data.get("msg_cd") == "EGW00201":
                if attempt < _retries - 1:
                    time.sleep(_retry_delay * (2 ** attempt))
                    continue
                raise KisApiError(f"KIS API rate limit exceeded after {_retries} retries: {data}")

            if response.status_code >= 400:
                raise KisHTTPError(response.status_code, data)

            if _is_business_error(data):
                raise KisBusinessError(
                    msg_cd=str(data.get("msg_cd", "")),
                    message=str(data.get("msg1", data.get("msg", ""))),
                    body=data,
                )

            return data

        raise KisApiError("KIS API request failed after all retries")

    def _refresh_token_with_backoff(self, max_attempts: int = 3) -> None:
        """토큰 재발급을 exponential backoff로 최대 max_attempts회 시도한다."""
        import time

        last_exc: Exception | None = None
        for i in range(max_attempts):
            try:
                self._access_token = None
                self.issue_access_token()
                return
            except KisApiError as exc:
                last_exc = exc
                if i < max_attempts - 1:
                    time.sleep(2 ** i)
        raise KisApiError(
            f"Failed to refresh access token after {max_attempts} attempts"
        ) from last_exc

    @property
    def access_token(self) -> str:
        if not self._access_token:
            self.issue_access_token()
        if not self._access_token:
            raise KisApiError("Failed to issue access token.")
        return self._access_token

    def _load_cached_access_token(self) -> str | None:
        if not TOKEN_CACHE_PATH.exists():
            return None
        try:
            data = jsonlib.loads(TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
            expires_at = datetime.fromisoformat(data["expires_at"])
        except (OSError, KeyError, TypeError, ValueError, jsonlib.JSONDecodeError):
            return None

        if expires_at <= datetime.now() + timedelta(minutes=5):
            return None
        token = data.get("access_token")
        return token if isinstance(token, str) and token else None

    def _save_token_cache(self, token_response: dict[str, Any]) -> None:
        token = token_response.get("access_token")
        expires_in = token_response.get("expires_in", 0)
        if not isinstance(token, str):
            return
        try:
            expires_at = datetime.now() + timedelta(seconds=int(expires_in))
            TOKEN_CACHE_PATH.write_text(
                jsonlib.dumps(
                    {"access_token": token, "expires_at": expires_at.isoformat()},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except (OSError, TypeError, ValueError) as e:
            warnings.warn(
                f"Failed to write token cache to {TOKEN_CACHE_PATH}: {e}",
                RuntimeWarning,
                stacklevel=2,
            )


# ──────────────────────────────────────────────────────────────
# 유틸리티
# ──────────────────────────────────────────────────────────────

def print_orderbook(f: list[str], levels: int = 5) -> None:
    """H0STASP0 필드 배열(f)로 호가창을 출력한다."""
    hour = f[1]
    t = f"{hour[:2]}:{hour[2:4]}:{hour[4:]}"
    stock_code = f[0]
    print(f"\n=== 호가창 [{stock_code}]  {t} ===")
    print(f"  {'매도호가':>12}  {'잔량':>10}")
    print("  " + "-" * 26)
    for i in range(levels, 0, -1):
        p = int(f[3  + (i - 1)])
        q = int(f[23 + (i - 1)])
        print(f"  {p:>12,}원  {q:>10,}주")
    print("  " + "=" * 26)
    for i in range(1, levels + 1):
        p = int(f[13 + (i - 1)])
        q = int(f[33 + (i - 1)])
        print(f"  {p:>12,}원  {q:>10,}주")
    print("  " + "-" * 26)
    tot_ask = int(f[43])
    tot_bid = int(f[44])
    print(f"  총매도잔량: {tot_ask:,}주 / 총매수잔량: {tot_bid:,}주")


def get_tick_size(price: int) -> int:
    """KRX 국내주식 호가단위 반환 (가격 구간별 최소 주문 단위)."""
    if price < 1_000:
        return 1
    elif price < 5_000:
        return 5
    elif price < 10_000:
        return 10
    elif price < 50_000:
        return 50
    elif price < 100_000:
        return 100
    elif price < 500_000:
        return 500
    else:
        return 1_000


def round_to_tick(price: int) -> int:
    """가격을 해당 구간의 호가단위에 맞게 내림 처리."""
    tick = get_tick_size(price)
    return (price // tick) * tick


def _parse_env(value: str) -> KisEnv:
    try:
        return KisEnv(value.strip().lower())
    except ValueError:
        raise ValueError(f"KIS_ENV must be 'paper' or 'real', got: {value!r}")


def _parse_execution_tick(
    f: list[str],
) -> tuple[str, int, str, int, str, int, str] | None:
    """H0STCNT0 필드 배열을 파싱해 (시각, 가격, 등락부호, 전일대비, 비율, 체결량, 구분) 반환.

    필드 수가 부족하면 None을 반환한다.
    """
    if len(f) <= H0stcnt0Field.EXEC_TYPE:
        return None
    hour  = f[H0stcnt0Field.TIME]
    price = int(f[H0stcnt0Field.PRICE])
    sign  = PriceSign.to_label(f[H0stcnt0Field.SIGN])
    vrss  = int(f[H0stcnt0Field.CHANGE])
    ctrt  = f[H0stcnt0Field.CHANGE_RATE]
    vol   = int(f[H0stcnt0Field.VOLUME])
    div   = "매수" if f[H0stcnt0Field.EXEC_TYPE] == ExecType.BUY else "매도"
    t     = f"{hour[:2]}:{hour[2:4]}:{hour[4:]}"
    return t, price, sign, vrss, ctrt, vol, div


def _ws_subscribe_msg(approval_key: str, tr_id: TrId, tr_key: str) -> dict:
    return {
        "header": {
            "approval_key": approval_key,
            "custtype": CustType.INDIVIDUAL,
            "tr_type": WsTrType.SUBSCRIBE,
            "content-type": "utf-8",
        },
        "body": {"input": {"tr_id": tr_id, "tr_key": tr_key}},
    }


def _required_env(name: str, *, fallback: str | None = None) -> str:
    value = os.getenv(name)
    if not value and fallback:
        value = os.getenv(fallback)
    if not value:
        names = f"{name} or {fallback}" if fallback else name
        raise RuntimeError(f"Missing required environment variable: {names}")
    return value.strip()


def _optional_account(account_var: str, product_code_var: str) -> KisAccount | None:
    account_no = os.getenv(account_var)
    product_code = os.getenv(product_code_var)
    if not account_no and not product_code:
        return None
    if not account_no or not product_code:
        raise RuntimeError(
            f"{account_var} and {product_code_var} must be set together."
        )
    return KisAccount(account_no=account_no.strip(), product_code=product_code.strip())


def _is_business_error(data: dict[str, Any]) -> bool:
    return data.get("rt_cd") not in (None, "0")
