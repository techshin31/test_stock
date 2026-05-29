from __future__ import annotations

import argparse
import json
from typing import Any

from api.kis_client import KisClient


def main() -> None:
    parser = argparse.ArgumentParser(description="KIS Open API smoke tests")
    parser.add_argument("command", choices=["token", "balance", "price"])
    parser.add_argument("stock_code", nargs="?", default="005930")
    args = parser.parse_args()

    client = KisClient.from_env()

    if args.command == "token":
        result = client.issue_access_token()
        result = _mask_token_response(result)
    elif args.command == "balance":
        result = client.get_balance()
    else:
        result = client.get_domestic_stock_price(args.stock_code)

    print(json.dumps(result, ensure_ascii=False, indent=2))


def _mask_token_response(data: dict[str, Any]) -> dict[str, Any]:
    masked = dict(data)
    token = masked.get("access_token")
    if isinstance(token, str) and len(token) > 12:
        masked["access_token"] = f"{token[:6]}...{token[-6:]}"
    return masked


if __name__ == "__main__":
    main()

