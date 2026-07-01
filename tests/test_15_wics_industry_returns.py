from datetime import date
from decimal import Decimal

import pytest

from apps.worker.analyzer.sector_job import (
    industry_returns_frame,
    reconstruct_industry_indices,
)


def test_reconstruction_never_uses_future_constituents():
    prices = [
        {"stock_code": "A", "price_date": date(2026, 1, day), "close": 100 + day}
        for day in range(1, 6)
    ] + [
        {"stock_code": "B", "price_date": date(2026, 1, day), "close": 10 if day < 4 else 100}
        for day in range(1, 6)
    ]
    wics = [
        {"stock_code": "A", "base_date": date(2026, 1, 1), "industry_code": "G4530", "mkt_val": 100},
        {"stock_code": "A", "base_date": date(2026, 1, 4), "industry_code": "G4530", "mkt_val": 100},
        {"stock_code": "B", "base_date": date(2026, 1, 4), "industry_code": "G4530", "mkt_val": 100},
    ]
    rows = reconstruct_industry_indices(prices, wics, minimum_coverage=1.0)
    before_addition = [row for row in rows if row["price_date"] < date(2026, 1, 4)]
    assert before_addition
    assert all(row["constituent_base_date"] == date(2026, 1, 1) for row in before_addition)


def test_low_constituent_coverage_is_excluded():
    prices = [
        {"stock_code": "A", "price_date": date(2026, 1, 1), "close": Decimal("100")},
        {"stock_code": "A", "price_date": date(2026, 1, 2), "close": Decimal("101")},
    ]
    wics = [
        {"stock_code": "A", "base_date": date(2026, 1, 1), "industry_code": "G4530", "mkt_val": 10},
        {"stock_code": "B", "base_date": date(2026, 1, 1), "industry_code": "G4530", "mkt_val": 90},
    ]
    assert reconstruct_industry_indices(prices, wics, minimum_coverage=0.8) == []


def test_weekly_and_monthly_returns_align_from_levels():
    rows = [
        {"industry_code": "G4530", "price_date": date(2026, 1, 2), "index_value": Decimal("100")},
        {"industry_code": "G4530", "price_date": date(2026, 1, 9), "index_value": Decimal("110")},
        {"industry_code": "G4530", "price_date": date(2026, 1, 30), "index_value": Decimal("121")},
        {"industry_code": "G4530", "price_date": date(2026, 2, 27), "index_value": Decimal("133.1")},
    ]
    weekly = industry_returns_frame(rows, "WEEKLY")
    monthly = industry_returns_frame(rows, "MONTHLY")
    assert weekly.iloc[0]["G4530"] == pytest.approx(0.1)
    assert monthly.iloc[0]["G4530"] == pytest.approx(0.1)
