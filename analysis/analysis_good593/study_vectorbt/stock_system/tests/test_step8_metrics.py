"""Step 8 — 성과 지표 단위 테스트 (metrics/calc.py, metrics/report.py)

검증 항목:
  - calc_metrics(): 11개 지표 전부 계산
  - 절대 지표: cagr, mdd, mdd_duration, calmar, sortino, win_rate
  - 상대 지표: alpha, beta, mdd_reduction, calmar_improvement, info_ratio
  - 설계 명세 목표/경보선 수치 일치 (profiles/neutral.py)
  - build_metrics_table(): 컬럼 구조, 상태 값(✓/⚠/✗/—)
"""

import numpy as np
import pandas as pd
import pytest

from stock_system.metrics.calc import calc_metrics, _calc_equity_metrics


# ── 합성 데이터 픽스처 ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def equity_series(dates):
    """수익률 곡선: 연 8% 수준, 일부 변동"""
    rng = np.random.default_rng(42)
    returns = rng.normal(0.0003, 0.010, len(dates))
    return pd.Series(
        1_000_000.0 * np.cumprod(1 + returns),
        index=dates,
        name="equity",
    )


@pytest.fixture(scope="module")
def kospi_series(dates):
    rng = np.random.default_rng(123)
    returns = rng.normal(0.0002, 0.012, len(dates))
    return pd.Series(
        2000.0 * np.cumprod(1 + returns),
        index=dates,
        name="KOSPI",
    )


@pytest.fixture(scope="module")
def etf_series(dates):
    """단기채 ETF: 연 3.5% 고정 수익"""
    daily_rate = (1 + 0.035) ** (1 / 252) - 1
    values = 1000.0 * (1 + daily_rate) ** np.arange(len(dates))
    return pd.Series(values, index=dates, name="단기채ETF")


# ── 절대 지표 계산 ─────────────────────────────────────────────────────────────

class TestCalcMetrics:
    REQUIRED_ABSOLUTE = ["cagr", "mdd", "mdd_duration", "calmar", "sortino", "win_rate"]
    REQUIRED_RELATIVE = ["alpha", "beta", "mdd_reduction", "calmar_improvement", "info_ratio"]

    def test_all_absolute_metrics_computed(self, equity_series):
        metrics = calc_metrics(equity_series)
        for key in self.REQUIRED_ABSOLUTE:
            assert key in metrics, f"지표 누락: {key}"

    def test_all_relative_metrics_computed_with_benchmark(self, equity_series, kospi_series):
        metrics = calc_metrics(equity_series, benchmark_series=kospi_series)
        for key in self.REQUIRED_ABSOLUTE + self.REQUIRED_RELATIVE:
            assert key in metrics, f"지표 누락: {key}"

    def test_no_relative_metrics_without_benchmark(self, equity_series):
        metrics = calc_metrics(equity_series, benchmark_series=None)
        for key in self.REQUIRED_RELATIVE:
            assert key not in metrics, f"benchmark 없이 상대 지표 계산됨: {key}"

    def test_cagr_reasonable_range(self, equity_series):
        metrics = calc_metrics(equity_series)
        assert -1.0 < metrics["cagr"] < 5.0, "CAGR 범위 이상"

    def test_mdd_negative(self, equity_series):
        metrics = calc_metrics(equity_series)
        assert metrics["mdd"] < 0, "MDD는 음수여야 함"

    def test_mdd_max_is_minus_one(self, equity_series):
        metrics = calc_metrics(equity_series)
        assert metrics["mdd"] >= -1.0, "MDD >= -100%"

    def test_mdd_duration_positive(self, equity_series):
        metrics = calc_metrics(equity_series)
        assert metrics["mdd_duration"] >= 0

    def test_calmar_positive_when_cagr_positive(self, equity_series):
        metrics = calc_metrics(equity_series)
        if metrics["cagr"] > 0:
            assert metrics["calmar"] > 0

    def test_win_rate_between_0_and_1(self, equity_series):
        metrics = calc_metrics(equity_series)
        assert 0.0 <= metrics["win_rate"] <= 1.0

    def test_beta_reasonable(self, equity_series, kospi_series):
        metrics = calc_metrics(equity_series, benchmark_series=kospi_series)
        assert -5.0 < metrics["beta"] < 5.0, "Beta 범위 이상"


# ── _calc_equity_metrics ──────────────────────────────────────────────────────

class TestCalcEquityMetrics:
    def test_uptrend_positive_cagr(self, dates):
        """순수 상승 데이터: CAGR > 0"""
        t = np.arange(len(dates))
        equity = pd.Series(100.0 * 1.001 ** t, index=dates)
        m = _calc_equity_metrics(equity)
        assert m["cagr"] > 0

    def test_flat_equity_zero_mdd(self, dates):
        """상수 equity: MDD = 0"""
        equity = pd.Series(1000.0, index=dates)
        m = _calc_equity_metrics(equity)
        assert m["mdd"] == 0.0

    def test_result_keys(self, equity_series):
        m = _calc_equity_metrics(equity_series)
        assert set(m.keys()) == {"cagr", "mdd", "mdd_duration", "calmar", "sortino", "win_rate"}


# ── 설계 명세 목표/경보선 수치 ─────────────────────────────────────────────────

class TestProfileConstants:
    def test_metrics_target(self):
        from stock_system.profiles import neutral
        T = neutral.METRICS_TARGET
        assert T["cagr"]         == 0.08
        assert T["mdd"]          == -0.30
        assert T["mdd_duration"] == 24
        assert T["calmar"]       == 0.35
        assert T["sortino"]      == 0.8
        assert T["alpha"]        == 0.02
        assert T["beta"]         == 0.8
        assert T["win_rate"]     == 0.55

    def test_metrics_alert(self):
        from stock_system.profiles import neutral
        A = neutral.METRICS_ALERT
        assert A["cagr"]         == 0.05
        assert A["mdd"]          == -0.40
        assert A["mdd_duration"] == 36
        assert A["calmar"]       == 0.20
        assert A["sortino"]      == 0.5
        assert A["alpha"]        == 0.0
        assert A["beta"]         == 1.0
        assert A["win_rate"]     == 0.45

    def test_all_target_keys_have_alert(self):
        from stock_system.profiles import neutral
        assert set(neutral.METRICS_TARGET.keys()) == set(neutral.METRICS_ALERT.keys())


# ── build_metrics_table ───────────────────────────────────────────────────────

class TestBuildMetricsTable:
    def test_table_columns_with_benchmark_and_etf(
        self, equity_series, kospi_series, etf_series, neutral_profile
    ):
        from stock_system.metrics.report import build_metrics_table
        close_df = pd.DataFrame({"dummy": equity_series})
        table = build_metrics_table(
            equity_series, close_df, neutral_profile,
            benchmark_series=kospi_series,
            etf_series=etf_series,
        )
        assert "단기채 100%" in table.columns
        assert "KOSPI"      in table.columns
        assert "목표"        in table.columns
        assert "경보선"      in table.columns
        assert "상태"        in table.columns

    def test_status_values_valid(
        self, equity_series, kospi_series, etf_series, neutral_profile
    ):
        from stock_system.metrics.report import build_metrics_table
        close_df = pd.DataFrame({"dummy": equity_series})
        table = build_metrics_table(
            equity_series, close_df, neutral_profile,
            benchmark_series=kospi_series,
            etf_series=etf_series,
        )
        valid_statuses = {"✓", "⚠", "✗", "—"}
        assert set(table["상태"].unique()).issubset(valid_statuses)

    def test_table_row_count(self, equity_series, neutral_profile):
        from stock_system.metrics.report import build_metrics_table
        close_df = pd.DataFrame({"dummy": equity_series})
        table = build_metrics_table(equity_series, close_df, neutral_profile)
        # META에 정의된 지표 수 = 11
        assert len(table) == 11

    def test_table_index_contains_metric_labels(self, equity_series, neutral_profile):
        from stock_system.metrics.report import build_metrics_table
        close_df = pd.DataFrame({"dummy": equity_series})
        table = build_metrics_table(equity_series, close_df, neutral_profile)
        assert "CAGR"    in table.index
        assert "MDD"     in table.index
        assert "Calmar"  in table.index
        assert "Sortino" in table.index

    def test_no_crash_without_benchmark(self, equity_series, neutral_profile):
        from stock_system.metrics.report import build_metrics_table
        close_df = pd.DataFrame({"dummy": equity_series})
        table = build_metrics_table(equity_series, close_df, neutral_profile)
        assert len(table) > 0

    def test_profile_name_in_column(self, equity_series, neutral_profile):
        """profile 이름이 컬럼에 반영됨 (neutral → 'neutral 전략')"""
        from stock_system.metrics.report import build_metrics_table
        close_df = pd.DataFrame({"dummy": equity_series})
        table = build_metrics_table(equity_series, close_df, neutral_profile)
        strategy_cols = [c for c in table.columns if "neutral" in c]
        assert len(strategy_cols) >= 1


# ── build_period_stats_table ──────────────────────────────────────────────────

class TestBuildPeriodStatsTable:
    def test_yearly_stats(self, equity_series, kospi_series):
        from stock_system.metrics.report import build_period_stats_table
        bh = equity_series * 1.0  # B&H = equity 자체
        table = build_period_stats_table(
            equity_series, bh, benchmark_series=kospi_series, freq="Y"
        )
        assert "전략(%)" in table.columns
        assert "B&H(%)"  in table.columns
        assert "KOSPI(%)" in table.columns
        # 연도별 인덱스 형식 확인
        assert all(len(str(i)) == 4 for i in table.index)

    def test_quarterly_stats(self, equity_series, kospi_series):
        from stock_system.metrics.report import build_period_stats_table
        bh = equity_series * 1.0
        table = build_period_stats_table(
            equity_series, bh, benchmark_series=kospi_series, freq="Q"
        )
        # 분기별 인덱스: "YYYYQN" 형식
        assert all("Q" in str(i) for i in table.index)

    def test_monthly_stats(self, equity_series):
        from stock_system.metrics.report import build_period_stats_table
        bh = equity_series * 1.0
        table = build_period_stats_table(equity_series, bh, freq="M")
        # 월별 인덱스: "YYYY-MM" 형식
        assert all("-" in str(i) for i in table.index)
