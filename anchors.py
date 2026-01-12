import logging
import difflib
from synonyms import normalize
from rapidfuzz import fuzz
from llm import call_llm_for_local_alignment
logger = logging.getLogger()

def align_linear_gap(sub_a, sub_b, threshold=80):
    """
    针对 gap 接近的区间进行自动对齐
    sub_a, sub_b: 台词列表 (List of strings)
    """
    local_mapping = {}

    norm_sub_a = [normalize(s) for s in sub_a]
    norm_sub_b = [normalize(s) for s in sub_b]
    
    matcher = difflib.SequenceMatcher(None, norm_sub_a, norm_sub_b)
    
    # get_matching_blocks 返回 (i, j, n)，表示 sub_a[i:i+n] 与 sub_b[j:j+n] 完全匹配
    for block in matcher.get_matching_blocks():
        i, j, n = block
        for k in range(n):
            local_mapping[i + k] = j + k

    for i, line in enumerate(sub_a):
        logger.info(f"  A[{i}]: {line}")
    for i, line in enumerate(sub_b):
        logger.info(f"  B[{i}]: {line}")
    for k, v in local_mapping.items():
        logger.info(f"  A[{k}] -> B[{v}]")
            
    # 对于没匹配上的行，进行简单的二重模糊检查
    if not (len(sub_a) > threshold and len(local_mapping)/len(sub_a) < 1/3):
        matched_a = set(local_mapping.keys())
        matched_b = set(local_mapping.values())
        
        for i, line_a in enumerate(norm_sub_a):
            if i in matched_a:
                continue
            for j, line_b in enumerate(norm_sub_b):
                if j in matched_b:
                    continue
                score = fuzz.WRatio(line_a, line_b)
                if score >= 92:
                    local_mapping[i] = j
                    logger.info(f"  A[{i}] -> B[{j}] (score: {score})")
                    matched_a.add(i)
                    matched_b.add(j)
                    break

    # 或者直接留空，让它们作为“未对齐项”
    return local_mapping

def find_stable_anchors(raw_matches:dict[int, list[int]], window_size=2):
    stable_anchors = {}
    
    for pos_a, b_candidates in raw_matches.items():
        if len(b_candidates) == 1:
            # 唯一匹配，暂时信任
            stable_anchors[pos_a] = b_candidates[0]
            continue
            
        # 存在多个 100% 匹配，寻找“有邻居支持”的那一个
        best_b = None
        max_neighbors = 0
        
        for cand_b in b_candidates:
            neighbor_count = 0
            # 检查 A 的前后邻居，看它们的匹配项是否也在 cand_b 的前后
            for offset in range(-window_size, window_size + 1):
                if offset == 0: continue
                neighbor_a = pos_a + offset
                if neighbor_a in raw_matches:
                    # 如果邻居的匹配项中，有一个正好落在 cand_b 的附近
                    if any(nb == cand_b for nb in raw_matches[neighbor_a]):
                        neighbor_count += 1
            
            if neighbor_count > max_neighbors:
                max_neighbors = neighbor_count
                best_b = cand_b
        
        if best_b is not None and max_neighbors > 0:
            stable_anchors[pos_a] = best_b

    b_to_a_map = {}
    for pos_a, pos_b in stable_anchors.items():
        b_to_a_map.setdefault(pos_b, [])
        b_to_a_map[pos_b].append(pos_a)

    stable_anchors = {k:v for k,v in stable_anchors.items() if len(b_to_a_map[v]) == 1}

    unwrapped_anchors = {}
    for k in stable_anchors.keys():
        unwrapped_anchors[k] = stable_anchors[k]
        unwrapped_anchors[k + 1] = stable_anchors[k] + 1
        unwrapped_anchors[k + 2] = stable_anchors[k] + 2

    return unwrapped_anchors

def process_with_anchors(script_a, script_b, matches):
    # 1. 提取所有 100% 分数的锚点
    raw_matches = {}
    for match in matches:
       raw_matches[match['pos_a']] = [m['pos_b'] for m in match['matches'] if m['score'] == 100]
        
    stable_anchors: dict[int,int] = find_stable_anchors(raw_matches)
    # 2. 按位置排序

    def compute_gaps(anchors):
        final_mapping = {}
        pos_a_list = sorted(anchors.keys())
        anchors_sorted = [(pos_a, anchors[pos_a]) for pos_a in pos_a_list]
        gaps = []
        for k in range(len(anchors_sorted) - 1):
            curr_a, curr_b = anchors_sorted[k]
            next_a, next_b = anchors_sorted[k + 1]
            # 保存起点锚点
            final_mapping[curr_a] = curr_b
            gap_a = next_a - curr_a
            gap_b = next_b - curr_b
            # 情况 1: 完美连续
            if gap_a == 1 and gap_b == 1:
                continue
            gaps.append((curr_a, curr_b, next_a, next_b))
        final_mapping[anchors_sorted[-1][0]] = anchors_sorted[-1][1]
        return final_mapping, gaps

    def update_matches_linear(anchors):
        final_mapping, gaps = compute_gaps(anchors)
        for gap in gaps:
            curr_a, curr_b, next_a, next_b = gap
            gap_a = next_a - curr_a
            gap_b = next_b - curr_b
            diff = abs(gap_a - gap_b)
            # 情况 2：局部线性区间 (区间非常近，可能存在微调)
            if gap_a > 0 and gap_b > 0 and (diff <= 5 or (diff/gap_a) <= 0.1):
                logger.info(f"检测到准线性区间: A[{curr_a+1}:{next_a}] vs B[{curr_b+1}:{next_b}]，执行自动对齐...")
                # 这里的 B 可能比 A 多，也可能比 A 少
                sub_a = script_a[curr_a + 1 : next_a]
                sub_b = script_b[curr_b + 1 : next_b]

                local_map = align_linear_gap(sub_a, sub_b)
                for rel_a, rel_b in local_map.items():
                    final_mapping[curr_a + 1 + rel_a] = curr_b + 1 + rel_b
            else:
                continue
        return final_mapping

    stable_anchors = update_matches_linear(stable_anchors)

    def update_matches_llm(anchors):
        final_mapping, gaps = compute_gaps(anchors)
        for gap in gaps:
            curr_a, curr_b, next_a, next_b = gap
            gap_a = next_a - curr_a
            gap_b = next_b - curr_b
            diff = abs(gap_a - gap_b)
            
            # 情况 2：小范围的近似线性区间，交给LLM
            if gap_a > 1 and gap_b > 1 and (gap_a + gap_b) < 42:
                # 这里的 B 可能比 A 多，也可能比 A 少
                # 提取这一小段内容交给 LLM
                sub_a = script_a[curr_a + 1 : next_a]
                sub_b = script_b[curr_b + 1 : next_b]

              
                logger.info(f"发现模糊区间: A[{curr_a+1}:{next_a}] -> B[{curr_b+1}:{next_b}]，调用 LLM...")
                for i, line in enumerate(sub_a):
                    logger.info(f"  A[{i}]: {line}")
                for i, line in enumerate(sub_b):
                    logger.info(f"  B[{i}]: {line}")
                
                # 调用 LLM 获取局部对齐结果
                # 返回格式建议为 {relative_idx_a: relative_idx_b}
                local_alignment: list[dict] = call_llm_for_local_alignment(sub_a, sub_b)
                # alignment: list[dict] = [{"a": [0], "b": [0]}, {"a": [1], "b": [1, 2]}]
                # Only keep the one-one match
                local_map = {}
                for item in local_alignment:
                    if item['a'] is None or item['b'] is None:
                        logger.info(f"  A[{item['a']}] -> B[{item['b']}] (略过)")
                        continue
                    if len(item['a']) == 1 and len(item['b']) == 1 and item['a'][0] is not None and item['b'][0] is not None:
                        logger.info(f"  A[{item['a'][0]}] -> B[{item['b'][0]}]")
                        local_map[item['a'][0]] = item['b'][0]
                    else:
                        logger.info(f"  A[{",".join(map(str, item['a']))}] -> B[{",".join(map(str, item['b']))}] (略过)")
                
                # 将相对坐标转换为绝对坐标存入 final_mapping
                for rel_a, rel_b in local_map.items():
                    if rel_b is not None and rel_a is not None:
                        final_mapping[curr_a + 1 + rel_a] = curr_b + 1 + rel_b

            else:
              continue
        return final_mapping

    stable_anchors = update_matches_llm(stable_anchors)

    _ , gaps = compute_gaps(stable_anchors)
    # 情况 3：跨度过大
    # 这种情况下，两个锚点之间可能跨场次了，保持原状，
    # 后续可以使用全量 Top-K 检索来补丁
    for curr_a, curr_b, next_a, next_b in gaps:
        logger.info(f"未处理锚点区间: A[{curr_a+1}:{next_a}] -> B[{curr_b+1}:{next_b}]")

    
    with open("gaps.json", "w") as f:
        import json
        json.dump(gaps, f, indent=2)
    
    return stable_anchors

