from __future__ import annotations

import argparse


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m apps.user",
        description="QuantPilot 사용자 등록 도구",
    )
    parser.add_argument(
        "command",
        choices=["register", "list"],
        help="register: 사용자 및 증권사 자격증명 등록 | list: 등록된 자격증명 목록 조회",
    )
    return parser.parse_args()


def _save_credential(db, cfg, account_number: str, account_product_code: str, account_type: str) -> int:
    from storage.postgres.repositories.credential_repo import save_broker_credential

    return save_broker_credential(
        db,
        user_id=cfg._user_id,
        broker_code=cfg.broker_code,
        account_number=account_number,
        api_key=cfg.api_key,
        api_secret=cfg.api_secret,
        environment_code=cfg.environment_code,
        extra={"account_product_code": account_product_code, "account_type": account_type},
    )


def run_register() -> None:
    from apps.user.config import build_db_config, load_config
    from storage.postgres.connection import PostgreDB
    from storage.postgres.repositories.credential_repo import save_broker_credential
    from storage.postgres.repositories.user_repo import create_user, fetch_user_by_email

    cfg = load_config()
    db = PostgreDB(build_db_config())

    try:
        # 1. 사용자 생성 또는 확인
        existing = fetch_user_by_email(db, cfg.email)
        if existing:
            user_id = existing["id"]
            print(f"[INFO] 기존 사용자 확인: id={user_id}, email={cfg.email}")
        else:
            user_id = create_user(db, cfg.email, cfg.display_name)
            print(f"[INFO] 신규 사용자 생성 완료: id={user_id}, email={cfg.email}")

        # 2. 주식 계좌 자격증명 저장
        stock_cred_id = save_broker_credential(
            db,
            user_id=user_id,
            broker_code=cfg.broker_code,
            account_number=cfg.stock_account_number,
            api_key=cfg.api_key,
            api_secret=cfg.api_secret,
            environment_code=cfg.environment_code,
            extra={
                "account_product_code": cfg.stock_account_product_code,
                "account_type": "STOCK",
            },
        )
        masked = _mask(cfg.stock_account_number)
        print(
            f"[INFO] 주식 계좌 저장 완료: id={stock_cred_id}, "
            f"broker={cfg.broker_code}, env={cfg.environment_code}, account={masked}"
        )

        # 3. 선물 계좌 자격증명 저장 (선택)
        if cfg.futures_account_number and cfg.futures_account_product_code:
            futures_cred_id = save_broker_credential(
                db,
                user_id=user_id,
                broker_code=cfg.broker_code,
                account_number=cfg.futures_account_number,
                api_key=cfg.api_key,
                api_secret=cfg.api_secret,
                environment_code=cfg.environment_code,
                extra={
                    "account_product_code": cfg.futures_account_product_code,
                    "account_type": "FUTURES",
                },
            )
            masked_f = _mask(cfg.futures_account_number)
            print(
                f"[INFO] 선물 계좌 저장 완료: id={futures_cred_id}, "
                f"broker={cfg.broker_code}, env={cfg.environment_code}, account={masked_f}"
            )
    finally:
        db.close()


def run_list() -> None:
    from apps.user.config import build_db_config, load_config
    from storage.postgres.connection import PostgreDB
    from storage.postgres.repositories.credential_repo import fetch_credentials_by_user
    from storage.postgres.repositories.user_repo import fetch_user_by_email

    cfg = load_config()
    db = PostgreDB(build_db_config())

    try:
        user = fetch_user_by_email(db, cfg.email)
        if not user:
            print(f"[INFO] 사용자를 찾을 수 없습니다: {cfg.email}")
            return

        print(f"[USER] id={user['id']} | email={user['email']} | active={user['is_active']}")

        creds = fetch_credentials_by_user(db, user["id"])
        if not creds:
            print("  자격증명 없음")
            return
        for c in creds:
            extra = c.get("extra") or {}
            account_type = extra.get("account_type", "-")
            print(
                f"  [{c['id']}] broker={c['broker_code']} | type={account_type} | "
                f"env={c['environment_code']} | account={_mask(c['account_number'])} | "
                f"active={c['is_active']}"
            )
    finally:
        db.close()


def _mask(account_number: str) -> str:
    return f"****{account_number[-4:]}" if len(account_number) >= 4 else "****"


def main() -> None:
    args = _parse_args()
    if args.command == "register":
        run_register()
    elif args.command == "list":
        run_list()


if __name__ == "__main__":
    main()
