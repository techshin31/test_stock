"""Persistence for monthly FA analysis runs and result ledgers."""
from __future__ import annotations

import json
from datetime import date

from ..connection import PostgreDB


# ---------------------------------------------------------------------------
# Audit / operations queries
# ---------------------------------------------------------------------------

def fetch_audit_counts(db: PostgreDB) -> dict:
    return db.fetch_one(
        """
        SELECT
          (SELECT COUNT(*)
           FROM fa_macro_results m JOIN fa_analysis_runs r ON r.id = m.run_id
           WHERE m.last_available_date > r.cutoff_date) AS macro_late,
          (SELECT COUNT(*)
           FROM fa_company_results c JOIN fa_analysis_runs r ON r.id = c.run_id
           WHERE c.latest_available_date > r.cutoff_date) AS company_late,
          (SELECT COUNT(*) FROM fa_analysis_runs
           WHERE status_code = 'RUNNING'
             AND created_at < NOW() - INTERVAL '1 hour') AS stale_running
        """
    ) or {}


def fetch_published_universe_mismatch(db: PostgreDB) -> dict:
    return db.fetch_one(
        """
        WITH latest_published AS (
          SELECT DISTINCT ON (strategy_id) id, strategy_id
          FROM fa_analysis_runs
          WHERE status_code = 'PUBLISHED'
          ORDER BY strategy_id, effective_date DESC, run_version DESC
        ), selected AS (
          SELECT p.strategy_id, c.stock_code
          FROM latest_published p
          JOIN fa_company_results c ON c.run_id = p.id AND c.is_selected = TRUE
        ), active AS (
          SELECT strategy_id, symbol AS stock_code
          FROM universe WHERE universe_status_code = 'ACTIVE'
        )
        SELECT
          (SELECT COUNT(*) FROM (
             (SELECT * FROM selected EXCEPT SELECT * FROM active)
             UNION ALL
             (SELECT * FROM active EXCEPT SELECT * FROM selected)
          ) differences) AS mismatch_count,
          (SELECT COUNT(*) FROM latest_published) AS published_count
        """
    ) or {}


def fetch_published_run_selections(db: PostgreDB) -> list[dict]:
    return db.fetch_all(
        """
        SELECT r.id AS run_id, r.analysis_month, c.stock_code
        FROM fa_analysis_runs r
        JOIN fa_company_results c ON c.run_id = r.id AND c.is_selected = TRUE
        WHERE r.status_code = 'PUBLISHED'
        ORDER BY r.effective_date, r.run_version, c.stock_code
        """
    )


# ---------------------------------------------------------------------------
# Validation queries
# ---------------------------------------------------------------------------

def fetch_macro_results_for_run(db: PostgreDB, run_id: int) -> list[dict]:
    return db.fetch_all(
        """
        SELECT signal_name_code, last_available_date
        FROM fa_macro_results WHERE run_id = %s
        ORDER BY signal_name_code
        """,
        (run_id,),
    )


def fetch_sector_summary_for_run(db: PostgreDB, run_id: int) -> dict:
    return db.fetch_one(
        """
        SELECT COUNT(*) FILTER (WHERE is_candidate) AS candidates,
               COUNT(*) FILTER (WHERE is_selected) AS selected
        FROM fa_sector_results WHERE run_id = %s
        """,
        (run_id,),
    ) or {}


def fetch_selected_companies_with_company_info(db: PostgreDB, run_id: int) -> list[dict]:
    return db.fetch_all(
        """
        SELECT r.*, c.market_type_code, c.status_code AS company_status_code
        FROM fa_company_results r
        JOIN companies c ON c.stock_code = r.stock_code
        WHERE r.run_id = %s AND r.is_selected = TRUE
        ORDER BY r.industry_code, r.industry_rank, r.stock_code
        """,
        (run_id,),
    )


# ---------------------------------------------------------------------------
# Backtester query
# ---------------------------------------------------------------------------

def fetch_published_fa_selections(
    db: PostgreDB,
    strategy_name: str,
    end_date: date,
) -> list[dict]:
    return db.fetch_all(
        """
        SELECT r.id AS run_id, r.cutoff_date, r.effective_date,
               c.stock_code, c.latest_available_date
        FROM fa_analysis_runs r
        JOIN strategies s ON s.id = r.strategy_id
        JOIN fa_company_results c
          ON c.run_id = r.id AND c.is_selected = TRUE
        WHERE s.name = %s
          AND r.status_code = 'PUBLISHED'
          AND r.effective_date <= %s
        ORDER BY r.effective_date, r.run_version, c.stock_code
        """,
        (strategy_name, end_date),
    )


def fetch_analysis_run(db: PostgreDB, run_id: int) -> dict | None:
    return db.fetch_one("SELECT * FROM fa_analysis_runs WHERE id = %s", (run_id,))


def fetch_reusable_run(
    db: PostgreDB,
    strategy_id: int,
    analysis_month: date,
    input_hash: str,
) -> dict | None:
    return db.fetch_one(
        """
        SELECT * FROM fa_analysis_runs
        WHERE strategy_id = %s
          AND analysis_month = %s
          AND input_hash = %s
          AND status_code <> 'FAIL'
        ORDER BY run_version DESC
        LIMIT 1
        """,
        (strategy_id, analysis_month, input_hash),
    )


def fail_stale_analysis_runs(
    db: PostgreDB,
    strategy_id: int,
    analysis_month: date,
) -> int:
    return db.execute(
        """
        UPDATE fa_analysis_runs
        SET status_code = 'FAIL',
            failure_reason = 'STALE_RUNNING_TIMEOUT',
            completed_at = NOW()
        WHERE strategy_id = %s
          AND analysis_month = %s
          AND status_code = 'RUNNING'
          AND created_at < NOW() - INTERVAL '1 hour'
        """,
        (strategy_id, analysis_month),
    )


def get_or_create_analysis_run(
    db: PostgreDB,
    *,
    strategy_id: int,
    analysis_month: date,
    cutoff_date: date,
    effective_date: date,
    model_version: str,
    input_hash: str,
    force: bool = False,
) -> tuple[dict, bool]:
    if not force:
        existing = fetch_reusable_run(db, strategy_id, analysis_month, input_hash)
        if existing is not None:
            return existing, False

    # 전략 행 잠금으로 동일 월 동시 실행의 MAX+1 경쟁 조건을 직렬화한다.
    with db.transaction() as conn:
        strategy = conn.execute(
            "SELECT id FROM strategies WHERE id = %s FOR UPDATE", (strategy_id,)
        ).fetchone()
        if strategy is None:
            raise ValueError(f"strategy not found: {strategy_id}")
        version_row = conn.execute(
            """
            SELECT COALESCE(MAX(run_version), 0) + 1 AS next_version
            FROM fa_analysis_runs
            WHERE strategy_id = %s AND analysis_month = %s
            """,
            (strategy_id, analysis_month),
        ).fetchone()
        run_version = int(version_row["next_version"])
        row = conn.execute(
            """
            INSERT INTO fa_analysis_runs (
                strategy_id, analysis_month, cutoff_date, effective_date,
                run_version, model_version, status_code, input_hash
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'RUNNING', %s)
            RETURNING *
            """,
            (
                strategy_id, analysis_month, cutoff_date, effective_date,
                run_version, model_version, input_hash,
            ),
        ).fetchone()
    return row, True


def update_analysis_run_status(
    db: PostgreDB,
    run_id: int,
    status_code: str,
    *,
    selected_industry_count: int | None = None,
    selected_company_count: int | None = None,
    validation_summary: dict | None = None,
    failure_reason: str | None = None,
) -> int:
    completed = status_code in {"PASS", "WARNING", "FAIL", "PUBLISHED"}
    published = status_code == "PUBLISHED"
    return db.execute(
        """
        UPDATE fa_analysis_runs
        SET status_code = %s,
            selected_industry_count = COALESCE(%s, selected_industry_count),
            selected_company_count = COALESCE(%s, selected_company_count),
            validation_summary = COALESCE(%s::jsonb, validation_summary),
            failure_reason = %s,
            completed_at = CASE WHEN %s THEN NOW() ELSE completed_at END,
            published_at = CASE WHEN %s THEN NOW() ELSE published_at END
        WHERE id = %s
        """,
        (
            status_code,
            selected_industry_count,
            selected_company_count,
            json.dumps(validation_summary, ensure_ascii=False, default=str)
            if validation_summary is not None else None,
            failure_reason,
            completed,
            published,
            run_id,
        ),
    )


def insert_macro_results(db: PostgreDB, run_id: int, rows: list[dict]) -> int:
    if not rows:
        return 0
    params = [
        (
            run_id, row["signal_name_code"], row["last_observation_date"],
            row["last_available_date"], row["direction_code"], row["trend_raw"],
            row["trend_strength"], row["data_point_count"], row["confidence"],
            json.dumps(row.get("calculation_detail", {}), ensure_ascii=False, default=str),
        )
        for row in rows
    ]
    db.execute_many(
        """
        INSERT INTO fa_macro_results (
            run_id, signal_name_code, last_observation_date, last_available_date,
            direction_code, trend_raw, trend_strength, data_point_count,
            confidence, calculation_detail
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
        ON CONFLICT (run_id, signal_name_code) DO UPDATE SET
            last_observation_date = EXCLUDED.last_observation_date,
            last_available_date = EXCLUDED.last_available_date,
            direction_code = EXCLUDED.direction_code,
            trend_raw = EXCLUDED.trend_raw,
            trend_strength = EXCLUDED.trend_strength,
            data_point_count = EXCLUDED.data_point_count,
            confidence = EXCLUDED.confidence,
            calculation_detail = EXCLUDED.calculation_detail
        """,
        params,
    )
    return len(params)


def insert_sector_results(db: PostgreDB, run_id: int, rows: list[dict]) -> int:
    if not rows:
        return 0
    params = [
        (
            run_id, row["sector_code"], row["industry_code"],
            row["up_benefit_score"], row["down_hedge_score"],
            row["macro_fit_score"], row["company_fa_breadth_score"],
            row["liquidity_capacity_score"], row["sector_risk_penalty"],
            row.get("cohort_quality_penalty"), row["sector_score"],
            row.get("candidate_source_code"),
            row.get("candidate_rank"), row.get("final_rank"),
            row.get("is_candidate", False), row.get("is_selected", False),
            row.get("eligible_large_count", 0), row.get("company_coverage_rate"),
            row.get("relationship_confidence"),
            json.dumps(row.get("macro_contributions", []), ensure_ascii=False, default=str),
            row.get("reason_code"), row.get("reason"),
        )
        for row in rows
    ]
    db.execute_many(
        """
        INSERT INTO fa_sector_results (
            run_id, sector_code, industry_code, up_benefit_score,
            down_hedge_score, macro_fit_score, company_fa_breadth_score,
            liquidity_capacity_score, sector_risk_penalty,
            cohort_quality_penalty, sector_score, candidate_source_code,
            candidate_rank, final_rank, is_candidate, is_selected,
            eligible_large_count, company_coverage_rate, relationship_confidence,
            macro_contributions, reason_code, reason
        ) VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s
        )
        ON CONFLICT (run_id, industry_code) DO UPDATE SET
            sector_code = EXCLUDED.sector_code,
            up_benefit_score = EXCLUDED.up_benefit_score,
            down_hedge_score = EXCLUDED.down_hedge_score,
            macro_fit_score = EXCLUDED.macro_fit_score,
            company_fa_breadth_score = EXCLUDED.company_fa_breadth_score,
            liquidity_capacity_score = EXCLUDED.liquidity_capacity_score,
            sector_risk_penalty = EXCLUDED.sector_risk_penalty,
            cohort_quality_penalty = EXCLUDED.cohort_quality_penalty,
            sector_score = EXCLUDED.sector_score,
            candidate_source_code = EXCLUDED.candidate_source_code,
            candidate_rank = EXCLUDED.candidate_rank,
            final_rank = EXCLUDED.final_rank,
            is_candidate = EXCLUDED.is_candidate,
            is_selected = EXCLUDED.is_selected,
            eligible_large_count = EXCLUDED.eligible_large_count,
            company_coverage_rate = EXCLUDED.company_coverage_rate,
            relationship_confidence = EXCLUDED.relationship_confidence,
            macro_contributions = EXCLUDED.macro_contributions,
            reason_code = EXCLUDED.reason_code,
            reason = EXCLUDED.reason
        """,
        params,
    )
    return len(params)


def fetch_sector_results(
    db: PostgreDB,
    run_id: int,
    *,
    selected_only: bool = False,
) -> list[dict]:
    condition = "AND is_selected = TRUE" if selected_only else ""
    return db.fetch_all(
        f"""
        SELECT * FROM fa_sector_results
        WHERE run_id = %s {condition}
        ORDER BY final_rank NULLS LAST, sector_score DESC, industry_code
        """,
        (run_id,),
    )


def insert_company_results(db: PostgreDB, run_id: int, rows: list[dict]) -> int:
    if not rows:
        return 0
    params = [
        (
            run_id, row["sector_result_id"], row["stock_code"],
            row.get("company_quarter_fa_id"), row["sector_code"],
            row["industry_code"], row.get("company_size_code"),
            row.get("fa_score"), row.get("score_confidence"),
            row.get("latest_available_date"), row.get("latest_trd_amt"),
            row.get("industry_rank"), row.get("is_eligible", False),
            row.get("is_selected", False), row.get("exclusion_reason_code"),
            row.get("reason"),
            json.dumps(row.get("selection_detail", {}), ensure_ascii=False, default=str),
        )
        for row in rows
    ]
    db.execute_many(
        """
        INSERT INTO fa_company_results (
            run_id, sector_result_id, stock_code, company_quarter_fa_id,
            sector_code, industry_code, company_size_code, fa_score,
            score_confidence, latest_available_date, latest_trd_amt,
            industry_rank, is_eligible, is_selected, exclusion_reason_code,
            reason, selection_detail
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
        ON CONFLICT (run_id, stock_code) DO UPDATE SET
            sector_result_id = EXCLUDED.sector_result_id,
            company_quarter_fa_id = EXCLUDED.company_quarter_fa_id,
            sector_code = EXCLUDED.sector_code,
            industry_code = EXCLUDED.industry_code,
            company_size_code = EXCLUDED.company_size_code,
            fa_score = EXCLUDED.fa_score,
            score_confidence = EXCLUDED.score_confidence,
            latest_available_date = EXCLUDED.latest_available_date,
            latest_trd_amt = EXCLUDED.latest_trd_amt,
            industry_rank = EXCLUDED.industry_rank,
            is_eligible = EXCLUDED.is_eligible,
            is_selected = EXCLUDED.is_selected,
            exclusion_reason_code = EXCLUDED.exclusion_reason_code,
            reason = EXCLUDED.reason,
            selection_detail = EXCLUDED.selection_detail
        """,
        params,
    )
    return len(params)
