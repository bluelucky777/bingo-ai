import requests
from bs4 import BeautifulSoup
import json, os, datetime, firebase_admin
from firebase_admin import credentials, db

# 1. Firebase 初始化 (維持原樣)
# 請確保在 Netlify 後台的 Environment variables 已設定 FIREBASE_CONFIG
def initialize_firebase():
    cred_json_str = os.environ.get('FIREBASE_CONFIG')
    if not cred_json_str:
        print("❌ 錯誤：未找到 FIREBASE_CONFIG 環境變數")
        return False
    
    try:
        cred_json = json.loads(cred_json_str)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(cred_json), {
                'databaseURL': 'https://bingo-ai-360ad-default-rtdb.firebaseio.com' 
            })
        return True
    except Exception as e:
        print(f"❌ Firebase 初始化失敗: {e}")
        return False

def fetch_fast():
    # [cite_start]改用 Requests 直接連線 [cite: 1]
    url = "https://lotto.auzonet.com/bingobingoV1.php"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        print("🚀 啟動極速爬蟲任務...")
        response = requests.get(url, headers=headers, timeout=20)
        soup = BeautifulSoup(response.text, "html.parser")
        
        new_records = []
        # [cite_start]尋找開獎表格行 [cite: 1]
        rows = soup.find_all("tr", class_=["list_tr", "list_tr2"])
        
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 2: continue
            
            period = cols[0].get_text(strip=True)
            # [cite_start]抓取所有數字球號碼 [cite: 1]
            nums = [n.get_text(strip=True) for n in cols[1].find_all("span") if n.get_text(strip=True).isdigit()]
            
            if len(nums) >= 20:
                new_records.append({"period": period, "numbers": nums[:20]})
            if len(new_records) >= 10: break

        if new_records:
            # [cite_start]推送到 Firebase [cite: 1]
            db.reference('bingo_data').set({
                "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "records": new_records
            })
            msg = f"🔥 Firebase 同步成功！最新時間：{datetime.datetime.now()}"
            print(msg)
            return {"status": "success", "message": msg, "period": new_records[0]['period']}
        else:
            return {"status": "error", "message": "未在網頁中找到號碼數據"}
            
    except Exception as e:
        print(f"❌ 錯誤原因: {e}")
        return {"status": "error", "message": str(e)}

# 2. Netlify Function 必備的進入點
def handler(event, context):
    # 確保 Firebase 已初始化
    if not initialize_firebase():
        return {
            "statusCode": 500,
            "body": json.dumps({"status": "error", "message": "Firebase config missing or invalid"})
        }

    # 執行爬蟲邏輯
    result = fetch_fast()
    
    # 回傳給前端 index.html 的回應
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*" # 允許跨網域呼叫
        },
        "body": json.dumps(result)
    }

# 供本地測試用
if __name__ == "__main__":
    initialize_firebase()
    fetch_fast()
