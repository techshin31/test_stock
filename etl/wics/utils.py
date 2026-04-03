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

