"""Bounded, read-only KIS PAPER authentication and balance check."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from apps.backtester.config import load_env
from core.utils.io import write_json


def inspect_paper():
    load_env()
    required = ("KIS_APP_KEY", "KIS_APP_SECRET", "KIS_DOMESTIC_STOCK_ACCOUNT_NO")
    report = {"status": "BLOCKED", "mode": "PAPER", "orders_submitted": False,
              "credential_presence": {name: bool(os.getenv(name)) for name in required}}
    if not all(report["credential_presence"].values()):
        return dict(report, reason="MISSING_PAPER_CREDENTIALS")
    if os.getenv("KIS_ENV", "paper").strip().lower() != "paper":
        return dict(report, reason="PAPER_ENV_REQUIRED")
    try:
        from core.broker.kis_api import KisBroker
        broker = KisBroker(mock=True)
        balance = broker.get_balance()
        report.update(status="PASS", authentication="VERIFIED", balance_schema="VERIFIED",
                      position_count=len(balance["positions"]))
    except Exception as exc:
        # SDK exception strings can contain tokens, URLs or account details.
        report.update(reason="PAPER_CONNECTION_FAILED", error_type=type(exc).__name__)
    return report


def check_paper():
    from apps.system.workflow import PROJECT_ROOT
    with tempfile.TemporaryDirectory(prefix="quantpilot-paper-check-") as temporary:
        output = Path(temporary) / "result.json"
        try:
            child = subprocess.run(
                [sys.executable, "-m", "apps.system.paper", str(output)],
                cwd=PROJECT_ROOT, env=dict(os.environ, PYTHONPATH=str(PROJECT_ROOT)),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=False,
            )
            if child.returncode == 0 and output.exists():
                return json.loads(output.read_text())
            reason = "PAPER_CHECK_FAILED"
        except subprocess.TimeoutExpired:
            reason = "PAPER_CHECK_TIMEOUT"
        return {"status": "BLOCKED", "mode": "PAPER", "orders_submitted": False, "reason": reason}


if __name__ == "__main__":
    write_json(Path(sys.argv[1]), inspect_paper())
