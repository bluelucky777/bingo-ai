"""
369 BINGO Flask API
- /api/predict: 號碼分析 + 預測 + 星級 + 攻略 + 脆友推薦 + 回測（一次回完整 payload）
- /api/backtest: 單純回測指定策略
- 資料來源：Firebase RTDB（不再讀本地 history.json）
"""
import json
import os
import traceback

import firebase_admin
from firebase_admin import credentials, db
from flask import Flask, jsonify, request
from flask_cors import CORS

from back import (
    analyze_strategy,
    analyze_star_levels,
    backtest_strategy,
    get_expert_strategies,
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

        # 分析範圍受 limit 控制（給機率排行 / n_groups / 策略預測用）
        history_data = full_history[:limit]
        # 顯示與下注結算用：至少 60 期，與 limit 解耦
        # 避免使用者選 limit=10 時，10 期下注因 history 太短永遠結不掉
        display_history = full_history[:max(limit, 60)]
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
        expert = get_expert_strategies(nums_only, n_groups, expert_count)

        # 回測（用全歷史，可省以加速）
        backtest = {}
        best_strategy_prediction = None
        if run_backtest and len(full_nums) >= 10:
            for s in ['hot', 'balanced', 'luck', 'pure_hot']:
                backtest[s] = backtest_strategy(full_nums, s, test_periods=30, lookback=50, ball_count=6)
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


if __name__ == '__main__':
    app.run(debug=True, port=5001, host='0.0.0.0')
