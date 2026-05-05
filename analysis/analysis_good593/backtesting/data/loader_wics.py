"""data/wics/ ZIP/CSV 로더 — 종목 가격(종가 역산) 및 섹터 분류"""
import zipfile
import pandas as pd
from pathlib import Path

_WICS_ROOT = Path(__file__).parent.parent.parent / "data" / "wics"

# MKT_VAL(백만원) / APT_SHR_CNT → 종가(원)
_PRICE_SCALE = 1_000_000


def load_wics(years: list[int]) -> pd.DataFrame:
    """연도별 WICS CSV를 병합한 전체 DataFrame 반환.

    컬럼: CMP_CD, CMP_KOR, SEC_CD, SEC_NM_KOR, MKT_VAL,
          APT_SHR_CNT, INFO_TRD_AMT, DATE, close
    """
    dfs = []
    for year in sorted(years):
        zip_path = _WICS_ROOT / f"wics_company_{year}.zip"
        csv_path = _WICS_ROOT / f"wics_company_{year}.csv"

        if zip_path.exists():
            with zipfile.ZipFile(zip_path) as z:
                csv_name = f"wics_company_{year}.csv"
                with z.open(csv_name) as f:
                    df = pd.read_csv(f, encoding="utf-8-sig", low_memory=False)
        elif csv_path.exists():
            df = pd.read_csv(csv_path, encoding="utf-8-sig", low_memory=False)
        else:
            continue

        dfs.append(df)

    if not dfs:
        raise FileNotFoundError(f"WICS 데이터 없음: years={years}")

    df = pd.concat(dfs, ignore_index=True)
    df["DATE"] = pd.to_datetime(df["DATE"].astype(str), format="%Y%m%d")
    df["CMP_CD"] = df["CMP_CD"].astype(str).str.zfill(6)

    # 종가 역산: 시가총액(백만원) * 1,000,000 / 적용주식수
    df["close"] = (df["MKT_VAL"] * _PRICE_SCALE / df["APT_SHR_CNT"]).round(0)

    keep_cols = [
        "DATE", "CMP_CD", "CMP_KOR", "SEC_CD", "SEC_NM_KOR",
        "MKT_VAL", "APT_SHR_CNT", "INFO_TRD_AMT", "close",
    ]
    return df[keep_cols].sort_values("DATE").reset_index(drop=True)


def build_stock_feeds(
    wics_df: pd.DataFrame,
    candidate_stocks: set[str],
) -> dict[str, pd.DataFrame]:
    """Backtrader PandasData 용 {CMP_CD: OHLCV DataFrame} 생성.

    WICS는 Close만 역산 가능하므로 Open=High=Low=Close로 설정.
    """
    feeds = {}
    for cmp_cd in candidate_stocks:
        sub = wics_df[wics_df["CMP_CD"] == cmp_cd].copy()
        if len(sub) < 5:
            continue

        sub = sub.set_index("DATE").sort_index()
        price_df = pd.DataFrame({
            "open":   sub["close"],
            "high":   sub["close"],
            "low":    sub["close"],
            "close":  sub["close"],
            "volume": sub["INFO_TRD_AMT"].fillna(0),
        }, index=sub.index)

        # Backtrader는 NaN/0 종가가 있으면 피드에서 제외
        price_df = price_df[price_df["close"] > 0].dropna(subset=["close"])
        if len(price_df) >= 5:
            feeds[cmp_cd] = price_df

    return feeds


def get_benchmark_returns(wics_df: pd.DataFrame) -> pd.Series:
    """WICS 전 종목 시가총액 가중 일별 수익률 (KOSPI 근사 벤치마크)."""
    daily_cap = wics_df.groupby("DATE")["MKT_VAL"].sum()
    return daily_cap.pct_change().rename("benchmark")
