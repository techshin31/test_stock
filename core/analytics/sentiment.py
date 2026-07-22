import re
from typing import List, Dict

class KeywordSentimentAnalyzer:
    """Analyzes text sentiment based on financial dictionary matching, with sector weights."""
    
    # 기본 호재/악재 키워드
    POSITIVE_KEYWORDS = [
        "수주", "실적", "상승", "호조", "흑자", "돌파", "급등", "성장", 
        "확대", "증가", "개선", "신작", "공급", "계약", "M&A", "인수", 
        "배당", "호실적", "목표가 상향", "강세", "수혜", "최대", "혁신"
    ]
    
    NEGATIVE_KEYWORDS = [
        "하락", "급락", "적자", "부진", "축소", "감소", "악화", "우려", 
        "리스크", "소송", "파산", "상장폐지", "매각", "침체", "목표가 하향", 
        "약세", "쇼크", "위기", "지연", "취소", "해지"
    ]

    # DART 전용 초강력 키워드 (가중치 3.0배 적용)
    DART_POSITIVE = ["단일판매ㆍ공급계약체결", "무상증자", "자기주식취득"]
    DART_NEGATIVE = ["유상증자", "감자", "상장폐지기준", "관리종목지정", "횡령", "배임", "영업정지"]

    # 섹터별 특화 가중치 키워드
    SECTOR_WEIGHTS = {
        "G3520": {"긍정": ["임상", "FDA", "승인", "기술수출", "신약"], "부정": ["임상 실패", "반려"]}, # 제약/바이오
        "G2560": {"긍정": ["양산", "엔비디아", "수주", "HBM"], "부정": ["감산", "단가 하락"]}, # 반도체
        "G4530": {"긍정": ["흥행", "글로벌 출시", "사전예약", "판호"], "부정": ["연기", "출시 지연"]}, # 게임/엔터
    }
    
    def __init__(self):
        self.pos_pattern = re.compile("|".join(self.POSITIVE_KEYWORDS))
        self.neg_pattern = re.compile("|".join(self.NEGATIVE_KEYWORDS))
        self.dart_pos_pattern = re.compile("|".join(self.DART_POSITIVE))
        self.dart_neg_pattern = re.compile("|".join(self.DART_NEGATIVE))
        
    def analyze_title(self, title: str, is_dart: bool = False, industry_code: str = None) -> float:
        """
        Returns a sentiment score between -3.0 and 3.0.
        """
        score = 0.0
        
        # DART 공시는 초강력 가중치 적용
        if is_dart:
            if self.dart_pos_pattern.search(title):
                score += 3.0
            if self.dart_neg_pattern.search(title):
                score -= 3.0
        
        # 기본 뉴스 점수
        pos_matches = len(self.pos_pattern.findall(title))
        neg_matches = len(self.neg_pattern.findall(title))
        
        # 섹터 특화 키워드 점수 (가중치 1.5배)
        if industry_code and industry_code in self.SECTOR_WEIGHTS:
            sector_dict = self.SECTOR_WEIGHTS[industry_code]
            sector_pos = sum(1 for k in sector_dict["긍정"] if k in title)
            sector_neg = sum(1 for k in sector_dict["부정"] if k in title)
            
            pos_matches += (sector_pos * 1.5)
            neg_matches += (sector_neg * 1.5)
            
        if pos_matches == 0 and neg_matches == 0 and score == 0.0:
            return 0.0
            
        if (pos_matches + neg_matches) > 0:
            # 정규화 (-1.0 ~ 1.0)
            score += (pos_matches - neg_matches) / (pos_matches + neg_matches)
            
        return max(-3.0, min(3.0, score))
        
    def analyze_news_list(self, news_items: List[Dict[str, str]], industry_code: str = None) -> float:
        """
        Calculates an aggregated sentiment score for a list of news/DART items.
        Returns a score from -3.0 to 3.0.
        """
        if not news_items:
            return 0.0
            
        total_score = 0.0
        valid_items = 0
        for item in news_items:
            is_dart = item.get("provider") == "DART"
            score = self.analyze_title(item.get("title", ""), is_dart=is_dart, industry_code=industry_code)
            if score != 0.0:
                total_score += score
                valid_items += 1
            
        if valid_items == 0:
            return 0.0
            
        return total_score / valid_items
