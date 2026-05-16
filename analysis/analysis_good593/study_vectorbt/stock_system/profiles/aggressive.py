from .base import FEES, SLIPPAGE, WF_TRAIN_MONTHS, WF_TEST_MONTHS, ADX_PARAM_GRID  # noqa: F401

ADX_THRESHOLD    = 20.0
ADX_SIDEWAYS     = 15.0
ENTRY1_SIZE      = 0.6
ENTRY2_SIZE      = 0.9
ENTRY_RANGE_SIZE = 0.4
EXIT1_SIZE       = 0.5
EXIT2_SIZE       = 0.2
RECENT_WINDOW    = 40
MOMENTUM_WINDOW  = {"UPTREND": 126, "TRANSITION": 63, "SIDEWAYS": 21}
MIN_MOMENTUM     = 0.05
ATR_PERIOD       = 14
ATR_MULTIPLIER   = 2.5
KOSPI_MA         = 120
CASH_RETURN      = 0.035

METRICS_TARGET = {
    "cagr":              0.15,   # 15%  — B&H 초과가 목표
    "mdd":              -0.35,   # -35% — 높은 위험 허용
    "mdd_duration":       24,
    "calmar":             0.45,  # 15% / 35% ≈ 0.43
    "sortino":            1.0,
    "alpha":              0.05,  # KOSPI 대비 +5%
    "beta":               1.3,
    "mdd_reduction":      0.0,   # KOSPI 대비 MDD 감소 불필요 (수익 우선)
    "calmar_improvement": 0.3,   # B&H 대비 Calmar 명확히 개선
    "info_ratio":         0.5,
    "win_rate":           0.55,
}
METRICS_ALERT = {
    "cagr":              0.10,   # 10% 미만이면 B&H 대비 의미 없음
    "mdd":              -0.50,   # -50% — 원금 절반 손실은 전략 실패
    "mdd_duration":       36,
    "calmar":             0.25,
    "sortino":            0.6,
    "alpha":              0.02,
    "beta":               1.5,
    "mdd_reduction":     -0.10,  # KOSPI보다 10% 이상 나쁘면 경보
    "calmar_improvement": 0.1,
    "info_ratio":         0.2,
    "win_rate":           0.45,
}


def make_signals(*_args, **_kwargs) -> tuple:
    raise NotImplementedError("적극투자형 make_signals() 미구현")


def get_signal(*_args, **_kwargs) -> dict:
    raise NotImplementedError("적극투자형 get_signal() 미구현")
