import os
from dotenv import load_dotenv
import mojito

class KisBroker:
    """한국투자증권(KIS) REST API Wrapper (mojito2 활용)"""
    def __init__(self, mock=True):
        load_dotenv()
        
        # 사용자의 .env 변수명 사용
        self.key = os.getenv("KIS_APP_KEY")
        self.secret = os.getenv("KIS_APP_SECRET")
        acc_no_front = os.getenv("KIS_DOMESTIC_STOCK_ACCOUNT_NO")
        acc_no_back = os.getenv("KIS_DOMESTIC_STOCK_ACCOUNT_PRODUCT_CODE", "01")
        
        if not self.key or not self.secret or not acc_no_front:
            raise ValueError("한국투자증권 API 키가 환경 변수에 없습니다 (KIS_APP_KEY, KIS_APP_SECRET, KIS_DOMESTIC_STOCK_ACCOUNT_NO)")
            
        self.acc_no = f"{acc_no_front}-{acc_no_back}"
        
        # mock 여부는 환경변수 KIS_ENV=paper 인지로 우선 판단
        env_mock = os.getenv("KIS_ENV", "").lower() == "paper"
        is_mock = env_mock if env_mock else mock
        
        self.broker = mojito.KoreaInvestment(
            api_key=self.key,
            api_secret=self.secret,
            acc_no=self.acc_no,
            mock=is_mock
        )
        
    def get_balance(self):
        """예수금 및 보유 종목 조회
        Returns:
            dict: {
                "cash": float, # 가용 현금
                "positions": { 
                    "005930": {"qty": 10, "avg_price": 70000, "current_price": 75000, "profit_rate": 7.14},
                    ...
                }
            }
        """
        resp = self.broker.fetch_balance()
        if "output2" not in resp or not resp["output2"]:
            # 에러 또는 응답 형식 문제
            print(f"[ERROR] 잔고 조회 실패: {resp}")
            return {"cash": 0.0, "positions": {}}
            
        # output2의 첫 번째 요소에 예수금 정보가 있음
        summary = resp["output2"][0]
        # prvs_rcdl_excc_amt: D+2 결제 후 실제 가용 현금 (전량 매도 다음날도 정확히 반영됨)
        # dnca_tot_amt는 당일 현금만 잡혀 D+2 대기분을 놓치므로 사용하지 않음
        cash = float(summary.get("prvs_rcdl_excc_amt", 0))
        total_asset = float(summary.get("tot_evlu_amt", 0))
        
        positions = {}
        if "output1" in resp:
            for item in resp["output1"]:
                ticker = item.get("pdno")
                qty = int(item.get("hldg_qty", 0))
                if qty > 0:
                    positions[ticker] = {
                        "qty": qty,
                        "avg_price": float(item.get("pchs_avg_pric", 0)),
                        "current_price": float(item.get("prpr", 0)),
                        "profit_rate": float(item.get("evlu_pfls_rt", 0))
                    }
                    
        return {
            "cash": cash,
            "total_asset": total_asset,
            "positions": positions
        }
        
    def place_market_buy(self, ticker: str, qty: int):
        """시장가 매수"""
        clean_ticker = ticker.split('.')[0]
        resp = self.broker.create_market_buy_order(
            symbol=clean_ticker,
            quantity=qty
        )
        return resp
        
    def place_market_sell(self, ticker: str, qty: int):
        """시장가 매도"""
        clean_ticker = ticker.split('.')[0]
        resp = self.broker.create_market_sell_order(
            symbol=clean_ticker,
            quantity=qty
        )
        return resp
