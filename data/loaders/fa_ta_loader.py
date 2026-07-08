import pandas as pd
from datetime import date
from storage.postgres.connection import PostgreDB
from storage.postgres.repositories.company_quarter_fa_repo import fetch_latest_company_fa_as_of

FA_MODEL_VERSION = "topdown-fa-v1.0.0"

def enrich_ohlcv_with_fa(db: PostgreDB, ohlcv_store: dict[str, pd.DataFrame], cutoff_date: date, model_version: str = FA_MODEL_VERSION) -> dict[str, pd.DataFrame]:
    """
    ohlcv_store의 각 종목 OHLCV DataFrame에 company_quarter_fa의 재무 지표를 병합합니다.
    look-ahead bias를 방지하기 위해 available_date를 기준으로 병합(merge_asof)합니다.
    """
    if not ohlcv_store:
        return ohlcv_store
        
    tickers_with_ks = list(ohlcv_store.keys())
    clean_tickers = [t.split('.')[0] for t in tickers_with_ks]
    
    # 1. DB에서 조건에 맞는 FA 데이터 전체 조회
    # fetch_latest_company_fa_as_of()는 최신 1행만 반환하므로, 
    # 여기서는 과거 이력이 모두 필요하기 때문에 직접 쿼리를 수행합니다.
    
    placeholders = ", ".join(["%s"] * len(clean_tickers))
    query = f"""
        SELECT stock_code, available_date,
               fa_score, is_eligible,
               per_proxy, pbr_proxy, roe,
               debt_ratio, operating_income_growth_yoy
        FROM company_quarter_fa
        WHERE model_version = %s
          AND stock_code IN ({placeholders})
          AND available_date <= %s
        ORDER BY stock_code, available_date ASC
    """
    
    params = [model_version] + clean_tickers + [cutoff_date]
    rows = db.fetch_all(query, tuple(params))
    
    if not rows:
        print("[WARN] No FA data found in DB. Returning original ohlcv_store.")
        return ohlcv_store
        
    fa_df_all = pd.DataFrame(rows)
    fa_df_all['available_date'] = pd.to_datetime(fa_df_all['available_date'])
    
    enriched_store = {}
    
    for ticker_with_ks, ohlcv in ohlcv_store.items():
        if ohlcv.empty:
            enriched_store[ticker_with_ks] = ohlcv
            continue
            
        clean_ticker = ticker_with_ks.split('.')[0]
        # 해당 종목의 FA 데이터 필터링
        fa_df = fa_df_all[fa_df_all['stock_code'] == clean_ticker].copy()
        
        if fa_df.empty:
            # FA 데이터가 없는 종목은 원본 유지
            enriched_store[ticker_with_ks] = ohlcv
            continue
            
        # merge_asof를 위해 정렬
        fa_df = fa_df.sort_values('available_date')
        
        # ohlcv 인덱스를 컬럼으로 빼서 날짜로 맞춤
        ohlcv = ohlcv.copy()
        is_datetime_index = isinstance(ohlcv.index, pd.DatetimeIndex)
        
        if is_datetime_index:
            ohlcv_temp = ohlcv.reset_index()
            date_col = 'date' if 'date' in ohlcv_temp.columns else ohlcv.index.name or 'index'
            ohlcv_temp[date_col] = pd.to_datetime(ohlcv_temp[date_col])
        else:
            ohlcv_temp = ohlcv
            date_col = 'date'
        
        ohlcv_temp = ohlcv_temp.sort_values(date_col)
        
        # 미래 참조 방지(look-ahead bias): ohlcv의 date >= FA의 available_date 중 가장 가까운 과거
        merged = pd.merge_asof(
            ohlcv_temp, 
            fa_df, 
            left_on=date_col, 
            right_on='available_date',
            direction='backward'
        )
        
        # 불필요한 컬럼 정리
        merged = merged.drop(columns=['stock_code', 'available_date'], errors='ignore')
        
        if is_datetime_index:
            merged = merged.set_index(date_col)
            
        enriched_store[ticker_with_ks] = merged
        
    return enriched_store
