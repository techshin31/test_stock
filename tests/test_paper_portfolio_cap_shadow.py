import datetime as dt
import json

import pytest

from core.analytics.paper_portfolio_cap_shadow import (
    evaluate_paper_portfolio_cap_shadow,
)


def test_cap_challengers_are_observe_only_and_do_not_mutate_targets(tmp_path):
    production_targets = {
        "005930.KS": 0.15,
        "000660.KS": 0.11,
        "035420.KS": 0.05,
        "EXIT.KS": 0.0,
    }
    original = dict(production_targets)

    payload = evaluate_paper_portfolio_cap_shadow(
        mode="PAPER",
        strategy="fa_ta_momentum",
        account_scope="****-01",
        signal_date=dt.date(2026, 7, 28),
        target_positions=production_targets,
        log_dir=tmp_path,
    )

    assert production_targets == original
    assert payload["observe_only"] is True
    assert payload["order_permission"] == "DENIED_BY_DESIGN"
    assert payload["production"]["max_single_position_weight"] == 0.15
    by_variant = {row["variant"]: row for row in payload["challengers"]}
    assert by_variant["C_CAP10"]["shadow_target_positions"]["005930.KS"] == 0.10
    assert by_variant["C_CAP10"]["shadow_target_positions"]["000660.KS"] == 0.10
    assert by_variant["C_CAP08"]["shadow_target_positions"]["005930.KS"] == 0.08
    assert by_variant["C_CAP08"]["capped_position_count"] == 2
    assert by_variant["C_CAP08"]["gross_target_weight"] == pytest.approx(0.21)

    state = json.loads(
        (tmp_path / "portfolio_cap_shadow_state.json").read_text(encoding="utf-8")
    )
    assert state == payload
    assert len(
        (tmp_path / "portfolio_cap_shadow_history.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ) == 1


def test_cap_challengers_append_only_once_per_session(tmp_path):
    kwargs = {
        "mode": "PAPER",
        "strategy": "fa_ta_momentum",
        "account_scope": "****-01",
        "signal_date": dt.date(2026, 7, 28),
        "target_positions": {"005930.KS": 0.15},
        "log_dir": tmp_path,
    }

    evaluate_paper_portfolio_cap_shadow(**kwargs)
    evaluate_paper_portfolio_cap_shadow(**kwargs)

    assert len(
        (tmp_path / "portfolio_cap_shadow_history.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ) == 1


def test_cap_challengers_reject_non_paper_scope(tmp_path):
    with pytest.raises(ValueError, match="PAPER-only"):
        evaluate_paper_portfolio_cap_shadow(
            mode="REAL",
            strategy="fa_ta_momentum",
            account_scope="****-01",
            signal_date=dt.date(2026, 7, 28),
            target_positions={},
            log_dir=tmp_path,
        )
