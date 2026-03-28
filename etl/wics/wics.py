from tqdm.auto import tqdm
from pandas import json_normalize
import requests
import pandas as pd
import time

def wics_url(date, wics_code):
    '''
    Parameter
    - date[str] : the date corresponding data (yyyymmdd)
    - wics_code[int] : the wics code corresponding data (use wics_lc or wics_mc)
    
    Return
    - url[str]
    '''
    url ='http://www.wiseindex.com/Index/GetIndexComponets?ceil_yn=0&'\
        'dt=' + date + '&sec_cd=G' + str(wics_code)
    return url

def wics_json(date, wics_code):
    '''
    Parameter
    - date[str] : the date corresponding data (yyyymmdd)
    - wics_code[int] : the wics code corresponding data (use wics_lc or wics_mc)
    
    Return
    - json[dict]
    '''
    
    url = wics_url(date, wics_code)
    response = requests.get(url)
    return response.json()


def save_wics_company(date_list, wics_medium_cds):
    df_save = pd.DataFrame()

    for date in tqdm(date_list, desc="date..", leave=True):
        for wics_cd in tqdm(wics_medium_cds, desc="wics..", leave=False):
            data_json = wics_json(date=date, wics_code=int(wics_cd))   
            if not data_json['list']:    
                continue  

            df = json_normalize(data_json, record_path=['list'])
            df['DATE'] = date
            
            # info 
            df['INFO_MKT_VAL'] = data_json['info']['MKT_VAL']
            df['INFO_TRD_AMT'] = data_json['info']['TRD_AMT']
            df['INFO_CNT'] = data_json['info']['CNT']
            # sector 
            sector = [
                sector for sector in data_json['sector'] if df['SEC_CD'].unique()[0] == sector['SEC_CD']
            ][0]
            df['SEC_RATE'] = sector['SEC_RATE']
            df['IDX_RATE'] = sector['IDX_RATE']
            # size 
            for size in data_json['size']:
                if size['SEC_CD'] == "WMI510":
                    df['SIZE_WMI510'] = "WMI500 대형주"
                    df['SIZE_WMI510_SEC_RATE'] = size['SEC_RATE']
                    df['SIZE_WMI510_IDX_RATE'] = size['IDX_RATE']
                elif size['SEC_CD'] == "WMI520":

                    df['SIZE_WMI520'] = "WMI500 중형주"
                    df['SIZE_WMI520_SEC_RATE'] = size['SEC_RATE']

                    df['SIZE_WMI520_IDX_RATE'] = size['IDX_RATE']
                elif size['SEC_CD'] == "WMI530":
                    df['SIZE_WMI530'] = "WMI500 소형주"
                    df['SIZE_WMI530_SEC_RATE'] = size['SEC_RATE']
                    df['SIZE_WMI530_IDX_RATE'] = size['IDX_RATE']

            df_save = pd.concat([df_save, df], axis=0)
            time.sleep(0.01)

    return df_save