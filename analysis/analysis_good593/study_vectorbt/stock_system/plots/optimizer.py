"""최적화 시각화 — Walk-Forward 포트폴리오 비교"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import koreanize_matplotlib


def plot_walkforward_portfolio_comparison(
    equity: pd.Series,
    equity_bh: pd.Series,
    wf_info: dict,
    benchmark_series: pd.Series = None,
    profile_name: str = "위험중립형",
) -> None:
    """WF 구간별 파라미터 + 전체 자산곡선 비교

    Parameters
    ----------
    equity    : 전략 포트폴리오 가치 곡선
    equity_bh : B&H 포트폴리오 가치 곡선
    """
    val     = equity
    init    = val.iloc[0]
    bh_norm = equity_bh.reindex(val.index, method="ffill")
    bh_norm = bh_norm / bh_norm.iloc[0] * init

    if benchmark_series is not None:
        bm = benchmark_series.reindex(val.index, method="ffill").dropna()
        bm_norm  = bm / bm.iloc[0] * init
        bm_label = benchmark_series.name or "벤치마크"
    else:
        bm_norm  = bh_norm
        bm_label = "균등 B&H"

    windows = wf_info.get("windows", [])

    fig, axes = plt.subplots(2, 1, figsize=(14, 9),
                              gridspec_kw={"height_ratios": [2, 1]}, sharex=True)

    axes[0].plot(bm_norm, color="gray",    lw=1.5, ls=":", label=bm_label)
    axes[0].plot(bh_norm, color="orange",  lw=2.0, ls="--", label="균등 B&H")
    axes[0].plot(val,     color="crimson", lw=2.5, label=f"★ {profile_name} WF")

    for w in windows:
        axes[0].axvline(w["test_start"], color="steelblue", lw=0.8, ls="--", alpha=0.5)

    axes[0].set_title(f"{profile_name} Walk-Forward 자산곡선", fontsize=13)
    axes[0].set_ylabel("포트폴리오 가치")
    axes[0].legend(fontsize=10)
    axes[0].grid(True, alpha=0.3)

    # 구간별 최적 파라미터 표시
    if windows:
        xs = [w["test_start"] for w in windows]
        thresholds = [w["best_params"].get("adx_threshold", np.nan) for w in windows]
        sideways   = [w["best_params"].get("adx_sideways",  np.nan) for w in windows]

        axes[1].step(xs, thresholds, where="post", color="steelblue", lw=2, label="adx_threshold")
        axes[1].step(xs, sideways,   where="post", color="darkorange", lw=2, label="adx_sideways")
        axes[1].set_ylabel("파라미터 값")
        axes[1].set_title("WF 구간별 최적 ADX 파라미터", fontsize=11)
        axes[1].legend(fontsize=9)
        axes[1].grid(True, alpha=0.3)

    plt.suptitle(f"Walk-Forward 최적화 결과 — {profile_name}", fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.show()

    if windows:
        print(f"\n{'구간':>4}  {'IS 시작':>12}  {'OOS 시작':>12}  {'adx_thr':>8}  {'adx_sw':>7}  {'IS score':>9}")
        print("-" * 62)
        for i, w in enumerate(windows, 1):
            p  = w["best_params"]
            sc = w["best_score"]
            sc_str = f"{sc:.3f}" if not np.isnan(sc) else "N/A"
            print(f"  {i:2d}  {str(w['train_start'].date()):>12}  "
                  f"{str(w['test_start'].date()):>12}  "
                  f"{p.get('adx_threshold', '?'):>8}  "
                  f"{p.get('adx_sideways',  '?'):>7}  "
                  f"{sc_str:>9}")
