"""vbt.Portfolio → 공통 metrics/plots용 pandas 데이터 추출

사용 예시 (노트북):
    from stock_system.backtest.adapter import extract

    pf, wf_info = run_walk_forward(...)
    pf_bh       = run_bh_portfolio(...)

    d    = extract(pf)
    d_bh = extract(pf_bh)

    calc_metrics(d["equity"], benchmark_series=kospi)
    plot_equity_curves(d["equity"], d["asset_values"], names, n, equity_bh=d_bh["equity"])
"""


def extract(pf) -> dict:
    """vbt.Portfolio에서 공통 pandas 데이터 추출

    Returns
    -------
    dict:
        equity       : pd.Series    — 포트폴리오 가치 곡선
        asset_values : pd.DataFrame — 종목별 자산 가치
    """
    return {
        "equity":       pf.value(),
        "asset_values": pf.asset_value(group_by=False),
    }
