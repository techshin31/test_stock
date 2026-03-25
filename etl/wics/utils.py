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
