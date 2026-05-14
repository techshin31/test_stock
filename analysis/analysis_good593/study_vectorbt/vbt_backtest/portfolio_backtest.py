"""멀티종목 포트폴리오 백테스팅 — 데이터 로드 · 신호 생성 · 백테스트 실행"""

import itertools

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
    kospi: pd.Series = None,
    kospi_ma: int = 120,
    atr_multiplier: float = 2.0,
    atr_period: int = 14,
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
            kospi=kospi,
            kospi_ma=kospi_ma,
            atr_multiplier=atr_multiplier,
            atr_period=atr_period,
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


# ── 3. 현금 → 단기채 ETF 비중 추가 ───────────────────────────────────────────

def add_cash_etf(
    size_df: pd.DataFrame,
    close_df: pd.DataFrame,
    high_df: pd.DataFrame,
    low_df: pd.DataFrame,
    cash_etf_close: pd.Series,
    min_weight: float = 0.01,
    etf_name: str = "단기채",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """주식 포지션의 남은 현금을 단기채 ETF 비중으로 채운다.

    Parameters
    ----------
    size_df        : build_size_df() 반환값 (주식 비중 DataFrame)
    close_df       : 주식 종가 DataFrame
    high_df        : 주식 고가 DataFrame
    low_df         : 주식 저가 DataFrame
    cash_etf_close : 단기채 ETF 종가 Series (153130.KS)
    min_weight     : 이 값 미만의 ETF 비중은 NaN으로 처리 (잦은 소액 매매 방지)
    etf_name       : 단기채 컬럼명

    Returns
    -------
    size_df, close_df, high_df, low_df — 모두 단기채 컬럼 추가된 상태
    """
    # 주식 투자 비중 합계 (NaN=유지이므로 0으로 채워서 계산)
    # ffill: NaN(유지) 구간은 마지막으로 설정된 비중으로 채워야
    # "현재 실제 투자 비중"을 올바르게 반영할 수 있다.
    # fillna(0)만 쓰면 NaN을 0%로 오인해 보유 구간마다 주식 강제 매도 발생.
    invested = size_df.ffill().fillna(0).clip(0, 1).sum(axis=1)
    cash_weight = (1 - invested).clip(0, 1)

    # min_weight 미만은 NaN(유지)으로 처리 — 소액 잦은 매매 방지
    etf_size = cash_weight.where(cash_weight >= min_weight, np.nan)

    # 단기채 ETF 가격을 주식 거래일 기준으로 정렬
    etf_close_aligned = cash_etf_close.reindex(close_df.index, method="ffill")

    size_df  = size_df.copy();  size_df[etf_name]  = etf_size
    close_df = close_df.copy(); close_df[etf_name] = etf_close_aligned
    high_df  = high_df.copy();  high_df[etf_name]  = etf_close_aligned
    low_df   = low_df.copy();   low_df[etf_name]   = etf_close_aligned

    return size_df, close_df, high_df, low_df


# ── 4. 백테스트 실행 ──────────────────────────────────────────────────────────

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


def _score_equity(equity: pd.Series, metric: str) -> float:
    """자산곡선에서 스칼라 최적화 지표 계산"""
    if len(equity) < 10:
        return np.nan
    n_years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-6)
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / n_years) - 1
    mdd  = (equity / equity.cummax() - 1).min()
    dr   = equity.pct_change().dropna()
    if metric == "calmar_ratio":
        return cagr / abs(mdd) if mdd < 0 else np.nan
    if metric == "sharpe_ratio":
        return dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 1e-12 else np.nan
    if metric == "total_return":
        return equity.iloc[-1] / equity.iloc[0] - 1
    return np.nan


def walk_forward_portfolio(
    close_df: pd.DataFrame,
    high_df: pd.DataFrame,
    low_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    param_grid: dict,
    train_months: int = 12,
    test_months: int = 6,
    fees: float = 0.0015,
    slippage: float = 0.001,
    metric: str = "calmar_ratio",
    warmup_days: int = 150,
    min_momentum: float = 0.0,
    kospi: pd.Series = None,
    kospi_ma: int = 120,
    atr_multiplier: float = 2.0,
    atr_period: int = 14,
    cash_etf: pd.Series = None,
) -> tuple[vbt.Portfolio, dict]:
    """포트폴리오 Walk-Forward Optimization

    12개월 학습 → 6개월 적용을 슬라이딩하며 ADX 파라미터를 구간마다 재탐색.
    각 검증 구간의 size_df를 이어붙여 단일 vbt.Portfolio로 반환한다.

    Parameters
    ----------
    metric   : 'calmar_ratio' | 'sharpe_ratio' | 'total_return'
    cash_etf : 단기채 ETF 종가 (None이면 현금 ETF 제외)

    Returns
    -------
    pf      : vbt.Portfolio — WF 최적화 파라미터로 구성된 단일 포트폴리오
    wf_info : dict
        'windows'      : 구간별 파라미터 및 score 정보 리스트
        'n_windows'    : 총 윈도우 수
        'close_df_all' : 주식 + 단기채 종가 DataFrame (시각화용)
        'names_all'    : 컬럼 이름 리스트
    """
    idx    = close_df.index
    keys   = list(param_grid.keys())
    combos = list(itertools.product(*param_grid.values()))

    windows      = []
    period_start = idx[0]

    # 검증 구간 size_df를 채울 전체 DataFrame 초기화
    full_size_df = pd.DataFrame(np.nan, index=idx, columns=close_df.columns)

    while True:
        train_end = period_start + pd.DateOffset(months=train_months)
        test_end  = train_end   + pd.DateOffset(months=test_months)

        if test_end > idx[-1] + pd.Timedelta(days=1):
            break

        train_mask = (idx >= period_start) & (idx < train_end)
        test_mask  = (idx >= train_end)    & (idx < test_end)

        if train_mask.sum() < 130 or test_mask.sum() < 5:
            period_start += pd.DateOffset(months=test_months)
            continue

        # ── 1. 학습: 포트폴리오 전체 metric 기준 그리드 서치 ─────────────────
        tr_close = close_df[train_mask]
        tr_high  = high_df[train_mask]
        tr_low   = low_df[train_mask]
        tr_vol   = volume_df[train_mask]

        best_score  = -np.inf
        best_params = None
        scan_rows   = []

        for combo in combos:
            params = dict(zip(keys, combo))
            try:
                sz_df, _ = build_size_df(
                    tr_close, tr_high, tr_low, tr_vol,
                    adx_threshold=params.get("adx_threshold", 25.0),
                    adx_sideways=params.get("adx_sideways", 20.0),
                    min_momentum=min_momentum,
                    kospi=kospi,
                    kospi_ma=kospi_ma,
                    atr_multiplier=atr_multiplier,
                    atr_period=atr_period,
                )
                pf    = run_portfolio_backtest(tr_close, sz_df, fees=fees, slippage=slippage)
                score = _score_equity(pf.value(), metric)
                scan_rows.append({**params, metric: score if np.isfinite(score) else np.nan})
                if np.isfinite(score) and score > best_score:
                    best_score  = score
                    best_params = params
            except Exception:
                continue

        if best_params is None:
            best_params = (
                windows[-1]["best_params"]
                if windows
                else {k: vals[len(vals) // 2] for k, vals in param_grid.items()}
            )

        # ── 2. 검증: warm-up 버퍼로 신호 계산 → 검증 구간만 full_size_df에 기록
        warmup_start = train_end - pd.Timedelta(days=int(warmup_days * 1.5))
        warmup_start = max(warmup_start, idx[0])
        wu_mask = (idx >= warmup_start) & (idx < test_end)

        try:
            sz_wu, _ = build_size_df(
                close_df[wu_mask], high_df[wu_mask], low_df[wu_mask], volume_df[wu_mask],
                adx_threshold=best_params.get("adx_threshold", 25.0),
                adx_sideways=best_params.get("adx_sideways", 20.0),
                min_momentum=min_momentum,
                kospi=kospi,
                kospi_ma=kospi_ma,
                atr_multiplier=atr_multiplier,
                atr_period=atr_period,
            )
            test_dates = close_df[test_mask].index
            full_size_df.loc[test_dates] = sz_wu.reindex(test_dates).values
        except Exception:
            period_start += pd.DateOffset(months=test_months)
            continue

        windows.append({
            "train_start": period_start,
            "train_end":   train_end,
            "test_start":  close_df[test_mask].index[0],
            "test_end":    close_df[test_mask].index[-1],
            "best_params": best_params,
            "best_score":  round(best_score, 4) if np.isfinite(best_score) else np.nan,
            "scan":        pd.DataFrame(scan_rows).sort_values(metric, ascending=False).reset_index(drop=True),
        })

        period_start += pd.DateOffset(months=test_months)

    # ── 검증 구간이 시작되는 날짜부터 포트폴리오 운용 ─────────────────────────
    first_test = windows[0]["test_start"] if windows else idx[0]
    active_idx = idx[idx >= first_test]

    close_used = close_df.loc[active_idx]
    high_used  = high_df.loc[active_idx]
    low_used   = low_df.loc[active_idx]
    size_used  = full_size_df.loc[active_idx]

    # ── 현금 → 단기채 ETF ──────────────────────────────────────────────────────
    if cash_etf is not None:
        size_used, close_all, _, _ = add_cash_etf(
            size_used, close_used, high_used, low_used, cash_etf
        )
    else:
        close_all = close_used

    pf = run_portfolio_backtest(close_all, size_used, fees=fees, slippage=slippage)

    wf_info = {
        "windows":      windows,
        "n_windows":    len(windows),
        "close_df_all": close_all,
        "names_all":    list(close_all.columns),
    }
    return pf, wf_info


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
