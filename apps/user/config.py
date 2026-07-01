from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UserRegisterConfig:
    email: str
    display_name: str | None
    broker_code: str
    api_key: str
    api_secret: str
    environment_code: str  # "REAL" | "PAPER"
    stock_account_number: str
    stock_account_product_code: str
    futures_account_number: str | None
    futures_account_product_code: str | None


def load_config(env_file: str | None = None) -> UserRegisterConfig:
    from dotenv import load_dotenv

    path = Path(env_file or os.getenv("QUANTPILOT_ENV_FILE", "apps/user/.env"))
    if path.exists():
        load_dotenv(path, override=False)

    required = {
        "USER_EMAIL": os.getenv("USER_EMAIL"),
        "KIS_APP_KEY": os.getenv("KIS_APP_KEY"),
        "KIS_APP_SECRET": os.getenv("KIS_APP_SECRET"),
        "KIS_DOMESTIC_STOCK_ACCOUNT_NO": os.getenv("KIS_DOMESTIC_STOCK_ACCOUNT_NO"),
        "KIS_DOMESTIC_STOCK_ACCOUNT_PRODUCT_CODE": os.getenv("KIS_DOMESTIC_STOCK_ACCOUNT_PRODUCT_CODE"),
        "CREDENTIAL_ENCRYPTION_KEY": os.getenv("CREDENTIAL_ENCRYPTION_KEY"),
        "POSTGRES_HOST": os.getenv("POSTGRES_HOST"),
        "POSTGRES_USER": os.getenv("POSTGRES_USER"),
        "POSTGRES_PASSWORD": os.getenv("POSTGRES_PASSWORD"),
        "POSTGRES_DB": os.getenv("POSTGRES_DB"),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"[CONFIG] 필수 환경 변수 누락: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    kis_env = os.getenv("KIS_ENV", "paper").lower()
    environment_code = "REAL" if kis_env == "real" else "PAPER"

    return UserRegisterConfig(
        email=required["USER_EMAIL"],
        display_name=os.getenv("USER_DISPLAY_NAME"),
        broker_code=os.getenv("BROKER_CODE", "KIS"),
        api_key=required["KIS_APP_KEY"],
        api_secret=required["KIS_APP_SECRET"],
        environment_code=environment_code,
        stock_account_number=required["KIS_DOMESTIC_STOCK_ACCOUNT_NO"],
        stock_account_product_code=required["KIS_DOMESTIC_STOCK_ACCOUNT_PRODUCT_CODE"],
        futures_account_number=os.getenv("KIS_DOMESTIC_FUTURES_ACCOUNT_NO") or None,
        futures_account_product_code=os.getenv("KIS_DOMESTIC_FUTURES_ACCOUNT_PRODUCT_CODE") or None,
    )


def build_db_config() -> dict:
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "user": os.getenv("POSTGRES_USER", ""),
        "password": os.getenv("POSTGRES_PASSWORD", ""),
        "database": os.getenv("POSTGRES_DB", "quantpilot_db"),
    }
