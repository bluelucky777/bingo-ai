# 369 BINGO AI 預測網站

## 架構

```
┌──────────────┐    HTTP    ┌────────────────────┐
│  index.html  │ ─────────> │  Flask API         │
│  (Vercel)    │ <───────── │  (Render)          │
└──────┬───────┘  JSON      │  api.py + back.py  │
       │                    └──────────┬─────────┘
       │ realtime listen               │
       v                               v read
┌─────────────────────────────────────────────┐
│        Firebase Realtime Database           │
│        (bingo_data/records[])               │
└─────────────────────────────────────────────┘
                ^
                │ write (Admin SDK)
                │
┌──────────────────────────────┐
│  GitHub Actions (每 5 分鐘)  │
│  bg.py 爬蟲 → Firebase       │
└──────────────────────────────┘
```

- **前端**：[index.html](index.html) 純靜態，Vercel 託管。Firebase 監聽只當「期數變化通知」，所有運算走 Flask API。
- **後端**：[api.py](api.py) Flask + [back.py](back.py) 核心算法，部署 Render。
- **爬蟲**：[bg.py](bg.py) Selenium 抓 lotto.auzonet.com，GitHub Actions 每 5 分鐘排程跑、推 Firebase。
- **資料**：Firebase RTDB `bingo_data/records[]`（最多 100 期）。

---

## 部署步驟

### 1. Firebase 設定

1. Firebase Console → 你的專案 → Realtime Database → **規則**：
   ```json
   {
     "rules": {
       ".read": true,
       ".write": false,
       "bingo_data": {
         ".read": true,
         ".write": false
       }
     }
   }
   ```
   前端唯讀；寫入端走 Admin SDK 不受 rules 限制。

2. 專案設定 → 服務帳戶 → 產生新私密金鑰 → 下載 service-account.json
3. 把整個 JSON 內容轉為單行字串備用（之後設環境變數用）

### 2. GitHub 設定

把專案 push 到 GitHub repo，然後：

1. Settings → Secrets and variables → Actions → **New repository secret**：
   - `FIREBASE_CONFIG`: 貼上 service-account.json 整個 JSON 字串
   - `FIREBASE_DATABASE_URL`: `https://bingo-ai-360ad-default-rtdb.firebaseio.com`
   - `RENDER_API_URL`: 你的 Render URL（部署完才知道，例 `https://369-bingo-ai.onrender.com`）

2. Actions tab → 確認 `Fetch BINGO Data` workflow 啟用
3. 手動觸發一次 (`workflow_dispatch`) 確認爬蟲能寫進 Firebase

### 3. Render 部署（後端 Flask API）

1. Render Dashboard → New → Web Service → 連 GitHub repo
2. 應該會自動讀到 [render.yaml](render.yaml)
3. Environment 區設環境變數：
   - `FIREBASE_CONFIG`: 同上 JSON
   - `FIREBASE_DATABASE_URL`: 同上 URL
   - `ALLOWED_ORIGINS`: 部署完前端後填，例 `https://xxx.vercel.app`
4. Deploy → 拿到 URL，例 `https://369-bingo-ai.onrender.com`
5. 測試 `curl https://369-bingo-ai.onrender.com/api/health` 應回 `{"status":"ok"}`

### 4. Vercel 部署（前端）

1. 編輯 [index.html](index.html) 把 `API_BASE` 改成你的 Render URL：
   ```js
   : 'https://你的-render-app.onrender.com';
   ```
2. Vercel → Import Project → 選 GitHub repo → Deploy
3. [vercel.json](vercel.json) 已設定為純靜態託管

### 5. 回填環境變數

- Render dashboard 把 `ALLOWED_ORIGINS` 設為 Vercel 給的網址
- GitHub Secrets 把 `RENDER_API_URL` 設為 Render URL（給保活 ping 用）

---

## 本機開發

```bash
cd "/Users/roy/Downloads/python in/roy big"

# 安裝
pip install -r requirements.txt

# 設環境變數（FIREBASE_CONFIG 是整個 service account JSON 字串）
export FIREBASE_CONFIG='{"type":"service_account",...}'
export FIREBASE_DATABASE_URL='https://bingo-ai-360ad-default-rtdb.firebaseio.com'

# 跑爬蟲（手動拉一次）
python bg.py

# 啟動 Flask API
python api.py  # http://localhost:5001

# 另開 terminal 跑前端靜態 server
python -m http.server 8000
# 瀏覽器開 http://localhost:8000
```

API 測試：
```bash
curl 'http://localhost:5001/api/predict?strategy=hot&limit=10&ball_count=6'
curl 'http://localhost:5001/api/backtest?strategy=hot&periods=30'
curl 'http://localhost:5001/api/backtest?strategy=balanced&periods=30'
curl 'http://localhost:5001/api/backtest?strategy=luck&periods=30'
```

> **本機開發 fallback**：如果沒設 `FIREBASE_CONFIG` 但有 [history.json](history.json)，API 會自動 fallback 讀本地檔案，方便離線開發。

---

## 算法改進摘要

| 項目 | 之前 | 現在 |
|---|---|---|
| N3 拖號 | `+1 / +10` 鄰號（與需求不符） | 全歷史掃描「下一期同出」Top 15 |
| N1 定義 | 前後端不一致（2~3 次 vs ≥2 次） | 統一 ≥2 次 |
| N6 未開小號 | 1~10 且近 2 期未出 | 1~15 且近 5 期未出 |
| N5 破冰 | O(n × 80) 重複線性掃 | 預建 last_seen dict O(n + 80 log 80) |
| 抽樣 | `random.sample` 均勻 | `weighted_pick` 加權無放回 |
| 期距權重 | 全部期數同權重 | `e^(-i/10)` 遞減 |
| 同出矩陣 | 無 | 有（80×80 加權矩陣） |
| 回測 | 無 | `/api/backtest` 三策略並排比較 |
| 相反牌 | 01↔10 到 04↔40 | 01↔10 到 08↔80 |
| G4 fallback | 寫死 "01" | 取目前最熱號 |

---

## 主要檔案

| 檔案 | 角色 |
|---|---|
| [index.html](index.html) | 前端 — 純 view，所有運算走 API |
| [api.py](api.py) | Flask API — `/api/predict`、`/api/backtest`、`/api/health` |
| [back.py](back.py) | 算法核心 — N1-N7、星級、G1-G4、三策略、脆友 10 池、回測 |
| [bg.py](bg.py) | Selenium 爬蟲 — GitHub Actions 排程跑 |
| [.github/workflows/fetch.yml](.github/workflows/fetch.yml) | GitHub Actions 排程 + Render 保活 |
| [render.yaml](render.yaml) | Render Web Service 設定 |
| [vercel.json](vercel.json) | Vercel 純靜態託管 |
| [requirements.txt](requirements.txt) | Python 套件 |
| [_archive/](_archive/) | 早期 React 試做版（已棄用） |
