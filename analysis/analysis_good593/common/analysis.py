import pandas as pd

def get_capitalization_by_wics_major(
    df_wics:pd.DataFrame, wics_major_nm:str) -> pd.DataFrame:
    # 섹터 전체 시가총액 = IDX_CD별 ALL_MKT_VAL 중복 제거 합산
    # IDX_CD가 G45로 시작하는 최상위 집계는 IDX_CD='G45**' 각 소분류별 합을 사용
    # ALL_MKT_VAL은 해당 IDX_CD 전체 시총 → 날짜별 소분류별 1행만 취해 합산
    return (
        df_wics
        .groupby(['DATE', 'IDX_CD'])['ALL_MKT_VAL']
        .first()           # 날짜 × 소분류 기준 중복 제거
        .groupby('DATE')   # 날짜별 소분류 합산
        .sum()
        .rename(f'{wics_major_nm}_ALL_MKT_VAL')
    )

def get_all_by_month(
    df_cap:pd.DataFrame, df_asset:pd.DataFrame, wics_major_nm:str) -> pd.DataFrame:
    # 월별 데이터와 글로벌 자산 월별 데이터 병합
    # 글로벌 자산: 영업일 기준 → 월 말 리샘플
    # => 가격은 특정 시점의 스냅샷
    # => 평균을 쓰면 월중 변동성이 희석되어 수익률 계산이 왜곡됨
    asset_m = df_asset.resample('ME').last().dropna(how='all')
    # 시총(Market Capitalization): 규모/크기를 나타내는 지표
    # => 월말 하루만 쓰면 결산일, 배당락일 등 이벤트에 의해 시총이 튀는 경우 왜곡 가능
    # => 평균을 쓰면 노이즈가 완화되고 추세가 부드럽게 표현됨
    cap_m = df_cap.resample('ME').mean().rename(f'{wics_major_nm}시총')

    return pd.concat([cap_m, asset_m], axis=1).dropna()

def get_corr_with_wics_major(
    df_all:pd.DataFrame, wics_major_nm:str) -> pd.DataFrame:
    corr_matrix = df_all.corr()

    # 상관계수 계산 (시총 vs 각 자산)
    corr_with_wics_major = corr_matrix[f'{wics_major_nm}시총'].drop(f'{wics_major_nm}시총').sort_values(ascending=False)

    return corr_with_wics_major

