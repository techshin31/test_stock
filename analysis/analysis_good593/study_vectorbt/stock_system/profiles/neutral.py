from .base import FEES, SLIPPAGE, WF_TRAIN_MONTHS, WF_TEST_MONTHS, ADX_PARAM_GRID  # noqa: F401

ADX_THRESHOLD    = 25.0
ADX_SIDEWAYS     = 20.0
ENTRY1_SIZE      = 0.4
ENTRY2_SIZE      = 0.7
ENTRY_RANGE_SIZE = 0.3
EXIT1_SIZE       = 0.4
EXIT2_SIZE       = 0.1
RECENT_WINDOW    = 60
MOMENTUM_WINDOW  = {"UPTREND": 126, "TRANSITION": 63, "SIDEWAYS": 21}
MIN_MOMENTUM     = 0.0
ATR_PERIOD       = 14
ATR_MULTIPLIER   = 2.0
KOSPI_MA         = 120
CASH_RETURN      = 0.035

METRICS_TARGET = {
    "cagr":              0.06,
    "mdd":              -0.25,
    "mdd_duration":       12,
    "calmar":             0.3,
    "sortino":            0.5,
    "alpha":              0.02,
    "beta":               0.8,
    "mdd_reduction":      0.20,
    "calmar_improvement": 0.1,
    "info_ratio":         0.3,
    "win_rate":           0.5,
}
METRICS_ALERT = {
    "cagr":              0.04,
    "mdd":              -0.35,
    "mdd_duration":       18,
    "calmar":             0.2,
    "sortino":            0.3,
    "alpha":              0.0,
    "beta":               1.0,
    "mdd_reduction":      0.10,
    "calmar_improvement": 0.0,
    "info_ratio":         0.0,
    "win_rate":           0.4,
}


def get_signal(close_df, high_df, low_df, kospi=None):
    """오늘의 매매 신호 생성 — 자동매매 시스템 진입점

    Parameters
    ----------
    close_df : DataFrame  최소 150일 이상의 과거 종가 (MA120 warmup 필요)

    Returns
    -------
    dict  종목명 → 오늘 목표 비중 (NaN=유지, 0.0=전량청산, 양수=목표비중)
    """
    from ..strategies.partial import make_signals
    result = {}
    for name in close_df.columns:
        _, _, size_s, _ = make_signals(
            close_df[name], high_df[name], low_df[name],
            adx_threshold=ADX_THRESHOLD,
            adx_sideways=ADX_SIDEWAYS,
            kospi=kospi,
            kospi_ma=KOSPI_MA,
            atr_multiplier=ATR_MULTIPLIER,
            atr_period=ATR_PERIOD,
        )
        result[name] = size_s.iloc[-1]
    return result
