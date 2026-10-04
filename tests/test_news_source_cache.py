import datetime
import json

from core.signal.news_signal import KST, NewsSignalGenerator


def test_naver_only_scores_ignore_previous_mixed_source_cache_and_reuse_new_cache(tmp_path, monkeypatch):
    monkeypatch.setenv('DART_API_KEY', 'unused-legacy-binding')
    today = datetime.datetime.now(KST).date()
    legacy = tmp_path / f'news_sentiment_{today.isoformat()}.json'
    legacy.write_text(json.dumps({'005930.KS': -1.0}))
    generator = NewsSignalGenerator(tmp_path)
    articles = [{'title': 'Naver article', 'provider': 'Naver'}]
    fetched, scored = [], []
    monkeypatch.setattr(generator.news_collector, 'fetch_recent_news',
                        lambda ticker, **kw: fetched.append(ticker) or articles)
    monkeypatch.setattr(generator, '_fetch_sector', lambda ticker: 'G4530')
    monkeypatch.setattr(generator.analyzer, 'analyze_news_list',
                        lambda rows, **kw: scored.append((rows, kw)) or 0.25)

    assert generator.generate_signals(['005930.KS']) == {'005930.KS': 0.25}
    assert generator.generate_signals(['005930.KS']) == {'005930.KS': 0.25}
    assert fetched == ['005930.KS']
    assert scored == [(articles, {'industry_code': 'G4530'})]
    assert json.loads(legacy.read_text()) == {'005930.KS': -1.0}
    assert json.loads(generator._get_cache_file(today).read_text()) == {'005930.KS': 0.25}
