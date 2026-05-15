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
    "cagr":              0.10,
    "mdd":              -0.35,
    "mdd_duration":       18,
    "calmar":             0.3,
    "sortino":            0.7,
    "alpha":              0.05,
    "beta":               1.2,
    "mdd_reduction":      0.10,
    "calmar_improvement": 0.1,
    "info_ratio":         0.3,
    "win_rate":           0.5,
}
METRICS_ALERT = {
    "cagr":              0.07,
    "mdd":              -0.45,
    "mdd_duration":       24,
    "calmar":             0.2,
    "sortino":            0.4,
    "alpha":              0.0,
    "beta":               1.5,
    "mdd_reduction":      0.0,
    "calmar_improvement": 0.0,
    "info_ratio":         0.0,
    "win_rate":           0.4,
}


# get_signal()은 neutral.py 검증 완료 후 별도 구현 예정
# 현재는 상수 정의만 완료된 상태
