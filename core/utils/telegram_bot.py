import requests
import os
from dotenv import load_dotenv

class TelegramBot:
    def __init__(self):
        load_dotenv()
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        if not self.token or not self.chat_id:
            print("[WARNING] 텔레그램 봇 토큰 또는 Chat ID가 설정되지 않았습니다. 알림이 전송되지 않습니다.")
            
    def send_message(self, message: str):
        if not self.token or not self.chat_id:
            return False
            
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            return True
        except Exception as e:
            safe_error = str(e).replace(str(self.token), "***")
            print(f"[ERROR] 텔레그램 전송 실패: {safe_error}")
            return False
