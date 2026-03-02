import json
import os
import re
import time
import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

DB_FILE = "history.json"
MAX_HISTORY = 10

def fetch_bingo_now():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") # 雲端執行必須開啟無頭模式
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("window-size=1920,1080")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    url = "https://lotto.auzonet.com/bingobingoV1.php"
    
    try:
        print(f"🚀 正在前往：{url}")
        driver.get(url)
        time.sleep(12) # 等待網頁渲染
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        driver.quit()
        
        new_records = []
        rows = soup.find_all("tr", class_=re.compile(r"list_tr|list_tr2")) # 抓取開獎行

        for row in rows:
            if len(new_records) >= MAX_HISTORY: break
            cols = row.find_all("td")
            if len(cols) < 2: continue
            
            # 提取期數
            period_match = re.search(r'(\d{9,10})', cols[0].get_text())
            if not period_match: continue
            period = period_match.group(1)

            # 提取號碼 (軌道 A：使用 nBXX 類別過濾序號)
            cell_html = str(cols[1])
            found_nums = sorted(list(set(re.findall(r'[nN][bB](\d{2})', cell_html))))
            
            if len(found_nums) >= 20:
                new_records.append({"period": period, "numbers": found_nums[:20]})

        if new_records:
            # 封裝包含時間標籤的數據結構
            data_to_save = {
                "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "records": new_records
            }
            with open(DB_FILE, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, ensure_ascii=False, indent=2)
            print(f"✅ 成功更新！時間：{data_to_save['last_update']}")
            return True
        return False
    except Exception as e:
        print(f"⚠️ 錯誤: {e}")
        return False

if __name__ == "__main__":
    fetch_bingo_now()
