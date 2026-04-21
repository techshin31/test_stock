import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

import koreanize_matplotlib
import seaborn as sns

import numpy as np
import pandas as pd 

plt.rcParams['figure.figsize'] = (14, 5)
plt.rcParams['axes.grid'] = True
plt.rcParams['grid.alpha'] = 0.3 

from .analysis import get_corr_with_wics_major

def plot_capitalization_by_month(
    df_cap:pd.DataFrame, wics_major_nm:str) -> None:
    """업종 시가총액 시계열 (월별)"""
    # 월별 리샘플 (평균)
    # -> resample('ME'): 데이터를 월 단위(월말 날짜 기준)로 그룹화
    # -> resample('ME').mean(): 월말 기준 그룹화에 평균(mean) 계산
    df_cap_by_month = df_cap.resample('ME').mean() / 1e6   # 단위: 조원

    fig, ax = plt.subplots(figsize=(14, 5))

    ax.fill_between(df_cap_by_month.index, df_cap_by_month.values, alpha=0.3, color='steelblue')
    ax.plot(df_cap_by_month.index, df_cap_by_month.values, color='steelblue', linewidth=1.5, label=f'{wics_major_nm} 시총 (조원)')
    
    ax.set_title(f'{wics_major_nm} 섹터 시가총액 추이 (월별)', fontsize=14, fontweight='bold')
    ax.set_ylabel('시가총액 (조원)')
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{x:.0f}조'))
    ax.legend()
    plt.tight_layout()
    plt.show()

def plot_capitalization_of_wics_medium_by_date(
    df_cap:pd.DataFrame, date:pd.Timestamp, wics_major_nm:str) -> None:
    """소분류별 시가총액 비중"""
    sub_cap = (
        df_cap[df_cap['DATE'] == date]
        .groupby(['IDX_CD', 'IDX_NM_KOR'])['ALL_MKT_VAL']
        .first()
        .reset_index()
        .sort_values('ALL_MKT_VAL', ascending=False)
    )
    sub_cap['비중(%)'] = sub_cap['ALL_MKT_VAL'] / sub_cap['ALL_MKT_VAL'].sum() * 100

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.barh(sub_cap['IDX_NM_KOR'], sub_cap['비중(%)'])
    for bar, pct in zip(bars, sub_cap['비중(%)']):
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height()/2,
                f'{pct:.1f}%', va='center', fontsize=11)
    ax.set_title(f'{wics_major_nm} 소분류별 시가총액 비중 ({date.date()})', fontsize=14, fontweight='bold')
    ax.set_xlabel('비중 (%)')
    ax.set_xlim(0, sub_cap['비중(%)'].max() * 1.15)
    plt.tight_layout()
    plt.show()

def plot_corr_with_wics_major(
    df_all:pd.DataFrame, 
    wics_major_nm:str) -> None:
    """글로벌 자산 상관계수"""

    # 상관계수 계산 (시총 vs 각 자산)
    corr_with_wics_major = get_corr_with_wics_major(
        df_all, wics_major_nm
    )
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))

    # 막대 그래프
    ax = axes[0]
    colors_c = ['#2ECC71' if v >= 0 else '#E74C3C' for v in corr_with_wics_major.values]
    ax.barh(corr_with_wics_major.index, corr_with_wics_major.values, color=colors_c)
    ax.axvline(0, color='black', linewidth=0.8)
    ax.set_xlabel('상관계수')
    ax.set_title(f'{wics_major_nm} 시총 vs 글로벌 경제지표 상관계수', fontsize=13, fontweight='bold')
    for i, (label, val) in enumerate(corr_with_wics_major.items()):
        ax.text(val + (0.01 if val >= 0 else -0.01), i,
                f'{val:.3f}',
                va='center', ha='left' if val >= 0 else 'right', fontsize=10)
    ax.set_xlim(-1.1, 1.1)

    # 히트맵
    corr_matrix = df_all.corr()

    ax2 = axes[1]
    mask = np.triu(np.ones_like(corr_matrix, dtype=bool))
    sns.heatmap(corr_matrix, annot=True, fmt='.2f', cmap='coolwarm', center=0,
                mask=mask, ax=ax2, linewidths=0.5, annot_kws={'size': 9})
    ax2.set_title('전체 상관관계 히트맵', fontsize=13, fontweight='bold')

    plt.tight_layout()
    plt.show()

def plot_corr_scatter_with_wics_major(
    df_all:pd.DataFrame, 
    wics_major_nm:str, k:int=3) -> None:
    """글로벌 자산 상관계수 산점도"""
    corr_with_wics_major = get_corr_with_wics_major(
        df_all, wics_major_nm
    )
    # 상관계수 상위 지표 3개 산점도
    top_indicators = corr_with_wics_major.abs().nlargest(k).index.tolist()

    fig, axes = plt.subplots(1, k, figsize=(18, 5))
    for ax, col in zip(axes, top_indicators):
        x = df_all[col]
        y = df_all[f'{wics_major_nm}시총'] / 1e6  # 조원
        corr_val = np.corrcoef(x.dropna(), y[x.notna()])[0, 1]
        ax.scatter(x, y, alpha=0.6, color='steelblue', s=60)
        # 추세선
        m, b = np.polyfit(x.dropna(), y[x.notna()], 1)
        ax.plot(sorted(x), [m * xi + b for xi in sorted(x)],
                color='tomato', linewidth=1.5, linestyle='--')
        ax.set_xlabel(col)
        ax.set_ylabel(f'{wics_major_nm} 시총 (조원)')
        ax.set_title(f'{col}\n(r={corr_val:.3f})', fontsize=12, fontweight='bold')

    plt.suptitle(f'{wics_major_nm} 시총 vs 주요 글로벌 지표 산점도', fontsize=14, y=1.02)
    plt.tight_layout()
    plt.show()

def plot_norm_with_wics_major(
    df_all:pd.DataFrame, 
    df_asset:pd.DataFrame, 
    df_cap:pd.DataFrame, 
    top_indicators:list,
    wics_major_nm:str) -> None:
    """상관계수 상위 지표 정규화 시계열"""
    corr_with_wics_major = get_corr_with_wics_major(
        df_all, wics_major_nm
    )

    # 정규화 (첫 관측치 = 100)
    # 시총: 일별 데이터
    # SOX: 영업일별 데이터
    available_cols = [c for c in top_indicators if c in df_asset.columns]

    # 공통 기간
    start = max(df_asset.index[0], df_cap.index[0])
    end   = min(df_asset.index[-1], df_cap.index[-1])

    # 월별 리샘플 후 정규화
    norm_asset = df_asset.loc[start:end, available_cols].copy()
    norm_it    = df_cap.loc[start:end].copy().rename(f'{wics_major_nm}시총')

    combined = pd.concat([norm_it, norm_asset], axis=1).dropna()
    normed = combined / combined.iloc[0] * 100

    fig, ax = plt.subplots(figsize=(14, 6))
    line_styles = ['-', '--', '-.', ':']
    colors_t = ['steelblue', 'tomato', 'seagreen', 'darkorange']
    for i, col in enumerate(normed.columns):
        ax.plot(normed.index, normed[col],
                label=col, linewidth=2,
                linestyle=line_styles[i % len(line_styles)],
                color=colors_t[i % len(colors_t)])

    ax.axhline(100, color='gray', linewidth=0.8, linestyle=':')
    ax.set_title(f'{wics_major_nm} 시총 vs 글로벌 지표 추이 (정규화, 기준=100)', fontsize=14, fontweight='bold')
    ax.set_ylabel('정규화 지수 (기준=100)')
    ax.legend(loc='upper left')
    plt.tight_layout()
    plt.show()
    


