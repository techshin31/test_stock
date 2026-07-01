"""WICS industry return construction and sector selection jobs."""
from __future__ import annotations

import math
from datetime import date, timedelta
from dataclasses import asdict

import pandas as pd

from apps.worker.analyzer.config import AnalyzerConfig
from apps.worker.analyzer.models import MacroDirection, MacroResult
from apps.worker.fa_contract import ALL_WICS_INDUSTRIES, MACRO_SIGNALS, SUPPORTED_INDUSTRIES
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.wics_industry_repo import (
    fetch_wics_constituent_prices,
    upsert_wics_industry_prices,
)
from storage.postgres.repositories.wics_repo import fetch_wics_companies
from storage.postgres.repositories.wics_repo import fetch_latest_wics_snapshot
from storage.postgres.repositories.company_quarter_fa_repo import fetch_latest_company_fa_as_of
from storage.postgres.repositories.company_repo import fetch_company_statuses
from storage.postgres.repositories.company_risk_repo import (
    fetch_active_company_risk_states,
)
from storage.postgres.repositories.fa_analysis_repo import insert_sector_results


def reconstruct_industry_indices(
    price_rows: list[dict],
    wics_rows: list[dict],
    *,
    minimum_coverage: float = 0.80,
    method_version: str = "mcap-v1",
) -> list[dict]:
    """Reconstruct point-in-time market-cap weighted industry indices."""
    if not price_rows or not wics_rows:
        return []
    prices = pd.DataFrame(price_rows)
    prices["price_date"] = pd.to_datetime(prices["price_date"])
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce").astype(float)
    close = prices.pivot_table(
        index="price_date", columns="stock_code", values="close", aggfunc="last"
    ).sort_index()
    returns = close.pct_change(fill_method=None)

    wics = pd.DataFrame(wics_rows)
    wics = wics[wics["industry_code"].isin(ALL_WICS_INDUSTRIES)].copy()
    if wics.empty:
        return []
    wics["base_date"] = pd.to_datetime(wics["base_date"])
    snapshot_dates = sorted(wics["base_date"].drop_duplicates())
    observations: list[dict] = []

    for position, snapshot_date in enumerate(snapshot_dates):
        next_snapshot = (
            snapshot_dates[position + 1] if position + 1 < len(snapshot_dates) else None
        )
        date_mask = returns.index >= snapshot_date
        if next_snapshot is not None:
            date_mask &= returns.index < next_snapshot
        period_returns = returns.loc[date_mask]
        if period_returns.empty:
            continue
        snapshot = wics[wics["base_date"] == snapshot_date]
        for industry_code, members in snapshot.groupby("industry_code"):
            full_weights = pd.to_numeric(
                members.set_index("stock_code")["mkt_val"], errors="coerce"
            )
            if (
                full_weights.notna().sum() == 0
                or float(full_weights.fillna(0).sum()) <= 0
            ):
                full_weights = pd.Series(1.0, index=members["stock_code"])
            full_weights = full_weights.fillna(0.0)
            available_symbols = [
                symbol for symbol in members["stock_code"] if symbol in period_returns.columns
            ]
            if not available_symbols:
                continue
            weights = full_weights.reindex(available_symbols).fillna(0.0)
            member_returns = period_returns[available_symbols]
            valid_weight = member_returns.notna().mul(weights, axis=1).sum(axis=1)
            total_weight = float(full_weights.sum())
            coverage = valid_weight / total_weight if total_weight else 0.0
            weighted_return = member_returns.mul(weights, axis=1).sum(
                axis=1, min_count=1
            ) / valid_weight.where(valid_weight != 0)
            for price_date, value in weighted_return.items():
                if pd.isna(value) or coverage.loc[price_date] < minimum_coverage:
                    continue
                observations.append({
                    "industry_code": industry_code,
                    "price_date": price_date.date(),
                    "daily_return": float(value),
                    "source_code": "DERIVED",
                    "constituent_base_date": snapshot_date.date(),
                    "method_version": method_version,
                })

    if not observations:
        return []
    result_frame = pd.DataFrame(observations).sort_values(
        ["industry_code", "price_date", "constituent_base_date"]
    )
    result_frame = result_frame.drop_duplicates(
        ["industry_code", "price_date"], keep="last"
    )
    result_frame["index_value"] = result_frame.groupby("industry_code")[
        "daily_return"
    ].transform(lambda series: 1000.0 * (1.0 + series).cumprod())
    return result_frame.drop(columns=["daily_return"]).to_dict("records")


def industry_returns_frame(
    price_rows: list[dict],
    frequency: str,
) -> pd.DataFrame:
    """Convert stored industry levels to aligned weekly or monthly returns."""
    if not price_rows:
        return pd.DataFrame()
    frame = pd.DataFrame(price_rows)
    frame["price_date"] = pd.to_datetime(frame["price_date"])
    frame["index_value"] = pd.to_numeric(
        frame["index_value"], errors="coerce"
    ).astype(float)
    levels = frame.pivot_table(
        index="price_date", columns="industry_code", values="index_value", aggfunc="last"
    ).sort_index()
    rule = "W-FRI" if frequency == "WEEKLY" else "ME"
    return levels.resample(rule).last().pct_change(fill_method=None).dropna(how="all")


def refresh_industry_prices(
    db: PostgreDB,
    cutoff_date: date,
    config: AnalyzerConfig,
) -> int:
    start_date = cutoff_date - timedelta(days=365 * 3 + 60)
    price_rows = fetch_wics_constituent_prices(
        db, cutoff_date=cutoff_date, start_date=start_date
    )
    stock_codes = sorted({row["stock_code"] for row in price_rows})
    wics_rows = fetch_wics_companies(
        db,
        stock_codes=stock_codes,
        start_date=start_date,
        end_date=cutoff_date,
    )
    derived = reconstruct_industry_indices(
        price_rows,
        wics_rows,
        minimum_coverage=config.scoring.minimum_industry_price_coverage,
    )
    return upsert_wics_industry_prices(db, derived)


def _number(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if pd.notna(result) else default


def _percentile_map(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    series = pd.Series(values, dtype=float)
    return series.rank(method="average", pct=True).mul(100.0).to_dict()


def _cap_macro_category_contributions(
    relations: list[dict],
    category_cap: float,
) -> list[dict]:
    """Limit total absolute macro contribution per category."""
    if category_cap < 0:
        raise ValueError("macro_category_contribution_cap must be non-negative")

    used_by_category: dict[str, float] = {}
    capped: list[dict] = []
    for item in relations:
        category = str(item.get("category_code", "UNKNOWN"))
        raw_contribution = _number(item.get("contribution"))
        used = used_by_category.get(category, 0.0)
        remaining = max(0.0, category_cap - used)
        applied = (
            math.copysign(min(abs(raw_contribution), remaining), raw_contribution)
            if raw_contribution else 0.0
        )
        used_by_category[category] = used + abs(applied)
        if applied != raw_contribution:
            capped.append({
                **item,
                "raw_contribution": raw_contribution,
                "contribution": applied,
                "category_cap_applied": True,
            })
        else:
            capped.append(item)
    return capped


def _cohort_quality_penalty(median_score: float, config: AnalyzerConfig) -> float:
    scoring = config.scoring
    shortfall = max(0.0, scoring.cohort_quality_threshold - median_score)
    return min(
        shortfall * scoring.cohort_quality_penalty_rate,
        scoring.maximum_cohort_quality_penalty,
    )


def _mark_candidate(row: dict, source_code: str, rank: int) -> None:
    row["is_candidate"] = True
    row["candidate_source_code"] = source_code
    row["candidate_pool"] = source_code
    row["candidate_rank"] = rank


def _assign_candidate_pool(rows: list[dict], config: AnalyzerConfig) -> None:
    scoring = config.scoring
    up_ranked = sorted(
        rows,
        key=lambda row: (-row["up_benefit_score"], row["industry_code"]),
    )
    for rank, row in enumerate(up_ranked[:scoring.candidate_up_count], 1):
        _mark_candidate(row, "UP", rank)

    down_ranked = sorted(
        rows,
        key=lambda row: (-row["down_hedge_score"], row["industry_code"]),
    )
    down_count = 0
    for row in down_ranked:
        if down_count == scoring.candidate_down_count:
            break
        if row["is_candidate"]:
            continue
        down_count += 1
        _mark_candidate(row, "DOWN", down_count)



def score_and_select_sectors(
    macro_results: list[MacroResult],
    snapshot_rows: list[dict],
    company_fa_rows: list[dict],
    company_status_rows: list[dict],
    config: AnalyzerConfig,
    *,
    company_risk_rows: list[dict] | None = None,
) -> list[dict]:
    """Score all supported industries and deterministically select 5/3."""
    snapshot = [
        row for row in snapshot_rows
        if row.get("industry_code") in SUPPORTED_INDUSTRIES
    ]
    industries = sorted({row["industry_code"] for row in snapshot})
    fa_by_stock = {row["stock_code"]: row for row in company_fa_rows}
    status_by_stock = {row["stock_code"]: row for row in company_status_rows}
    risk_blocked_codes = {
        row["stock_code"] for row in (company_risk_rows or [])
    }
    category_by_signal = {item.code: item.category for item in MACRO_SIGNALS}
    direction_by_signal = {
        result.signal_name_code: result.direction_code for result in macro_results
    }
    strength_by_signal = {
        result.signal_name_code: result.trend_strength for result in macro_results
    }
    active_macro_count = max(len(macro_results), 1)
    relationships: dict[str, list[dict]] = {code: [] for code in industries}
    for result in macro_results:
        for relation in result.calculation_detail.get("relationships", []):
            industry_code = relation["industry_code"]
            if industry_code not in relationships:
                continue
            relationships[industry_code].append({
                **relation,
                "direction_code": result.direction_code.value,
                "trend_strength": result.trend_strength,
                "category_code": category_by_signal[result.signal_name_code],
            })

    industry_members = {
        code: [row for row in snapshot if row["industry_code"] == code]
        for code in industries
    }
    liquidity_raw = {
        code: sum(_number(row.get("trd_amt")) for row in rows)
        for code, rows in industry_members.items()
    }
    liquidity_pct = _percentile_map(liquidity_raw)
    median_fa: dict[str, float] = {}
    for code, members in industry_members.items():
        scores = [
            _number(fa_by_stock[row["stock_code"]].get("fa_score"))
            for row in members if row["stock_code"] in fa_by_stock
        ]
        median_fa[code] = float(pd.Series(scores).median()) if scores else 0.0
    median_fa_pct = _percentile_map(median_fa)

    rows: list[dict] = []
    for industry_code in industries:
        members = industry_members[industry_code]
        member_fa = [fa_by_stock[row["stock_code"]] for row in members if row["stock_code"] in fa_by_stock]
        eligible_large = []
        for member in members:
            fa = fa_by_stock.get(member["stock_code"])
            company = status_by_stock.get(member["stock_code"])
            if member["stock_code"] in risk_blocked_codes:
                continue
            if not fa or not company or member.get("company_size_code") != config.scoring.allowed_company_size:
                continue
            if company.get("status_code") != "ACTIVE" or company.get("market_type_code") not in config.scoring.enabled_market_types:
                continue
            if not fa.get("is_eligible"):
                continue
            if _number(fa.get("fa_score"), -1.0) < config.scoring.minimum_company_fa_score:
                continue
            if _number(fa.get("score_confidence"), -1.0) < config.scoring.minimum_score_confidence:
                continue
            eligible_large.append(member["stock_code"])

        improved = 0
        confident = 0
        for fa in member_fa:
            changes = (
                fa.get("revenue_growth_yoy"),
                fa.get("operating_income_growth_yoy"),
                fa.get("operating_margin_change_yoy"),
                fa.get("operating_cashflow_change_yoy"),
            )
            improved += sum(value is not None and _number(value) > 0 for value in changes) >= 2
            confident += _number(fa.get("score_confidence")) >= config.scoring.minimum_score_confidence
        fa_count = len(member_fa)
        coverage = fa_count / len(members) if members else 0.0
        improvement_rate = improved / fa_count if fa_count else 0.0
        confidence_rate = confident / fa_count if fa_count else 0.0
        breadth = (
            median_fa_pct[industry_code] * 0.40
            + improvement_rate * 100.0 * 0.35
            + confidence_rate * 100.0 * 0.25
        )
        liquidity = (
            liquidity_pct[industry_code] * 0.60
            + min(len(eligible_large) / 2.0, 1.0) * 100.0 * 0.40
        )

        contributions = relationships[industry_code]
        eligible_relations = [item for item in contributions if item["is_eligible"]]
        capped_relations = _cap_macro_category_contributions(
            eligible_relations,
            config.scoring.macro_category_contribution_cap,
        )
        capped_iter = iter(capped_relations)
        stored_contributions = [
            next(capped_iter) if item["is_eligible"] else item
            for item in contributions
        ]
        up_score = sum(
            max(_number(item.get("correlation")), 0.0)
            * _number(item.get("trend_strength"))
            * _number(item.get("relationship_confidence")) / active_macro_count
            for item in eligible_relations
            if direction_by_signal[item["signal_name_code"]] == MacroDirection.UP
        )
        down_score = sum(
            max(-_number(item.get("correlation")), 0.0)
            * _number(item.get("trend_strength"))
            * _number(item.get("relationship_confidence")) / active_macro_count
            for item in eligible_relations
            if direction_by_signal[item["signal_name_code"]] == MacroDirection.DOWN
        )
        macro_raw = max(-1.0, min(1.0, sum(
            _number(item.get("contribution")) for item in capped_relations
        )))
        macro_fit = (macro_raw + 1.0) * 50.0
        rel_confidence = (
            sum(_number(item.get("relationship_confidence")) for item in eligible_relations)
            / len(eligible_relations) if eligible_relations else 0.0
        )
        total_cap = sum(_number(member.get("mkt_val")) for member in members)
        concentration = (
            max((_number(member.get("mkt_val")) for member in members), default=0.0)
            / total_cap if total_cap else 0.0
        )
        cohort_penalty = _cohort_quality_penalty(median_fa[industry_code], config)
        risk_penalty = (10.0 if coverage < 0.80 else 0.0)
        risk_penalty += 5.0 if rel_confidence < 0.50 else 0.0
        risk_penalty += 5.0 if len(members) < 3 else 0.0
        risk_penalty += min(max(concentration - 0.50, 0.0) * 20.0, 10.0)
        risk_penalty += cohort_penalty
        sector_score = max(0.0, min(100.0,
            macro_fit * config.scoring.sector_score_weights[0]
            + breadth * config.scoring.sector_score_weights[1]
            + liquidity * config.scoring.sector_score_weights[2]
            - risk_penalty
        ))
        rows.append({
            "sector_code": members[0]["sector_code"],
            "industry_code": industry_code,
            "up_benefit_score": up_score,
            "down_hedge_score": down_score,
            "macro_fit_score": macro_fit,
            "company_fa_breadth_score": breadth,
            "liquidity_capacity_score": liquidity,
            "sector_risk_penalty": risk_penalty,
            "cohort_quality_penalty": cohort_penalty,
            "sector_score": sector_score,
            "eligible_large_count": len(eligible_large),
            "company_coverage_rate": coverage,
            "relationship_confidence": rel_confidence,
            "macro_contributions": stored_contributions,
            "is_candidate": False,
            "is_selected": False,
            "candidate_source_code": None,
            "candidate_pool": None,
            "candidate_rank": None,
        })

    _assign_candidate_pool(rows, config)

    selected: list[dict] = []

    def _select(row: dict) -> bool:
        if len(selected) == config.scoring.final_industry_count:
            return False
        if row["eligible_large_count"] < config.scoring.companies_per_industry:
            row["reason_code"] = "INSUFFICIENT_LARGE"
            row["reason"] = "eligible LARGE companies are fewer than two"
            return False
        selected.append(row)
        return True

    candidate_rows = sorted(
        [row for row in rows if row["is_candidate"]],
        key=lambda row: (-row["sector_score"], row["industry_code"]),
    )
    for row in candidate_rows:
        _select(row)
        if len(selected) == config.scoring.final_industry_count:
            break

    fallback_rank = 0
    if len(selected) < config.scoring.final_industry_count:
        fallback_rows = sorted(
            [row for row in rows if not row["is_candidate"]],
            key=lambda row: (-row["sector_score"], row["industry_code"]),
        )
        for row in fallback_rows:
            if len(selected) == config.scoring.final_industry_count:
                break
            previous_reason = row.get("reason_code")
            if _select(row):
                fallback_rank += 1
                _mark_candidate(row, "FALLBACK", fallback_rank)
            elif previous_reason is None:
                row.pop("reason_code", None)
                row.pop("reason", None)

    for rank, row in enumerate(selected, 1):
        row["is_selected"] = True
        row["final_rank"] = rank
        row["reason_code"] = "SELECTED"
        row["reason"] = "selected by sector score"
    for row in rows:
        if (
            row["is_candidate"]
            and row["eligible_large_count"] < config.scoring.companies_per_industry
            and "reason_code" not in row
        ):
            row["reason_code"] = "INSUFFICIENT_LARGE"
            row["reason"] = "eligible LARGE companies are fewer than two"
        if "reason_code" not in row:
            row["reason_code"] = "LOW_SCORE"
            row["reason"] = "ranked below the final selection cutoff"
    return sorted(rows, key=lambda row: row["industry_code"])


def run(
    db: PostgreDB,
    run_id: int,
    cutoff_date: date,
    macro_results: list[MacroResult],
    config: AnalyzerConfig,
) -> list[dict]:
    snapshot = fetch_latest_wics_snapshot(db, cutoff_date)
    stock_codes = [row["stock_code"] for row in snapshot]
    company_fa = fetch_latest_company_fa_as_of(
        db, cutoff_date, config.model_version, stock_codes=stock_codes
    )
    statuses = fetch_company_statuses(db, stock_codes)
    risk_states = fetch_active_company_risk_states(
        db, cutoff_date, stock_codes=stock_codes
    )
    results = score_and_select_sectors(
        macro_results, snapshot, company_fa, statuses, config,
        company_risk_rows=risk_states,
    )
    insert_sector_results(db, run_id, results)
    return results
