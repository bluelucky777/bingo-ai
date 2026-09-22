
"""
369 BINGO AI 核心算法
- N1-N7 號碼屬性分組
- G1-G4 攻略
- 三策略預測（純熱門 / 追熱門 / 馬可夫 / 雙窗熱號）
- 脆友精銳推薦池 (已套用 100 期全視野與波段動態切割)
- 加權抽樣 + 期距遞減 + 同出矩陣
- 策略回測（avg_hit / high_hit_rate）
"""
import collections
import math
import random

ALL_NUMS = [str(i).zfill(2) for i in range(1, 81)]
DECAY_TAU = 10.0   
HIGH_HIT_THRESHOLD = 3  


# ---------- 基礎工具 ----------

def _period_weight(i):
    return math.exp(-i / DECAY_TAU)

def compute_weighted_counts(history_nums):
    weighted = collections.defaultdict(float)
    for i, draw in enumerate(history_nums):
        w = _period_weight(i)
        for n in draw:
            weighted[n] += w
    return weighted

def plain_counts(history_nums):
    flat = [n for sub in history_nums for n in sub]
    return collections.Counter(flat)

def build_cooc_matrix(history_nums):
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
    history_nums = [item['numbers'] for item in full_history_data]
    if not history_nums:
        return {f"n{i}": [] for i in range(1, 8)}

    counts = plain_counts(history_nums)
    last_draw = history_nums[0]
    last_5_set = set(n for sub in history_nums[:5] for n in sub)

    n1_raw = [n for n, c in counts.items() if c >= 2]
    n2_raw = [n for n, c in counts.items() if c >= 2 and n not in last_draw]

    trail_freq = collections.Counter()
    for n in last_draw:
        for i in range(1, len(history_nums)):
            if n in history_nums[i]:
                for trail_n in history_nums[i - 1]:
                    if trail_n != n:
                        trail_freq[trail_n] += 1
    n3_raw = [n for n, _ in trail_freq.most_common(15)]
    n4_raw = [n for n, c in counts.items() if c >= 2]

    last_seen = {n: 999 for n in ALL_NUMS}
    for i, draw in enumerate(history_nums):
        for n in draw:
            if last_seen[n] == 999:
                last_seen[n] = i
    n5_raw = sorted(ALL_NUMS, key=lambda x: last_seen[x], reverse=True)[:15]

    n6_raw = [str(i).zfill(2) for i in range(1, 16) if str(i).zfill(2) not in last_5_set]
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
MIRRORS = {f"0{i}": f"{i}0" for i in range(1, 9)}
MIRRORS.update({f"{i}0": f"0{i}" for i in range(1, 9)})

def get_strategy_analysis(history_data, n_groups, counts):
    last_draw = history_data[0] if history_data else []
    g1 = [x['num'] for x in n_groups.get('n7', [])[:6]]
    tails = set()
    s_last = sorted(int(n) for n in last_draw)
    for i in range(len(s_last) - 1):
        if s_last[i + 1] == s_last[i] + 1:
            tails.add(str(s_last[i] % 10))
    g2 = [n for n in ALL_NUMS if n[-1] in tails][:8]
    g3 = [MIRRORS[n] for n in last_draw if n in MIRRORS]
    main = g1[0] if g1 else (counts.most_common(1)[0][0] if counts else "01")
    g4 = [main] + [x['num'] for x in n_groups.get('n2', [])[:5]]
    return {"g1": g1, "g2": g2, "g3": g3, "g4": g4}

# ---------- AI 核心預測策略 ----------
def _to_weight_pool(items, weighted_counts):
    pool = []
    for item in items:
        n = item['num'] if isinstance(item, dict) else item
        pool.append((n, weighted_counts.get(n, 0.1)))
    return pool

PRIORITY = {
    'high': 1, 'n3': 2, 'n4': 3, 'n2': 4, 'n5': 4, 'n6': 4, 'n7': 4,
}

# 🌟 移除 balanced 與 luck，僅保留實戰菁英
STRATEGY_COMPOSITION = {
    'hot':      [('high', 2), ('n3', 2), ('n4', 1), ('n7', 1)],
    'pure_hot': [('high', 6)], 
}

def _parity_zone_pick(weighted, ball_count, rng):
    zones = [
        [n for n in ALL_NUMS if 1 <= int(n) <= 20],
        [n for n in ALL_NUMS if 21 <= int(n) <= 40],
        [n for n in ALL_NUMS if 41 <= int(n) <= 60],
        [n for n in ALL_NUMS if 61 <= int(n) <= 80],
    ]
    base = ball_count // 4
    extra = ball_count - base * 4
    counts_per_zone = [base + (1 if i < extra else 0) for i in range(4)]
    selected = []
    for zone, k in zip(zones, counts_per_zone):
        if k <= 0: continue
        zone_pool = [(n, weighted.get(n, 0.1)) for n in zone]
        weighted_pick(zone_pool, k, selected, rng=rng)
    if len(selected) < ball_count:
        all_pool = [(n, weighted.get(n, 0.1)) for n in ALL_NUMS]
        weighted_pick(all_pool, ball_count - len(selected), selected, rng=rng)
    return selected[:ball_count]

def _markov_pick(history_nums, ball_count, rng):
    if len(history_nums) < 2: return []
    trans = collections.defaultdict(lambda: collections.Counter())
    for i in range(len(history_nums) - 1):
        newer_draw = history_nums[i]
        older_draw = history_nums[i + 1]
        for a in older_draw:
            for b in newer_draw:
                trans[a][b] += 1
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
        if len(picks) >= ball_count: break
    if len(picks) < ball_count:
        weighted = compute_weighted_counts(history_nums)
        remain = sorted((n for n in ALL_NUMS if n not in seen), key=lambda n: -weighted.get(n, 0))
        picks.extend(remain[:ball_count - len(picks)])
    return picks[:ball_count]

def _dual_window_pick(history_nums, ball_count, rng):
    short_top = set(n for n, _ in plain_counts(history_nums[:5]).most_common(15))
    long_counts = plain_counts(history_nums[:30])
    long_top = set(n for n, _ in long_counts.most_common(15))
    intersect = short_top & long_top
    weighted = compute_weighted_counts(history_nums)
    picks = sorted(intersect, key=lambda n: -weighted.get(n, 0))[:ball_count]
    seen = set(picks)
    if len(picks) < ball_count:
        for n, _ in long_counts.most_common():
            if n not in seen:
                picks.append(n)
                seen.add(n)
            if len(picks) >= ball_count: break
    if len(picks) < ball_count:
        remain = sorted((n for n in ALL_NUMS if n not in seen), key=lambda n: -weighted.get(n, 0))
        picks.extend(remain[:ball_count - len(picks)])
    return picks[:ball_count]

def _apply_smart_filter(candidate_pool, ball_count):
    selected = []
    tail_counts = collections.Counter()
    odd_count, even_count, big_count, small_count = 0, 0, 0, 0
    for n in candidate_pool:
        if len(selected) == ball_count: break
        num_val = int(n)
        tail = n[-1]
        is_odd = (num_val % 2 != 0)
        is_big = (num_val > 40)
        if tail_counts[tail] >= 2: continue
        if ball_count >= 4:
            limit = ball_count - 1
            if is_odd and odd_count >= limit: continue
            if not is_odd and even_count >= limit: continue
            if is_big and big_count >= limit: continue
            if not is_big and small_count >= limit: continue
        selected.append(n)
        tail_counts[tail] += 1
        if is_odd: odd_count += 1
        else: even_count += 1
        if is_big: big_count += 1
        else: small_count += 1
    if len(selected) < ball_count:
        for n in candidate_pool:
            if n not in selected:
                selected.append(n)
            if len(selected) == ball_count: break
    return selected

def analyze_strategy(history_nums, strategy, n_groups, ball_count=6, rng=None):
    # 🌟 短線切割：純熱門/追熱門只看近 10 期
    if strategy in ['pure_hot', 'hot']:
        history_nums = history_nums[:10]

    r = rng or random
    weighted = compute_weighted_counts(history_nums)
    counts = plain_counts(history_nums)
    pool_size = max(ball_count + 10, 15)

    if strategy == "random":
        raw_picks = r.sample(ALL_NUMS, pool_size)
        final_picks = _apply_smart_filter(raw_picks, ball_count)
        return [{"num": n, "count": counts.get(n, 0)} for n in final_picks]

    if strategy == "markov":
        raw_picks = _markov_pick(history_nums, pool_size, r)
        final_picks = _apply_smart_filter(raw_picks, ball_count)
        return [{"num": n, "count": counts.get(n, 0)} for n in final_picks]

    if strategy == "dual_window":
        raw_picks = _dual_window_pick(history_nums, pool_size, r)
        final_picks = _apply_smart_filter(raw_picks, ball_count)
        return [{"num": n, "count": counts.get(n, 0)} for n in final_picks]

    composition = STRATEGY_COMPOSITION.get(strategy)
    if not composition:
        return []

    slots = []
    for group_key, count in composition:
        for _ in range(count):
            slots.append((PRIORITY[group_key], group_key))
    slots.sort(key=lambda x: x[0])
    selected = slots[:pool_size]
    needed = collections.Counter(s[1] for s in selected)
    high_prob = sorted(weighted.items(), key=lambda x: x[1], reverse=True)[:15]
    pools_map = {
        'high': [(n, w) for n, w in high_prob],
        'n2': n_groups.get('n2', []), 'n3': n_groups.get('n3', []),
        'n4': n_groups.get('n4', []), 'n5': n_groups.get('n5', []),
        'n6': n_groups.get('n6', []), 'n7': n_groups.get('n7', []),
    }

    used = []
    raw_final = []
    def take(pool_items, k):
        if not pool_items or k <= 0: return
        pool = pool_items if isinstance(pool_items[0], tuple) else _to_weight_pool(pool_items, weighted)
        picks = weighted_pick(pool, k, used, rng=r)
        raw_final.extend(picks)

    for group_key in sorted(needed.keys(), key=lambda k: PRIORITY[k]):
        take(pools_map[group_key], needed[group_key])
    if len(raw_final) < pool_size:
        take([(n, weighted.get(n, 0.1)) for n in ALL_NUMS], pool_size - len(raw_final))

    final_picks = _apply_smart_filter(raw_final, ball_count)
    return [{"num": n, "count": counts.get(n, 0)} for n in final_picks]


# ---------- 脆友攻略推薦池 ----------
def _compute_strategy_pools(history_nums, n_groups=None):
    if not history_nums: return {}
    latest = history_nums[0]
    weighted = compute_weighted_counts(history_nums)
    latest_int = {int(n) for n in latest}
    pools = {}

    c10 = plain_counts(history_nums[:10])
    g1_set = set(n for n, _ in c10.most_common(10))
    tails = set()
    if latest:
        s_last = sorted(int(n) for n in latest)
        for i in range(len(s_last) - 1):
            if s_last[i + 1] == s_last[i] + 1:
                tails.add(str(s_last[i] % 10))
    MIRRORS_DICT = {f"0{i}": f"{i}0" for i in range(1, 9)}
    MIRRORS_DICT.update({f"{i}0": f"0{i}" for i in range(1, 9)})
    g3_set = set(MIRRORS_DICT[n] for n in latest if n in MIRRORS_DICT)
    g4_set = set(n for n, c in c10.items() if c >= 2 and n not in latest)

    scores = collections.defaultdict(int)
    for n in ALL_NUMS:
        if n in g1_set: scores[n] += 2
        if n[-1] in tails: scores[n] += 1
        if n in g3_set: scores[n] += 2
        if n in g4_set: scores[n] += 2
    pools['g1_to_g5'] = sorted(ALL_NUMS, key=lambda x: (scores[x], c10.get(x, 0)), reverse=True)[:15]

    # 🌟 移除舊版 cheng (承) 與 xiaotian (小天)
    f20 = plain_counts(history_nums[:20])
    f10 = plain_counts(history_nums[:10])
    cheng2 = [n for n in ALL_NUMS if f20.get(n, 0) > 4 and f10.get(n, 0) <= 1]
    cheng2 += [n for n, _ in f20.most_common(10) if n not in cheng2]
    pools['cheng2'] = cheng2

    pools['baobaolong'] = [n for n in ALL_NUMS if (int(n) - 1) in latest_int or (int(n) + 1) in latest_int]

    hot_top25 = set(n for n, _ in sorted(weighted.items(), key=lambda x: -x[1])[:25])
    cooc = build_cooc_matrix(history_nums)
    partner_scores = collections.Counter()
    for n in latest:
        for partner, score in cooc.get(n, {}).items():
            partner_scores[partner] += score
    partner_top25 = set(n for n, _ in partner_scores.most_common(25))
    last_seen = {n: 999 for n in ALL_NUMS}
    for i, draw in enumerate(history_nums):
        for n in draw:
            if last_seen[n] == 999: last_seen[n] = i
    warm_set = {n for n in ALL_NUMS if last_seen[n] <= 5}
    triangle_strict = list(hot_top25 & partner_top25 & warm_set)
    if len(triangle_strict) >= 6:
        triangle_pool = triangle_strict
    else:
        relaxed = [n for n in ALL_NUMS if n not in triangle_strict and sum(n in s for s in (hot_top25, partner_top25, warm_set)) >= 2]
        triangle_pool = triangle_strict + relaxed
    pools['triangle'] = triangle_pool

    return pools

def _backtest_champion(history_nums, lookback=30):
    if len(history_nums) < lookback + 10: return None, None, {}
    name_map = {'cheng2': '承 2.0', 'baobaolong': '暴暴龍', 'triangle': '本頻道的老祖宗'}
    score_sums = collections.defaultdict(float)
    score_counts = collections.defaultdict(int)
    for i in range(lookback):
        past = history_nums[i + 1:]
        if not past: continue
        actual = set(history_nums[i])
        past_pools = _compute_strategy_pools(past, n_groups=None)
        for name, pool_set in past_pools.items():
            unique = set(pool_set)
            if not unique: continue
            lift = len(unique & actual) / (len(unique) * 0.25)
            score_sums[name] += lift
            score_counts[name] += 1
    avg_scores = {k: score_sums[k] / score_counts[k] for k in score_sums if score_counts[k] > 0}
    if not avg_scores: return None, None, {}
    champion_key = max(avg_scores, key=avg_scores.get)
    return champion_key, name_map.get(champion_key, champion_key), avg_scores

def _top_cooccurrence_triple_pool(history_nums, top_n_triples=10, recent_cap=500):
    if not history_nums: return []
    recent = history_nums[:recent_cap]
    triple_counts = collections.Counter()
    for draw in recent:
        unique = sorted(set(draw))
        n = len(unique)
        if n < 3: continue
        for i in range(n):
            for j in range(i + 1, n):
                for k in range(j + 1, n):
                    triple_counts[(unique[i], unique[j], unique[k])] += 1
    if not triple_counts: return []
    pool = []
    seen = set()
    for triple, _ in triple_counts.most_common(top_n_triples):
        for n in triple:
            if n not in seen:
                seen.add(n)
                pool.append(n)
    return pool

def get_expert_strategies(history_nums, n_groups, ball_count=3, rng=None, full_history_nums=None):
    r = rng or random
    if not history_nums: return []

    # 🌟 解除封印：讓所有脆友都拿到最完整的歷史數據
    full = full_history_nums if full_history_nums else history_nums
    weighted = compute_weighted_counts(full)
    pools_dict = _compute_strategy_pools(full, n_groups)

    champion_key, champion_name_zh, _ = _backtest_champion(full, lookback=20)
    if champion_key:
        full_pools_for_champion = _compute_strategy_pools(full, n_groups=None)
        pools_dict['champion'] = full_pools_for_champion.get(champion_key, [])
        champion_label = f"老祖宗的回測冠軍：{champion_name_zh}"
    else:
        pools_dict['champion'] = []
        champion_label = "老祖宗的回測冠軍（資料不足）"

    pools_dict['cluster3'] = _top_cooccurrence_triple_pool(full, top_n_triples=10)

    # 🌟 移除了舊版 cheng 與 xiaotian，留下 S 級陣容
    pools_meta = [
        ("g1_to_g5", "老祖宗攻略1-5", "整合 G1~G4 多因子共識評分，最高分優先"),
        ("triangle", "本頻道的老祖宗", "高頻 ∩ 共伴 ∩ 不冷"),
        ("champion", champion_label, "近 20 期表現最佳池當期候選"),
        ("cluster3", "老祖宗的三人", "歷史最常 3 顆同開的鐵三角們"),
        ("cheng2", "承 2.0", "近 20 期熱 + 近 10 期冷"),
        ("baobaolong", "暴暴龍", "上期 ±1 鄰號"),
    ]

    result = []
    for key, name, desc in pools_meta:
        pool = pools_dict.get(key, [])
        if not pool: pool = list(ALL_NUMS)
        weighted_pool = _to_weight_pool(pool, weighted)
        picks = weighted_pick(weighted_pool, ball_count, exclude=[], rng=r)
        picks.sort()
        result.append({"key": key, "name": name, "desc": desc, "picks": picks})
    return result

def calculate_tracking_win_rate(full_history):
    if len(full_history) < 20:
        return {"core": [], "expert": []}
    rng = random.Random(369)
    core_strats = ['pure_hot', 'hot', 'markov', 'dual_window']
    core_res = {s: {"strategy": s, "hit_2": 0, "hit_3": 0, "hit_4": 0, "total_wins": 0, "details": []} for s in core_strats}
    expert_res = {}

    for i in range(10):
        target_idx = 9 - i  
        if target_idx >= len(full_history): continue
        history_slice = full_history[target_idx:]
        if len(history_slice) < 5: continue
        base_period = history_slice[0]['period']
        history_for_pred = [item['numbers'] for item in history_slice]
        wrapped = [{"numbers": nums} for nums in history_for_pred]
        n_groups = get_n_groups(wrapped)
        
        track_info_list = []
        last_known = int(base_period)
        for step in range(1, 11):
            check_idx = target_idx - step
            if check_idx >= 0:
                draw = full_history[check_idx]
                last_known = int(draw['period'])
                track_info_list.append({"period": str(last_known), "drawn": set(draw['numbers']), "status": "drawn"})
            else:
                last_known += 1
                track_info_list.append({"period": str(last_known), "drawn": set(), "status": "pending"})
                
        def _evaluate_and_record(picks, target_dict, key):
            pred_set = set(picks)
            h2 = h3 = h4 = 0
            t_results = []
            for t in track_info_list:
                hits = len(pred_set & t['drawn']) if t['status'] == 'drawn' else 0
                if hits == 2: h2 += 1
                elif hits == 3: h3 += 1
                elif hits == 4: h4 += 1
                t_results.append({"period": t['period'], "hits": hits, "status": t['status']})
            target_dict[key]["hit_2"] += h2
            target_dict[key]["hit_3"] += h3
            target_dict[key]["hit_4"] += h4
            target_dict[key]["total_wins"] += (h2 + h3 + h4)
            target_dict[key]["details"].append({
                "group_id": i + 1,
                "base_period": base_period,
                "predicted_nums": sorted(picks),
                "sub_hit_2": h2, "sub_hit_3": h3, "sub_hit_4": h4,
                "track_results": t_results
            })

        for s in core_strats:
            pred = analyze_strategy(history_for_pred, s, n_groups, ball_count=4, rng=rng)
            _evaluate_and_record([p['num'] for p in pred], core_res, s)
            
        experts = get_expert_strategies(history_for_pred, n_groups, ball_count=4, rng=rng, full_history_nums=history_for_pred)
        for exp in experts:
            ekey = exp['key']
            if ekey not in expert_res:
                expert_res[ekey] = {"strategy": exp['name'], "hit_2": 0, "hit_3": 0, "hit_4": 0, "total_wins": 0, "details": []}
            _evaluate_and_record(exp['picks'][:4], expert_res, ekey)

    return {"core": list(core_res.values()), "expert": list(expert_res.values())}

def get_frequency_bias_report(history_nums, z_threshold=1.96):
    if not history_nums:
        return {"total_periods": 0, "hot_numbers": [], "cold_numbers": []}
    counts = plain_counts(history_nums)
    n_periods = len(history_nums)
    expected = n_periods * 20 / 80
    std = math.sqrt(expected * 0.75) if expected > 0 else 0
    details = []
    for num in ALL_NUMS:
        observed = counts.get(num, 0)
        z = (observed - expected) / std if std > 0 else 0
        status = 'hot' if z > z_threshold else 'cold' if z < -z_threshold else 'normal'
        details.append({
            'num': num, 'observed': observed,
            'expected': round(expected, 1), 'z_score': round(z, 2), 'status': status,
        })
    hot = sorted([d for d in details if d['status'] == 'hot'], key=lambda x: -x['z_score'])
    cold = sorted([d for d in details if d['status'] == 'cold'], key=lambda x: x['z_score'])
    return {
        'total_periods': n_periods, 'expected_per_num': round(expected, 1),
        'z_threshold': z_threshold, 'hot_count': len(hot), 'cold_count': len(cold),
        'hot_numbers': hot, 'cold_numbers': cold,
    }

def backtest_strategy(full_history_nums, strategy, test_periods=30, lookback=50, ball_count=6):
    available = len(full_history_nums)
    if available < test_periods + lookback:
        if available >= test_periods + 5:
            lookback = available - test_periods
        else:
            test_periods = max(0, available - 5)
            lookback = available - test_periods
    if test_periods <= 0 or lookback < 5:
        return {"avg_hit": 0.0, "high_hit_rate": 0.0, "total_periods": 0}
    rng = random.Random(42)
    hits = []
    for t in range(test_periods):
        history_slice = full_history_nums[t + 1: t + 1 + lookback]
        if len(history_slice) < 5: continue
        wrapped = [{"numbers": nums} for nums in history_slice]
        n_groups = get_n_groups(wrapped)
        prediction = analyze_strategy(history_slice, strategy, n_groups, ball_count, rng=rng)
        predicted_nums = {p['num'] for p in prediction}
        actual_nums = set(full_history_nums[t])
        hits.append(len(predicted_nums & actual_nums))
    if not hits:
        return {"avg_hit": 0.0, "high_hit_rate": 0.0, "total_periods": 0}
    avg_hit = sum(hits) / len(hits)
    high_hit_count = sum(1 for h in hits if h >= HIGH_HIT_THRESHOLD)
    return {
        "avg_hit": round(avg_hit, 2),
        "high_hit_rate": round(high_hit_count / len(hits), 3),
        "total_periods": len(hits),
        "high_hit_periods": high_hit_count,
    }
