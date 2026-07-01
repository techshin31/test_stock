from contextlib import contextmanager
from datetime import date, datetime

import pytest

from apps.worker.analyzer.config import load_config
from apps.worker.analyzer.models import MacroDirection, MacroResult
from apps.worker.analyzer.universe_job import UniversePublishError, publish
from apps.worker.analyzer.validation import ResultCheck, RunValidationResult, validate_run
from apps.worker.fa_contract import REQUIRED_MACRO_CODES


def _selected_rows():
    return [
        {
            "id": index, "stock_code": f"{index:06d}", "fa_score": 70 + index,
            "market_type_code": "KOSPI", "status_code": "ACTIVE",
        }
        for index in range(1, 7)
    ]


class Result:
    def __init__(self, one=None, all_rows=None):
        self.one = one
        self.all_rows = all_rows or []

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.all_rows


class PublishConnection:
    def __init__(self, status="PASS", fail_on_insert=False, effective_date=date(2026, 6, 1)):
        self.status = status
        self.fail_on_insert = fail_on_insert
        self.effective_date = effective_date
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((query, params))
        normalized = " ".join(query.split())
        if "FROM fa_analysis_runs" in normalized and "FOR UPDATE" in normalized:
            return Result(one={
                "id": 9, "strategy_id": 1, "status_code": self.status,
                "effective_date": self.effective_date,
            })
        if "FROM strategies" in normalized:
            return Result(one={"id": 1, "name": "risk_neutral", "is_active": True})
        if "FROM fa_company_results" in normalized:
            return Result(all_rows=_selected_rows())
        if "FROM company_risk_states" in normalized:
            return Result(all_rows=[])
        if normalized.startswith("UPDATE universe"):
            return Result(all_rows=[{"symbol": "999999"}])
        if normalized.startswith("INSERT INTO universe"):
            if self.fail_on_insert:
                raise RuntimeError("insert failed")
            return Result()
        if normalized.startswith("UPDATE fa_analysis_runs"):
            self.status = "PUBLISHED"
            return Result()
        if "SELECT symbol FROM universe" in normalized:
            return Result(all_rows=[{"symbol": row["stock_code"]} for row in _selected_rows()])
        raise AssertionError(normalized)


class PublishDB:
    def __init__(self, connection):
        self.connection = connection
        self.rolled_back = False

    @contextmanager
    def transaction(self):
        try:
            yield self.connection
        except Exception:
            self.rolled_back = True
            raise


def test_pass_and_warning_runs_can_publish_after_same_day_deadline():
    config = load_config("risk_neutral")
    for status in ("PASS", "WARNING"):
        connection = PublishConnection(status=status)
        publish(
            PublishDB(connection), 9, config,
            now_kst=datetime(2026, 6, 1, 8, 0),
        )
        assert connection.status == "PUBLISHED"

    late_connection = PublishConnection()
    publish(
        PublishDB(late_connection), 9, config,
        now_kst=datetime(2026, 6, 1, 9, 0),
    )
    assert late_connection.status == "PUBLISHED"

    with pytest.raises(UniversePublishError, match="only PASS or WARNING"):
        publish(
            PublishDB(PublishConnection(status="FAIL")), 9, config,
            now_kst=datetime(2026, 6, 1, 8, 0),
        )
    with pytest.raises(UniversePublishError, match="past"):
        publish(
            PublishDB(PublishConnection()), 9, config,
            now_kst=datetime(2026, 6, 2, 9, 0),
        )


def test_publish_is_atomic_and_links_selected_rows_up_to_limit():
    connection = PublishConnection()
    db = PublishDB(connection)
    result = publish(
        db, 9, load_config("risk_neutral"),
        now_kst=datetime(2026, 6, 1, 8, 0),
    )
    inserts = [query for query, _ in connection.calls if "INSERT INTO universe" in query]
    assert len(inserts) == 6
    assert result.active_symbols == tuple(f"{index:06d}" for index in range(1, 7))
    assert result.sell_only_symbols == ("999999",)
    assert connection.status == "PUBLISHED"

    connection.status = "PUBLISHED"
    again = publish(
        db, 9, load_config("risk_neutral"),
        now_kst=datetime(2026, 6, 2, 9, 0),
    )
    assert again.already_published


def test_publish_failure_rolls_back_transaction():
    db = PublishDB(PublishConnection(fail_on_insert=True))
    with pytest.raises(RuntimeError, match="insert failed"):
        publish(
            db, 9, load_config("risk_neutral"),
            now_kst=datetime(2026, 6, 1, 8, 0),
        )
    assert db.rolled_back


class ValidationDB:
    def __init__(self):
        self.one_calls = 0

    def fetch_one(self, query, params=None):
        self.one_calls += 1
        if self.one_calls == 1:
            return {
                "id": 9, "cutoff_date": date(2026, 5, 31),
                "effective_date": date(2026, 6, 1),
            }
        return {"candidates": 5, "selected": 5, "sectors": 5}

    def fetch_all(self, query, params=None):
        if "fa_macro_results" in query:
            return [
                {"signal_name_code": code, "last_available_date": date(2026, 5, 30)}
                for code in REQUIRED_MACRO_CODES
            ]
        if "fa_company_results" in query:
            return [
                {
                    "stock_code": f"{index:06d}", "industry_code": f"G{index // 2}",
                    "is_eligible": True, "company_size_code": "LARGE",
                    "company_status_code": "ACTIVE", "market_type_code": "KOSPI",
                    "latest_available_date": date(2026, 5, 15),
                }
                for index in range(10)
            ]
        if "company_risk_states" in query:
            return []
        raise AssertionError(query)


class MissingMacroValidationDB(ValidationDB):
    def fetch_all(self, query, params=None):
        if "fa_macro_results" in query:
            return [
                {"signal_name_code": code, "last_available_date": date(2026, 5, 30)}
                for code in REQUIRED_MACRO_CODES
                if code != "KR_TOURIST"
            ]
        return super().fetch_all(query, params)


class PartialSelectionValidationDB(ValidationDB):
    def fetch_one(self, query, params=None):
        self.one_calls += 1
        if self.one_calls == 1:
            return {
                "id": 9, "cutoff_date": date(2026, 5, 31),
                "effective_date": date(2026, 6, 1),
            }
        return {"candidates": 5, "selected": 3, "sectors": 5}

    def fetch_all(self, query, params=None):
        if "fa_company_results" in query:
            return [
                {
                    "stock_code": f"{index:06d}", "industry_code": f"G{index // 2}",
                    "is_eligible": True, "company_size_code": "LARGE",
                    "company_status_code": "ACTIVE", "market_type_code": "KOSPI",
                    "latest_available_date": date(2026, 5, 15),
                }
                for index in range(6)
            ]
        return super().fetch_all(query, params)


def test_run_validation_rechecks_stored_result_contract(monkeypatch):
    from apps.worker.analyzer import validation

    monkeypatch.setattr(validation, "fetch_buy_blocked_stock_codes", lambda *args: set())
    result = validate_run(ValidationDB(), 9, load_config("risk_neutral"))
    assert result.status == "PASS"
    assert all(check.passed for check in result.checks)


def test_run_validation_accepts_partial_selection_up_to_configured_limit(monkeypatch):
    from apps.worker.analyzer import validation

    monkeypatch.setattr(validation, "fetch_buy_blocked_stock_codes", lambda *args: set())
    result = validate_run(PartialSelectionValidationDB(), 9, load_config("risk_neutral"))
    assert result.status == "PASS"
    assert all(check.passed for check in result.checks)


def test_run_validation_warns_on_noncritical_company_risk(monkeypatch):
    from apps.worker.analyzer import validation

    monkeypatch.setattr(
        validation,
        "fetch_buy_blocked_stock_codes",
        lambda *args: {"000001"},
    )
    result = validate_run(ValidationDB(), 9, load_config("risk_neutral"))
    assert result.status == "WARNING"
    company_risk = next(check for check in result.checks if check.name == "company_risk")
    assert not company_risk.passed


def test_run_validation_warns_when_macro_inputs_are_missing(monkeypatch):
    from apps.worker.analyzer import validation

    monkeypatch.setattr(validation, "fetch_buy_blocked_stock_codes", lambda *args: set())
    result = validate_run(MissingMacroValidationDB(), 9, load_config("risk_neutral"))

    assert result.status == "WARNING"
    macro_check = next(check for check in result.checks if check.name == "macro_results")
    assert not macro_check.passed
    assert "KR_TOURIST" in macro_check.detail


def test_reused_pass_run_can_be_published(monkeypatch):
    from apps.worker.analyzer import pipeline
    from apps.worker.analyzer.models import AnalysisRunContext
    from apps.worker.analyzer.pipeline import build_request

    context = AnalysisRunContext(
        run_id=9, target="all", strategy_id=1,
        analysis_month=date(2026, 6, 1), cutoff_date=date(2026, 5, 31),
        effective_date=date(2026, 6, 1), input_hash="a" * 64,
        model_version="v1", created=False,
    )
    monkeypatch.setattr(pipeline, "prepare_run", lambda *args: context)
    published = []
    monkeypatch.setattr(
        pipeline, "publish_universe",
        lambda db, run_id, config: published.append(run_id),
    )
    request = build_request(
        target="all", analysis_month="2026-06",
        cutoff_date="2026-05-31", effective_date="2026-06-01",
        publish=True,
    )
    pipeline.run(object(), request, load_config("risk_neutral"))
    assert published == [9]


def test_new_warning_run_can_be_published(monkeypatch):
    from apps.worker.analyzer import pipeline
    from apps.worker.analyzer.models import AnalysisRunContext
    from apps.worker.analyzer.pipeline import build_request

    context = AnalysisRunContext(
        run_id=9, target="all", strategy_id=1,
        analysis_month=date(2026, 6, 1), cutoff_date=date(2026, 5, 31),
        effective_date=date(2026, 6, 1), input_hash="a" * 64,
        model_version="v1", created=True,
    )
    macro = MacroResult(
        signal_name_code="SOX",
        last_observation_date=date(2026, 5, 30),
        last_available_date=date(2026, 5, 31),
        direction_code=MacroDirection.UP,
        trend_raw=1.0,
        trend_strength=1.0,
        data_point_count=160,
        confidence=1.0,
        calculation_detail={},
    )
    sectors = [
        {
            "industry_code": f"G{index}",
            "sector_code": f"S{index}",
            "sector_score": 80.0,
            "eligible_large_count": 2,
            "is_selected": True,
            "final_rank": index,
        }
        for index in range(1, 4)
    ]
    companies = [
        {"stock_code": f"{index:06d}", "industry_code": f"G{index // 2}", "is_selected": True}
        for index in range(6)
    ]
    monkeypatch.setattr(pipeline, "prepare_run", lambda *args: context)
    monkeypatch.setattr(pipeline, "refresh_quarterly_scores", lambda *args: 10)
    monkeypatch.setattr(pipeline, "run_macro_analysis", lambda *args: [macro])
    monkeypatch.setattr(pipeline, "run_sector_analysis", lambda *args: sectors)
    monkeypatch.setattr(pipeline, "run_company_selection", lambda *args: companies)
    monkeypatch.setattr(
        pipeline,
        "validate_run",
        lambda *args: RunValidationResult(
            status="WARNING",
            checks=(ResultCheck("company_risk", False, "['000001']"),),
        ),
    )
    updates = []
    published = []
    monkeypatch.setattr(
        pipeline,
        "update_analysis_run_status",
        lambda *args, **kwargs: updates.append((args, kwargs)),
    )
    monkeypatch.setattr(
        pipeline,
        "publish_universe",
        lambda db, run_id, config: published.append(run_id),
    )
    request = build_request(
        target="all", analysis_month="2026-06",
        cutoff_date="2026-05-31", effective_date="2026-06-01",
        publish=True,
    )
    pipeline.run(object(), request, load_config("risk_neutral"), show_progress=False)
    assert updates[-1][0][2] == "WARNING"
    assert updates[-1][1]["failure_reason"] is None
    assert published == [9]
