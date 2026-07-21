import datetime as dt
import os
import re
import threading
import time
from typing import Any

import mojito
import requests
from dotenv import load_dotenv


class BrokerResponseError(RuntimeError):
    """KIS가 실패 응답 또는 불완전한 데이터를 반환했을 때 발생한다."""


_SENSITIVE_QUERY_PATTERN = re.compile(
    r"(?i)(\b(?:CANO|ACNT_PRDT_CD|authorization|appkey|appsecret|hashkey|access_token)=)"
    r"([^&\s]+)"
)


def redact_sensitive_text(value: object) -> str:
    """Remove KIS credentials and account fields from an error string."""
    return _SENSITIVE_QUERY_PATTERN.sub(r"\1***", str(value))


def normalize_symbol(ticker: str) -> str:
    """내부/DB 저장용 6자리 종목코드로 정규화한다."""
    return str(ticker).strip().upper().split(".", 1)[0]


def to_yahoo_ticker(symbol: str) -> str:
    return f"{normalize_symbol(symbol)}.KS"


def _env_true(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


class KisBroker:
    """한국투자증권(KIS) REST API wrapper.

    실계좌는 ``mock=False``, ``KIS_ENV=real``, ``ALLOW_LIVE_ORDER=true``가
    모두 충족될 때만 초기화된다. 기본값은 항상 모의투자다.
    """

    def __init__(self, mock: bool = True):
        load_dotenv()
        self.key = os.getenv("KIS_APP_KEY")
        self.secret = os.getenv("KIS_APP_SECRET")
        acc_no_front = os.getenv("KIS_DOMESTIC_STOCK_ACCOUNT_NO")
        acc_no_back = os.getenv("KIS_DOMESTIC_STOCK_ACCOUNT_PRODUCT_CODE", "01")

        if not self.key or not self.secret or not acc_no_front:
            raise ValueError(
                "한국투자증권 API 키가 환경 변수에 없습니다 "
                "(KIS_APP_KEY, KIS_APP_SECRET, KIS_DOMESTIC_STOCK_ACCOUNT_NO)"
            )

        self.is_mock = bool(mock)
        kis_env = os.getenv("KIS_ENV", "paper").strip().lower()
        if not self.is_mock:
            if kis_env != "real":
                raise PermissionError("실전투자는 KIS_ENV=real을 명시해야 합니다.")
            if not _env_true("ALLOW_LIVE_ORDER"):
                raise PermissionError(
                    "실주문이 잠겨 있습니다. 의도한 경우에만 ALLOW_LIVE_ORDER=true를 설정하세요."
                )

        self.acc_no = f"{acc_no_front}-{acc_no_back}"
        self.masked_account = f"***{acc_no_front[-4:]}-{acc_no_back}"
        self.broker = mojito.KoreaInvestment(
            api_key=self.key,
            api_secret=self.secret,
            acc_no=self.acc_no,
            mock=self.is_mock,
        )
        self.request_min_interval = float(os.getenv("KIS_REQUEST_MIN_INTERVAL", "0.20"))
        self.get_retry_attempts = int(os.getenv("KIS_GET_RETRY_ATTEMPTS", "3"))
        self.retry_backoff_seconds = float(os.getenv("KIS_RETRY_BACKOFF_SECONDS", "0.5"))
        if self.request_min_interval < 0 or self.get_retry_attempts < 1 or self.retry_backoff_seconds < 0:
            raise ValueError("KIS request retry/rate-limit settings are invalid")
        self._request_lock = threading.Lock()
        self._last_request_at = 0.0

    def _rate_limit(self) -> None:
        """Keep API calls below the configured process-wide request pace."""
        with self._request_lock:
            wait = self.request_min_interval - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            self._last_request_at = time.monotonic()

    def _safe_error_message(self, exc: BaseException) -> str:
        message = redact_sensitive_text(exc)
        broker = getattr(self, "broker", None)
        for secret in (
            getattr(self, "key", None),
            getattr(self, "secret", None),
            getattr(broker, "access_token", None),
            getattr(broker, "acc_no_prefix", None),
        ):
            if secret:
                message = message.replace(str(secret), "***")
        return message

    def _safe_request(self, method: str, url: str, **kwargs):
        """Retry idempotent reads/hash generation, never an actual order submission."""
        retryable_statuses = {429, 500, 502, 503, 504}
        last_error = None
        for attempt in range(self.get_retry_attempts):
            self._rate_limit()
            try:
                response = requests.request(method, url, timeout=10, **kwargs)
                if response.status_code not in retryable_statuses:
                    response.raise_for_status()
                    return response
                last_error = requests.HTTPError(
                    f"{response.status_code} Server Error", response=response
                )
            except requests.RequestException as exc:
                last_error = exc
            if attempt + 1 < self.get_retry_attempts:
                retry_after = 0.0
                if getattr(last_error, "response", None) is not None:
                    try:
                        retry_after = float(last_error.response.headers.get("Retry-After", 0) or 0)
                    except (TypeError, ValueError):
                        retry_after = 0.0
                time.sleep(max(retry_after, self.retry_backoff_seconds * (2 ** attempt)))
        raise last_error or requests.RequestException("KIS request failed")

    @staticmethod
    def _require_success(resp: Any, operation: str) -> dict:
        if not isinstance(resp, dict):
            raise BrokerResponseError(f"{operation}: 응답 형식이 dict가 아닙니다.")
        if "rt_cd" in resp and str(resp.get("rt_cd")) != "0":
            raise BrokerResponseError(
                f"{operation} 실패: {resp.get('msg1') or resp.get('msg_cd') or 'unknown error'}"
            )
        return resp

    def get_balance(self) -> dict:
        """검증된 예수금과 보유 종목을 반환한다. 오류 시 빈 잔고로 대체하지 않는다."""
        output1: list[dict] = []
        output2: list[dict] = []
        fk100 = ""
        nk100 = ""

        while True:
            resp = self._require_success(
                self._fetch_balance_page(fk100, nk100), "잔고 조회"
            )
            if not isinstance(resp.get("output1"), list) or not isinstance(resp.get("output2"), list):
                raise BrokerResponseError("잔고 조회: output1/output2가 누락되었습니다.")
            output1.extend(resp["output1"])
            output2.extend(resp["output2"])
            if resp.get("tr_cont") != "M":
                break
            fk100 = resp.get("ctx_area_fk100", "")
            nk100 = resp.get("ctx_area_nk100", "")

        if not output2:
            raise BrokerResponseError("잔고 조회: 계좌 요약이 비어 있습니다.")

        summary = output2[0]
        required = ("prvs_rcdl_excc_amt", "dnca_tot_amt", "tot_evlu_amt")
        if any(key not in summary for key in required):
            raise BrokerResponseError("잔고 조회: 필수 계좌 요약 필드가 누락되었습니다.")

        try:
            cash = float(summary["prvs_rcdl_excc_amt"])
            today_cash = float(summary["dnca_tot_amt"])
            total_asset = float(summary["tot_evlu_amt"])
        except (TypeError, ValueError) as exc:
            raise BrokerResponseError("잔고 조회: 계좌 금액을 숫자로 변환할 수 없습니다.") from exc

        positions = {}
        for item in output1:
            try:
                symbol = normalize_symbol(item.get("pdno", ""))
                qty = int(item.get("hldg_qty", 0) or 0)
                if not symbol or qty <= 0:
                    continue
                positions[to_yahoo_ticker(symbol)] = {
                    "qty": qty,
                    "avg_price": float(item.get("pchs_avg_pric", 0) or 0),
                    "current_price": float(item.get("prpr", 0) or 0),
                    "profit_rate": float(item.get("evlu_pfls_rt", 0) or 0),
                }
            except (TypeError, ValueError) as exc:
                raise BrokerResponseError(f"잔고 조회: {item.get('pdno')} 포지션 값이 잘못되었습니다.") from exc

        def optional_float(*keys: str) -> float:
            for key in keys:
                value = summary.get(key)
                if value not in (None, ""):
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        continue
            return 0.0

        return {
            "cash": cash,
            "today_cash": today_cash,
            "total_asset": total_asset,
            "unrealized_pnl": optional_float("evlu_pfls_smtl_amt", "evlu_pfls_amt"),
            "daily_asset_change": optional_float("asst_icdc_amt"),
            "daily_asset_change_rate": optional_float("asst_icdc_erng_rt"),
            "positions": positions,
            "as_of": dt.datetime.now(dt.timezone.utc),
        }

    def _fetch_balance_page(self, fk100: str, nk100: str) -> dict:
        headers = {
            "content-type": "application/json",
            "authorization": self.broker.access_token,
            "appKey": self.key,
            "appSecret": self.secret,
            "tr_id": "VTTC8434R" if self.is_mock else "TTTC8434R",
        }
        params = {
            "CANO": self.broker.acc_no_prefix,
            "ACNT_PRDT_CD": self.broker.acc_no_postfix,
            "AFHR_FLPR_YN": "N", "OFL_YN": "N", "INQR_DVSN": "01",
            "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01",
            "CTX_AREA_FK100": fk100, "CTX_AREA_NK100": nk100,
        }
        try:
            response = self._safe_request("GET",
                f"{self.broker.base_url}/uapi/domestic-stock/v1/trading/inquire-balance",
                headers=headers, params=params,
            )
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise BrokerResponseError(
                f"잔고 조회 통신 실패: {self._safe_error_message(exc)}"
            ) from None
        payload["tr_cont"] = response.headers.get("tr_cont", "")
        return payload

    def get_current_price(self, ticker: str) -> float:
        headers = {
            "content-type": "application/json",
            "authorization": self.broker.access_token,
            "appKey": self.key,
            "appSecret": self.secret,
            "tr_id": "FHKST01010100",
        }
        params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": normalize_symbol(ticker)}
        try:
            response = self._safe_request("GET",
                f"{self.broker.base_url}/uapi/domestic-stock/v1/quotations/inquire-price",
                headers=headers, params=params,
            )
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise BrokerResponseError(
                f"현재가 조회 통신 실패: {self._safe_error_message(exc)}"
            ) from None
        resp = self._require_success(payload, "현재가 조회")
        output = resp.get("output")
        if not isinstance(output, dict):
            raise BrokerResponseError("현재가 조회: output이 누락되었습니다.")
        try:
            price = float(output.get("stck_prpr", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise BrokerResponseError("현재가 조회: 현재가가 숫자가 아닙니다.") from exc
        if price <= 0:
            raise BrokerResponseError("현재가 조회: 현재가가 0 이하입니다.")
        return price

    def place_market_buy(self, ticker: str, qty: int) -> dict:
        return self._place_market_order("buy", ticker, qty)

    def place_market_sell(self, ticker: str, qty: int) -> dict:
        return self._place_market_order("sell", ticker, qty)

    def _place_market_order(self, side: str, ticker: str, qty: int) -> dict:
        """명시적 HTTP timeout을 적용해 국내주식 시장가 주문을 제출한다."""
        if qty <= 0:
            raise ValueError("주문 수량은 1주 이상이어야 합니다.")
        data = {
            "CANO": self.broker.acc_no_prefix,
            "ACNT_PRDT_CD": self.broker.acc_no_postfix,
            "PDNO": normalize_symbol(ticker),
            "ORD_DVSN": "01",
            "ORD_QTY": str(qty),
            "ORD_UNPR": "0",
        }
        try:
            hash_response = self._safe_request("POST",
                f"{self.broker.base_url}/uapi/hashkey",
                headers={
                    "content-type": "application/json",
                    "appKey": self.key,
                    "appSecret": self.secret,
                },
                json=data,
            )
            hashkey = hash_response.json().get("HASH")
            if not hashkey:
                raise BrokerResponseError("주문 해시키 발급 응답에 HASH가 없습니다.")

            if self.is_mock:
                tr_id = "VTTC0802U" if side == "buy" else "VTTC0801U"
            else:
                tr_id = "TTTC0802U" if side == "buy" else "TTTC0801U"
            # This call is deliberately made once. Retrying an ambiguous market-order
            # response can create a duplicate order at the broker.
            self._rate_limit()
            response = requests.post(
                f"{self.broker.base_url}/uapi/domestic-stock/v1/trading/order-cash",
                headers={
                    "content-type": "application/json",
                    "authorization": self.broker.access_token,
                    "appKey": self.key,
                    "appSecret": self.secret,
                    "tr_id": tr_id,
                    "custtype": "P",
                    "hashkey": hashkey,
                },
                json=data,
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except BrokerResponseError:
            raise
        except (requests.RequestException, ValueError) as exc:
            # timeout/연결 종료는 서버 접수 여부를 단정할 수 없다.
            raise RuntimeError(
                f"시장가 주문 통신 결과 불명: {self._safe_error_message(exc)}"
            ) from None
        return self._require_success(payload, "시장가 매수" if side == "buy" else "시장가 매도")

    def fetch_daily_orders(self, target_date: dt.date | None = None) -> list[dict]:
        """KIS 일별 주문/체결 조회 원문 행을 반환한다."""
        target_date = target_date or dt.date.today()
        path = "uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        url = f"{self.broker.base_url}/{path}"
        headers = {
            "content-type": "application/json",
            "authorization": self.broker.access_token,
            "appKey": self.key,
            "appSecret": self.secret,
            "tr_id": "VTTC0081R" if self.is_mock else "TTTC0081R",
            "custtype": "P",
        }
        ymd = target_date.strftime("%Y%m%d")
        params = {
            "CANO": self.broker.acc_no_prefix,
            "ACNT_PRDT_CD": self.broker.acc_no_postfix,
            "INQR_STRT_DT": ymd,
            "INQR_END_DT": ymd,
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "00",
            "PDNO": "",
            "CCLD_DVSN": "00",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
            "EXCG_ID_DVSN_CD": "ALL",
        }
        rows = []
        for _ in range(20):
            try:
                response = self._safe_request("GET", url, headers=headers, params=params)
                payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                raise BrokerResponseError(
                    f"주문 체결 조회 통신 실패: {self._safe_error_message(exc)}"
                ) from None
            payload = self._require_success(payload, "주문 체결 조회")
            page_rows = payload.get("output1", [])
            if not isinstance(page_rows, list):
                raise BrokerResponseError("주문 체결 조회: output1 형식이 잘못되었습니다.")
            rows.extend(page_rows)
            if response.headers.get("tr_cont") != "M":
                return rows
            params["CTX_AREA_FK100"] = payload.get("ctx_area_fk100", "")
            params["CTX_AREA_NK100"] = payload.get("ctx_area_nk100", "")
        raise BrokerResponseError("주문 체결 조회 페이지 수가 안전 한도를 초과했습니다.")

    def get_order_status(self, broker_order_id: str, target_date: dt.date | None = None) -> dict:
        """주문번호의 누적 체결 상태를 정규화한다."""
        order_id = str(broker_order_id).lstrip("0") or "0"
        for row in self.fetch_daily_orders(target_date):
            row_id = str(row.get("odno", row.get("ODNO", ""))).lstrip("0") or "0"
            if row_id != order_id:
                continue
            ordered = int(row.get("ord_qty", 0) or 0)
            filled = int(row.get("tot_ccld_qty", 0) or 0)
            remaining = int(row.get("rmn_qty", max(ordered - filled, 0)) or 0)
            total_amount = float(row.get("tot_ccld_amt", 0) or 0)
            avg_price = float(row.get("avg_prvs", 0) or 0)
            cancelled = str(row.get("cncl_yn", "N")).upper() == "Y"
            if cancelled:
                status = "CANCELLED"
            elif filled >= ordered and ordered > 0:
                status = "FILLED"
            elif filled > 0:
                status = "PARTIAL"
            else:
                status = "ACCEPTED"
            return {
                "status": status,
                "ordered_qty": ordered,
                "filled_qty": filled,
                "remaining_qty": remaining,
                "avg_fill_price": avg_price,
                "total_fill_amount": total_amount,
                "raw": row,
            }
        raise BrokerResponseError(f"주문 체결 조회에서 주문번호 {broker_order_id}를 찾지 못했습니다.")
