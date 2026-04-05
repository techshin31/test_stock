from tqdm.auto import tqdm
from pandas import json_normalize
import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import ChunkedEncodingError
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import ContentDecodingError
from requests.exceptions import Timeout as RequestsTimeout
from urllib3.util.retry import Retry
import pandas as pd
import time

_CONNECT_TIMEOUT = 20
_READ_TIMEOUT = 180
_REQUEST_TIMEOUT = (_CONNECT_TIMEOUT, _READ_TIMEOUT)
_WICS_JSON_ATTEMPTS = 4
_WICS_JSON_BACKOFF_BASE = 3.0
_WICS_TRANSIENT_ERRORS = (
    RequestsTimeout,
    RequestsConnectionError,
    ChunkedEncodingError,
    ContentDecodingError,
)


def _wics_session():
    retry = Retry(
        total=3,
        connect=3,
        read=False,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }
    )
    return session


_WICS_SESSION = _wics_session()


def wics_url(date, wics_code):
    '''
    Parameter
    - date[str] : the date corresponding data (yyyymmdd)
    - wics_code[int] : the wics code corresponding data (use wics_lc or wics_mc)

    Return
    - url[str]
    '''
    url = (
        "https://www.wiseindex.com/Index/GetIndexComponets?ceil_yn=0&"
        "dt=" + date + "&sec_cd=G" + str(wics_code)
    )
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
    for attempt in range(_WICS_JSON_ATTEMPTS):
        try:
            response = _WICS_SESSION.get(url, timeout=_REQUEST_TIMEOUT)
            return response.json()
        except _WICS_TRANSIENT_ERRORS:
            if attempt >= _WICS_JSON_ATTEMPTS - 1:
                raise
            time.sleep(_WICS_JSON_BACKOFF_BASE * (2**attempt))


def save_wics_company(date_list, wics_medium_cds):
    df_save = pd.DataFrame()

    for date in tqdm(date_list, desc="date..", leave=True):
        for wics_cd in tqdm(wics_medium_cds, desc="wics..", leave=False):
            time.sleep(0.5)
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

    return df_save
