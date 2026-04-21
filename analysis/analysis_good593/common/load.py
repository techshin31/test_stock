import os
import zipfile
import pandas as pd
from glob import glob

def load_asset_data(data_path:str) -> pd.DataFrame:
    """글로벌 자산 데이터 로딩"""
    df = pd.read_csv(data_path, encoding='utf-8-sig', index_col='Date', parse_dates=True)
    df = df.sort_index()
    return df

def __load_wics_by_year(file_path):
    """연도별 WICS 데이터 로딩 (zip 또는 csv 자동 처리)"""

    if file_path.endswith('.zip'):
        with zipfile.ZipFile(file_path) as z:
            with z.open(z.namelist()[0]) as f:
                df = pd.read_csv(f, encoding='utf-8-sig')
    else:
        df = pd.read_csv(file_path, encoding='utf-8-sig')

    df['DATE'] = pd.to_datetime(df['DATE'].astype(str), format='%Y%m%d')
    return df

def load_wics_all_by_wics_major(data_path:str, wics_major_cd:str) -> pd.DataFrame:
    wics_frames = []
    for file_path in glob(data_path):
        df_y = __load_wics_by_year(file_path)
        if df_y is not None:
            it_mask = df_y['IDX_CD'].str.startswith(wics_major_cd)
            wics_frames.append(df_y[it_mask])
            print(f'{file_path}: {wics_major_cd} 행 {it_mask.sum():,}')

    return pd.concat(wics_frames, ignore_index=True)

