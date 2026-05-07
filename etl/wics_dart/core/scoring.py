from __future__ import annotations

import pandas as pd


# ============================================================
# WICS-DART FA scoring logic
#
# This module only handles scoring rules:
# - DART event counts -> scoring features
# - year/sector percentile ranks
# - sub-score calculation
# - sector-specific overall score weights
# ============================================================


EVENT_WEIGHTS = {
    "cash_dividend": 1.0,
    "buyback": 1.0,
    "share_cancellation": 1.2,
    "treasury_disposal": -0.7,
    "clinical_trial": 0.6,
    "approval": 1.0,
    "technology_transfer": 1.2,
    "major_contract": 1.0,
    "paid_in_capital_increase": 0.8,
    "bonus_issue": 0.3,
    "convertible_bond": 0.6,
    "bond_with_warrant": 0.5,
    "exchange_bond": 0.5,
}


EVENT_FEATURE_COLUMNS = [
    "stock_code",
    "fiscal_year",
    "shareholder_return_raw",
    "pipeline_event_raw",
    "major_contract_raw",
    "capital_support_raw",
]


SECTOR_WEIGHT_CONFIG = {
    "금융": {
        "profitability_score": 30,
        "stability_score": 30,
        "growth_score": 10,
        "shareholder_return_score": 10,
    },
    "유틸리티": {
        "cashflow_score": 30,
        "stability_score": 30,
        "profitability_score": 20,
        "shareholder_return_score": 20,
    },
    "커뮤니케이션서비스": {
        "profitability_score": 25,
        "cashflow_score": 25,
        "growth_score": 20,
        "stability_score": 15,
        "shareholder_return_score": 15,
    },
    "에너지": {
        "cashflow_score": 25,
        "profitability_score": 25,
        "stability_score": 25,
        "shareholder_return_score": 10,
    },
    "건강관리_profit": {
        "growth_score": 25,
        "profitability_score": 25,
        "cashflow_score": 20,
        "stability_score": 20,
    },
    "건강관리_loss": {
        "survival_score": 40,
        "pipeline_event_score": 25,
        "cost_control_score": 20,
        "revenue_generation_score": 15,
    },
    "fallback": {
        "growth_score": 1,
        "profitability_score": 1,
        "stability_score": 1,
    },
}


METRIC_RANKING_RULES = {
    "revenue_growth_yoy": False,
    "operating_margin": False,
    "roe": False,
    "debt_ratio": True,
    "current_ratio": False,
    "ocf_to_revenue": False,
    "shareholder_return_raw": False,
    "pipeline_event_raw": False,
    "capital_support_raw": False,
    "major_contract_raw": False,
    "revenue": False,
    "equity_ratio": False,
    "financing_cash_flow": False,
}


def empty_event_features() -> pd.DataFrame:
    """Return the empty event feature frame expected by the ranking merge."""
    return pd.DataFrame(columns=EVENT_FEATURE_COLUMNS)


def weighted_event_count(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    total = pd.Series(0.0, index=frame.index)
    for column in columns:
        if column not in frame.columns:
            continue
        total = total + pd.to_numeric(frame[column], errors="coerce").fillna(0.0) * EVENT_WEIGHTS[column]
    return total


def build_event_features(events: pd.DataFrame) -> pd.DataFrame:
    """Aggregate DART event disclosures into company-year scoring features."""
    if events.empty:
        return empty_event_features()

    events = events.copy()
    events["stock_code"] = events["stock_code"].astype(str).str.split(".").str[0].str.zfill(6)
    events["fiscal_year"] = pd.to_numeric(events["rcept_dt"].str[:4], errors="coerce").astype("Int64")
    events = events.dropna(subset=["fiscal_year", "event_subtype"])

    counts = (
        events.groupby(["stock_code", "fiscal_year", "event_subtype"])
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )

    counts["shareholder_return_raw"] = weighted_event_count(
        counts,
        ["cash_dividend", "buyback", "share_cancellation", "treasury_disposal"],
    )
    counts["pipeline_event_raw"] = weighted_event_count(
        counts,
        ["clinical_trial", "approval", "technology_transfer"],
    )
    counts["major_contract_raw"] = weighted_event_count(counts, ["major_contract"])
    counts["capital_support_raw"] = weighted_event_count(
        counts,
        ["paid_in_capital_increase", "bonus_issue", "convertible_bond", "bond_with_warrant", "exchange_bond"],
    )

    return counts.loc[:, EVENT_FEATURE_COLUMNS]


def percentile_rank(series: pd.Series, *, ascending: bool) -> pd.DataFrame:
    """Calculate rank and percentile inside one year-sector group."""
    valid = series.dropna()

    if valid.empty:
        return pd.DataFrame(index=series.index, columns=["rank", "percentile"])

    ordered = valid.sort_values(ascending=ascending)
    ranks = pd.Series(range(1, len(ordered) + 1), index=ordered.index)

    if len(ordered) == 1:
        percentiles = pd.Series(1.0, index=ordered.index)
    else:
        percentiles = (len(ordered) - ranks) / (len(ordered) - 1)

    result = pd.DataFrame(index=series.index, columns=["rank", "percentile"])
    result.loc[ranks.index, "rank"] = ranks
    result.loc[percentiles.index, "percentile"] = percentiles
    return result


def bucket_from_score(score: float | None) -> str | None:
    """Convert the 0-1 overall score into a broad label."""
    if pd.isna(score):
        return None
    if score >= 0.8:
        return "top_20%"
    if score >= 0.6:
        return "top_40%"
    if score >= 0.4:
        return "middle"
    if score >= 0.2:
        return "bottom_40%"
    return "bottom_20%"


def mean_available(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    valid_columns = [column for column in columns if column in frame.columns]
    if not valid_columns:
        return pd.Series(float("nan"), index=frame.index, dtype="float64")
    return frame[valid_columns].mean(axis=1, skipna=True)


def weighted_mean_available(frame: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    total = pd.Series(0.0, index=frame.index)
    total_weight = pd.Series(0.0, index=frame.index)

    for column, weight in weights.items():
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        mask = values.notna()
        total.loc[mask] = total.loc[mask] + values.loc[mask] * weight
        total_weight.loc[mask] = total_weight.loc[mask] + weight

    result = total.where(total_weight != 0) / total_weight.where(total_weight != 0)
    return pd.to_numeric(result, errors="coerce")


def score_model_for_row(row: pd.Series) -> str:
    if row["wics_large"] != "건강관리":
        return str(row["wics_large"])
    net_income = pd.to_numeric(row.get("net_income"), errors="coerce")
    return "건강관리_profit" if pd.notna(net_income) and net_income > 0 else "건강관리_loss"


def apply_sector_weighted_score(result: pd.DataFrame) -> pd.DataFrame:
    result["score_model"] = result.apply(score_model_for_row, axis=1)
    result["overall_score_common"] = mean_available(
        result,
        ["growth_score", "profitability_score", "stability_score"],
    )

    overall = pd.Series(float("nan"), index=result.index, dtype="float64")
    for model_name, weights in SECTOR_WEIGHT_CONFIG.items():
        if model_name == "fallback":
            continue
        mask = result["score_model"] == model_name
        if mask.any():
            overall.loc[mask] = weighted_mean_available(result.loc[mask], weights)

    fallback_mask = overall.isna()
    if fallback_mask.any():
        overall.loc[fallback_mask] = weighted_mean_available(
            result.loc[fallback_mask],
            SECTOR_WEIGHT_CONFIG["fallback"],
        )
        result.loc[fallback_mask, "score_model"] = result.loc[fallback_mask, "score_model"].where(
            result.loc[fallback_mask, "score_model"].isin(SECTOR_WEIGHT_CONFIG.keys()),
            "fallback",
        )

    result["overall_score"] = overall
    result["overall_bucket"] = result["overall_score"].apply(bucket_from_score)
    return result


def score_group(group: pd.DataFrame) -> pd.DataFrame:
    """Score one fiscal-year and WICS-large group by relative ranking."""
    result = group.copy()

    result["equity_ratio"] = pd.to_numeric(result["total_equity"], errors="coerce") / pd.to_numeric(
        result["total_assets"], errors="coerce"
    )

    for metric, ascending in METRIC_RANKING_RULES.items():
        if metric not in result.columns:
            continue
        score_df = percentile_rank(result[metric], ascending=ascending)
        result[f"{metric}_rank"] = score_df["rank"]
        result[f"{metric}_percentile"] = score_df["percentile"]

    result["growth_score"] = result.get("revenue_growth_yoy_percentile")
    result["profitability_score"] = mean_available(
        result,
        ["operating_margin_percentile", "roe_percentile"],
    )
    result["stability_score"] = mean_available(
        result,
        ["debt_ratio_percentile", "current_ratio_percentile"],
    )
    result["cashflow_score"] = result.get("ocf_to_revenue_percentile")
    result["shareholder_return_score"] = result.get("shareholder_return_raw_percentile")
    result["pipeline_event_score"] = result.get("pipeline_event_raw_percentile")
    result["survival_score"] = mean_available(
        result,
        ["equity_ratio_percentile", "current_ratio_percentile", "capital_support_raw_percentile", "financing_cash_flow_percentile"],
    )
    result["cost_control_score"] = mean_available(
        result,
        ["operating_margin_percentile", "ocf_to_revenue_percentile"],
    )
    result["revenue_generation_score"] = mean_available(
        result,
        ["revenue_percentile", "major_contract_raw_percentile"],
    )

    return apply_sector_weighted_score(result)


def build_rankings(master: pd.DataFrame, event_features: pd.DataFrame | None = None) -> pd.DataFrame:
    """Build the full company-sector ranking table from master data and event features."""
    if event_features is None:
        event_features = empty_event_features()

    working = master.merge(event_features, on=["stock_code", "fiscal_year"], how="left")

    frames: list[pd.DataFrame] = []
    for (fiscal_year, wics_large), group in working.groupby(["fiscal_year", "wics_large"], dropna=False):
        scored = score_group(group)
        scored["fiscal_year"] = fiscal_year
        scored["wics_large"] = wics_large
        frames.append(scored)

    ranking = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return ranking.sort_values(
        ["fiscal_year", "wics_large", "overall_score", "company_name"],
        ascending=[True, True, False, True],
        na_position="last",
    )
