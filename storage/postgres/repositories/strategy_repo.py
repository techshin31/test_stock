from ..connection import PostgreDB


def fetch_active_strategy(db: PostgreDB, name: str) -> dict:
    row = db.fetch_one(
        "SELECT id, name, params FROM strategies WHERE name = %s AND is_active = TRUE",
        (name,),
    )
    if row is None:
        raise ValueError(f"전략 '{name}'을 DB에서 찾을 수 없거나 비활성 상태입니다.")
    return row


def fetch_strategy_params(db: PostgreDB, name: str) -> dict:
    """strategies 테이블에서 전략 파라미터를 조회한다.

    Parameters
    ----------
    db : PostgreDB
        싱글턴 DB 연결 객체.
    name : str
        전략 이름 (예: "risk_neutral", "aggressive").

    Returns
    -------
    dict
        strategies.params JSONB 값. 전략 클래스 __init__에 그대로 전달한다.

    Raises
    ------
    ValueError
        해당 이름의 활성 전략이 없을 때.
    """
    row = db.fetch_one(
        "SELECT params FROM strategies WHERE name = %s AND is_active = TRUE",
        (name,),
    )
    if row is None:
        raise ValueError(f"전략 '{name}'을 DB에서 찾을 수 없거나 비활성 상태입니다.")
    return row["params"]
