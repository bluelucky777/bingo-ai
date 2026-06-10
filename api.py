"""
369 BINGO Flask API
- /api/predict: 號碼分析 + 預測 + 星級 + 攻略 + 脆友推薦 + 回測（一次回完整 payload）
- /api/backtest: 單純回測指定策略
- /api/scrape: 立即觸發爬蟲，更新 Firebase（給 UptimeRobot + 前端「立即同步」鈕用）
- 資料來源：Firebase RTDB（不再讀本地 history.json）
"""
import datetime as _dt
import json
import os
import re
import traceback

import firebase_admin
import requests
from bs4 import BeautifulSoup
from firebase_admin import credentials, db
from flask import Flask, jsonify, request
from flask_cors import CORS

from back import (
    analyze_strategy,
    analyze_star_levels,
    backtest_strategy,
    get_expert_strategies,
    get_frequency_bias_report,
    get_n_groups,
    get_strategy_analysis,
    plain_counts,
)

app = Flask(__name__)

# CORS：開發允許所有 origin，部署時用 ALLOWED_ORIGINS env 收斂
# .strip() + 每個 origin 也 strip：防止複製貼上 env var 時殘留換行/空白
allowed_origins = os.environ.get('ALLOWED_ORIGINS', '*').strip()
if allowed_origins == '*' or not allowed_origins:
    CORS(app)
else:
    origins = [o.strip() for o in allowed_origins.split(',') if o.strip()]
    CORS(app, resources={r"/api/*": {"origins": origins}})


# ---------- Firebase 初始化 ----------

def _init_firebase():
    if firebase_admin._apps:
        return
    cred_json = os.environ.get('FIREBASE_CONFIG')
    db_url = os.environ.get('FIREBASE_DATABASE_URL')
    if not cred_json:
        raise RuntimeError("缺少環境變數 FIREBASE_CONFIG（service account JSON 字串）")
    if not db_url:
        raise RuntimeError("缺少環境變數 FIREBASE_DATABASE_URL（例：https://xxx.firebaseio.com）")
    cred = credentials.Certificate(json.loads(cred_json))
    firebase_admin.initialize_app(cred, {'databaseURL': db_url})


def _load_history():
    """從 Firebase 讀；本機 dev 若沒設 env 則 fallback 到 history.json"""
    try:
        _init_firebase()
        snapshot = db.reference('bingo_data').get() or {}
        return snapshot.get('records', []), snapshot.get('last_update')
    except RuntimeError as e:
        # dev fallback
        if os.path.exists("history.json"):
            print(f"⚠️ Firebase 未設定，fallback 讀 history.json：{e}")
            with open("history.json", "r", encoding="utf-8") as f:
                return json.load(f), None
        raise


def _next_period(period_str):
    """期數 +1 推算下一期；若超出 int 範圍直接回 None"""
    try:
        return str(int(period_str) + 1)
    except (ValueError, TypeError):
        return None


# 全模組級快取：backtest 4 個策略總共 6000 次運算，Render 免費版要 ~3 秒
# 但 backtest 結果只跟 history 內容相關，與 limit/strategy/ball_count 無關
# → 用 last_update 當 key 快取，5 分鐘內所有切換都命中
_BACKTEST_CACHE = {}


def _get_or_compute_backtest(full_nums, last_update):
    """快取 backtest 結果。Key 用 last_update（每次 /api/scrape 都會變）"""
    key = (last_update, len(full_nums))
    if key in _BACKTEST_CACHE:
        return _BACKTEST_CACHE[key]
    result = {}
    # 4 個策略 × 10 期 = 40 次回測（balanced/luck/parity_zone 已從 UI 移除不再 backtest，
    # 但 balanced/luck 保留在 back.py 供 consensus 內部投票使用）
    for s in ['hot', 'pure_hot', 'consensus', 'markov']:
        result[s] = backtest_strategy(full_nums, s, test_periods=10, lookback=50, ball_count=6)
    _BACKTEST_CACHE[key] = result
    # 簡易 LRU：只留最近 3 個 key 防止記憶體膨脹
    if len(_BACKTEST_CACHE) > 3:
        del _BACKTEST_CACHE[next(iter(_BACKTEST_CACHE))]
    return result


# ---------- 端點 ----------

@app.route('/api/predict', methods=['GET'])
def predict():
    try:
        strategy = request.args.get('strategy', 'hot')
        limit = int(request.args.get('limit', 10))
        ball_count = int(request.args.get('ball_count', 6))
        expert_count = int(request.args.get('expert_count', 3))
        run_backtest = request.args.get('backtest', '1') == '1'

        full_history, last_update = _load_history()
        if not full_history:
            return jsonify({"error": "資料庫為空，請等候爬蟲首次同步"}), 200

        cache_signature = last_update or (full_history[0].get('period') if full_history else None)

        # 分析範圍受 limit 控制（給機率排行 / n_groups / 策略預測用）
        history_data = full_history[:limit]
        # 顯示與下注結算用：至少 20 期
        # 前端只顯示前 10 筆，其餘 10 筆當「結算緩衝」讓 10 期下注完還能往回查得到錨點
        display_history = full_history[:max(limit, 20)]
        nums_only = [item['numbers'] for item in history_data]
        full_nums = [item['numbers'] for item in full_history]

        # 各區塊
        n_groups = get_n_groups(history_data)
        counts = plain_counts(nums_only)

        # 機率排行（Top 10 / Low 10）
        sorted_counts = sorted(
            [(n, counts.get(n, 0)) for n in [str(i).zfill(2) for i in range(1, 81)]],
            key=lambda x: x[1]
        )
        top10 = [{"num": n, "count": c} for n, c in sorted_counts[-10:][::-1]]
        low10 = [{"num": n, "count": c} for n, c in sorted_counts[:10]]

        prediction = analyze_strategy(nums_only, strategy, n_groups, ball_count)
        star_levels = analyze_star_levels(n_groups)
        strategies = get_strategy_analysis(nums_only, n_groups, counts)
        # 傳 full_nums 給回測冠軍 + 三人組（這 2 池需要 ≥ 40 期，不能受 limit 限制）
        expert = get_expert_strategies(nums_only, n_groups, expert_count, full_history_nums=full_nums)
        # bias 報告用全期統計（不受 limit 影響），讓樣本量盡量大
        bias_report = get_frequency_bias_report(full_nums)

        # 回測：最貴的部分，用 last_update 當 key 快取；切換 limit/strategy/ball 都命中
        backtest = {}
        best_strategy_prediction = None
        if run_backtest and len(full_nums) >= 10:
            backtest = _get_or_compute_backtest(full_nums, cache_signature)
            # 找回測 avg_hit 最高的策略 → 用同樣固定 seed 預測下一期 6 顆作為「推薦下注」
            best_key = max(backtest, key=lambda k: backtest[k]['avg_hit'])
            import random as _r
            rec_rng = _r.Random(369)  # 固定 seed → 同一期推薦穩定
            rec_pred = analyze_strategy(nums_only, best_key, n_groups, 6, rng=rec_rng)
            best_strategy_prediction = {
                "strategy": best_key,
                "avg_hit": backtest[best_key]['avg_hit'],
                "next_period": _next_period(full_history[0]['period']),
                "numbers": [p['num'] for p in rec_pred],
            }

        return jsonify({
            "last_period": full_history[0]['period'],
            "last_update": last_update,
            "current_limit": len(history_data),
            "history": display_history,
            "prob_rank": {"top10": top10, "low10": low10},
            "n_groups": n_groups,
            "prediction": prediction,
            "star_levels": star_levels,
            "strategies": strategies,
            "expert_strategies": expert,
            "bias_report": bias_report,
            "backtest": backtest,
            "recommended_bet": best_strategy_prediction,
        })
    except Exception as e:
        print(f"❌ /api/predict 錯誤：{type(e).__name__}: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/backtest', methods=['GET'])
def backtest_endpoint():
    try:
        strategy = request.args.get('strategy', 'hot')
        periods = int(request.args.get('periods', 30))
        lookback = int(request.args.get('lookback', 50))
        ball_count = int(request.args.get('ball_count', 6))

        full_history, _ = _load_history()
        if not full_history:
            return jsonify({"error": "資料庫為空"}), 200

        full_nums = [item['numbers'] for item in full_history]
        result = backtest_strategy(full_nums, strategy, periods, lookback, ball_count)
        return jsonify({"strategy": strategy, **result})
    except Exception as e:
        print(f"❌ /api/backtest 錯誤：{type(e).__name__}: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health():
    """Render 保活用 — 不碰 Firebase，純回 200"""
    return jsonify({"status": "ok"})


# ---------- 即時爬蟲端點 ----------

_SCRAPE_SOURCE = "https://lotto.auzonet.com/bingobingoV1.php"
_SCRAPE_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_SCRAPE_THROTTLE_SEC = 30   # 30 秒節流，防止狂按 / UptimeRobot 重複觸發
_SCRAPE_MAX_HISTORY = 100
# Render 預設 UTC，但顯示要給台灣使用者看 → 寫入用 UTC+8
_TPE_TZ = _dt.timezone(_dt.timedelta(hours=8))


def _now_taipei_str():
    """回傳台灣時間字串，給 last_update 用"""
    return _dt.datetime.now(_TPE_TZ).strftime('%Y-%m-%d %H:%M:%S')


def _scrape_records():
    """從來源網站靜態 HTML 抓最近期數；回傳 list of {period, numbers}

    來源 HTML 結構：<td><b>115031155</b><br/>15:00</td>
    必須從 <b> 標籤內取期數，否則 get_text() 會把後面時間 "15:00" 黏進來，
    被 regex \\d{9,10} 誤抓成 10 位數（含時間 HH 的第一位）。
    """
    resp = requests.get(_SCRAPE_SOURCE, headers={"User-Agent": _SCRAPE_UA}, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    rows = soup.find_all("tr", class_="bingo_text_row")

    records = []
    for row in rows[:_SCRAPE_MAX_HISTORY]:
        cols = row.find_all("td")
        if len(cols) < 2:
            continue
        # 從 <b> 標籤拿期數（避免黏到時間欄）
        b_tag = cols[0].find("b")
        if not b_tag:
            continue
        period = b_tag.get_text(strip=True)
        if not re.fullmatch(r'\d{8,10}', period):
            continue

        ball_td = row.find("td", class_="BBALL")
        if not ball_td:
            continue
        text = ball_td.get_text(separator=' ')
        raw_nums = re.findall(r'\b(\d{1,2})\b', text)
        found = sorted(set(n.zfill(2) for n in raw_nums if 1 <= int(n) <= 80))
        if len(found) >= 20:
            records.append({"period": period, "numbers": found[:20]})
    return records


@app.route('/api/scrape', methods=['GET', 'POST'])
def scrape():
    """立即抓最新一期，30 秒節流避免被狂打。給 UptimeRobot + 前端立即同步鈕用。"""
    try:
        _init_firebase()
        ref = db.reference('bingo_data')
        existing = ref.get() or {}
        existing_records = existing.get('records', [])
        existing_last = existing.get('last_update')

        # 30 秒節流（比對台灣時間；舊資料是 UTC 字串會算出負值 age → fallthrough 去刷新）
        if existing_last:
            try:
                last_dt = _dt.datetime.strptime(existing_last, '%Y-%m-%d %H:%M:%S')
                now_naive_tpe = _dt.datetime.now(_TPE_TZ).replace(tzinfo=None)
                age_sec = (now_naive_tpe - last_dt).total_seconds()
                if 0 <= age_sec < _SCRAPE_THROTTLE_SEC:
                    return jsonify({
                        "status": "throttled",
                        "message": f"上次同步 {int(age_sec)} 秒前，{_SCRAPE_THROTTLE_SEC} 秒內請勿重複觸發",
                        "last_update": existing_last,
                        "last_period": existing_records[0]['period'] if existing_records else None,
                    }), 200
            except (ValueError, TypeError):
                pass  # 解析失敗就 fallthrough 去爬

        # 開爬
        new_records = _scrape_records()
        if not new_records:
            return jsonify({"status": "error", "message": "來源網站抓不到任何紀錄"}), 502

        # 一次性遷移：舊資料的 period 是 10 位（regex bug 把時間第一位黏進來），
        # 新爬下來的是正確 9 位 — 過濾掉舊的不一致格式避免污染排序
        new_period_len = len(new_records[0]['period'])
        existing_records = [r for r in existing_records if len(r.get('period', '')) == new_period_len]

        # 合併去重，排序，取前 100
        seen = set()
        merged = []
        for r in new_records + existing_records:
            if r['period'] not in seen:
                seen.add(r['period'])
                merged.append(r)
        merged = sorted(merged, key=lambda x: x['period'], reverse=True)[:_SCRAPE_MAX_HISTORY]

        now_str = _now_taipei_str()
        ref.set({"last_update": now_str, "records": merged})

        # 判斷是否真的有更新（最新期數有沒有變）
        prev_top = existing_records[0]['period'] if existing_records else None
        new_top = merged[0]['period']
        return jsonify({
            "status": "ok",
            "updated": prev_top != new_top,
            "scraped_count": len(new_records),
            "total_count": len(merged),
            "last_update": now_str,
            "last_period": new_top,
            "previous_period": prev_top,
        }), 200

    except requests.exceptions.RequestException as e:
        return jsonify({"status": "error", "message": f"來源網站連線失敗：{type(e).__name__}: {e}"}), 502
    except Exception as e:
        print(f"❌ /api/scrape 錯誤：{type(e).__name__}: {e}")
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"{type(e).__name__}: {e}"}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5001, host='0.0.0.0')
