from datetime import date

import pandas as pd

from storage.postgres.connection import PostgreDB


FA_MODEL_VERSION = "topdown-fa-v1.0.0"
DEFAULT_MAX_FA_AGE_DAYS = 180
DEFAULT_MIN_SCORE_CONFIDENCE = 0.50


def enrich_ohlcv_with_fa(
    db: PostgreDB,
    ohlcv_store: dict[str, pd.DataFrame],
    cutoff_date: date | str,
    model_version: str = FA_MODEL_VERSION,
    *,
    max_age_days: int = DEFAULT_MAX_FA_AGE_DAYS,
    min_score_confidence: float = DEFAULT_MIN_SCORE_CONFIDENCE,
) -> dict[str, pd.DataFrame]:
    """OHLCV에 시점 안전하고 결정적인 분기 FA 스냅샷을 병합한다.

    동일 종목·동일 공개일에 정정/복수 보고서가 있으면 최신 결산기간,
    접수번호, 원장 id 순으로 한 행만 선택한다. 각 거래일 기준으로 너무 오래된
    점수나 신뢰도가 낮은 점수는 ``is_eligible=False``로 강제한다.
    """
    if not ohlcv_store:
        return ohlcv_store
    if max_age_days < 1:
        raise ValueError("max_age_days must be positive")
    if not 0 <= min_score_confidence <= 1:
        raise ValueError("min_score_confidence must be between 0 and 1")

    clean_tickers = [ticker.split(".", 1)[0] for ticker in ohlcv_store]
    placeholders = ", ".join(["%s"] * len(clean_tickers))
    rows = db.fetch_all(
        f"""
        SELECT stock_code, available_date, period_end, source_rcept_no,
               fa_score, is_eligible, score_confidence, score_model_code,
               per_proxy, pbr_proxy, roe, debt_ratio,
               operating_income_growth_yoy
        FROM (
            SELECT DISTINCT ON (stock_code, available_date) *
            FROM company_quarter_fa
            WHERE model_version = %s
              AND stock_code IN ({placeholders})
              AND available_date <= %s::date
            ORDER BY stock_code, available_date,
                     period_end DESC, source_rcept_no DESC, id DESC
        ) snapshot
        ORDER BY stock_code, available_date
        """,
        tuple([model_version, *clean_tickers, str(cutoff_date)]),
    )

    if not rows:
        return ohlcv_store

    fa_all = pd.DataFrame(rows)
    fa_all["available_date"] = pd.to_datetime(fa_all["available_date"])
    enriched_store: dict[str, pd.DataFrame] = {}

    for ticker, original in ohlcv_store.items():
        if original.empty:
            enriched_store[ticker] = original
            continue
        symbol = ticker.split(".", 1)[0]
        fa = fa_all[fa_all["stock_code"] == symbol].copy()
        if fa.empty:
            enriched_store[ticker] = original
            continue

        ohlcv = original.copy()
        had_datetime_index = isinstance(ohlcv.index, pd.DatetimeIndex)
        if had_datetime_index:
            temp = ohlcv.reset_index()
            date_col = "date" if "date" in temp.columns else ohlcv.index.name or "index"
        else:
            temp = ohlcv.copy()
            date_col = "date"
        temp[date_col] = pd.to_datetime(temp[date_col])
        temp = temp.sort_values(date_col)
        fa = fa.sort_values(["available_date", "period_end", "source_rcept_no"])

        merged = pd.merge_asof(
            temp,
            fa,
            left_on=date_col,
            right_on="available_date",
            direction="backward",
            allow_exact_matches=True,
        )
        merged["fa_available_date"] = merged["available_date"]
        merged["fa_age_days"] = (
            merged[date_col].dt.normalize() - merged["available_date"].dt.normalize()
        ).dt.days
        merged["fa_is_stale"] = merged["fa_age_days"].gt(max_age_days).fillna(True)
        merged["fa_low_confidence"] = (
            merged["score_confidence"].lt(min_score_confidence).fillna(True)
        )
        eligible = merged["is_eligible"].fillna(False).astype(bool)
        supported = merged["score_model_code"].fillna("UNSUPPORTED").ne("UNSUPPORTED")
        merged["is_eligible"] = (
            eligible & supported & ~merged["fa_is_stale"] & ~merged["fa_low_confidence"]
        )
        merged = merged.drop(
            columns=["stock_code", "available_date", "period_end", "source_rcept_no"],
            errors="ignore",
        )
        if had_datetime_index:
            merged = merged.set_index(date_col)
        enriched_store[ticker] = merged

    return enriched_store
