"""
369 BINGO AI 核心算法
- N1-N7 號碼屬性分組
- G1-G4 攻略
- 三策略預測（追熱門 / 均衡 / 拼運氣）
- 脆友 10 個推薦池
- 加權抽樣 + 期距遞減 + 同出矩陣
- 策略回測（avg_hit / high_hit_rate）
"""
import collections
import math
import random

ALL_NUMS = [str(i).zfill(2) for i in range(1, 81)]
DECAY_TAU = 10.0   # 期距遞減 e^(-i/tau)，10 表示第 10 期權重約 0.37
HIGH_HIT_THRESHOLD = 3  # 6 顆中 3+ 算「高命中」
# 為什麼 3：25% 機率 × 6 顆 = 期望 1.5 命中，3+ 約 17%/期；
# 10 期回測下 5+ 命中率僅 4%（≈0.4/10），訊號太微弱無法分辨策略差異


# ---------- 基礎工具 ----------

def _period_weight(i):
    """第 i 期（i=0 為最新）的時間衰減權重"""
    return math.exp(-i / DECAY_TAU)


def compute_weighted_counts(history_nums):
    """加權出現次數（最近期權重高）"""
    weighted = collections.defaultdict(float)
    for i, draw in enumerate(history_nums):
        w = _period_weight(i)
        for n in draw:
            weighted[n] += w
    return weighted


def plain_counts(history_nums):
    """未加權次數（顯示用）"""
    flat = [n for sub in history_nums for n in sub]
    return collections.Counter(flat)


def build_cooc_matrix(history_nums):
    """同出矩陣：cooc[a][b] = 號碼 a, b 同期出現的加權次數"""
    cooc = collections.defaultdict(lambda: collections.defaultdict(float))
    for i, draw in enumerate(history_nums):
        w = _period_weight(i)
        unique = list(set(draw))
        for a in range(len(unique)):
            for b in range(a + 1, len(unique)):
                na, nb = unique[a], unique[b]
                cooc[na][nb] += w
                cooc[nb][na] += w
    return cooc


def weighted_pick(pool_with_weights, k, exclude, rng=None):
    """
    加權無放回抽 k 顆。
    pool_with_weights: [(num, weight), ...]
    exclude: 已選號碼 list（in-place 更新）
    rng: 可選的 random.Random 實例（回測時固定 seed 用）
    """
    r = rng or random
    candidates = [(n, w) for n, w in pool_with_weights if n not in exclude and w > 0]
    if not candidates:
        return []
    selected = []
    for _ in range(min(k, len(candidates))):
        total = sum(w for _, w in candidates)
        if total <= 0:
            break
        pick = r.uniform(0, total)
        acc = 0
        for idx, (n, w) in enumerate(candidates):
            acc += w
            if acc >= pick:
                selected.append(n)
                exclude.append(n)
                candidates.pop(idx)
                break
    return selected


# ---------- N1~N7 號碼屬性 ----------

def get_n_groups(full_history_data):
    """
    N1 溫熱：出現 ≥2 次（前後端對齊）
    N2 回歸：出現 2 次但本期沒開
    N3 拖號（真正定義）：歷史中最新期號碼的「下一期」最常跟出的號碼 Top 15
    N4 共伴：出現 ≥2 次（同出矩陣輔助）
    N5 破冰：最久沒出（last_seen_index 最大）Top 15
    N6 未開小號：≤15 且近 5 期未出
    N7 5熱：近 5 期出現 ≥2 次
    """
    history_nums = [item['numbers'] for item in full_history_data]
    if not history_nums:
        return {f"n{i}": [] for i in range(1, 8)}

    counts = plain_counts(history_nums)
    last_draw = history_nums[0]
    last_5_set = set(n for sub in history_nums[:5] for n in sub)

    # N1: 溫熱 ≥2 次
    n1_raw = [n for n, c in counts.items() if c >= 2]

    # N2: 回歸 (≥2 次但本期沒開)
    n2_raw = [n for n, c in counts.items() if c >= 2 and n not in last_draw]

    # N3: 拖號（真正定義 — 全歷史掃描）
    # 對於上期每個號 n，找出 n 在歷史中出現的所有期 i，統計 i-1 期（更早的下一期 = 拖出的號）
    # 注意 history_nums[0] 是最新，所以「下一期」= history_nums[i-1]
    trail_freq = collections.Counter()
    for n in last_draw:
        for i in range(1, len(history_nums)):
            if n in history_nums[i]:
                # i-1 是更靠近現在的期數（= n 出現後的下一期）
                for trail_n in history_nums[i - 1]:
                    if trail_n != n:
                        trail_freq[trail_n] += 1
    n3_raw = [n for n, _ in trail_freq.most_common(15)]

    # N4: 共伴 ≥2 次（基礎版，準確版用 build_cooc_matrix）
    n4_raw = [n for n, c in counts.items() if c >= 2]

    # N5: 破冰 — 預建 last_seen dict（O(n)）
    last_seen = {n: 999 for n in ALL_NUMS}
    for i, draw in enumerate(history_nums):
        for n in draw:
            if last_seen[n] == 999:
                last_seen[n] = i
    # 沒出現過的維持 999；按 last_seen 由大到小（最久沒出）取前 15
    n5_raw = sorted(ALL_NUMS, key=lambda x: last_seen[x], reverse=True)[:15]

    # N6: 未開小號 ≤15 且近 5 期未出
    n6_raw = [str(i).zfill(2) for i in range(1, 16) if str(i).zfill(2) not in last_5_set]

    # N7: 近 5 期出現 ≥2 次
    counts_5 = plain_counts(history_nums[:5])
    n7_raw = [n for n, c in counts_5.items() if c >= 2]

    def limit_10(num_list):
        if len(num_list) > 10:
            return random.sample(num_list, 10)
        return num_list

    return {
        "n1": [{"num": n, "count": counts.get(n, 0)} for n in limit_10(n1_raw)],
        "n2": [{"num": n, "count": counts.get(n, 0)} for n in limit_10(n2_raw)],
        "n3": [{"num": n, "count": counts.get(n, 0)} for n in limit_10(n3_raw)],
        "n4": [{"num": n, "count": counts.get(n, 0)} for n in limit_10(n4_raw)],
        "n5": [{"num": n, "count": counts.get(n, 0)} for n in limit_10(n5_raw)],
        "n6": [{"num": n, "count": counts.get(n, 0)} for n in limit_10(n6_raw)],
        "n7": [{"num": n, "count": counts.get(n, 0)} for n in limit_10(n7_raw)],
    }


# ---------- 星級配號 ----------

def analyze_star_levels(n_groups):
    """2-10 星配號公式（pick 內部用 random.sample，保持原有行為）"""
    def pick(key, count):
        pool = [x['num'] for x in n_groups.get(key, [])]
        if not pool:
            return ["--"] * count
        return random.sample(pool, min(len(pool), count))

    return {
        "2星": pick('n1', 2),
        "3星": pick('n1', 2) + pick('n5', 1),
        "4星": pick('n1', 2) + pick('n3', 1) + pick('n5', 1),
        "5星": pick('n1', 2) + pick('n3', 2) + pick('n5', 1),
        "6星": pick('n1', 3) + pick('n3', 2) + pick('n5', 1),
        "7星": pick('n3', 2) + pick('n5', 2) + pick('n4', 2) + pick('n6', 1),
        "8星": pick('n3', 2) + pick('n5', 2) + pick('n4', 1) + pick('n6', 1) + pick('n7', 2),
        "10星": pick('n1', 2) + pick('n2', 1) + pick('n3', 2) + pick('n4', 2)
                + pick('n5', 1) + pick('n6', 1) + pick('n7', 1),
    }


# ---------- G1-G4 攻略 ----------

# 相反牌完整版：01↔10、02↔20 … 08↔80（09↔90 超出 80 範圍排除）
MIRRORS = {f"0{i}": f"{i}0" for i in range(1, 9)}
MIRRORS.update({f"{i}0": f"0{i}" for i in range(1, 9)})


def get_strategy_analysis(history_data, n_groups, counts):
    """G1-G4 攻略邏輯"""
    last_draw = history_data[0] if history_data else []

    # G1 同出 / 熱號（N7 前 6）
    g1 = [x['num'] for x in n_groups.get('n7', [])[:6]]

    # G2 連號尾數
    tails = set()
    s_last = sorted(int(n) for n in last_draw)
    for i in range(len(s_last) - 1):
        if s_last[i + 1] == s_last[i] + 1:
            tails.add(str(s_last[i] % 10))
    g2 = [n for n in ALL_NUMS if n[-1] in tails][:8]

    # G3 相反牌
    g3 = [MIRRORS[n] for n in last_draw if n in MIRRORS]

    # G4 主隻搭配（主隻 + N2 前 5）
    main = g1[0] if g1 else (counts.most_common(1)[0][0] if counts else "01")
    g4 = [main] + [x['num'] for x in n_groups.get('n2', [])[:5]]

    return {"g1": g1, "g2": g2, "g3": g3, "g4": g4}


# ---------- 三策略預測 ----------

def _to_weight_pool(items, weighted_counts):
    """[{num, count}] or [str] → [(num, weighted_count)]"""
    pool = []
    for item in items:
        n = item['num'] if isinstance(item, dict) else item
        pool.append((n, weighted_counts.get(n, 0.1)))  # 0.1 floor 避免從沒出現的號碼權重 0
    return pool


# 球數縮減優先級（read.md 原始定義：高機率 > 拖號 > 共伴 > 熱門）
# 數字越小 = 越優先保留（球數減少時最後被丟）
PRIORITY = {
    'high': 1,   # 高機率
    'n3': 2,     # 拖號
    'n4': 3,     # 共伴
    'n2': 4,     # 熱門類（回歸）
    'n5': 4,     # 熱門類（破冰）
    'n6': 4,     # 熱門類（未開小號）
    'n7': 4,     # 熱門類（5熱）
}

# 各策略 6 球組成（list of (group_key, slot_count)）
STRATEGY_COMPOSITION = {
    'hot':      [('high', 2), ('n3', 2), ('n4', 1), ('n7', 1)],
    'balanced': [('high', 1), ('n3', 1), ('n4', 1), ('n2', 2), ('n6', 1)],
    'luck':     [('high', 1), ('n6', 2), ('n4', 1), ('n5', 1), ('n7', 1)],
    'pure_hot': [('high', 6)],  # 純熱門：6 顆全部從加權熱號池抽
}


def _consensus_pick(history_nums, n_groups, ball_count, rng):
    """🎯 共識挑：跑 4 個基礎策略各抽 10 顆，依投票數 + 加權頻率排序取 ball_count

    理論：多策略都看好的號碼有更強的「綜合訊號」（雖然數學期望仍 25%）
    """
    base_strategies = ['hot', 'balanced', 'luck', 'pure_hot']
    votes = collections.Counter()
    for s in base_strategies:
        # 用大球數抽提高交集機會
        picks = analyze_strategy(history_nums, s, n_groups, ball_count=10, rng=rng)
        for p in picks:
            votes[p['num']] += 1
    weighted = compute_weighted_counts(history_nums)
    # tie-break：投票相同時看加權出現次數
    ranked = sorted(votes.items(), key=lambda x: (-x[1], -weighted.get(x[0], 0)))
    return [n for n, _ in ranked[:ball_count]]


def _parity_zone_pick(weighted, ball_count, rng):
    """🌐 區間平衡：4 區（1-20/21-40/41-60/61-80）分配球數，區內按加權頻率抽

    分配規則：ball_count // 4 為底，餘數按順序灑前幾區（6 → 2+1+1+2 不對，是 2+2+1+1）
    """
    zones = [
        [n for n in ALL_NUMS if 1 <= int(n) <= 20],
        [n for n in ALL_NUMS if 21 <= int(n) <= 40],
        [n for n in ALL_NUMS if 41 <= int(n) <= 60],
        [n for n in ALL_NUMS if 61 <= int(n) <= 80],
    ]
    base = ball_count // 4
    extra = ball_count - base * 4
    counts_per_zone = [base + (1 if i < extra else 0) for i in range(4)]

    # weighted_pick 會把 picks 寫進 exclude 參數的 list，所以 selected 同時當 exclude 和 result
    # 不能再 extend(picks) 否則會 double-append（exclude 已被 mutated 過）
    selected = []
    for zone, k in zip(zones, counts_per_zone):
        if k <= 0:
            continue
        zone_pool = [(n, weighted.get(n, 0.1)) for n in zone]
        weighted_pick(zone_pool, k, selected, rng=rng)
    # 補不足（理論上不會發生，保險）
    if len(selected) < ball_count:
        all_pool = [(n, weighted.get(n, 0.1)) for n in ALL_NUMS]
        weighted_pick(all_pool, ball_count - len(selected), selected, rng=rng)
    return selected[:ball_count]


def _markov_pick(history_nums, ball_count, rng):
    """🔗 馬可夫鏈：對「上一期某球出 → 下一期某球出」做條件機率累計，挑高轉移分

    history_nums desc 排序：index 0 最新。第 i 期之後（更新）= i-1。
    """
    if len(history_nums) < 2:
        return []
    # trans[a][b]: 較舊期 a 出 → 較新期 b 出 的次數
    trans = collections.defaultdict(lambda: collections.Counter())
    for i in range(len(history_nums) - 1):
        newer_draw = history_nums[i]
        older_draw = history_nums[i + 1]
        for a in older_draw:
            for b in newer_draw:
                trans[a][b] += 1

    # 從「最新期出現的號碼」出發，累計轉移分數
    last_drawn = history_nums[0]
    scores = collections.Counter()
    for a in last_drawn:
        for b, cnt in trans.get(a, {}).items():
            scores[b] += cnt

    seen = set()
    picks = []
    for n, _ in scores.most_common():
        if n not in seen:
            seen.add(n)
            picks.append(n)
        if len(picks) >= ball_count:
            break
    # 補不足
    if len(picks) < ball_count:
        weighted = compute_weighted_counts(history_nums)
        remain = sorted(
            (n for n in ALL_NUMS if n not in seen),
            key=lambda n: -weighted.get(n, 0)
        )
        picks.extend(remain[:ball_count - len(picks)])
    return picks[:ball_count]


def analyze_strategy(history_nums, strategy, n_groups, ball_count=6, rng=None):
    """
    多策略預測 — 用加權抽樣 + 球數縮減優先級。
    strategy: hot / balanced / luck / random / pure_hot / consensus / parity_zone / markov
    球數減少時依優先權保留：高機率 > 拖號 > 共伴 > 熱門
    """
    r = rng or random
    weighted = compute_weighted_counts(history_nums)
    counts = plain_counts(history_nums)

    if strategy == "random":
        # 完全隨機（不參考任何頻率）
        picks = r.sample(ALL_NUMS, ball_count)
        return [{"num": n, "count": counts.get(n, 0)} for n in picks]

    if strategy == "consensus":
        picks = _consensus_pick(history_nums, n_groups, ball_count, r)
        return [{"num": n, "count": counts.get(n, 0)} for n in picks]

    if strategy == "parity_zone":
        picks = _parity_zone_pick(weighted, ball_count, r)
        return [{"num": n, "count": counts.get(n, 0)} for n in picks]

    if strategy == "markov":
        picks = _markov_pick(history_nums, ball_count, r)
        return [{"num": n, "count": counts.get(n, 0)} for n in picks]

    composition = STRATEGY_COMPOSITION.get(strategy)
    if not composition:
        return []

    # Step 1: 展開為 slots，每 slot = (priority, group_key)
    slots = []
    for group_key, count in composition:
        for _ in range(count):
            slots.append((PRIORITY[group_key], group_key))

    # Step 2: 按優先級升冪排序（小=保留優先），同優先級保留 composition 原順序
    slots.sort(key=lambda x: x[0])

    # Step 3: 取前 ball_count 個 slot（從尾端砍 = 砍最低優先）
    selected = slots[:ball_count]

    # Step 4: 統計每組需要抽幾顆
    needed = collections.Counter(s[1] for s in selected)

    # Step 5: 準備池子
    high_prob = sorted(weighted.items(), key=lambda x: x[1], reverse=True)[:15]
    high_prob_pool = [(n, w) for n, w in high_prob]
    pools_map = {
        'high': high_prob_pool,
        'n2': n_groups.get('n2', []),
        'n3': n_groups.get('n3', []),
        'n4': n_groups.get('n4', []),
        'n5': n_groups.get('n5', []),
        'n6': n_groups.get('n6', []),
        'n7': n_groups.get('n7', []),
    }

    used = []
    final = []

    def take(pool_items, k):
        if not pool_items or k <= 0:
            return
        if isinstance(pool_items[0], tuple):
            pool = pool_items
        else:
            pool = _to_weight_pool(pool_items, weighted)
        picks = weighted_pick(pool, k, used, rng=r)
        final.extend(picks)

    # Step 6: 按優先級順序從池子抽（高機率先抽，確保它一定有）
    for group_key in sorted(needed.keys(), key=lambda k: PRIORITY[k]):
        take(pools_map[group_key], needed[group_key])

    # Step 7: 補足球數（某些池子可能為空，從全號池兜底）
    if len(final) < ball_count:
        all_pool = [(n, weighted.get(n, 0.1)) for n in ALL_NUMS]
        take(all_pool, ball_count - len(final))

    return [{"num": n, "count": counts.get(n, 0)} for n in final[:ball_count]]


# ---------- 脆友 9 個攻略推薦池 ----------

def get_expert_strategies(history_nums, n_groups, ball_count=3, rng=None):
    """
    回傳 9 個推薦池各自挑 ball_count 顆球。
    顯示順序依數據評分（A → D）：
    本頻道的老祖宗 / Xij / 承 / Mix Lin / 承 2.0 / 小天 / 暴暴龍 / Yang / Bob
    """
    r = rng or random
    if not history_nums:
        return []

    latest = history_nums[0]
    prev = history_nums[1] if len(history_nums) > 1 else []
    weighted = compute_weighted_counts(history_nums)

    # Xij: 拖號（用 N3 的真正定義）
    xij_pool = [x['num'] for x in n_groups.get('n3', [])]

    # 承: 最新一期號碼在近 5 期的頻率排序（read.md 原始定義）
    h5 = history_nums[:5]
    f5 = plain_counts(h5)
    cheng_pool = sorted(latest, key=lambda x: -f5.get(x, 0)) if latest else []

    # 承 2.0: 近 20 期 >4 次 但近 10 期 ≤1 次（低頻熱號）
    h20, h10 = history_nums[:20], history_nums[:10]
    f20, f10 = plain_counts(h20), plain_counts(h10)
    cheng2_pool = [n for n in ALL_NUMS if f20.get(n, 0) > 4 and f10.get(n, 0) <= 1]
    cheng2_pool += [n for n, _ in f20.most_common(10) if n not in cheng2_pool]

    counts = plain_counts(history_nums)

    # 小天: 上期出現最多的尾數對應的所有號碼
    tail_map = collections.Counter(n[-1] for n in latest)
    if tail_map:
        top_tail = tail_map.most_common(1)[0][0]
        xiaotian_pool = [n for n in ALL_NUMS if n.endswith(top_tail)]
    else:
        xiaotian_pool = []

    # 暴暴龍: 跟上期任一號碼相鄰（±1）
    latest_int = {int(n) for n in latest}
    baobaolong_pool = [n for n in ALL_NUMS
                       if (int(n) - 1) in latest_int or (int(n) + 1) in latest_int]

    # Bob: 頭 10 + 尾 10
    bob_pool = ALL_NUMS[:10] + ALL_NUMS[-10:]

    # Yang: 同時 n-1 和 n+1 都在上期
    yang_pool = [n for n in ALL_NUMS
                 if (int(n) - 1) in latest_int and (int(n) + 1) in latest_int]
    if not yang_pool:
        yang_pool = baobaolong_pool  # 太嚴苛時降級

    # Mix Lin: 全期熱號 Top 10
    mixlin_pool = [n for n, _ in counts.most_common(10)]

    # 本頻道的老祖宗: 高頻 ∩ 共伴 ∩ 不冷（三項獨立訊號交集，空時降級 3 取 2）
    # 訊號 1：高頻 — 加權熱號 Top 25
    hot_top25 = set(n for n, _ in sorted(weighted.items(), key=lambda x: -x[1])[:25])
    # 訊號 2：共伴 — 與上期任一號碼的同出加權 Top 25
    cooc = build_cooc_matrix(history_nums)
    partner_scores = collections.Counter()
    for n in latest:
        for partner, score in cooc.get(n, {}).items():
            partner_scores[partner] += score
    partner_top25 = set(n for n, _ in partner_scores.most_common(25))
    # 訊號 3：不冷 — last_seen ≤ 5 期（避開長期冷號）
    last_seen = {n: 999 for n in ALL_NUMS}
    for i, draw in enumerate(history_nums):
        for n in draw:
            if last_seen[n] == 999:
                last_seen[n] = i
    warm_set = {n for n in ALL_NUMS if last_seen[n] <= 5}
    # 嚴格交集
    triangle_strict = list(hot_top25 & partner_top25 & warm_set)
    if len(triangle_strict) >= max(ball_count, 6):
        triangle_pool = triangle_strict
    else:
        # 降級：3 取 2（任 2 訊號同時成立）— 嚴格交集排前面
        relaxed = [
            n for n in ALL_NUMS
            if n not in triangle_strict
            and sum(n in s for s in (hot_top25, partner_top25, warm_set)) >= 2
        ]
        triangle_pool = triangle_strict + relaxed

    # 顯示順序依數據評分（A → D），老祖宗強制第一
    pools = [
        ("triangle", "本頻道的老祖宗", "高頻 ∩ 共伴 ∩ 不冷", triangle_pool),
        ("xij", "Xij:", "拖號（下一期同出 Top 15）", xij_pool),
        ("cheng", "承", "上期在近 5 期頻率", cheng_pool),
        ("mixlin", "Mix Lin", "全期熱號 Top 10", mixlin_pool),
        ("cheng2", "承 2.0", "近 20 期熱 + 近 10 期冷", cheng2_pool),
        ("xiaotian", "小天", "上期最熱尾數", xiaotian_pool),
        ("baobaolong", "暴暴龍", "上期 ±1 鄰號", baobaolong_pool),
        ("yang", "Yang", "上期 ±1 雙夾", yang_pool),
        ("bob", "Bob", "頭尾各 10 號", bob_pool),
    ]

    result = []
    for key, name, desc, pool in pools:
        if not pool:
            pool = list(ALL_NUMS)
        weighted_pool = _to_weight_pool(pool, weighted)
        picks = weighted_pick(weighted_pool, ball_count, exclude=[], rng=r)
        picks.sort()
        result.append({"key": key, "name": name, "desc": desc, "picks": picks})

    return result


# ---------- 回測 ----------

def backtest_strategy(full_history_nums, strategy, test_periods=30, lookback=50, ball_count=6):
    """
    對最近 test_periods 期，每期都用「該期之前的 lookback 期」跑預測，
    比對預測 ball_count 顆 vs 實際開出 20 顆，統計命中數。

    回傳：
      avg_hit: 平均命中數
      high_hit_rate: 5 顆以上命中的期數比例
      total_periods: 實際參與回測的期數
    """
    # 資料不足時動態調整：優先保留 test_periods，lookback 縮到剩下夠用即可
    # 至少 lookback ≥ 5 才有統計意義
    available = len(full_history_nums)
    if available < test_periods + lookback:
        if available >= test_periods + 5:
            lookback = available - test_periods  # 縮 lookback
        else:
            test_periods = max(0, available - 5)  # 連 test_periods 都要縮
            lookback = available - test_periods
    if test_periods <= 0 or lookback < 5:
        return {"avg_hit": 0.0, "high_hit_rate": 0.0, "total_periods": 0}

    rng = random.Random(42)  # 固定 seed → 結果穩定
    hits = []
    for t in range(test_periods):
        # 第 t 期是「要被預測的目標」（從最新算起）
        # 拿 t+1 ~ t+lookback 期作為歷史
        history_slice = full_history_nums[t + 1: t + 1 + lookback]
        if len(history_slice) < 5:
            continue
        # 重建 n_groups 需要 dict 結構，但 backtest 只需要 numbers，包裝一下
        wrapped = [{"numbers": nums} for nums in history_slice]
        n_groups = get_n_groups(wrapped)
        prediction = analyze_strategy(history_slice, strategy, n_groups, ball_count, rng=rng)
        predicted_nums = {p['num'] for p in prediction}
        actual_nums = set(full_history_nums[t])
        hit = len(predicted_nums & actual_nums)
        hits.append(hit)

    if not hits:
        return {"avg_hit": 0.0, "high_hit_rate": 0.0, "total_periods": 0}

    avg_hit = sum(hits) / len(hits)
    high_hit_count = sum(1 for h in hits if h >= HIGH_HIT_THRESHOLD)
    high_hit_rate = high_hit_count / len(hits)

    return {
        "avg_hit": round(avg_hit, 2),
        "high_hit_rate": round(high_hit_rate, 3),
        "total_periods": len(hits),
        "high_hit_periods": high_hit_count,
    }
