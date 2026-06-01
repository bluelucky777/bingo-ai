"""
369 BINGO 爬蟲 — 從 lotto.auzonet.com 抓最近 N 期推 Firebase RTDB
跑法：GitHub Actions 每 5 分鐘排程觸發
"""
import datetime
import json
import os
import re
import sys
import time
import traceback

import firebase_admin
from bs4 import BeautifulSoup
from firebase_admin import credentials, db
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

MAX_HISTORY = 100  # 加大窗口，回測需要至少 80+ 期


def _init_firebase():
    cred_json = os.environ.get('FIREBASE_CONFIG')
    db_url = os.environ.get('FIREBASE_DATABASE_URL')
    if not cred_json:
        print("❌ 找不到環境變數 FIREBASE_CONFIG（service account JSON 字串）")
        sys.exit(1)
    if not db_url:
        print("❌ 找不到環境變數 FIREBASE_DATABASE_URL")
        print("   例：https://bingo-ai-360ad-default-rtdb.firebaseio.com")
        sys.exit(1)
    cred = credentials.Certificate(json.loads(cred_json))
    firebase_admin.initialize_app(cred, {'databaseURL': db_url})


def fetch_bingo_now():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

    # Selenium 4.6+ 內建 Selenium Manager 會自動找系統 chromedriver
    # （GitHub Actions 的 browser-actions/setup-chrome@v1 已在 PATH 裝好）
    driver = webdriver.Chrome(options=chrome_options)
    url = "https://lotto.auzonet.com/bingobingoV1.php"

    try:
        print(f"🚀 正在前往爬取數據：{url}")
        driver.get(url)
        time.sleep(12)

        soup = BeautifulSoup(driver.page_source, "html.parser")
        driver.quit()

        new_records = []
        rows = soup.find_all("tr", class_=re.compile(r"list_tr|list_tr2"))

        for row in rows:
            if len(new_records) >= MAX_HISTORY:
                break
            cols = row.find_all("td")
            if len(cols) < 2:
                continue

            period_match = re.search(r'(\d{9,10})', cols[0].get_text())
            if not period_match:
                continue
            period = period_match.group(1)

            cell_html = str(cols[1])
            found_nums = sorted(list(set(re.findall(r'[nN][bB](\d{2})', cell_html))))

            if len(found_nums) >= 20:
                new_records.append({"period": period, "numbers": found_nums[:20]})

        if not new_records:
            print("⚠️ 沒抓到任何記錄（網頁結構可能變了）")
            return False

        # 合併現有歷史避免回測樣本被洗掉
        ref = db.reference('bingo_data')
        existing = ref.get() or {}
        existing_records = existing.get('records', [])

        # 用 period 去重，新爬到的優先
        seen = set()
        merged = []
        for r in new_records + existing_records:
            if r['period'] not in seen:
                seen.add(r['period'])
                merged.append(r)
        merged = sorted(merged, key=lambda x: x['period'], reverse=True)[:MAX_HISTORY]

        data_to_save = {
            "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "records": merged,
        }
        ref.set(data_to_save)
        print(f"🔥 Firebase 同步成功！期數：{merged[0]['period']}，總筆數：{len(merged)}，時間：{data_to_save['last_update']}")
        return True

    except Exception as e:
        print(f"⚠️ 錯誤：{type(e).__name__}: {e}")
        traceback.print_exc()
        try:
            driver.quit()
        except Exception:
            pass
        return False


if __name__ == "__main__":
    _init_firebase()
    success = fetch_bingo_now()
    sys.exit(0 if success else 1)
