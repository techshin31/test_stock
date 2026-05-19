"""공통 포트폴리오 전략 — backtest·trading 공유

공개 API:
  build_size_df(profile, close_df, ...)   신호 생성 + 모멘텀 비례 가중치
  add_cash_etf(size_df, ...)              현금 → 단기채 ETF
"""

import numpy as np
import pandas as pd


def build_size_df(
    profile,
    close_df: pd.DataFrame,
    high_df: pd.DataFrame,
    low_df: pd.DataFrame,
    per_stock_params: dict = None,
    adx_threshold: float = 25.0,
    adx_sideways: float = 20.0,
    min_momentum: float = 0.0,
    kospi: pd.Series = None,
    use_adx_mode: bool = True,
) -> tuple:
    """종목별 신호 생성 → 국면별 모멘텀 비례 가중치 DataFrame 구성

    per_stock_params가 주어지면 종목별 best_params·use_adx_mode를 사용하고,
    없으면 adx_threshold·adx_sideways·use_adx_mode 공통값을 fallback으로 사용한다.

    Returns
    -------
    size_df      : 비중 DataFrame
    signal_info  : 종목별 신호 횟수 dict
    """
    names       = list(close_df.columns)
    mom_windows = profile.MOMENTUM_WINDOW

    size_raw    = pd.DataFrame(np.nan, index=close_df.index, columns=names)
    momentum_df = pd.DataFrame(np.nan, index=close_df.index, columns=names)
    signal_info = {}

    for name in names:
        if per_stock_params and name in per_stock_params:
            sp   = per_stock_params[name]
            thr  = sp["best_params"].get("adx_threshold", adx_threshold)
            sid  = sp["best_params"].get("adx_sideways", adx_sideways)
            mode = sp["use_adx_mode"]
        else:
            thr  = adx_threshold
            sid  = adx_sideways
            mode = use_adx_mode

        _, _, size_s, detail = profile.make_signals(
            close_df[name], high_df[name], low_df[name],
            adx_threshold=thr,
            adx_sideways=sid,
            kospi=kospi,
            use_adx_mode=mode,
        )
        size_raw[name] = size_s

        entries = detail["entry1"] | detail["entry2"] | detail["entry_range"]
        signal_info[name] = {
            "진입 횟수": int(entries.sum()),
            "1차 익절":  int(detail["transition_from_up"].sum()),
            "2차 청산":  int(detail["dead_cross"].sum()),
        }

        UPTREND    = detail["masks"]["UPTREND"]
        SIDEWAYS   = detail["masks"]["SIDEWAYS"]
        TRANSITION = detail["masks"]["TRANSITION"]

        mom_up  = close_df[name].pct_change(mom_windows["UPTREND"])
        mom_sid = close_df[name].pct_change(mom_windows["SIDEWAYS"])
        mom_tr  = close_df[name].pct_change(mom_windows["TRANSITION"])

        mom = pd.Series(np.nan, index=close_df.index)
        mom[UPTREND]    = mom_up[UPTREND]
        mom[SIDEWAYS]   = mom_sid[SIDEWAYS]
        mom[TRANSITION] = mom_tr[TRANSITION]
        momentum_df[name] = mom

    entry_mask  = size_raw > 0
    valid_entry = entry_mask & (momentum_df >= min_momentum)

    desired       = size_raw.where(valid_entry, 0)
    total_desired = desired.sum(axis=1)

    combined     = (size_raw * momentum_df).where(valid_entry)
    combined_sum = combined.sum(axis=1).replace(0, np.nan)
    weight       = combined.div(combined_sum, axis=0)

    size_df = size_raw.copy()
    size_df[entry_mask & ~valid_entry] = np.nan

    sufficient   = (total_desired > 0) & (total_desired <= 1.0)
    insufficient = total_desired > 1.0

    size_df[valid_entry & sufficient.values[:, None]]   = size_raw[valid_entry & sufficient.values[:, None]]
    size_df[valid_entry & insufficient.values[:, None]] = weight[valid_entry & insufficient.values[:, None]]

    return size_df, signal_info


def add_cash_etf(
    size_df: pd.DataFrame,
    close_df: pd.DataFrame,
    high_df: pd.DataFrame,
    low_df: pd.DataFrame,
    cash_etf_close: pd.Series,
    min_weight: float = 0.01,
    etf_name: str = "단기채",
) -> tuple:
    """주식 포지션의 남은 현금을 단기채 ETF 비중으로 채운다.

    Returns
    -------
    size_df, close_df, high_df, low_df — 단기채 컬럼 추가 버전
    """
    invested    = size_df.ffill().fillna(0).clip(0, 1).sum(axis=1)
    cash_weight = (1 - invested).clip(0, 1)
    etf_size    = cash_weight.where(cash_weight >= min_weight, np.nan)

    etf_close_aligned = cash_etf_close.reindex(close_df.index, method="ffill")

    size_df  = size_df.copy();  size_df[etf_name]  = etf_size
    close_df = close_df.copy(); close_df[etf_name] = etf_close_aligned
    high_df  = high_df.copy();  high_df[etf_name]  = etf_close_aligned
    low_df   = low_df.copy();   low_df[etf_name]   = etf_close_aligned

    return size_df, close_df, high_df, low_df
