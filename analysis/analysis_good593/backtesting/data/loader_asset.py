"""data/asset/ CSV 로더 — 매크로 신호 생성용"""
import pandas as pd
from pathlib import Path

_ASSET_ROOT = Path(__file__).parent.parent.parent / "data" / "asset"

# 티커 → 폴더명 매핑
_FOLDER_MAP = {
    "copper": "구리 (Copper)",
    "gold":   "금 (Gold)",
    "dxy":    "달러 (USD)",
    "sox":    "반도체 가격 (DRAM, NAND)",
    "wti":    "석유 (Crude Oil)",
    "bdry":   "해운 운임 지수 (BDI, SCFI)",
    "cpi":    "현금 (Cash)",
    "tnx":    "현금 (Cash)",
}

_QUARTER_MONTHS = {1: [1,2,3], 2: [4,5,6], 3: [7,8,9], 4: [10,11,12]}


def load_asset(ticker: str, years: list[int]) -> pd.DataFrame:
    """지정 티커의 연도별 CSV를 병합해 Date 인덱스 DataFrame 반환.

    CPI는 발표 주기가 월 1회이므로 일봉으로 forward-fill 처리.
    """
    folder = _ASSET_ROOT / _FOLDER_MAP[ticker]
    dfs = []
    for year in sorted(years):
        path = folder / f"{ticker}_{year}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, parse_dates=["Date"])
        dfs.append(df)

    if not dfs:
        raise FileNotFoundError(f"'{ticker}' 데이터 없음: years={years}")

    result = pd.concat(dfs, ignore_index=True).sort_values("Date").set_index("Date")
    result.index = pd.to_datetime(result.index)

    if ticker == "cpi":
        # 월봉 → 일봉 forward-fill (룩어헤드 방지: shift 1개월)
        result = result.resample("D").ffill()

    return result


def filter_period(
    df: pd.DataFrame,
    year: int | list[int] | None = None,
    quarter: int | None = None,
    month: int | None = None,
) -> pd.DataFrame:
    """Date 인덱스 DataFrame을 연도/분기/월 조건으로 필터링."""
    if year is None:
        return df

    years = [year] if isinstance(year, int) else year
    df = df[df.index.year.isin(years)]

    if quarter is not None:
        df = df[df.index.month.isin(_QUARTER_MONTHS[quarter])]
    elif month is not None:
        df = df[df.index.month == month]

    return df
