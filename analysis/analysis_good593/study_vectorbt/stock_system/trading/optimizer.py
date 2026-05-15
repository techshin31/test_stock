"""Walk-Forward 실행 → best_params.json 저장 (3개월마다 개발 머신에서 실행)

vbt 필요 환경에서만 동작한다.
"""

import json
from pathlib import Path

from ..profiles import get_profile
from ..backtest.portfolio import run_walk_forward
from .data import load_data


def run_optimization(
    profile_name: str = "neutral",
    start: str = "2019-01-01",
    end: str = None,
    output_path: str = "best_params.json",
) -> dict:
    """WF 실행 후 최근 OOS 구간의 최적 파라미터를 저장

    Parameters
    ----------
    profile_name : 'neutral' | 'aggressive'
    start        : 학습 데이터 시작일
    end          : 종료일 (None이면 오늘)
    output_path  : 저장 경로

    Returns
    -------
    dict  best_params (최근 OOS 구간 기준)
    """
    import pandas as pd
    end = end or pd.Timestamp.today().strftime("%Y-%m-%d")

    profile = get_profile(profile_name)
    data    = load_data(start, end)

    pf, wf_info = run_walk_forward(
        profile,
        data["close"], data["high"], data["low"], data["volume"],
        kospi=data["kospi"],
        cash_etf=data["cash_etf"],
    )

    windows = wf_info["windows"]
    if not windows:
        raise RuntimeError("WF 구간이 생성되지 않았습니다. 데이터 기간을 늘려주세요.")

    last = windows[-1]
    best_params = last["best_params"]
    best_params["profile"]      = profile_name
    best_params["use_adx_mode"] = last["use_adx_mode"]

    Path(output_path).write_text(json.dumps(best_params, ensure_ascii=False, indent=2))
    print(f"[optimizer] best_params 저장 완료: {output_path}")
    print(f"  {best_params}")
    return best_params
