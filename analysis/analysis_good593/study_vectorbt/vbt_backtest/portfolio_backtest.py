"""멀티종목 포트폴리오 백테스팅 — 데이터 로드 · 신호 생성 · 백테스트 실행

사용 예시
---------
from vbt_backtest.portfolio_backtest import (
    load_portfolio_data, build_size_df,
    run_portfolio_backtest, run_bh_portfolio, run_bh_single,
)
from vbt_backtest.metrics import build_metrics_table
from vbt_backtest.plots.performance import (
    plot_equity_curves, plot_weight_heatmap,
    plot_contribution, plot_diversification, plot_yearly_returns,
)
"""

import numpy as np
import pandas as pd
import vectorbt as vbt
import yfinance as yf

from .strategies.combined import partial_auto_strategy


# ── 1. 데이터 로드 ────────────────────────────────────────────────────────────

def load_portfolio_data(
    tickers: dict[str, str],
    start: str,
    end: str,
) -> dict[str, pd.DataFrame]:
    """yfinance에서 멀티 종목 OHLCV 로드 및 결측값 처리

    Parameters
    ----------
    tickers : 종목명 → 티커 코드  예) {'삼성전자': '005930.KS', ...}
    start   : 시작일 'YYYY-MM-DD'
    end     : 종료일 'YYYY-MM-DD'

    Returns
    -------
    {'close': DataFrame, 'high': DataFrame, 'low': DataFrame, 'volume': DataFrame}
    """
    names = list(tickers.keys())
    codes = list(tickers.values())
    name_map = {v: k for k, v in tickers.items()}

    df_raw = yf.download(codes, start=start, end=end, auto_adjust=True, progress=False)

    close  = df_raw["Close"].rename(columns=name_map)[names].ffill().dropna()
    high   = df_raw["High"].rename(columns=name_map)[names].ffill().dropna()
    low    = df_raw["Low"].rename(columns=name_map)[names].ffill().dropna()
    volume = df_raw["Volume"].rename(columns=name_map)[names].fillna(0)

    return {"close": close, "high": high, "low": low, "volume": volume}


# ── 2. 신호 생성 ──────────────────────────────────────────────────────────────

def build_size_df(
    close_df: pd.DataFrame,
    high_df: pd.DataFrame,
    low_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    adx_threshold: float = 25.0,
    adx_sideways: float = 20.0,
    min_momentum: float = 0.0,
) -> tuple[pd.DataFrame, dict]:
    """종목별 partial_auto 신호 생성 → 국면별 모멘텀 비례 가중치 포트폴리오 DataFrame 구성

    [국면별 모멘텀 윈도우]
    UPTREND    → 126일(6개월): 추세가 길게 이어지므로 장기 모멘텀 신뢰도 높음
    TRANSITION →  63일(3개월): 방향 불확실, 중기 모멘텀으로 중간값 사용
    SIDEWAYS   →  21일(1개월): 단기 등락 반복, 빠른 반응 필요
    DOWNTREND  → 진입 안 함 (어차피 size=0 청산 국면)

    Returns
    -------
    size_df     : 비중 DataFrame (index=날짜, columns=종목명)
    signal_info : 종목별 신호 횟수 dict
    """
    names = list(close_df.columns)

    size_raw    = pd.DataFrame(np.nan, index=close_df.index, columns=names)
    momentum_df = pd.DataFrame(np.nan, index=close_df.index, columns=names)
    signal_counts = {}

    for name in names:
        _, _, size_s, detail = partial_auto_strategy.make_signals(
            close_df[name], high_df[name], low_df[name], volume_df[name],
            adx_threshold=adx_threshold,
            adx_sideways=adx_sideways,
        )
        size_raw[name] = size_s

        entries = detail["entry1"] | detail["entry2"] | detail["entry_range"]
        signal_counts[name] = {
            "진입 횟수": int(entries.sum()),
            "1차 익절":  int(detail["transition_from_up"].sum()),
            "2차 청산":  int(detail["dead_cross"].sum()),
        }

        UPTREND    = detail["masks"]["UPTREND"]
        SIDEWAYS   = detail["masks"]["SIDEWAYS"]
        TRANSITION = detail["masks"]["TRANSITION"]

        mom_21  = close_df[name].pct_change(21)
        mom_63  = close_df[name].pct_change(63)
        mom_126 = close_df[name].pct_change(126)

        mom = pd.Series(np.nan, index=close_df.index)
        mom[UPTREND]    = mom_126[UPTREND]
        mom[SIDEWAYS]   = mom_21[SIDEWAYS]
        mom[TRANSITION] = mom_63[TRANSITION]
        momentum_df[name] = mom

    entry_mask  = size_raw > 0
    valid_entry = entry_mask & (momentum_df >= min_momentum)

    mom_valid  = momentum_df.where(valid_entry)
    mom_sum    = mom_valid.sum(axis=1).replace(0, np.nan)
    mom_weight = mom_valid.div(mom_sum, axis=0)

    size_df = size_raw.copy()
    size_df[entry_mask & ~valid_entry] = np.nan
    size_df[valid_entry] = (size_raw * mom_weight)[valid_entry]

    return size_df, signal_counts


# ── 3. 백테스트 실행 ──────────────────────────────────────────────────────────

def run_portfolio_backtest(
    close_df: pd.DataFrame,
    size_df: pd.DataFrame,
    fees: float = 0.0015,
    slippage: float = 0.001,
) -> vbt.Portfolio:
    """09번 전략 포트폴리오 실행 (group_by + cash_sharing)"""
    return vbt.Portfolio.from_orders(
        close_df,
        size=size_df,
        size_type="targetpercent",
        group_by=True,
        cash_sharing=True,
        fees=fees,
        slippage=slippage,
        freq="D",
    )


def run_bh_portfolio(
    close_df: pd.DataFrame,
    fees: float = 0.0015,
    slippage: float = 0.001,
) -> vbt.Portfolio:
    """균등 비중 Buy & Hold 포트폴리오 (첫날 1/N씩 매수)"""
    n = close_df.shape[1]
    bh_size_df = pd.DataFrame(np.nan, index=close_df.index, columns=close_df.columns)
    bh_size_df.iloc[0] = 1.0 / n
    return vbt.Portfolio.from_orders(
        close_df,
        size=bh_size_df,
        size_type="targetpercent",
        group_by=True,
        cash_sharing=True,
        fees=fees,
        slippage=slippage,
        freq="D",
    )


def run_bh_single(
    close: pd.Series,
    fees: float = 0.0015,
    slippage: float = 0.001,
) -> vbt.Portfolio:
    """단일 종목 Buy & Hold (첫날 매수 → 마지막 날 청산)"""
    entries = pd.Series(False, index=close.index); entries.iloc[0] = True
    exits   = pd.Series(False, index=close.index); exits.iloc[-1] = True
    return vbt.Portfolio.from_signals(
        close, entries, exits,
        fees=fees, slippage=slippage, freq="D",
    )
