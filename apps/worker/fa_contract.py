"""Versioned data contract for the top-down monthly FA pipeline.

This module is shared by the collector and the future analyzer.  It contains
only deterministic configuration and validation helpers; it must not import
external data clients or database repositories.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Callable, Iterable, Mapping


MODEL_VERSION = "topdown-fa-v1.0.0"


@dataclass(frozen=True)
class MacroSignalContract:
    code: str
    category: str
    frequency: str
    transform: str
    source_code: str
    source_value_key: str
    available_date_rule: str
    eligible_industry_codes: tuple[str, ...] | None = None
    minimum_abs_correlation_override: float | None = None


MACRO_SIGNALS: tuple[MacroSignalContract, ...] = (
    MacroSignalContract("COPPER", "COMMODITY", "DAILY", "MARKET_RETURN", "YAHOO", "HG=F", "NEXT_KRX_SESSION"),
    MacroSignalContract("GOLD", "COMMODITY", "DAILY", "MARKET_RETURN", "YAHOO", "GC=F", "NEXT_KRX_SESSION"),
    MacroSignalContract("WTI", "COMMODITY", "DAILY", "MARKET_RETURN", "YAHOO", "CL=F", "NEXT_KRX_SESSION"),
    MacroSignalContract("TNX", "RATES", "DAILY", "YIELD_CHANGE", "YAHOO", "^TNX", "NEXT_KRX_SESSION"),
    MacroSignalContract("CPI", "RATES", "MONTHLY", "CPI_YOY_PRESSURE", "FRED", "CPIAUCSL", "SOURCE_RELEASE_DATE"),
    MacroSignalContract("SOX", "RISK", "DAILY", "MARKET_RETURN", "YAHOO", "^SOX", "NEXT_KRX_SESSION"),
    MacroSignalContract("BDRY", "RISK", "DAILY", "MARKET_RETURN", "YAHOO", "BDRY", "NEXT_KRX_SESSION"),
    MacroSignalContract("DXY", "FX", "DAILY", "MARKET_RETURN", "YAHOO", "DX=F", "NEXT_KRX_SESSION"),
    MacroSignalContract("VIX", "RISK", "DAILY", "MARKET_RETURN", "YAHOO", "^VIX", "NEXT_KRX_SESSION"),
    MacroSignalContract("USDKRW", "FX", "DAILY", "MARKET_RETURN", "YAHOO", "KRW=X", "NEXT_KRX_SESSION"),
    MacroSignalContract("US2Y", "RATES", "DAILY", "YIELD_CHANGE", "YAHOO", "^IRX", "NEXT_KRX_SESSION"),
    MacroSignalContract("GPR", "RISK", "MONTHLY", "MARKET_RETURN", "GPR", "GPR_MONTHLY", "SOURCE_RELEASE_DATE"),
    MacroSignalContract("US_MFG_IP", "MANUFACTURING", "MONTHLY", "YOY_CHANGE", "FRED", "IPMAN", "SOURCE_RELEASE_DATE"),
    MacroSignalContract("SEMIPROD", "MANUFACTURING", "MONTHLY", "YOY_CHANGE", "FRED", "IPG3344S", "SOURCE_RELEASE_DATE"),
    MacroSignalContract(
        "GTREND_KPOP", "HALLYU", "MONTHLY", "LEVEL", "GTRENDS",
        "K-pop", "NEXT_KRX_SESSION",
        eligible_industry_codes=("G2550", "G5010", "G2560"),
        minimum_abs_correlation_override=0.25,
    ),
    MacroSignalContract(
        "GTREND_KDRAMA", "HALLYU", "MONTHLY", "LEVEL", "GTRENDS",
        "Korean drama", "NEXT_KRX_SESSION",
        eligible_industry_codes=("G2550", "G5010", "G2560"),
        minimum_abs_correlation_override=0.25,
    ),
    MacroSignalContract(
        "KR_TOURIST", "HALLYU", "MONTHLY", "YOY_CHANGE", "KTO",
        "inbnd_touris_num", "SOURCE_RELEASE_DATE",
        eligible_industry_codes=("G2550", "G2530", "G5010", "G5020"),
        minimum_abs_correlation_override=0.20,
    ),
)

# 실거래 발행을 막는 핵심 시그널은 API 키 없이 시점 안전하게 수집 가능한 원천으로
# 제한한다. 나머지는 데이터가 있을 때 섹터 설명력을 보강하는 선택 시그널이다.
REQUIRED_MACRO_CODES = (
    "COPPER", "GOLD", "WTI", "TNX", "SOX",
    "BDRY", "DXY", "VIX", "USDKRW", "US2Y",
)
OPTIONAL_MACRO_CODES = tuple(
    signal.code for signal in MACRO_SIGNALS if signal.code not in REQUIRED_MACRO_CODES
)


ALL_WICS_INDUSTRIES = (
    "G1010", "G1510", "G2010", "G2020", "G2030",
    "G2510", "G2520", "G2530", "G2550", "G2560",
    "G3010", "G3020", "G3030", "G3510", "G3520",
    "G4010", "G4020", "G4030", "G4040", "G4510",
    "G4520", "G4530", "G5010", "G5020", "G5510",
)

UNSUPPORTED_INDUSTRIES: Mapping[str, str] = {}
SUPPORTED_INDUSTRIES = ALL_WICS_INDUSTRIES

_FINANCIAL_INDUSTRIES = frozenset({"G4010", "G4020", "G4030", "G4040"})
_BIOTECH_INDUSTRIES = frozenset({"G3520"})


class UnsupportedIndustryError(ValueError):
    """Raised when an industry has no validated score model."""


def score_model_for(industry_code: str) -> str:
    """Return the score model code without silently falling back."""
    if industry_code not in ALL_WICS_INDUSTRIES:
        raise UnsupportedIndustryError(f"{industry_code}: UNKNOWN_WICS_INDUSTRY")
    if industry_code in _FINANCIAL_INDUSTRIES:
        return "FINANCIAL_V1"
    if industry_code in _BIOTECH_INDUSTRIES:
        return "BIOTECH_V1"
    return "GENERAL_V1"


@dataclass(frozen=True)
class FaV1Config:
    model_version: str = MODEL_VERSION
    macro_trend_windows: tuple[int, int, int] = (20, 60, 120)
    macro_trend_weights: tuple[float, float, float] = (0.2, 0.3, 0.5)
    macro_direction_threshold: float = 0.5
    daily_relationship_years: int = 3
    cpi_relationship_years: int = 5
    minimum_weekly_samples: int = 104
    minimum_monthly_samples: int = 36
    minimum_abs_correlation: float = 0.15
    minimum_relationship_confidence: float = 0.50
    candidate_up_count: int = 5
    candidate_down_count: int = 3
    final_industry_count: int = 5
    companies_per_industry: int = 2
    allowed_company_size: str = "LARGE"
    minimum_company_fa_score: float = 50.0
    minimum_scoring_cohort_size: int = 10
    minimum_score_confidence: float = 0.70
    minimum_industry_price_coverage: float = 0.80
    sector_score_weights: tuple[float, float, float] = (0.45, 0.35, 0.20)
    macro_category_contribution_cap: float = 0.30
    cohort_quality_threshold: float = 60.0
    cohort_quality_penalty_rate: float = 0.20
    maximum_cohort_quality_penalty: float = 12.0
    enabled_market_types: tuple[str, ...] = ("KOSPI",)
    industry_price_source_priority: tuple[str, ...] = ("WISEINDEX", "DERIVED")
    # Retained for config fingerprint compatibility; same-day publish has no time gate.
    publish_deadline_kst: time = time(8, 30)

    def validate(self) -> None:
        if self.model_version != MODEL_VERSION:
            raise ValueError("config model_version must match MODEL_VERSION")
        if len(self.macro_trend_windows) != len(self.macro_trend_weights):
            raise ValueError("macro windows and weights must have equal lengths")
        if abs(sum(self.macro_trend_weights) - 1.0) > 1e-9:
            raise ValueError("macro trend weights must sum to 1")
        if abs(sum(self.sector_score_weights) - 1.0) > 1e-9:
            raise ValueError("sector score weights must sum to 1")
        if self.candidate_up_count + self.candidate_down_count != 8:
            raise ValueError("v1 must produce exactly eight sector candidates")
        if self.final_industry_count * self.companies_per_industry != 10:
            raise ValueError("v1 must allow up to ten companies")
        if not 0 <= self.cohort_quality_threshold <= 100:
            raise ValueError("cohort_quality_threshold must be between 0 and 100")
        if self.cohort_quality_penalty_rate < 0:
            raise ValueError("cohort_quality_penalty_rate must be non-negative")
        if self.maximum_cohort_quality_penalty < 0:
            raise ValueError("maximum_cohort_quality_penalty must be non-negative")
        if set(SUPPORTED_INDUSTRIES) & set(UNSUPPORTED_INDUSTRIES):
            raise ValueError("supported and unsupported industries overlap")


DEFAULT_CONFIG = FaV1Config()


SOURCE_INPUT_COLUMNS: Mapping[str, frozenset[str]] = {
    "macro_signals": frozenset({
        "signal_name_code", "category_code", "observation_date",
        "available_date", "value", "frequency_code", "source_code",
        "source_value_key", "revision_no", "collected_at",
    }),
    "wics_companies": frozenset({
        "stock_code", "base_date", "sector_code", "industry_code",
        "mkt_val", "trd_amt", "company_size_code", "collected_at",
    }),
    "wics_industry_prices": frozenset({
        "industry_code", "price_date", "index_value", "source_code",
        "constituent_base_date", "method_version", "collected_at",
    }),
    "wics_constituent_prices": frozenset({
        "stock_code", "price_date", "close", "source_code", "collected_at",
    }),
    "financial_statements": frozenset({
        "stock_code", "corp_code", "bsns_year", "reprt_code", "fs_div",
        "sj_div", "account_id", "account_nm", "source_rcept_no",
        "rcept_dt", "available_date", "period_start", "period_end",
        "thstrm_amount", "frmtrm_amount", "bfefrmtrm_amount",
        "thstrm_add_amount", "frmtrm_add_amount", "revision_no",
        "collected_at",
    }),
    "company_risk_states": frozenset({
        "id", "stock_code", "risk_action_code", "reason_code",
        "source_dart_event_id", "effective_date", "expires_at",
        "policy_version", "is_manual_override", "detail", "updated_at",
    }),
}


def missing_source_columns(
    actual_columns: Mapping[str, Iterable[str]],
) -> dict[str, tuple[str, ...]]:
    """Return missing Phase 0 columns by source table."""
    missing: dict[str, tuple[str, ...]] = {}
    for table, required in SOURCE_INPUT_COLUMNS.items():
        actual = set(actual_columns.get(table, ()))
        absent = tuple(sorted(required - actual))
        if absent:
            missing[table] = absent
    return missing


@dataclass(frozen=True)
class MonthlyRunDates:
    analysis_month: date
    cutoff_date: date
    effective_date: date


def monthly_run_dates(
    analysis_month: date,
    is_trading_day: Callable[[str], bool],
) -> MonthlyRunDates:
    """Build the monthly cutoff and first effective KRX session."""
    month_start = analysis_month.replace(day=1)
    cutoff_date = month_start - timedelta(days=1)
    effective_date = month_start
    while not is_trading_day(effective_date.isoformat()):
        effective_date += timedelta(days=1)
        if effective_date.month != month_start.month:
            raise ValueError("analysis month contains no trading session")
    return MonthlyRunDates(month_start, cutoff_date, effective_date)


ANALYZE_TARGET_STEPS: Mapping[str, tuple[str, ...]] = {
    "macro": ("readiness", "quarter_fa", "macro"),
    "sector": ("readiness", "quarter_fa", "macro", "sector"),
    "company": ("readiness", "quarter_fa", "macro", "sector", "company"),
    "all": (
        "readiness", "quarter_fa", "macro", "sector", "company",
        "validation", "publish_optional",
    ),
}


DEFAULT_CONFIG.validate()
