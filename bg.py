import json
import os
import re
import time
import datetime
import firebase_admin
from firebase_admin import credentials, db
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# Firebase 初始化
cred_json_str = os.environ.get('FIREBASE_CONFIG')
if not cred_json_str:
    print("❌ 錯誤：找不到 FIREBASE_CONFIG")
    exit(1)

cred = credentials.Certificate(json.loads(cred_json_str))
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {'databaseURL': 'https://bingo-ai-360ad-default-rtdb.firebaseio.com'})

def fetch_bingo_now():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # 模擬真實瀏覽器，避免被擋
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    try:
        print(f"🚀 啟動爬蟲任務...")
        driver.get("https://lotto.auzonet.com/bingobingoV1.php")
        time.sleep(15) # 增加等待時間，確保網頁跑完
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        driver.quit()
        
        new_records = []
        # 修改解析邏輯，增加穩定性
        rows = soup.find_all("tr") 
        for row in rows:
            text = row.get_text()
            if "期序" in text or "開獎號碼" in text: continue
            
            period_match = re.search(r'(\d{9,10})', text)
            if period_match:
                period = period_match.group(1)
                # 抓取該行內所有的數字球
                nums = re.findall(r'(\d{2})', str(row))
                # 過濾出真正的 20 個號碼
                valid_nums = sorted(list(set([n for n in nums if 1 <= int(n) <= 80])))[:20]
                
                if len(valid_nums) >= 20:
                    new_records.append({"period": period, "numbers": valid_nums})
            if len(new_records) >= 10: break

        print(f"🔎 抓取結果：共找到 {len(new_records)} 筆資料")

        if new_records:
            ref = db.reference('bingo_data')
            data_to_save = {
                "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "records": new_records
            }
            ref.set(data_to_save)
            print(f"🔥 Firebase 同步成功！最後更新：{data_to_save['last_update']}")
            return True
        else:
            print("⚠️ 警告：抓取完成但沒找到任何號碼，可能是網頁結構改變或被擋。")
            return False
    except Exception as e:
        print(f"⚠️ 發生異常錯誤: {e}")
        return False

if __name__ == "__main__":
    fetch_bingo_now()
