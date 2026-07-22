import requests
from bs4 import BeautifulSoup
import re
from typing import List, Dict

class NaverNewsCollector:
    """Scrapes recent news headlines for a given stock from Naver Finance."""
    
    BASE_URL = "https://finance.naver.com/item/news_news.naver"
    
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
    def fetch_recent_news(self, ticker: str, limit: int = 10) -> List[Dict[str, str]]:
        """
        Fetches the most recent news headlines for the given ticker.
        ticker should be a 6-digit string without the .KS suffix.
        """
        raw_ticker = ticker.split(".")[0]
        params = {"code": raw_ticker}
        
        try:
            resp = requests.get(self.BASE_URL, params=params, headers=self.headers, timeout=5)
            resp.raise_for_status()
            
            # Using html.parser
            soup = BeautifulSoup(resp.text, "html.parser")
            
            news_items = []
            
            # Find the news table
            # In Naver Finance iframe, it's typically inside a table with class 'type5'
            table = soup.find("table", class_="type5")
            if not table:
                return []
                
            rows = table.find_all("tr")
            for row in rows:
                if len(news_items) >= limit:
                    break
                    
                title_tag = row.find("td", class_="title")
                if not title_tag:
                    continue
                    
                a_tag = title_tag.find("a")
                if not a_tag:
                    continue
                    
                title = a_tag.get_text(strip=True)
                # optionally find provider and date
                provider_tag = row.find("td", class_="info")
                date_tag = row.find("td", class_="date")
                
                provider = provider_tag.get_text(strip=True) if provider_tag else "Unknown"
                date_str = date_tag.get_text(strip=True) if date_tag else ""
                
                news_items.append({
                    "title": title,
                    "provider": provider,
                    "date": date_str
                })
                
            return news_items
            
        except Exception as e:
            print(f"[NewsCollector] Failed to fetch news for {ticker}: {e}")
            return []
