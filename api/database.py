"""Connection configuration shared by dashboard database readers."""
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv


def connection_kwargs(project_root: Path, *, dotenv_loader=load_dotenv) -> dict | None:
    dotenv_loader(project_root / '.env', override=False)
    password = os.getenv('POSTGRES_PASSWORD')
    if not password:
        return None
    return {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': int(os.getenv('POSTGRES_PORT', '5433')),
        'dbname': os.getenv('POSTGRES_DB', 'quantpilot_db'),
        'user': os.getenv('POSTGRES_USER', 'admin'),
        'password': password,
        'connect_timeout': 2,
    }


def connect_database(project_root: Path):
    """Return a short-lived connection, or None when the DB is unavailable."""
    params = connection_kwargs(project_root)
    if params is None:
        return None
    try:
        return psycopg.connect(**params, row_factory=psycopg.rows.dict_row)
    except (OSError, psycopg.Error):
        return None
