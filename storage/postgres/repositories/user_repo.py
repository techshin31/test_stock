from ..connection import PostgreDB


def create_user(db: PostgreDB, email: str, display_name: str | None = None) -> int:
    row = db.fetch_one(
        "INSERT INTO users (email, display_name) VALUES (%s, %s) RETURNING id",
        (email, display_name),
    )
    if row is None:
        raise RuntimeError(f"사용자 생성 실패: {email}")
    return row["id"]


def fetch_user_by_email(db: PostgreDB, email: str) -> dict | None:
    return db.fetch_one(
        "SELECT id, email, display_name, is_active, created_at FROM users WHERE email = %s",
        (email,),
    )


def fetch_user_by_id(db: PostgreDB, user_id: int) -> dict | None:
    return db.fetch_one(
        "SELECT id, email, display_name, is_active, created_at FROM users WHERE id = %s",
        (user_id,),
    )
