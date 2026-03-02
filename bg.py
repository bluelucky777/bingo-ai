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

# Firebase 初始化設定
# 請確保 GitHub Secrets 已設定 FIREBASE_CONFIG
cred_json_str = os.environ.get('FIREBASE_CONFIG')
if not cred_json_str:
    print("❌ 錯誤：找不到 FIREBASE_CONFIG 環境變數，請檢查 GitHub Secrets 設定。")
    exit(1)

cred = credentials.Certificate(json.loads(cred_json_str))
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://bingo-ai-360ad-default-rtdb.firebaseio.com' # 已根據您的配置填寫
})

MAX_HISTORY = 10

def fetch_bingo_now():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    url = "https://lotto.auzonet.com/bingobingoV1.php"
    
    try:
        print(f"🚀 啟動爬蟲，前往：{url}")
        driver.get(url)
        time.sleep(12) 
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        driver.quit()
        
        new_records = []
        rows = soup.find_all("tr", class_=re.compile(r"list_tr|list_tr2"))

        for row in rows:
            if len(new_records) >= MAX_HISTORY: break
            cols = row.find_all("td")
            if len(cols) < 2: continue
            
            period_match = re.search(r'(\d{9,10})', cols[0].get_text())
            if not period_match: continue
            period = period_match.group(1)

            cell_html = str(cols[1])
            found_nums = sorted(list(set(re.findall(r'[nN][bB](\d{2})', cell_html))))
            
            if len(found_nums) >= 20:
                new_records.append({"period": period, "numbers": found_nums[:20]})

        if new_records:
            # 將數據同步至 Firebase
            ref = db.reference('bingo_data')
            data_to_save = {
                "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "records": new_records
            }
            ref.set(data_to_save)
            print(f"🔥 Firebase 同步成功！最後更新時間：{data_to_save['last_update']}")
            return True
        else:
            print("⚠️ 抓取成功但未找到開獎數據。")
            return False
    except Exception as e:
        print(f"⚠️ 爬蟲發生錯誤: {e}")
        return False

if __name__ == "__main__":
    fetch_bingo_now()
