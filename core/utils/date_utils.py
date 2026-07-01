
import datetime
from dateutil.relativedelta import relativedelta

def convert_to_str(date: datetime.date, format_string: str = '%Y-%m-%d') -> str:
    """
    datetime.date 객체를 지정된 형식의 문자열로 변환하는 함수입니다.
    
    Parameters:
    - date: 변환할 날짜 (datetime.date 객체)
    - format_string: 변환할 형식 (기본값: '%Y-%m-%d')
    
    Returns:
    - 지정된 형식의 날짜 문자열
    """
    return date.strftime(format_string)

def get_date_n_years_before(date: datetime.date, n: int) -> datetime.date:
    """
    주어진 날짜로부터 n년 전의 날짜를 계산하여 반환하는 함수입니다.
    
    Parameters:
    - date: 기준이 되는 날짜 (datetime.date 객체)
    - n: 몇 년 전의 날짜를 계산할지 (정수)
    
    Returns:
    - n년 전의 날짜 (datetime.date 객체)
    """
    return date - relativedelta(years=n)



