from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DEFAULT_STRATEGY_NAME = "risk_neutral"
DEFAULT_INITIAL_CAPITAL = 10_000_000.0
DEFAULT_RISK_FREE_RATE = 0.030
DEFAULT_UNIVERSE_SIZE = 5
DEFAULT_ROTATION_SIZE = 2
DEFAULT_ROTATION_INTERVAL_YEARS = 2
DEFAULT_RANDOM_SEED = 42


@dataclass(frozen=True)
class BacktesterConfig:
    strategy_name: str
    universe_source: str
    start_date: date
    end_date: date
    initial_capital: float
    risk_free_rate: float
    universe_size: int
    rotation_size: int
    rotation_interval_years: int
    random_seed: int
    output_dir: Path
    save_charts: bool


def load_env(env_file: str | None = None) -> None:
    """apps/backtester/.env를 로드한다 (DB 접속 정보 등).

    apps/trader/config.py와 동일하게 .env가 없어도 조용히 통과시킨다.
    DB 환경 변수가 실제로 없으면 PostgreDB 연결 시점에서 에러가 난다.
    """
    from dotenv import load_dotenv

    path = Path(env_file or os.getenv("QUANTPILOT_ENV_FILE", "apps/backtester/.env"))
    if path.exists():
        load_dotenv(path, override=False)


def build_db_config() -> dict:
    """PostgreDB 생성용 설정 dict를 반환한다.

    apps/trader/config.py의 build_db_config()와 동일한 POSTGRES_* 컨벤션을 따른다.
    """
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "user": os.getenv("POSTGRES_USER", ""),
        "password": os.getenv("POSTGRES_PASSWORD", ""),
        "database": os.getenv("POSTGRES_DB", "quantpilot"),
    }
