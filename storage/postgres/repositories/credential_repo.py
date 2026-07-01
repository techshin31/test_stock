import json

from core.utils.crypto import decrypt, encrypt

from ..connection import PostgreDB


def save_broker_credential(
    db: PostgreDB,
    user_id: int,
    broker_code: str,
    account_number: str,
    api_key: str,
    api_secret: str,
    environment_code: str = "PAPER",
    extra: dict | None = None,
) -> int:
    row = db.fetch_one(
        """
        INSERT INTO user_broker_credentials
            (user_id, broker_code, account_number, api_key, api_secret, environment_code, extra)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id, broker_code, account_number, environment_code)
            DO UPDATE SET
                api_key    = EXCLUDED.api_key,
                api_secret = EXCLUDED.api_secret,
                extra      = EXCLUDED.extra,
                is_active  = TRUE,
                updated_at = NOW()
        RETURNING id
        """,
        (
            user_id,
            broker_code,
            account_number,
            encrypt(api_key),
            encrypt(api_secret),
            environment_code,
            json.dumps(extra or {}),
        ),
    )
    return row["id"]


def fetch_credentials_by_user(db: PostgreDB, user_id: int) -> list[dict]:
    rows = db.fetch_all(
        """
        SELECT id, user_id, broker_code, account_number, api_key, api_secret,
               environment_code, extra, is_active, created_at, updated_at
        FROM user_broker_credentials
        WHERE user_id = %s
        ORDER BY broker_code, environment_code
        """,
        (user_id,),
    )
    return [_decrypt_row(row) for row in rows]


def fetch_active_credential(
    db: PostgreDB,
    user_id: int,
    broker_code: str,
    account_number: str,
    environment_code: str = "PAPER",
) -> dict | None:
    row = db.fetch_one(
        """
        SELECT id, user_id, broker_code, account_number, api_key, api_secret,
               environment_code, extra, is_active, created_at, updated_at
        FROM user_broker_credentials
        WHERE user_id = %s
          AND broker_code = %s
          AND account_number = %s
          AND environment_code = %s
          AND is_active = TRUE
        """,
        (user_id, broker_code, account_number, environment_code),
    )
    return _decrypt_row(row) if row else None


def fetch_credential_by_account_type(
    db: PostgreDB,
    user_id: int,
    broker_code: str,
    account_type: str,
    environment_code: str = "PAPER",
) -> dict | None:
    row = db.fetch_one(
        """
        SELECT id, user_id, broker_code, account_number, api_key, api_secret,
               environment_code, extra, is_active, created_at, updated_at
        FROM user_broker_credentials
        WHERE user_id = %s
          AND broker_code = %s
          AND environment_code = %s
          AND extra->>'account_type' = %s
          AND is_active = TRUE
        """,
        (user_id, broker_code, environment_code, account_type),
    )
    return _decrypt_row(row) if row else None


def deactivate_credential(db: PostgreDB, credential_id: int) -> None:
    db.execute(
        "UPDATE user_broker_credentials SET is_active = FALSE, updated_at = NOW() WHERE id = %s",
        (credential_id,),
    )


def _decrypt_row(row: dict) -> dict:
    result = dict(row)
    result["api_key"] = decrypt(result["api_key"])
    result["api_secret"] = decrypt(result["api_secret"])
    return result
