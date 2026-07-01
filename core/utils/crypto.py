import os
from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    key = os.environ.get("CREDENTIAL_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "CREDENTIAL_ENCRYPTION_KEY 환경변수가 설정되지 않았습니다. "
            "generate_key()로 키를 생성한 뒤 .env에 추가하세요."
        )
    return Fernet(key.encode())


def encrypt(plaintext: str) -> str:
    """평문 문자열을 Fernet(AES-128-CBC + HMAC-SHA256)으로 암호화합니다."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """encrypt()로 암호화된 문자열을 복호화합니다."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def generate_key() -> str:
    """CREDENTIAL_ENCRYPTION_KEY 값을 새로 생성합니다. 최초 1회만 실행하세요."""
    return Fernet.generate_key().decode()
