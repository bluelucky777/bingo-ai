import requests
from bs4 import BeautifulSoup
import json
import os
import datetime
import firebase_admin
from firebase_admin import credentials, db

# 1. Firebase 初始化函式
def initialize_firebase():
    # 這裡會從 Netlify 後台的環境變數讀取 JSON 字串
    cred_json_str = os.environ.get('FIREBASE_CONFIG')
    
    if not cred_json_str:
        print("❌ 錯誤：找不到 FIREBASE_CONFIG 環境變數")
        return False
    
    try:
        if not firebase_admin._apps:
            cred_dict = json.loads(cred_json_str)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred, {
                'databaseURL': 'https://bingo-ai-360ad-default-rtdb.firebaseio.com'
            })
        return True
    except Exception as e:
        print(f"❌ Firebase 初始化失敗: {str(e)}")
        return False

# 2. 爬蟲核心邏輯
def run_scraper():
    url = "https://lotto.auzonet.com/bingobingoV1.php"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, "html.parser")
        new_records = []
        
        rows = soup.find_all("tr", class_=["list_tr", "list_tr2"])
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 2: continue
            
            period = cols[0].get_text(strip=True)
            nums = [n.get_text(strip=True) for n in cols[1].find_all("span") if n.get_text(strip=True).isdigit()]
            
            if len(nums) >= 20:
                new_records.append({"period": period, "numbers": nums[:20]})
            if len(new_records) >= 5: break # 抓最近 5 期即可

        if new_records:
            db.reference('bingo_data').set({
                "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "records": new_records
            })
            return {"status": "success", "period": new_records[0]['period']}
        return {"status": "error", "message": "No data found"}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}

# 3. Netlify Function 必須的進入點 (Handler)
def handler(event, context):
    # 這裡放你爬蟲的邏輯
    try:
        # 假設這是你的執行結果
        data = {"status": "success", "message": "已更新"} 
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(data)
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
