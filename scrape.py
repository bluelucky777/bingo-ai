import json
import os
import requests
from bs4 import BeautifulSoup
import datetime
import firebase_admin
from firebase_admin import credentials, db

def handler(event, context):
    # 1. Firebase 初始化 (從 Netlify 環境變數讀取)
    if not firebase_admin._apps:
        cred_json = json.loads(os.environ.get('FIREBASE_CONFIG'))
        firebase_admin.initialize_app(credentials.Certificate(cred_json), {
            'databaseURL': 'https://bingo-ai-360ad-default-rtdb.firebaseio.com'
        })

    # 2. 極速爬蟲邏輯
    url = "https://lotto.auzonet.com/bingobingoV1.php"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        res = requests.get(url, headers=headers, timeout=8)
        soup = BeautifulSoup(res.text, "html.parser")
        new_records = []
        rows = soup.find_all("tr", class_=["list_tr", "list_tr2"])
        
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 2: continue
            nums = [n.get_text(strip=True) for n in cols[1].find_all("span") if n.get_text(strip=True).isdigit()]
            if len(nums) >= 20:
                new_records.append({"period": cols[0].get_text(strip=True), "numbers": nums[:20]})
            if len(new_records) >= 10: break

        # 3. 更新 Firebase 並回傳結果
        data = {
            "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "records": new_records
        }
        db.reference('bingo_data').set(data)

        return {
            "statusCode": 200,
            "body": json.dumps({"status": "success", "data": data})
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"status": "error", "message": str(e)})
        }