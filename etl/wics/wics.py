import requests
import pandas as pd

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

