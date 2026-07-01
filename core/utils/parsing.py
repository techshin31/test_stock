from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def parse_int(value: Any, default: int = 0) -> int:
    """KIS API 응답값(문자열·숫자·Decimal)을 안전하게 int로 변환한다.

    쉼표 구분 숫자("1,234"), 소수 문자열("123.0"), Decimal, None, "" 모두 처리한다.
    변환 불가일 때는 default를 반환한다.
    """
    if value in (None, ""):
        return default
    if isinstance(value, Decimal):
        return int(value)
    text = str(value).replace(",", "").strip()
    try:
        return int(text)
    except ValueError:
        try:
            return int(Decimal(text))
        except (InvalidOperation, ValueError):
            return default
