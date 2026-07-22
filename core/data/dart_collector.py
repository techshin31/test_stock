import os
import requests
import datetime
from typing import List, Dict

class DartRealtimeCollector:
    """Fetches real-time DART filings for the current day across the market."""
    
    BASE_URL = "https://opendart.fss.or.kr/api/list.json"
    
    def __init__(self):
        self.api_key = os.environ.get("DART_API_KEY")
        if not self.api_key:
            print("[DartCollector] WARNING: DART_API_KEY is not set.")
            
    def fetch_today_filings(self) -> Dict[str, List[Dict[str, str]]]:
        """
        Fetches today's filings for all listed companies.
        Returns a dictionary mapping stock_code (6-digit) to a list of filings.
        """
        if not self.api_key:
            return {}
            
        today_str = datetime.date.today().strftime("%Y%m%d")
        
        params = {
            "crtfc_key": self.api_key,
            "bgn_de": today_str,
            "end_de": today_str,
            "page_count": 100 # Fetch up to 100 latest filings
        }
        
        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            if data.get("status") != "000":
                if data.get("status") == "013": # No data
                    return {}
                print(f"[DartCollector] API Error: {data.get('message')}")
                return {}
                
            filings_by_ticker = {}
            for item in data.get("list", []):
                stock_code = item.get("stock_code")
                if not stock_code or not stock_code.strip():
                    continue # Skip unlisted companies
                    
                stock_code = stock_code.strip()
                if stock_code not in filings_by_ticker:
                    filings_by_ticker[stock_code] = []
                    
                filings_by_ticker[stock_code].append({
                    "title": item.get("report_nm", ""),
                    "provider": "DART",
                    "date": item.get("rcept_dt", "")
                })
                
            return filings_by_ticker
            
        except Exception as e:
            print(f"[DartCollector] Failed to fetch DART filings: {e}")
            return {}
