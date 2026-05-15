import pandas as pd


def calc_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    return (close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0)) * volume).cumsum()
