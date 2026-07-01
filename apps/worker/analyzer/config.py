"""Versioned analyzer configuration."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field

from apps.worker.fa_contract import DEFAULT_CONFIG, FaV1Config


@dataclass(frozen=True)
class AnalyzerConfig:
    strategy_name: str
    scoring: FaV1Config = field(default_factory=lambda: DEFAULT_CONFIG)

    @property
    def model_version(self) -> str:
        return self.scoring.model_version

    @property
    def fingerprint(self) -> str:
        payload = {
            "strategy_name": self.strategy_name,
            "scoring": asdict(self.scoring),
        }
        canonical = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def validate(self) -> None:
        if not self.strategy_name.strip():
            raise ValueError("strategy_name must not be blank")
        self.scoring.validate()


def load_config(strategy_name: str | None = None) -> AnalyzerConfig:
    config = AnalyzerConfig(
        strategy_name=strategy_name or os.getenv("STRATEGY_NAME", "risk_neutral")
    )
    config.validate()
    return config
