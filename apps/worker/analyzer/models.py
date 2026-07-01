"""Internal immutable models used across analyzer jobs."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    PUBLISHED = "PUBLISHED"


class MacroDirection(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


@dataclass(frozen=True)
class MacroResult:
    signal_name_code: str
    last_observation_date: date
    last_available_date: date
    direction_code: MacroDirection
    trend_raw: float
    trend_strength: float
    data_point_count: int
    confidence: float
    calculation_detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RelationshipResult:
    signal_name_code: str
    industry_code: str
    frequency_code: str
    correlation: float | None
    beta: float | None
    sample_count: int
    sign_stability: float
    relationship_confidence: float
    contribution: float
    is_eligible: bool


@dataclass(frozen=True)
class SectorResult:
    sector_code: str
    industry_code: str
    sector_score: float
    is_candidate: bool = False
    is_selected: bool = False
    reason_code: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompanyResult:
    stock_code: str
    industry_code: str
    fa_score: float | None
    score_confidence: float | None
    is_eligible: bool
    is_selected: bool = False
    exclusion_reason_code: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisRunContext:
    run_id: int
    target: str
    strategy_id: int
    analysis_month: date
    cutoff_date: date
    effective_date: date
    input_hash: str
    model_version: str
    created: bool
    input_quality: dict[str, Any] = field(default_factory=dict)
