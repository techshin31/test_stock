from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class WorkerConfig:
    fred_api_key: str | None
    kto_api_key: str | None
    dart_api_key: str | None
    company_years: list[int]
    dart_start_date: str  # YYYYMMDD
    show_progress: bool


def load_config(env_file: str | None = None) -> WorkerConfig:
    from dotenv import load_dotenv

    path = Path(env_file or os.getenv("QUANTPILOT_ENV_FILE", "apps/worker/.env"))
    if path.exists():
        load_dotenv(path, override=False)

    required = {
        "POSTGRES_HOST":     os.getenv("POSTGRES_HOST"),
        "POSTGRES_USER":     os.getenv("POSTGRES_USER"),
        "POSTGRES_PASSWORD": os.getenv("POSTGRES_PASSWORD"),
        "POSTGRES_DB":       os.getenv("POSTGRES_DB"),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"[CONFIG] 필수 환경 변수 누락: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    current_year = date.today().year
    years_env = os.getenv("COMPANY_YEARS")
    if years_env:
        company_years = [int(y.strip()) for y in years_env.split(",")]
    else:
        company_years = [current_year - 2, current_year - 1, current_year]

    return WorkerConfig(
        fred_api_key=os.getenv("FRED_API_KEY"),
        kto_api_key=os.getenv("KTO_API_KEY"),
        dart_api_key=os.getenv("DART_API_KEY"),
        company_years=company_years,
        dart_start_date=os.getenv("DART_START_DATE", "20200101"),
        show_progress=os.getenv("SHOW_PROGRESS", "true").lower() != "false",
    )


def build_db_config() -> dict:
    return {
        "host":     os.getenv("POSTGRES_HOST", "localhost"),
        "port":     int(os.getenv("POSTGRES_PORT", "5432")),
        "user":     os.getenv("POSTGRES_USER", ""),
        "password": os.getenv("POSTGRES_PASSWORD", ""),
        "database": os.getenv("POSTGRES_DB", "quantpilot"),
    }
