"""
369 BINGO 爬蟲 — 從 lotto.auzonet.com 抓最近 N 期推 Firebase RTDB
跑法：GitHub Actions 每 5 分鐘排程觸發

注意：來源網站是靜態 HTML（無 JS 渲染），用 requests + BeautifulSoup
比 Selenium 快 ~30 倍、失敗點更少。若哪天網站改 JS render 才需再裝回 Selenium。
"""
import datetime
import json
import os
import re
import sys
import traceback

import firebase_admin
import requests
from bs4 import BeautifulSoup
from firebase_admin import credentials, db

MAX_HISTORY = 100  # 加大窗口，回測需要至少 80+ 期
URL = "https://lotto.auzonet.com/bingobingoV1.php"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
REQUEST_TIMEOUT = 15


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
    try:
        print(f"🚀 正在前往爬取數據：{URL}")
        resp = requests.get(URL, headers={"User-Agent": UA}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        print(f"   HTTP {resp.status_code}, {len(resp.content)} bytes, {resp.elapsed.total_seconds():.2f}s")

        soup = BeautifulSoup(resp.text, "html.parser")
        # 2026 改版後的 tr class 是 bingo_text_row
        rows = soup.find_all("tr", class_="bingo_text_row")
        print(f"📊 抓到 {len(rows)} 個 bingo_text_row")

        new_records = []
        for row in rows:
            if len(new_records) >= MAX_HISTORY:
                break
            cols = row.find_all("td")
            if len(cols) < 2:
                continue

            # 期數：第一個 <td> 內，9-10 位數
            period_match = re.search(r'(\d{9,10})', cols[0].get_text())
            if not period_match:
                continue
            period = period_match.group(1)

            # 號碼：<td class="BBALL"> 內，純文字 1-2 位數
            ball_td = row.find("td", class_="BBALL")
            if not ball_td:
                continue
            text = ball_td.get_text(separator=' ')
            # 提取所有 1-80 的整數（過濾無關數字）
            raw_nums = re.findall(r'\b(\d{1,2})\b', text)
            found_nums = sorted(set(n.zfill(2) for n in raw_nums if 1 <= int(n) <= 80))

            if len(found_nums) >= 20:
                new_records.append({"period": period, "numbers": found_nums[:20]})

        if not new_records:
            print("⚠️ 沒抓到任何記錄（網頁結構可能變了，請檢查 bingo_text_row 選擇器）")
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

    except requests.exceptions.RequestException as e:
        print(f"⚠️ 網路錯誤：{type(e).__name__}: {e}")
        return False
    except Exception as e:
        print(f"⚠️ 錯誤：{type(e).__name__}: {e}")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    _init_firebase()
    success = fetch_bingo_now()
    sys.exit(0 if success else 1)
