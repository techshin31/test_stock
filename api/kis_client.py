from __future__ import annotations

import os
import json as jsonlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


PAPER_BASE_URL = "https://openapivts.koreainvestment.com:29443"
REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"
TOKEN_CACHE_PATH = Path("api/.token_cache.json")


class KisApiError(RuntimeError):
    """Raised when the KIS API returns an unsuccessful response."""


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
    env: str = "paper"

    @property
    def base_url(self) -> str:
        if self.env == "real":
            return REAL_BASE_URL
        if self.env == "paper":
            return PAPER_BASE_URL
        raise ValueError("KIS_ENV must be 'paper' or 'real'.")

    @property
    def is_paper(self) -> bool:
        return self.env == "paper"


class KisClient:
    def __init__(self, config: KisConfig):
        self.config = config
        self._access_token: str | None = self._load_cached_access_token()

    @classmethod
    def from_env(cls, env_path: str | None = "api/.env") -> "KisClient":
        if env_path:
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
            env=os.getenv("KIS_ENV", "paper").strip().lower(),
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

    def get_domestic_stock_balance(self) -> dict[str, Any]:
        tr_id = "VTTC8434R" if self.config.is_paper else "TTTC8434R"
        params = {
            "CANO": self.config.domestic_stock.account_no,
            "ACNT_PRDT_CD": self.config.domestic_stock.product_code,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        return self._request(
            "GET",
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            params=params,
            tr_id=tr_id,
        )

    def get_balance(self) -> dict[str, Any]:
        return self.get_domestic_stock_balance()

    def get_domestic_stock_price(self, stock_code: str) -> dict[str, Any]:
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
        }
        return self._request(
            "GET",
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            params=params,
            tr_id="FHKST01010100",
        )

    def buy_domestic_stock_market(self, stock_code: str, quantity: int) -> dict[str, Any]:
        if quantity <= 0:
            raise ValueError("quantity must be greater than 0.")

        tr_id = "VTTC0802U" if self.config.is_paper else "TTTC0802U"
        payload = {
            "CANO": self.config.domestic_stock.account_no,
            "ACNT_PRDT_CD": self.config.domestic_stock.product_code,
            "PDNO": stock_code,
            "ORD_DVSN": "01",
            "ORD_QTY": str(quantity),
            "ORD_UNPR": "0",
        }
        return self._request(
            "POST",
            "/uapi/domestic-stock/v1/trading/order-cash",
            json=payload,
            tr_id=tr_id,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        tr_id: str | None = None,
        auth: bool = True,
    ) -> dict[str, Any]:
        headers = {
            "content-type": "application/json; charset=utf-8",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
            "custtype": "P",
        }
        if tr_id:
            headers["tr_id"] = tr_id
        if auth:
            headers["authorization"] = f"Bearer {self.access_token}"

        response = requests.request(
            method,
            f"{self.config.base_url}{path}",
            headers=headers,
            params=params,
            json=json,
            timeout=10,
        )

        try:
            data = response.json()
        except ValueError as exc:
            raise KisApiError(
                f"KIS API returned non-JSON response: {response.status_code} {response.text}"
            ) from exc

        if response.status_code >= 400 or _is_business_error(data):
            raise KisApiError(f"KIS API error: HTTP {response.status_code}, body={data}")

        return data

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
        except (OSError, TypeError, ValueError):
            return


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
