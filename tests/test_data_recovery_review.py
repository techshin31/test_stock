from datetime import date, datetime, timedelta
import json
import tarfile
import io
from pathlib import Path

import pandas as pd
import pytest

from apps.worker.collector import monitor
from apps.system import recovery
from apps.system.strategy_review import review
from core.utils.io import write_json


def collection_record():
    return json.loads((Path(__file__).parents[1] / "integration/fixtures/collection-public-sample.json").read_text())


@pytest.mark.parametrize("case", ["valid", "stale", "unknown_failure", "missing_page", "out_of_scope", "malformed", "pagination", "scope", "future"])
def test_collection_evidence_blocks_stale_failed_or_incomplete_sources(case):
    now = datetime(2026, 10, 5, 12, tzinfo=monitor.KST)
    record = {**collection_record(), "checked_at": now.isoformat()}
    if case == "stale":
        record["checked_at"] = (now - timedelta(days=3)).isoformat()
    elif case == "unknown_failure":
        record["finance"]["failures"].append({"reason": "HTTP_502"})
    elif case == "missing_page":
        record["risk_source_pages"] = record["risk_source_pages"][:1]
    elif case == "out_of_scope":
        record["risk_start"] = "2026-10-03"
    elif case == "malformed":
        record = []
    elif case == "pagination":
        record["risk_source_pages"] = [p for p in record["risk_source_pages"] if p["page"] == 1]
    elif case == "scope":
        record["company_size_codes"] = ["MID"]
    elif case == "future":
        record["checked_at"] = (now + timedelta(hours=1)).isoformat()
    write_json(monitor.health_path(), record)
    result = monitor.collection_health(date(2026, 10, 2), now=now)
    assert result["status"] == ("PASS" if case == "valid" else "BLOCKED")


def test_backup_checksum_rejects_corruption_before_database_creation(tmp_path, monkeypatch):
    dump = tmp_path / "database.dump"
    dump.write_bytes(b"original")
    write_json(tmp_path / "manifest.json", {"format_version": 1, "files": {"database.dump": recovery.digest(dump)}})
    dump.write_bytes(b"corrupt")
    monkeypatch.setattr(recovery, "load_env", lambda: None)
    monkeypatch.setattr(recovery, "build_db_config", lambda: {})
    monkeypatch.setattr(recovery.psycopg, "connect", lambda **kw: pytest.fail("Database contacted before checksum verification"))
    with pytest.raises(ValueError, match="CHECKSUM"):
        recovery.restore(tmp_path)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "folder/../../escape", "C:\\escape"])
def test_source_restore_refuses_path_escape(tmp_path, name):
    archive = tmp_path / "sources.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        entry = tarfile.TarInfo(name)
        entry.size = 1
        handle.addfile(entry, io.BytesIO(b"x"))
    with pytest.raises(ValueError, match="UNSAFE"):
        recovery.extract_sources(archive, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_chronological_cost_stress_and_concentration_use_observed_inputs(tmp_path):
    days = pd.bdate_range("2026-01-01", periods=60)
    equity = pd.Series(100 * (1.001 ** pd.RangeIndex(60)), index=days)
    pd.DataFrame({"equity": equity}).to_csv(tmp_path / "equity-curve.csv")
    pd.DataFrame({"stock": .4, "BOND_ETF": .3}, index=days).to_csv(tmp_path / "weights.csv")
    pd.DataFrame({"benchmark": 100 * (1.002 ** pd.RangeIndex(60))}, index=days).to_csv(tmp_path / "benchmark.csv")
    pd.DataFrame([{"date": days[10], "trade_turnover": .5, "trade_reason": "ENTRY"}]).to_csv(tmp_path / "trade-ledger.csv", index=False)
    result = review(tmp_path, tmp_path / "benchmark.csv")
    assert [p["strategy"]["sessions"] for p in result["chronological_periods"]] == [40, 20]
    assert result["concentration"]["sessions_above_paper_cap"] == 60
    assert result["concentration"]["mean_cash_weight"] == pytest.approx(.3)
    assert result["cost_stress"][0]["return_pct"] > result["cost_stress"][-1]["return_pct"]
    assert "BENCHMARK_UNDERPERFORMANCE" in result["promotion_reasons"]
    assert result["promotion_status"] == "BLOCKED"
    benchmark = pd.read_csv(tmp_path / "benchmark.csv")
    benchmark.iloc[1:].to_csv(tmp_path / "benchmark.csv", index=False)
    with pytest.raises(ValueError, match="COVERAGE"):
        review(tmp_path, tmp_path / "benchmark.csv")
