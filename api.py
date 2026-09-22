"""
369 BINGO Flask API
- 包含最新「智慧快取 (Cache)」機制，保護伺服器免受重複運算過載
- /api/predict: 號碼分析 + 預測 + 星級 + 攻略 + 脆友推薦 + 回測 + 近期勝率追蹤
- 資料來源：Firebase RTDB
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
from flask import Flask, jsonify, request, send_from_directory
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
    calculate_tracking_win_rate,
)

app = Flask(__name__)

# CORS 設定
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
        raise RuntimeError("缺少環境變數 FIREBASE_CONFIG")
    if not db_url:
        raise RuntimeError("缺少環境變數 FIREBASE_DATABASE_URL")
    cred = credentials.Certificate(json.loads(cred_json))
    firebase_admin.initialize_app(cred, {'databaseURL': db_url})


def _load_history():
    """從 Firebase 讀；本機 dev fallback 到 history.json"""
    try:
        _init_firebase()
        snapshot = db.reference('bingo_data').get() or {}
        return snapshot.get('records', []), snapshot.get('last_update')
    except RuntimeError as e:
        if os.path.exists("history.json"):
            print(f"⚠️ Firebase 未設定，fallback 讀 history.json：{e}")
            with open("history.json", "r", encoding="utf-8") as f:
                return json.load(f), None
        raise

def _next_period(period_str):
    try:
        return str(int(period_str) + 1)
    except (ValueError, TypeError):
        return None


# ==========================================
# 🛡️ 智慧快取系統 (Cache Shield) 🛡️
# ==========================================
_BACKTEST_CACHE = {}
_PREDICT_CACHE = {}
_CURRENT_CACHE_PERIOD = None

def _get_or_compute_backtest(full_nums, last_update):
    key = (last_update, len(full_nums))
    if key in _BACKTEST_CACHE:
        return _BACKTEST_CACHE[key]
    result = {}
    for s in ['pure_hot', 'hot', 'markov', 'dual_window']:
        result[s] = backtest_strategy(full_nums, s, test_periods=10, lookback=50, ball_count=6)
    _BACKTEST_CACHE[key] = result
    
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

        # === 快取攔截機制 START ===
        global _PREDICT_CACHE, _CURRENT_CACHE_PERIOD
        latest_period = full_history[0]['period']

        # 如果開獎期數更新了，立刻把舊的黑板（快取）擦掉
        if _CURRENT_CACHE_PERIOD != latest_period:
            _PREDICT_CACHE.clear()
            _CURRENT_CACHE_PERIOD = latest_period
            print(f"🔄 偵測到新期數 {latest_period}，已清空舊快取。")

        # 為這次使用者的選項打造一把專屬鑰匙
        cache_key = (strategy, limit, ball_count, expert_count, run_backtest)

        # 檢查黑板上有沒有算好的答案？有就直接秒回傳！
        if cache_key in _PREDICT_CACHE:
            print(f"⚡ 快取命中！瞬間回傳 {latest_period} 的運算結果。 (策略: {strategy}, 球數: {ball_count})")
            return jsonify(_PREDICT_CACHE[cache_key])
        # === 快取攔截機制 END ===

        print(f"⏳ 尚無快取，開始進行龐大運算... (策略: {strategy}, 球數: {ball_count})")

        history_data = full_history[:limit]
        display_history = full_history[:max(limit, 20)]
        nums_only = [item['numbers'] for item in history_data]
        full_nums = [item['numbers'] for item in full_history]

        n_groups = get_n_groups(history_data)
        counts = plain_counts(nums_only)

        sorted_counts = sorted(
            [(n, counts.get(n, 0)) for n in [str(i).zfill(2) for i in range(1, 81)]],
            key=lambda x: x[1]
        )
        top10 = [{"num": n, "count": c} for n, c in sorted_counts[-10:][::-1]]
        low10 = [{"num": n, "count": c} for n, c in sorted_counts[:10]]

        prediction = analyze_strategy(nums_only, strategy, n_groups, ball_count)
        star_levels = analyze_star_levels(n_groups)
        strategies = get_strategy_analysis(nums_only, n_groups, counts)
        expert = get_expert_strategies(nums_only, n_groups, expert_count, full_history_nums=full_nums)
        bias_report = get_frequency_bias_report(full_nums)
        tracking_win_rate = calculate_tracking_win_rate(full_history)

        backtest = {}
        best_strategy_prediction = None
        if run_backtest and len(full_nums) >= 10:
            backtest = _get_or_compute_backtest(full_nums, last_update)
            if backtest:
                best_key = max(backtest, key=lambda k: backtest[k]['avg_hit'])
                import random as _r
                rec_rng = _r.Random(369)
                rec_pred = analyze_strategy(nums_only, best_key, n_groups, 6, rng=rec_rng)
                best_strategy_prediction = {
                    "strategy": best_key,
                    "avg_hit": backtest[best_key]['avg_hit'],
                    "next_period": _next_period(full_history[0]['period']),
                    "numbers": [p['num'] for p in rec_pred],
                }

        # 整理最終報告
        response_data = {
            "last_period": latest_period,
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
            "tracking_win_rate": tracking_win_rate,
        }

        # 將算好的報告抄在黑板上（存入快取）
        _PREDICT_CACHE[cache_key] = response_data
        
        return jsonify(response_data)

    except Exception as e:
        print(f"❌ /api/predict 錯誤：{type(e).__name__}: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/scrape', methods=['GET', 'POST'])
def scrape():
    # ...(略) 爬蟲邏輯維持不變，這裡是爬蟲自動更新 Firebase 的地方
    _SCRAPE_SOURCE = "https://lotto.auzonet.com/bingobingoV1.php"
    _SCRAPE_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    _SCRAPE_THROTTLE_SEC = 30
    _SCRAPE_MAX_HISTORY = 100
    _TPE_TZ = _dt.timezone(_dt.timedelta(hours=8))

    def _now_taipei_str():
        return _dt.datetime.now(_TPE_TZ).strftime('%Y-%m-%d %H:%M:%S')

    try:
        _init_firebase()
        ref = db.reference('bingo_data')
        existing = ref.get() or {}
        existing_records = existing.get('records', [])
        existing_last = existing.get('last_update')

        if existing_last:
            try:
                last_dt = _dt.datetime.strptime(existing_last, '%Y-%m-%d %H:%M:%S')
                now_naive_tpe = _dt.datetime.now(_TPE_TZ).replace(tzinfo=None)
                age_sec = (now_naive_tpe - last_dt).total_seconds()
                if 0 <= age_sec < _SCRAPE_THROTTLE_SEC:
                    return jsonify({"status": "throttled", "message": f"上次同步 {int(age_sec)} 秒前"}), 200
            except (ValueError, TypeError):
                pass

        resp = requests.get(_SCRAPE_SOURCE, headers={"User-Agent": _SCRAPE_UA}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.find_all("tr", class_="bingo_text_row")

        records = []
        for row in rows[:_SCRAPE_MAX_HISTORY]:
            cols = row.find_all("td")
            if len(cols) < 2: continue
            b_tag = cols[0].find("b")
            if not b_tag: continue
            period = b_tag.get_text(strip=True)
            if not re.fullmatch(r'\d{8,10}', period): continue
            ball_td = row.find("td", class_="BBALL")
            if not ball_td: continue
            text = ball_td.get_text(separator=' ')
            raw_nums = re.findall(r'\b(\d{1,2})\b', text)
            found = sorted(set(n.zfill(2) for n in raw_nums if 1 <= int(n) <= 80))
            if len(found) >= 20:
                records.append({"period": period, "numbers": found[:20]})

        if not records:
            return jsonify({"status": "error", "message": "抓不到紀錄"}), 502

        new_period_len = len(records[0]['period'])
        existing_records = [r for r in existing_records if len(r.get('period', '')) == new_period_len]

        seen = set()
        merged = []
        for r in records + existing_records:
            if r['period'] not in seen:
                seen.add(r['period'])
                merged.append(r)
        merged = sorted(merged, key=lambda x: x['period'], reverse=True)[:_SCRAPE_MAX_HISTORY]

        now_str = _now_taipei_str()
        ref.set({"last_update": now_str, "records": merged})

        prev_top = existing_records[0]['period'] if existing_records else None
        new_top = merged[0]['period']
        return jsonify({
            "status": "ok",
            "updated": prev_top != new_top,
            "last_period": new_top,
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/')
def serve_index():
    """首頁路徑，直接提供同資料夾下的 index.html"""
    return send_from_directory('.', 'index.html')


if __name__ == '__main__':
    app.run(debug=True, port=5001, host='0.0.0.0')
