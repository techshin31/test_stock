"""멀티종목 포트폴리오 백테스팅 — 10번 노트북 핵심 로직 모듈화

데이터 로드 → 신호 생성 → 백테스트 실행 → 성과 분석 → 시각화 순서로 사용한다.

사용 예시
---------
from vbt_backtest.portfolio_backtest import (
    load_portfolio_data, build_size_df, run_portfolio_backtest,
    run_bh_portfolio, run_bh_single,
    build_metrics_table,
    plot_equity_curves, plot_weight_heatmap,
    plot_contribution, plot_diversification, plot_yearly_returns,
)
"""

import numpy as np
import pandas as pd
import vectorbt as vbt
import yfinance as yf
import matplotlib.pyplot as plt
import seaborn as sns

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
    모든 DataFrame 컬럼 순서는 tickers.keys() 순서와 동일
    """
    names = list(tickers.keys())
    codes = list(tickers.values())
    name_map = {v: k for k, v in tickers.items()}

    df_raw = yf.download(codes, start=start, end=end, auto_adjust=True, progress=False)

    close  = df_raw['Close'].rename(columns=name_map)[names].ffill().dropna()
    high   = df_raw['High'].rename(columns=name_map)[names].ffill().dropna()
    low    = df_raw['Low'].rename(columns=name_map)[names].ffill().dropna()
    volume = df_raw['Volume'].rename(columns=name_map)[names].fillna(0)

    return {'close': close, 'high': high, 'low': low, 'volume': volume}


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

    [처리 순서]
    1. 종목별 partial_auto 신호 생성
    2. 국면 정보(detail['masks'])로 종목별 모멘텀 Series 구성
    3. min_momentum 미만 종목 진입 제외
    4. 통과 종목의 모멘텀 합 대비 비율로 가중치 산출
    5. 최종 비중 = 신호 크기 × 모멘텀 가중치 (가변 투자 비중)

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

        entries = detail['entry1'] | detail['entry2'] | detail['entry_range']
        signal_counts[name] = {
            '진입 횟수': int(entries.sum()),
            '1차 익절':  int(detail['transition_from_up'].sum()),
            '2차 청산':  int(detail['dead_cross'].sum()),
        }

        # 국면별 모멘텀 윈도우 선택
        UPTREND    = detail['masks']['UPTREND']
        SIDEWAYS   = detail['masks']['SIDEWAYS']
        TRANSITION = detail['masks']['TRANSITION']

        mom_21  = close_df[name].pct_change(21)    # SIDEWAYS: 1개월
        mom_63  = close_df[name].pct_change(63)    # TRANSITION: 3개월
        mom_126 = close_df[name].pct_change(126)   # UPTREND: 6개월

        mom = pd.Series(np.nan, index=close_df.index)
        mom[UPTREND]    = mom_126[UPTREND]
        mom[SIDEWAYS]   = mom_21[SIDEWAYS]
        mom[TRANSITION] = mom_63[TRANSITION]
        momentum_df[name] = mom

    # 진입 신호 마스크 (양수 = 매수 신호)
    entry_mask = size_raw > 0

    # 유효 진입: 신호 발생 + 모멘텀 min_momentum 이상
    valid_entry = entry_mask & (momentum_df >= min_momentum)

    # 유효 진입 종목의 날짜별 모멘텀 합 → 가중치 산출
    mom_valid  = momentum_df.where(valid_entry)
    mom_sum    = mom_valid.sum(axis=1).replace(0, np.nan)
    mom_weight = mom_valid.div(mom_sum, axis=0)

    # size_df 구성
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
        size_type='targetpercent',
        group_by=True,
        cash_sharing=True,
        fees=fees,
        slippage=slippage,
        freq='D',
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
        size_type='targetpercent',
        group_by=True,
        cash_sharing=True,
        fees=fees,
        slippage=slippage,
        freq='D',
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
        fees=fees, slippage=slippage, freq='D',
    )


# ── 4. 성과 지표 ──────────────────────────────────────────────────────────────

def _calc_metrics(equity: pd.Series, label: str, n_years: float) -> dict:
    total  = equity.iloc[-1] / equity.iloc[0] - 1
    cagr   = (equity.iloc[-1] / equity.iloc[0]) ** (1 / n_years) - 1
    dr     = equity.pct_change().dropna()
    vol    = dr.std() * np.sqrt(252)
    sharpe = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else np.nan
    mdd    = (equity / equity.cummax() - 1).min()
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    return {
        '전략':        label,
        '총 수익률':   f'{total:.2%}',
        'CAGR':       f'{cagr:.2%}',
        '연간 변동성': f'{vol:.2%}',
        '샤프비율':    f'{sharpe:.2f}',
        'MDD':        f'{mdd:.2%}',
        'Calmar':      f'{calmar:.2f}' if not np.isnan(calmar) else 'N/A',
    }


def build_metrics_table(
    pf_09: vbt.Portfolio,
    pf_bh: vbt.Portfolio,
    pf_bh_ss: vbt.Portfolio,
    close_df: pd.DataFrame,
    bh_ss_name: str = '삼성전자',
) -> pd.DataFrame:
    """성과 비교 테이블 생성

    Parameters
    ----------
    pf_09      : 09번 포트폴리오
    pf_bh      : 균등 B&H 포트폴리오
    pf_bh_ss   : 단일 종목 B&H (기준 종목)
    close_df   : 전체 종가 DataFrame (종목별 단독 B&H 계산용)
    bh_ss_name : pf_bh_ss에 해당하는 종목명

    Returns
    -------
    DataFrame (index=전략명)
    """
    n_years = (close_df.index[-1] - close_df.index[0]).days / 365.25
    names = list(close_df.columns)

    val_09 = pf_09.value()
    val_bh = pf_bh.value()
    init   = val_09.iloc[0]

    bh_norm    = val_bh / val_bh.iloc[0] * init
    bh_ss_val  = pf_bh_ss.value()
    bh_ss_norm = bh_ss_val / bh_ss_val.iloc[0] * init

    rows = [
        _calc_metrics(bh_ss_norm, f'{bh_ss_name} 단독 B&H', n_years),
        _calc_metrics(bh_norm,    f'{len(names)}종목 균등 B&H', n_years),
        _calc_metrics(val_09,     '★ 09번 포트폴리오', n_years),
    ]
    for name in names:
        s = close_df[name]
        rows.append(_calc_metrics(s / s.iloc[0] * init, f'  {name} 단독 B&H', n_years))

    return pd.DataFrame(rows).set_index('전략')


# ── 5. 시각화 ─────────────────────────────────────────────────────────────────

def plot_equity_curves(
    pf_09: vbt.Portfolio,
    pf_bh: vbt.Portfolio,
    pf_bh_ss: vbt.Portfolio,
    names: list[str],
    n: int,
) -> None:
    """자산 곡선 · 드로다운 · 보유 종목 수 3단 플롯"""
    val_09    = pf_09.value()
    val_bh    = pf_bh.value()
    bh_ss_val = pf_bh_ss.value()
    init      = val_09.iloc[0]

    bh_norm    = val_bh / val_bh.iloc[0] * init
    bh_ss_norm = bh_ss_val / bh_ss_val.iloc[0] * init

    asset_vals = pf_09.asset_value(group_by=False)
    asset_vals.columns = names

    fig, axes = plt.subplots(3, 1, figsize=(14, 11),
                              gridspec_kw={'height_ratios': [3, 1, 1]}, sharex=True)

    axes[0].plot(bh_ss_norm, color='gray',    lw=1.5, ls=':',  label=f'{names[0]} 단독 B&H')
    axes[0].plot(bh_norm,    color='orange',  lw=2.0, ls='--', label=f'{n}종목 균등 B&H')
    axes[0].plot(val_09,     color='crimson', lw=2.5, ls='-',  label='★ 09번 포트폴리오')
    axes[0].set_title('자산 곡선 비교', fontsize=13)
    axes[0].set_ylabel('포트폴리오 가치 (정규화)')
    axes[0].legend(fontsize=10)
    axes[0].grid(True, alpha=0.3)

    dd09  = (val_09  / val_09.cummax()  - 1) * 100
    dd_bh = (bh_norm / bh_norm.cummax() - 1) * 100
    axes[1].fill_between(dd09.index,  0, dd09,  color='crimson', alpha=0.4, label='09번 포트폴리오 MDD')
    axes[1].fill_between(dd_bh.index, 0, dd_bh, color='orange',  alpha=0.3, label=f'{n}종목 B&H MDD')
    axes[1].set_ylabel('드로다운 (%)')
    axes[1].set_ylim(min(dd09.min(), dd_bh.min()) * 1.15, 5)
    axes[1].legend(fontsize=9)
    axes[1].grid(True, alpha=0.3)

    n_held = (asset_vals > 0.5).sum(axis=1)
    axes[2].fill_between(n_held.index, 0, n_held, color='steelblue', alpha=0.5)
    axes[2].set_ylabel('보유 종목 수')
    axes[2].set_ylim(0, n + 0.5)
    axes[2].set_yticks(range(n + 1))
    axes[2].axhline(n, color='gray', lw=1, ls='--', alpha=0.5)
    axes[2].grid(True, alpha=0.3)

    plt.suptitle('09번 포트폴리오 vs Buy & Hold 비교', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.show()


def plot_weight_heatmap(
    pf_09: vbt.Portfolio,
    names: list[str],
) -> None:
    """월별 종목 보유 비중 히트맵"""
    val_09     = pf_09.value()
    asset_vals = pf_09.asset_value(group_by=False)
    asset_vals.columns = names

    weights   = asset_vals.div(val_09, axis=0).clip(0, 1) * 100
    weights_m = weights.resample('M').mean()

    fig, ax = plt.subplots(figsize=(16, 4))
    sns.heatmap(
        weights_m.T,
        ax=ax,
        cmap='RdYlGn',
        vmin=0, vmax=20,
        linewidths=0.3,
        cbar_kws={'label': '보유 비중 (%)', 'shrink': 0.8},
        xticklabels=[d.strftime('%y.%m') for d in weights_m.index],
    )
    ax.set_title('월별 종목 보유 비중 히트맵 (빨강=0%, 초록=20%)', fontsize=12)
    ax.set_xlabel('날짜')
    ax.set_ylabel('')
    plt.xticks(rotation=45, ha='right', fontsize=8)
    plt.tight_layout()
    plt.show()

    print('\n=== 종목별 평균 포지션 비중 ===')
    avg_w = weights.mean()
    for name in names:
        print(f'  {name:10s}: {avg_w[name]:.1f}%  (최대 {weights[name].max():.1f}%)')


def plot_contribution(
    pf_09: vbt.Portfolio,
    close_df: pd.DataFrame,
    names: list[str],
    colors_line: list[str] | None = None,
) -> None:
    """종목별 포트폴리오 수익 기여도 분석 (바차트 + 누적 시계열)"""
    if colors_line is None:
        colors_line = ['#e41a1c', '#377eb8', '#4daf4a', '#984ea3', '#ff7f00']

    val_09     = pf_09.value()
    asset_vals = pf_09.asset_value(group_by=False)
    asset_vals.columns = names

    stock_rets    = close_df.pct_change().fillna(0)
    pos_w         = asset_vals.div(val_09, axis=0).fillna(0).clip(0, 1)
    daily_contrib = pos_w.shift(1).fillna(0) * stock_rets
    total_contrib = daily_contrib.sum() * 100
    cum_contrib   = daily_contrib.cumsum() * 100

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    colors_c = ['#2166ac' if v >= 0 else '#b2182b' for v in total_contrib]
    bars = axes[0].barh(names, total_contrib, color=colors_c,
                        edgecolor='black', linewidth=0.6, alpha=0.88)
    axes[0].axvline(0, color='black', linewidth=0.9)
    axes[0].set_xlabel('포트폴리오 수익률 기여도 (%p)')
    axes[0].set_title('종목별 포트폴리오 수익 기여도', fontsize=12)
    axes[0].grid(True, alpha=0.3, axis='x')
    for bar, val in zip(bars, total_contrib):
        xpos = val + 0.15 if val >= 0 else val - 0.15
        ha   = 'left' if val >= 0 else 'right'
        axes[0].text(xpos, bar.get_y() + bar.get_height() / 2,
                     f'{val:+.1f}%p', va='center', ha=ha, fontsize=9, fontweight='bold')

    for name, color in zip(names, colors_line):
        axes[1].plot(cum_contrib[name], lw=1.8, color=color, label=name)
    axes[1].axhline(0, color='black', lw=0.8, ls='--', alpha=0.5)
    axes[1].set_title('종목별 누적 기여도 추이', fontsize=12)
    axes[1].set_ylabel('누적 기여도 (%p)')
    axes[1].legend(fontsize=9)
    axes[1].grid(True, alpha=0.3)

    plt.suptitle('종목별 기여도 분석', fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.show()

    print('\n=== 종목별 기여도 순위 ===')
    for name in total_contrib.sort_values(ascending=False).index:
        print(f'  {name:10s}: {total_contrib[name]:+.2f}%p')


def plot_diversification(
    pf_09: vbt.Portfolio,
    pf_bh: vbt.Portfolio,
    close_df: pd.DataFrame,
    names: list[str],
) -> None:
    """분산투자 효과: 상관관계 히트맵 + 변동성 비교 바차트"""
    val_09 = pf_09.value()
    val_bh = pf_bh.value()
    init   = val_09.iloc[0]
    bh_norm = val_bh / val_bh.iloc[0] * init

    returns_df = close_df.pct_change().dropna()
    corr_mat   = returns_df.corr()
    vols       = returns_df.std() * np.sqrt(252) * 100

    pf_vol  = returns_df.mean(axis=1).std() * np.sqrt(252) * 100
    pf09_vol = val_09.pct_change().dropna().std() * np.sqrt(252) * 100

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    sns.heatmap(
        corr_mat,
        ax=axes[0],
        annot=True, fmt='.2f', cmap='coolwarm',
        vmin=-1, vmax=1, linewidths=0.5,
        cbar_kws={'shrink': 0.8},
    )
    axes[0].set_title(f'{len(names)}종목 수익률 상관관계', fontsize=12)

    n = len(names)
    vol_data   = list(vols[names]) + [pf_vol, pf09_vol]
    vol_labels = names + ['균등B&H\n포트폴리오', '09번\n포트폴리오']
    colors_vol = ['#aec7e8'] * n + ['orange', 'crimson']

    bars = axes[1].bar(range(len(vol_data)), vol_data, color=colors_vol,
                       edgecolor='black', linewidth=0.6, alpha=0.9)
    axes[1].set_xticks(range(len(vol_data)))
    axes[1].set_xticklabels(vol_labels, fontsize=9)
    axes[1].set_ylabel('연간 변동성 (%)')
    axes[1].set_title('변동성 비교: 개별 종목 vs 포트폴리오', fontsize=12)
    axes[1].grid(True, alpha=0.3, axis='y')
    for bar, val in zip(bars, vol_data):
        axes[1].text(bar.get_x() + bar.get_width() / 2, val + 0.3,
                     f'{val:.1f}%', ha='center', va='bottom', fontsize=8.5, fontweight='bold')

    plt.suptitle('분산투자 효과 분석', fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.show()

    print('\n=== 분산투자 효과 ===')
    avg_stock_vol = vols.mean()
    print(f'개별 종목 평균 변동성: {avg_stock_vol:.1f}%')
    print(f'균등 B&H 포트폴리오:  {pf_vol:.1f}%  (개별 대비 {pf_vol/avg_stock_vol:.0%})')
    print(f'09번 포트폴리오:       {pf09_vol:.1f}%  (개별 대비 {pf09_vol/avg_stock_vol:.0%})')


def _yearly_returns(equity: pd.Series) -> pd.Series:
    return equity.resample('A').last().pct_change().dropna()


def plot_yearly_returns(
    pf_09: vbt.Portfolio,
    pf_bh: vbt.Portfolio,
    pf_bh_ss: vbt.Portfolio,
    bh_ss_name: str = '삼성전자',
    n: int = 5,
) -> None:
    """연도별 성과 비교 바차트"""
    val_09    = pf_09.value()
    val_bh    = pf_bh.value()
    bh_ss_val = pf_bh_ss.value()
    init      = val_09.iloc[0]

    bh_norm    = val_bh / val_bh.iloc[0] * init
    bh_ss_norm = bh_ss_val / bh_ss_val.iloc[0] * init

    yr_09 = _yearly_returns(val_09)
    yr_bh = _yearly_returns(bh_norm)
    yr_ss = _yearly_returns(bh_ss_norm)

    years = [str(y.year) for y in yr_09.index]
    x = np.arange(len(years))
    w = 0.28

    fig, ax = plt.subplots(figsize=(13, 5))

    C_SS = ['#4292c6' if v >= 0 else '#9ecae1' for v in yr_ss]
    C_BH = ['#fd8d3c' if v >= 0 else '#fdbe85' for v in yr_bh]
    C_09 = ['#b2182b' if v >= 0 else '#fca69a' for v in yr_09]

    b1 = ax.bar(x - w, yr_ss * 100, w, color=C_SS, edgecolor='#333', lw=0.6, label=f'{bh_ss_name} 단독 B&H')
    b2 = ax.bar(x,     yr_bh * 100, w, color=C_BH, edgecolor='#333', lw=0.6, label=f'{n}종목 균등 B&H')
    b3 = ax.bar(x + w, yr_09 * 100, w, color=C_09, edgecolor='#333', lw=0.6, label='★ 09번 포트폴리오')

    ax.axhline(0, color='black', lw=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels(years, fontsize=10)
    ax.set_ylabel('연간 수익률 (%)')
    ax.set_title('연도별 성과 비교', fontsize=13)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3, axis='y')

    for bars, vals in [(b1, yr_ss), (b2, yr_bh), (b3, yr_09)]:
        for bar, val in zip(bars, vals):
            v  = val * 100
            yp = v + 0.5 if v >= 0 else v - 1.2
            ax.text(bar.get_x() + bar.get_width() / 2, yp,
                    f'{v:.0f}%', ha='center',
                    va='bottom' if v >= 0 else 'top',
                    fontsize=7, fontweight='bold')

    plt.tight_layout()
    plt.show()
