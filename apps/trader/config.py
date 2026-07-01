from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TraderConfig:
    user_email: str
    broker_code: str
    kis_env: str
    allow_live_order: bool
    strategy_name: str
    daily_loss_limit: float
    cycle_interval_sec: int

    @property
    def is_live(self) -> bool:
        return self.kis_env == "real" and self.allow_live_order

    @property
    def environment_code(self) -> str:
        return "REAL" if self.kis_env == "real" else "PAPER"


def load_config(env_file: str | None = None) -> TraderConfig:
    """환경 변수를 검증하고 TraderConfig를 반환한다.

    모든 os.getenv 호출을 이 함수에서 집중 처리한다.
    core/trade/ 내부에서 직접 os.getenv를 호출하지 않도록 한다.
    브로커 자격증명(API 키/시크릿/계좌번호)은 DB에서 로드하므로 여기서 요구하지 않는다.
    """
    from dotenv import load_dotenv

    path = Path(env_file or os.getenv("QUANTPILOT_ENV_FILE", "apps/trader/.env"))
    if path.exists():
        load_dotenv(path, override=False)

    kis_env = os.getenv("KIS_ENV", "paper")
    allow_live = os.getenv("ALLOW_LIVE_ORDER", "false").lower() == "true"

    if kis_env == "real" and not allow_live:
        print(
            "[CONFIG] KIS_ENV=real이지만 ALLOW_LIVE_ORDER=true가 없습니다.\n"
            "         실주문을 허용하려면 ALLOW_LIVE_ORDER=true를 명시하세요.",
            file=sys.stderr,
        )
        sys.exit(1)

    required = {
        "USER_EMAIL": os.getenv("USER_EMAIL"),
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

    return TraderConfig(
        user_email=required["USER_EMAIL"],
        broker_code=os.getenv("BROKER_CODE", "KIS"),
        kis_env=kis_env,
        allow_live_order=allow_live,
        strategy_name=os.getenv("STRATEGY_NAME", "risk_neutral"),
        daily_loss_limit=float(os.getenv("DAILY_LOSS_LIMIT", "0.10")),
        cycle_interval_sec=int(os.getenv("CYCLE_INTERVAL_SEC", "60")),
    )


def build_db_config() -> dict:
    """PostgreDB 생성용 설정 dict를 반환한다."""
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "user": os.getenv("POSTGRES_USER", ""),
        "password": os.getenv("POSTGRES_PASSWORD", ""),
        "database": os.getenv("POSTGRES_DB", "quantpilot"),
    }
