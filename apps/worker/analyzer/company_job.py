"""Quarterly company FA ledger and monthly company selection calculations."""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import date
from typing import Any

import pandas as pd

from apps.worker.analyzer.config import AnalyzerConfig
from apps.worker.fa_contract import ALL_WICS_INDUSTRIES, UnsupportedIndustryError, score_model_for
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.company_quarter_fa_repo import (
    fetch_latest_company_fa_as_of,
    upsert_company_quarter_fa,
)
from storage.postgres.repositories.company_repo import fetch_company_statuses
from storage.postgres.repositories.company_risk_repo import (
    fetch_active_company_risk_states,
)
from storage.postgres.repositories.fa_analysis_repo import (
    fetch_sector_results,
    insert_company_results,
)
from storage.postgres.repositories.financial_repo import fetch_financial_statements_as_of
from storage.postgres.repositories.wics_repo import (
    fetch_latest_wics_snapshot,
    fetch_wics_companies,
)


_QUARTER_BY_REPORT = {"11013": 1, "11012": 2, "11014": 3, "11011": 4}

_ACCOUNT_MAP: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "revenue": ("IS", ("ifrs_Revenue", "ifrs-full_Revenue"), ("매출액", "수익(매출액)")),
    "operating_income": ("IS", ("dart_OperatingIncomeLoss",), ("영업이익",)),
    "net_income": ("IS", ("ifrs_ProfitLoss", "ifrs-full_ProfitLoss"), ("당기순이익", "분기순이익", "반기순이익")),
    "total_assets": ("BS", ("ifrs_Assets", "ifrs-full_Assets"), ("자산총계",)),
    "total_liabilities": ("BS", ("ifrs_Liabilities", "ifrs-full_Liabilities"), ("부채총계",)),
    "total_equity": ("BS", ("ifrs_Equity", "ifrs-full_Equity"), ("자본총계",)),
    "current_assets": ("BS", ("ifrs-full_CurrentAssets",), ("유동자산",)),
    "current_liabilities": ("BS", ("ifrs-full_CurrentLiabilities",), ("유동부채",)),
    "operating_cashflow": (
        "CF",
        (
            "ifrs-full_CashFlowsFromUsedInOperatingActivities",
            "ifrs-full_CashFlowsFromOperatingActivities",
        ),
        ("영업활동현금흐름", "영업활동으로 인한 현금흐름"),
    ),
    "capex": (
        "CF",
        (
            "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
            "ifrs-full_AcquisitionOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        ),
        ("유형자산의 취득", "유형자산취득"),
    ),
}

_FLOW_METRICS = {
    "revenue", "operating_income", "net_income", "operating_cashflow", "capex"
}


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(result) else result


def _ranking_number(value: Any, default: float = 0.0) -> float:
    result = _number(value)
    return default if result is None else result


def _account_row(rows: list[dict], metric: str) -> dict | None:
    statement, account_ids, keywords = _ACCOUNT_MAP[metric]
    candidates = [
        row for row in rows
        if row.get("sj_div") == statement
        or (statement == "IS" and row.get("sj_div") == "CIS")
    ]
    for account_id in account_ids:
        match = next((row for row in candidates if row.get("account_id") == account_id), None)
        if match is not None:
            return match
    for keyword in keywords:
        match = next(
            (row for row in candidates if keyword in str(row.get("account_nm") or "")),
            None,
        )
        if match is not None:
            return match
    return None


def _extract_report_amounts(rows: list[dict]) -> tuple[dict[str, float | None], dict[str, float | None]]:
    cumulative: dict[str, float | None] = {}
    individual_hint: dict[str, float | None] = {}
    for metric in _ACCOUNT_MAP:
        row = _account_row(rows, metric)
        if row is None:
            cumulative[metric] = None
            individual_hint[metric] = None
            continue
        current = _number(row.get("thstrm_amount"))
        if metric in _FLOW_METRICS:
            cumulative[metric] = _number(row.get("thstrm_add_amount")) or current
            individual_hint[metric] = current
        else:
            cumulative[metric] = current
            individual_hint[metric] = current
    return cumulative, individual_hint


def build_quarter_fundamentals(financial_rows: list[dict]) -> list[dict]:
    """Convert DART cumulative flows to deterministic individual quarters."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in financial_rows:
        grouped[row["source_rcept_no"]].append(row)

    reports: list[dict] = []
    for receipt_rows in grouped.values():
        first = receipt_rows[0]
        reprt_code = first["reprt_code"]
        if reprt_code not in _QUARTER_BY_REPORT:
            continue
        cumulative, individual_hint = _extract_report_amounts(receipt_rows)
        reports.append({
            "stock_code": first["stock_code"],
            "source_rcept_no": first["source_rcept_no"],
            "fiscal_year": int(first["bsns_year"]),
            "quarter_no": _QUARTER_BY_REPORT[reprt_code],
            "reprt_code": reprt_code,
            "fs_div": first["fs_div"],
            "period_end": first["period_end"],
            "available_date": first["available_date"],
            "_cumulative": cumulative,
            "_individual_hint": individual_hint,
        })

    reports.sort(key=lambda row: (
        row["stock_code"], row["fiscal_year"], row["quarter_no"],
        row["available_date"], row["source_rcept_no"],
    ))
    latest_by_period: dict[tuple[str, int, int, str], dict] = {}
    for report in reports:
        key = (
            report["stock_code"], report["fiscal_year"],
            report["quarter_no"], report["fs_div"],
        )
        latest_by_period[key] = report

    output: list[dict] = []
    previous_cumulative: dict[tuple[str, int, str, str], float | None] = {}
    for report in sorted(latest_by_period.values(), key=lambda row: (
        row["stock_code"], row["fiscal_year"], row["quarter_no"], row["fs_div"]
    )):
        result = {key: value for key, value in report.items() if not key.startswith("_")}
        for metric, cumulative_value in report["_cumulative"].items():
            if metric not in _FLOW_METRICS:
                result[metric] = cumulative_value
                continue
            previous_key = (
                report["stock_code"], report["fiscal_year"], report["fs_div"], metric
            )
            if report["quarter_no"] == 1:
                individual = cumulative_value
            else:
                previous = previous_cumulative.get(previous_key)
                individual = (
                    cumulative_value - previous
                    if cumulative_value is not None and previous is not None
                    else report["_individual_hint"].get(metric)
                )
            result[metric] = individual
            previous_cumulative[previous_key] = cumulative_value
        result["fiscal_quarter"] = f"{report['fiscal_year']}Q{report['quarter_no']}"
        capex = result.get("capex")
        ocf = result.get("operating_cashflow")
        result["fcf"] = ocf - abs(capex) if ocf is not None and capex is not None else None
        output.append(result)
    return output


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _latest_wics_by_date(wics_rows: list[dict]):
    by_stock: dict[str, list[dict]] = defaultdict(list)
    for row in wics_rows:
        if row.get("industry_code") in ALL_WICS_INDUSTRIES:
            by_stock[row["stock_code"]].append(row)
    for rows in by_stock.values():
        rows.sort(key=lambda row: row["base_date"])

    def lookup(stock_code: str, target_date: date) -> dict | None:
        rows = by_stock.get(stock_code, [])
        dates = [row["base_date"] for row in rows]
        index = bisect_right(dates, target_date) - 1
        return rows[index] if index >= 0 else None

    return lookup


def _add_derived_metrics(records: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    if frame.empty:
        return frame
    frame = frame.sort_values(["stock_code", "fiscal_year", "quarter_no"])
    for index, row in frame.iterrows():
        frame.at[index, "operating_margin"] = _safe_div(row.get("operating_income"), row.get("revenue"))
        frame.at[index, "roe"] = _safe_div(row.get("net_income"), row.get("total_equity"))
        frame.at[index, "roa"] = _safe_div(row.get("net_income"), row.get("total_assets"))
        frame.at[index, "debt_ratio"] = _safe_div(row.get("total_liabilities"), row.get("total_equity"))
        frame.at[index, "current_ratio"] = _safe_div(row.get("current_assets"), row.get("current_liabilities"))
        frame.at[index, "ocf_to_revenue"] = _safe_div(row.get("operating_cashflow"), row.get("revenue"))
        frame.at[index, "ocf_to_net_income"] = _safe_div(row.get("operating_cashflow"), row.get("net_income"))
        market_cap = row.get("market_cap")
        frame.at[index, "per_proxy"] = _safe_div(market_cap, row.get("net_income"))
        frame.at[index, "pbr_proxy"] = _safe_div(market_cap, row.get("total_equity"))

    by_key = {
        (row.stock_code, int(row.fiscal_year), int(row.quarter_no)): row
        for row in frame.itertuples()
    }
    for index, row in frame.iterrows():
        prior = by_key.get((row["stock_code"], int(row["fiscal_year"]) - 1, int(row["quarter_no"])))
        if prior is None:
            continue
        frame.at[index, "revenue_growth_yoy"] = _safe_div(
            row.get("revenue") - prior.revenue if row.get("revenue") is not None and prior.revenue is not None else None,
            abs(prior.revenue) if prior.revenue is not None else None,
        )
        frame.at[index, "operating_income_growth_yoy"] = _safe_div(
            row.get("operating_income") - prior.operating_income
            if row.get("operating_income") is not None and prior.operating_income is not None else None,
            abs(prior.operating_income) if prior.operating_income is not None else None,
        )
        frame.at[index, "operating_margin_change_yoy"] = (
            row.get("operating_margin") - prior.operating_margin
            if row.get("operating_margin") is not None and prior.operating_margin is not None else None
        )
        frame.at[index, "operating_cashflow_change_yoy"] = _safe_div(
            row.get("operating_cashflow") - prior.operating_cashflow
            if row.get("operating_cashflow") is not None and prior.operating_cashflow is not None else None,
            abs(prior.operating_cashflow) if prior.operating_cashflow is not None else None,
        )
        frame.at[index, "debt_ratio_change_yoy"] = (
            row.get("debt_ratio") - prior.debt_ratio
            if row.get("debt_ratio") is not None and prior.debt_ratio is not None else None
        )
    return frame


_GENERAL_V1_LEVEL_WEIGHTS = {
    "operating_margin": (10.0, True), "roe": (10.0, True),
    "debt_ratio": (7.5, False), "current_ratio": (7.5, True),
    "ocf_to_revenue": (7.5, True), "ocf_to_net_income": (3.75, True),
    "fcf": (3.75, True), "per_proxy": (5.0, False), "pbr_proxy": (5.0, False),
}
_GENERAL_V1_CHANGE_WEIGHTS = {
    "revenue_growth_yoy": (10.0, True),
    "operating_income_growth_yoy": (8.0, True),
    "operating_margin_change_yoy": (6.0, True),
    "operating_cashflow_change_yoy": (6.0, True),
}

# 금융 (은행·보험·증권·다각화금융): 부채비율·유동비율 제외, ROE·ROA 비중 확대
_FINANCIAL_V1_LEVEL_WEIGHTS = {
    "roe": (20.0, True),
    "roa": (15.0, True),
    "operating_margin": (12.5, True),
    "pbr_proxy": (7.5, False),
    "per_proxy": (5.0, False),
}
_FINANCIAL_V1_CHANGE_WEIGHTS = {
    "revenue_growth_yoy": (12.0, True),
    "operating_income_growth_yoy": (12.0, True),
    "operating_margin_change_yoy": (6.0, True),
}

# 바이오텍: 수익성 대신 생존력(유동비율) + 손실 궤적 중심
_BIOTECH_V1_LEVEL_WEIGHTS = {
    "current_ratio": (20.0, True),
    "debt_ratio": (15.0, False),
    "roe": (10.0, True),
    "roa": (10.0, True),
    "pbr_proxy": (5.0, False),
}
_BIOTECH_V1_CHANGE_WEIGHTS = {
    "operating_margin_change_yoy": (12.0, True),
    "revenue_growth_yoy": (10.0, True),
    "operating_cashflow_change_yoy": (8.0, True),
}

_MODEL_WEIGHTS: dict[str, tuple[dict, dict]] = {
    "GENERAL_V1":  (_GENERAL_V1_LEVEL_WEIGHTS,  _GENERAL_V1_CHANGE_WEIGHTS),
    "FINANCIAL_V1": (_FINANCIAL_V1_LEVEL_WEIGHTS, _FINANCIAL_V1_CHANGE_WEIGHTS),
    "BIOTECH_V1":  (_BIOTECH_V1_LEVEL_WEIGHTS,  _BIOTECH_V1_CHANGE_WEIGHTS),
}


def _calc_risk_penalty(row: pd.Series, model_code: str) -> float:
    penalty = 0.0

    if model_code == "GENERAL_V1":
        if (row.get("net_income") or 0) > 0 and (row.get("operating_cashflow") or 0) < 0:
            penalty += 3.0
        debt_change = row.get("debt_ratio_change_yoy")
        if debt_change is not None and not pd.isna(debt_change) and debt_change > 0.5:
            penalty += 3.0
        if (
            (row.get("revenue_growth_yoy") or 0) > 0
            and (row.get("operating_income_growth_yoy") or 0) < 0
            and (row.get("operating_cashflow_change_yoy") or 0) < 0
        ):
            penalty += 3.0

    elif model_code == "FINANCIAL_V1":
        if (row.get("net_income") or 0) < 0:
            penalty += 5.0
        if (row.get("operating_income") or 0) < 0:
            penalty += 3.0
        if (
            (row.get("revenue_growth_yoy") or 0) > 0
            and (row.get("operating_income_growth_yoy") or 0) < 0
            and (row.get("operating_cashflow_change_yoy") or 0) < 0
        ):
            penalty += 3.0

    elif model_code == "BIOTECH_V1":
        current_ratio = row.get("current_ratio")
        if current_ratio is not None and not pd.isna(current_ratio) and current_ratio < 1.0:
            penalty += 5.0
        debt_change = row.get("debt_ratio_change_yoy")
        if debt_change is not None and not pd.isna(debt_change) and debt_change > 0.5:
            penalty += 3.0
        if (
            (row.get("revenue_growth_yoy") or 0) < 0
            and (row.get("operating_cashflow_change_yoy") or 0) < 0
        ):
            penalty += 3.0

    return min(penalty, 10.0)


def score_quarter_fundamentals(frame: pd.DataFrame, config: AnalyzerConfig) -> list[dict]:
    if frame.empty:
        return []
    frame = frame.copy()
    for group_key, group in frame.groupby(["fiscal_quarter", "score_model_code"]):
        if len(group) < config.scoring.minimum_scoring_cohort_size:
            continue
        model_code = group_key[1]
        level_w, change_w = _MODEL_WEIGHTS.get(model_code, _MODEL_WEIGHTS["GENERAL_V1"])
        for metric, (_, higher_is_better) in {**level_w, **change_w}.items():
            frame.loc[group.index, f"_pct_{metric}"] = group[metric].rank(
                pct=True, ascending=higher_is_better, method="average"
            )

    results: list[dict] = []
    for _, row in frame.iterrows():
        model_code = row.get("score_model_code", "GENERAL_V1")
        level_w, change_w = _MODEL_WEIGHTS.get(model_code, _MODEL_WEIGHTS["GENERAL_V1"])
        detail: dict[str, Any] = {"percentiles": {}}
        def axis_score(weights: dict[str, tuple[float, bool]], total: float):
            weighted = 0.0
            available_weight = 0.0
            for metric, (weight, _) in weights.items():
                percentile = row.get(f"_pct_{metric}")
                if percentile is not None and not pd.isna(percentile):
                    weighted += float(percentile) * weight
                    available_weight += weight
                    detail["percentiles"][metric] = float(percentile)
            score = weighted / available_weight * total if available_weight else 0.0
            return score, available_weight / total

        level_score, level_confidence = axis_score(level_w, 60.0)
        change_score, change_confidence = axis_score(change_w, 30.0)
        risk_inputs = [row.get(name) for name in (
            "total_equity", "debt_ratio", "operating_cashflow", "company_status_code"
        )]
        risk_confidence = sum(
            value is not None and not (isinstance(value, float) and pd.isna(value))
            for value in risk_inputs
        ) / len(risk_inputs)
        risk_penalty = _calc_risk_penalty(row, model_code)
        risk_score = 10.0 - risk_penalty
        fa_score = min(max(level_score + change_score + risk_score, 0.0), 100.0)
        score_confidence = (
            level_confidence * 0.6 + change_confidence * 0.3 + risk_confidence * 0.1
        )
        excluded_reason = None
        if row.get("score_model_code") == "UNSUPPORTED":
            excluded_reason = "MAPPING_ERROR"
        elif row.get("company_status_code") != "ACTIVE":
            excluded_reason = "MAPPING_ERROR"
        elif row.get("total_equity") is None or row.get("total_equity") <= 0:
            excluded_reason = "CAPITAL_IMPAIRMENT"
        elif score_confidence < config.scoring.minimum_score_confidence:
            excluded_reason = "LOW_CONFIDENCE"
        elif fa_score < config.scoring.minimum_company_fa_score:
            excluded_reason = "LOW_FA_SCORE"
        result = row.to_dict()
        result.update({
            "level_score": level_score,
            "change_score": change_score,
            "risk_penalty": risk_penalty,
            "risk_score": risk_score,
            "fa_score": fa_score,
            "level_confidence": level_confidence,
            "change_confidence": change_confidence,
            "score_confidence": score_confidence,
            "is_eligible": excluded_reason is None,
            "excluded_reason_code": excluded_reason,
            "score_detail": detail,
        })
        results.append(result)
    return results


def refresh_quarterly_scores(
    db: PostgreDB,
    cutoff_date: date,
    config: AnalyzerConfig,
) -> int:
    financial_rows = fetch_financial_statements_as_of(db, cutoff_date)
    fundamentals = build_quarter_fundamentals(financial_rows)
    if not fundamentals:
        return 0
    stock_codes = sorted({row["stock_code"] for row in fundamentals})
    statuses = {
        row["stock_code"]: row for row in fetch_company_statuses(db, stock_codes)
    }
    wics_rows = fetch_wics_companies(db, stock_codes=stock_codes, end_date=cutoff_date)
    wics_lookup = _latest_wics_by_date(wics_rows)
    for row in fundamentals:
        wics = wics_lookup(row["stock_code"], row["available_date"])
        status = statuses.get(row["stock_code"], {})
        row["company_status_code"] = status.get("status_code")
        row["market_cap"] = _number(wics.get("mkt_val")) if wics else None
        row["market_data_date"] = wics.get("base_date") if wics else None
        row["industry_code"] = wics.get("industry_code") if wics else None
        try:
            row["score_model_code"] = score_model_for(row["industry_code"])
        except UnsupportedIndustryError:
            row["score_model_code"] = "UNSUPPORTED"
        row["model_version"] = config.model_version
    frame = _add_derived_metrics(fundamentals)
    scored = score_quarter_fundamentals(frame, config)
    clean_rows = []
    for row in scored:
        clean_rows.append({
            key: (None if isinstance(value, float) and pd.isna(value) else value)
            for key, value in row.items()
            if not key.startswith("_")
        })
    return upsert_company_quarter_fa(db, clean_rows)


def select_companies(
    selected_sector_rows: list[dict],
    snapshot_rows: list[dict],
    company_fa_rows: list[dict],
    company_status_rows: list[dict],
    config: AnalyzerConfig,
    *,
    buy_blocked_codes: set[str] | None = None,
    company_risk_rows: list[dict] | None = None,
) -> list[dict]:
    """Apply hard filters and select up to the configured count per industry."""
    risk_by_stock = {
        row["stock_code"]: row for row in (company_risk_rows or [])
    }
    blocked = set(buy_blocked_codes or set()) | set(risk_by_stock)
    fa_by_stock = {row["stock_code"]: row for row in company_fa_rows}
    status_by_stock = {row["stock_code"]: row for row in company_status_rows}
    sector_by_industry = {row["industry_code"]: row for row in selected_sector_rows}
    results: list[dict] = []

    for member in snapshot_rows:
        industry_code = member.get("industry_code")
        sector_result = sector_by_industry.get(industry_code)
        if sector_result is None:
            continue
        stock_code = member["stock_code"]
        fa = fa_by_stock.get(stock_code)
        status = status_by_stock.get(stock_code)
        risk_state = risk_by_stock.get(stock_code)
        exclusion = None
        if status is None or not industry_code:
            exclusion = "MAPPING_ERROR"
        elif status.get("status_code") != "ACTIVE":
            exclusion = "BUY_BLOCKED"
        elif status.get("market_type_code") not in config.scoring.enabled_market_types:
            exclusion = "MAPPING_ERROR"
        elif member.get("company_size_code") != config.scoring.allowed_company_size:
            exclusion = "NOT_LARGE"
        elif fa is None:
            exclusion = "NO_QUARTER_FA"
        elif _ranking_number(fa.get("total_equity"), 0.0) <= 0 or fa.get("excluded_reason_code") == "CAPITAL_IMPAIRMENT":
            exclusion = "CAPITAL_IMPAIRMENT"
        elif _ranking_number(fa.get("score_confidence"), -1.0) < config.scoring.minimum_score_confidence:
            exclusion = "LOW_CONFIDENCE"
        elif _ranking_number(fa.get("fa_score"), -1.0) < config.scoring.minimum_company_fa_score:
            exclusion = "LOW_FA_SCORE"
        elif not fa.get("is_eligible"):
            exclusion = fa.get("excluded_reason_code") or "LOW_FA_SCORE"
        elif stock_code in blocked:
            exclusion = "BUY_BLOCKED"

        results.append({
            "sector_result_id": sector_result["id"],
            "stock_code": stock_code,
            "company_quarter_fa_id": fa.get("id") if fa else None,
            "sector_code": member["sector_code"],
            "industry_code": industry_code,
            "company_size_code": member.get("company_size_code"),
            "fa_score": _ranking_number(fa.get("fa_score")) if fa else None,
            "score_confidence": _ranking_number(fa.get("score_confidence")) if fa else None,
            "latest_available_date": fa.get("available_date") if fa else None,
            "latest_trd_amt": member.get("trd_amt"),
            "industry_rank": None,
            "is_eligible": exclusion is None,
            "is_selected": False,
            "exclusion_reason_code": exclusion,
            "reason": exclusion or "eligible for industry ranking",
            "selection_detail": {
                "sort_keys": ["fa_score", "score_confidence", "latest_trd_amt", "stock_code"],
                "source_fa_id": fa.get("id") if fa else None,
                "risk_state": {
                    "risk_action_code": risk_state.get("risk_action_code"),
                    "reason_code": risk_state.get("reason_code"),
                    "source_dart_event_id": risk_state.get("source_dart_event_id"),
                    "effective_date": risk_state.get("effective_date"),
                    "expires_at": risk_state.get("expires_at"),
                    "policy_version": risk_state.get("policy_version"),
                } if risk_state else None,
            },
        })

    for industry_code in sector_by_industry:
        eligible = [
            row for row in results
            if row["industry_code"] == industry_code and row["is_eligible"]
        ]
        eligible.sort(key=lambda row: (
            -_ranking_number(row["fa_score"]),
            -_ranking_number(row["score_confidence"]),
            -_ranking_number(row["latest_trd_amt"]),
            row["stock_code"],
        ))
        for rank, row in enumerate(eligible, 1):
            row["industry_rank"] = rank
            row["is_selected"] = rank <= config.scoring.companies_per_industry
            row["reason"] = (
                "selected by FA score, confidence, liquidity, and stock code"
                if row["is_selected"] else "ranked below the top two eligible companies"
            )
    return sorted(results, key=lambda row: (row["industry_code"], row["stock_code"]))


def run(
    db: PostgreDB,
    run_id: int,
    cutoff_date: date,
    config: AnalyzerConfig,
    *,
    buy_blocked_codes: set[str] | None = None,
) -> list[dict]:
    sectors = fetch_sector_results(db, run_id, selected_only=True)
    snapshot = fetch_latest_wics_snapshot(db, cutoff_date)
    selected_industries = {row["industry_code"] for row in sectors}
    members = [row for row in snapshot if row.get("industry_code") in selected_industries]
    stock_codes = [row["stock_code"] for row in members]
    company_fa = fetch_latest_company_fa_as_of(
        db, cutoff_date, config.model_version, stock_codes=stock_codes
    )
    statuses = fetch_company_statuses(db, stock_codes)
    risk_states = fetch_active_company_risk_states(
        db, cutoff_date, stock_codes=stock_codes
    )
    results = select_companies(
        sectors, members, company_fa, statuses, config,
        buy_blocked_codes=buy_blocked_codes,
        company_risk_rows=risk_states,
    )
    insert_company_results(db, run_id, results)
    return results
