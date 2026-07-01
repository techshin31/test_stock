import pandas as pd


def calc_bollinger(
    close: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """(upper, mid, lower) 반환"""
    mid   = close.rolling(window).mean()
    std   = close.rolling(window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower
