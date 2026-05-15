import pandas as pd


def calc_ma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window).mean()
