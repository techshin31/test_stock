"""최적화 결과 시각화 — Walk-Forward 구간별 성과"""

import numpy as np
import pandas as pd
import vectorbt as vbt
import matplotlib.pyplot as plt
import koreanize_matplotlib


def plot_walkforward_portfolio_comparison(
    wf_info: dict,
    kospi: pd.Series | None = None,
) -> None:
    """Walk-Forward 포트폴리오 자산곡선 + 드로다운 + 구간별 파라미터 테이블

    Parameters
    ----------
    wf_info : walk_forward_portfolio() 반환 dict
    kospi   : KOSPI 벤치마크 시리즈 (optional)
    """
    windows = wf_info.get("windows", [])
    if not windows:
        print("Walk-Forward 윈도우 데이터가 없습니다.")
        return

    fig, axes = plt.subplots(2, 1, figsize=(14, 8),
                             gridspec_kw={"height_ratios": [2, 1.5]})

    # ── 구간별 최적 파라미터 테이블 ────────────────────────────────────────────
    ax0 = axes[0]
    ax0.axis("off")
    col_labels = ["검증 구간", "adx_threshold", "adx_sideways", "학습 score (calmar)"]
    table_data = []
    for w in windows:
        p     = w["best_params"]
        score = w["best_score"]
        score_str = f"{score:.3f}" if isinstance(score, float) and np.isfinite(score) else "N/A"
        table_data.append([
            f"{w['test_start'].strftime('%Y-%m')} ~ {w['test_end'].strftime('%Y-%m')}",
            str(p.get("adx_threshold", "-")),
            str(p.get("adx_sideways", "-")),
            score_str,
        ])
    tbl = ax0.table(cellText=table_data, colLabels=col_labels, loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10)
    tbl.scale(1, 1.6)
    ax0.set_title("구간별 Walk-Forward 최적 파라미터", fontsize=12, pad=10)

    # ── adx_threshold 시계열 바 차트 ───────────────────────────────────────────
    ax1 = axes[1]
    test_starts  = [w["test_start"] for w in windows]
    thresholds   = [w["best_params"].get("adx_threshold", 0) for w in windows]
    sideways_vals = [w["best_params"].get("adx_sideways", 0) for w in windows]
    x = np.arange(len(windows))
    w = 0.35
    ax1.bar(x - w / 2, thresholds,    w, color="#4472C4", alpha=0.8, label="adx_threshold")
    ax1.bar(x + w / 2, sideways_vals, w, color="#ED7D31", alpha=0.8, label="adx_sideways")
    ax1.set_xticks(x)
    ax1.set_xticklabels([d.strftime("%Y-%m") for d in test_starts], rotation=30, ha="right", fontsize=9)
    ax1.set_ylabel("파라미터 값")
    ax1.set_title("검증 구간별 채택된 ADX 파라미터 추이", fontsize=11)
    ax1.legend(fontsize=9)
    ax1.set_ylim(0, 40)
    ax1.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    plt.show()


def plot_walkforward_comparison(
    wf_result: dict,
    pf_single: vbt.Portfolio,
    pf_bh_single: vbt.Portfolio,
) -> None:
    """Walk-Forward vs 고정 파라미터 자산곡선 + 드로다운 비교"""
    equity_wf = wf_result["equity_curve"]

    if len(equity_wf) == 0:
        print("Walk-Forward 검증 구간 데이터가 부족합니다.")
        return

    val_s  = pf_single.value()
    init   = val_s.iloc[0]
    wf_norm = equity_wf / equity_wf.iloc[0] * init
    bh_norm = pf_bh_single.value() / pf_bh_single.value().iloc[0] * init

    fig, axes = plt.subplots(2, 1, figsize=(14, 7), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1]})

    axes[0].plot(bh_norm, color="gray",   lw=1.5, ls="--", label="Buy & Hold")
    axes[0].plot(val_s,   color="blue",   lw=1.5, ls="-",  label="고정 파라미터")
    axes[0].plot(wf_norm, color="crimson", lw=2,  ls="-",  label="Walk-Forward")
    axes[0].set_title("Walk-Forward vs 고정 파라미터 비교")
    axes[0].set_ylabel("자산가치")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    dd_wf    = (wf_norm / wf_norm.cummax()   - 1) * 100
    dd_fixed = (val_s   / val_s.cummax()     - 1) * 100
    axes[1].fill_between(dd_wf.index,    0, dd_wf,    color="crimson", alpha=0.4, label="WF MDD")
    axes[1].fill_between(dd_fixed.index, 0, dd_fixed, color="blue",    alpha=0.2, label="고정 MDD")
    axes[1].axhline(-15, color="red", lw=1, ls="--", label="기준 -15%")
    axes[1].set_ylabel("드로다운 (%)")
    axes[1].legend(fontsize=9)
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()
