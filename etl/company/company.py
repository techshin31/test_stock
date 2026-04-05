import requests

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

def comp_json(code):
    '''
    Parameter
    - code[str] : the company code corresponding data
    
    Return
    - json[dict]
    '''
    url = comp_url(code)
    response = requests.get(url)
    return response.json()

