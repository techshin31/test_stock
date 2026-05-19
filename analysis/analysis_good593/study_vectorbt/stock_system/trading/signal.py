"""오늘의 매매 신호 생성 — vbt 불필요, 브로커 서버에서 매일 실행

best_params.json → profile.get_signal() → 주문 dict
"""

import json
from pathlib import Path

from ..profiles import get_profile
from .data import load_data


def get_today_signal(
    params_path: str = "best_params.json",
    lookback_days: int = 200,
    rotation_state_path: str = None,
) -> dict:
    """오늘 목표 비중 dict 반환

    Parameters
    ----------
    params_path   : run_optimization()이 저장한 JSON 경로
    lookback_days : MA120 warmup을 위해 최소 150일 이상 필요

    Returns
    -------
    dict  종목명 → 목표 비중 (NaN=유지, 0.0=전량청산, 양수=목표비중)
    """
    import pandas as pd

    params = json.loads(Path(params_path).read_text())
    profile_name = params.get("profile", "neutral")
    use_adx_mode = params.get("use_adx_mode", True)
    profile = get_profile(profile_name)

    end   = pd.Timestamp.today().strftime("%Y-%m-%d")
    start = (pd.Timestamp.today() - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    data   = load_data(start, end)
    signal = profile.get_signal(
        data["close"], data["high"], data["low"],
        kospi=data["kospi"],
        use_adx_mode=use_adx_mode,
    )

    if rotation_state_path and Path(rotation_state_path).exists():
        from ..rotation import RotationManager, apply_rotation_to_signal
        manager = RotationManager.from_json(rotation_state_path)
        signal  = apply_rotation_to_signal(manager, signal, pd.Timestamp.today())

    return signal
