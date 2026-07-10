import pandas as pd


def calc_adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 14,
) -> pd.DataFrame:
    """ADX, +DI, -DI 반환 (Wilder's smoothing)"""
    prev_high  = high.shift(1)
    prev_low   = low.shift(1)
    prev_close = close.shift(1)

    plus_dm  = (high - prev_high).clip(lower=0)
    minus_dm = (prev_low - low).clip(lower=0)
    # +DM과 -DM이 같거나 둘 다 0이면 0
    valid_plus_dm  = (plus_dm > minus_dm) & (plus_dm > 0)
    valid_minus_dm = (minus_dm > plus_dm) & (minus_dm > 0)
    plus_dm  = plus_dm.where(valid_plus_dm, 0.0)
    minus_dm = minus_dm.where(valid_minus_dm, 0.0)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr_w    = tr.ewm(com=window - 1, min_periods=window).mean()
    plus_di  = 100 * plus_dm.ewm(com=window - 1, min_periods=window).mean() / atr_w
    minus_di = 100 * minus_dm.ewm(com=window - 1, min_periods=window).mean() / atr_w

    di_sum  = (plus_di + minus_di).replace(0, float("nan"))
    dx      = 100 * (plus_di - minus_di).abs() / di_sum
    adx     = dx.ewm(com=window - 1, min_periods=window).mean()

    return pd.DataFrame({"adx": adx, "adx_plus_di": plus_di, "adx_minus_di": minus_di})
