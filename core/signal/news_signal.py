import datetime
import json
import os
import psycopg
from pathlib import Path
from typing import Dict
from core.data.news_collector import NaverNewsCollector
from core.data.dart_collector import DartRealtimeCollector
from core.analytics.sentiment import KeywordSentimentAnalyzer

class NewsSignalGenerator:
    """Fetches news and calculates sentiment scores for a list of tickers, with caching."""
    
    def __init__(self, cache_dir: Path):
        self.news_collector = NaverNewsCollector()
        self.dart_collector = DartRealtimeCollector()
        self.analyzer = KeywordSentimentAnalyzer()
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.dart_filings_cache = {}
        self.dart_fetched_today = False
        self.sector_cache = {}
        
    def _fetch_sector(self, ticker: str) -> str:
        """Fetch WICS industry code from PostgreSQL."""
        if ticker in self.sector_cache:
            return self.sector_cache[ticker]
            
        code = ticker.split('.')[0]
        try:
            password = os.environ.get("POSTGRES_PASSWORD")
            if not password:
                self.sector_cache[ticker] = None
                return None
            conn_str = (
                f"postgresql://{os.environ.get('POSTGRES_USER', 'admin')}:{password}"
                f"@{os.environ.get('POSTGRES_HOST', 'localhost')}:"
                f"{os.environ.get('POSTGRES_PORT', '5433')}/"
                f"{os.environ.get('POSTGRES_DB', 'quantpilot_db')}"
            )
            with psycopg.connect(conn_str) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT industry_code FROM wics_companies WHERE stock_code = %s ORDER BY base_date DESC LIMIT 1", (code,))
                    row = cur.fetchone()
                    industry = row[0] if row else None
                    self.sector_cache[ticker] = industry
                    return industry
        except Exception as e:
            self.sector_cache[ticker] = None
            return None
        
    def _get_cache_file(self, date: datetime.date) -> Path:
        return self.cache_dir / f"news_sentiment_{date.isoformat()}.json"
        
    def generate_signals(self, tickers: list[str], limit_per_ticker: int = 5) -> Dict[str, float]:
        """
        Generates sentiment scores (-1.0 to 1.0) for the given tickers.
        Uses cached scores if available for today.
        """
        today = datetime.date.today()
        cache_file = self._get_cache_file(today)
        
        cache_data = {}
        if cache_file.exists():
            try:
                cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                pass
                
        results = {}
        updated = False
        
        # Load DART filings once per day to save API limits
        if not self.dart_fetched_today:
            self.dart_filings_cache = self.dart_collector.fetch_today_filings()
            self.dart_fetched_today = True
        
        for ticker in tickers:
            if ticker in cache_data:
                results[ticker] = cache_data[ticker]
                continue
                
            industry = self._fetch_sector(ticker)
            
            # Fetch News
            news_items = self.news_collector.fetch_recent_news(ticker, limit=limit_per_ticker)
            
            # Fetch DART (from today's market-wide cache)
            raw_ticker = ticker.split('.')[0]
            dart_items = self.dart_filings_cache.get(raw_ticker, [])
            
            # Combine
            combined_items = news_items + dart_items
            
            score = self.analyzer.analyze_news_list(combined_items, industry_code=industry)
            
            results[ticker] = score
            cache_data[ticker] = score
            updated = True
            
        if updated:
            cache_file.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8")
            
        return results
