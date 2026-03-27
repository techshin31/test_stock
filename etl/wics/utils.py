from datetime import datetime, timedelta 

def get_today(format='%Y%m%d'):
    today = datetime.now()
    return today.strftime(format)

def get_yesterday(format='%Y%m%d'):
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    return yesterday.strftime(format)

def get_date_list(start_date:str, end_date:str, format='%Y%m%d'):
    start_date = datetime.strptime(start_date, format)
    end_date = datetime.strptime(end_date, format)
    # 날짜 차이 계산
    delta = end_date - start_date

    # 리스트 컴프리헨션을 사용하여 문자열 리스트 생성
    # '%Y-%m-%d' 형식으로 저장 (예: '2020-01-01')
    date_str_list = [
        (start_date + timedelta(days=i)).strftime(format) 
        for i in range(delta.days + 1)
    ]
    return date_str_list



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

def comp_url(code):
    '''
    Parameter
    - code[str] : the company code corresponding data
    
    Return
    - url[str]
    '''
    url = 'http://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&'\
        'gicode=A' + code + \
        '&cID=&MenuYn=Y&ReportGB=&NewMenuID=Y&stkGb=701'
    return url
