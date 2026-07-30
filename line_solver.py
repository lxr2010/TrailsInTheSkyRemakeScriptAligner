import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from rapidfuzz import fuzz
from synonyms import normalize
from llm import match_script_segment

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def load_cached_llm_segment():
  import json
  import os
  if not os.path.exists("llm_segments.json"):
    return {}
  try:
    with open("llm_segments.json", "r", encoding="utf-8") as f:
      obj = json.load(f)
      if isinstance(obj, dict):
        return {int(k):v for k,v in obj.items()}
      else:
        return {}
  except Exception as e:
    logger.error(f"Failed to load cache: {e}")
    return {}

def store_cached_llm_segment(llm_cache):
  import json
  with open("llm_segments.json", "w", encoding="utf-8") as f:
    json.dump(llm_cache, f, indent=2, ensure_ascii=False)

def single_match(script_a:list[str], script_b:list[str], matches:list[dict], anchors:dict[int,int]):

  llm_cache = load_cached_llm_segment()

  # 注：这些窗口切片在 pos_a/pos_b ∈ {0,1} 时会因 Python 负索引取到末尾行。
  # 但实际触发概率极低：开头几行必然被锚点锁定，走不到需要取上下文的模糊匹配分支。
  def get_norm_text_b(pos_b, window_size=3):
    return " / ".join(map(normalize, script_b[pos_b-(window_size//2):pos_b+(window_size//2)+1]))

  def get_text_b(pos_b, window_size=3):
    return " / ".join(script_b[pos_b-(window_size//2):pos_b+(window_size//2)+1])

  def get_text_a(pos_a, window_size=3):
    return " / ".join(script_a[pos_a-(window_size//2):pos_a+(window_size//2)+1])

  def get_norm_text_a(pos_a, window_size=3):
    return " / ".join(map(normalize, script_a[pos_a-(window_size//2):pos_a+(window_size//2)+1]))

  def get_text_list_a(pos_a, window_size=3):
    return script_a[pos_a-(window_size//2):pos_a+(window_size//2)+1]
    
      
  single_matches = { k:v for k,v in anchors.items()}
  multiple_matches = {}
  pos_a_to_match = {m['pos_a']: m for m in matches}

  # ── Phase 1: 收集所有需要 LLM 判断的歧义位置 ──
  pending_llm = {}      # p -> sorted candidates
  temp_single = dict(single_matches)

  for pos_a in pos_a_to_match:
    if all(pos_a + i in temp_single for i in range(3)):
      continue
    candidates = set()
    curr_match = pos_a_to_match[pos_a]
    next_match1 = pos_a_to_match.get(pos_a + 1)
    next_match2 = pos_a_to_match.get(pos_a + 2)
    for match in [curr_match, next_match1, next_match2]:
      if match:
        for m in match['matches']:
          candidates.add(m['pos_b'])
          candidates.add(m['pos_b'] + 1)
          candidates.add(m['pos_b'] + 2)
    for p in [pos_a, pos_a + 1, pos_a + 2]:
      if p in temp_single:
        p_b = temp_single[p]
        candidates.add(p_b)
        candidates.add(p_b + 1)
        candidates.add(p_b + 2)

    for p in [pos_a, pos_a + 1, pos_a + 2]:
      if p in temp_single or p in llm_cache:
        continue
      score_map = {c : fuzz.WRatio(normalize(script_a[p]), normalize(script_b[c])) for c in candidates}
      good = {c: score_map[c] for c in candidates if score_map[c] >= 92}
      if not good:
        continue
      max_score = max(good.values())
      max_c = max(good, key=good.get)
      max_norm = get_norm_text_b(max_c)
      top_cands = [c for c in good if good[c] == max_score]

      if len(top_cands) == 1 or all(max_norm == get_norm_text_b(c) for c in top_cands):
        temp_single[p] = max_c
      else:
        if p not in pending_llm:
          pending_llm[p] = sorted(good.keys())
          logger.info(f"在3-gram({pos_a}, {pos_a + 1}, {pos_a + 2})中：")
          logger.info(f"匹配{p}的内容: {get_text_a(p,5)} -> {normalize(get_text_a(p,5))}")
          logger.info(f"匹配{p}的候选位置: {sorted(good.keys())}")
          for c in sorted(good.keys()):
            logger.info(f"  候选位置 {c} 相似度 {good[c]} : {get_text_b(c,5)} -> {get_norm_text_b(c,5)}")

  # ── Phase 2: 并发调用 LLM ──
  if pending_llm:
    logger.info(f"共 {len(pending_llm)} 个歧义位置需要 LLM 判断，并发调用中...")
    with ThreadPoolExecutor(max_workers=8) as executor:
      futures = {}
      for p, cands in pending_llm.items():
        future = executor.submit(
          match_script_segment,
          get_text_list_a(p, 5), 5,
          [{"id": c, "lines": [get_text_b(c, 5)]} for c in cands]
        )
        futures[future] = p
      for future in as_completed(futures):
        p = futures[future]
        llm_cache[p] = future.result()
        logger.info(f"LLM匹配结果(p={p})：{llm_cache[p]}")
    store_cached_llm_segment(llm_cache)

  # ── Phase 3: 使用已缓存的 LLM 结果完成匹配 ──
  single_matches = { k:v for k,v in anchors.items()}
  multiple_matches = {}

  for pos_a in pos_a_to_match:
    if all(pos_a + i in single_matches for i in range(3)):
      continue
    candidates = set()
    curr_match = pos_a_to_match[pos_a]
    next_match1 = pos_a_to_match.get(pos_a + 1)
    next_match2 = pos_a_to_match.get(pos_a + 2)
    for match in [curr_match, next_match1, next_match2]:
      if match:
        for m in match['matches']:
          candidates.add(m['pos_b'])
          candidates.add(m['pos_b'] + 1)
          candidates.add(m['pos_b'] + 2)
    for p in [pos_a, pos_a + 1, pos_a + 2]:
      if p in single_matches:
        p_b = single_matches[p]
        candidates.add(p_b)
        candidates.add(p_b + 1)
        candidates.add(p_b + 2)

    for p in [pos_a, pos_a + 1, pos_a + 2]:
      if p in single_matches:
        continue
      score_map = {c : fuzz.WRatio(normalize(script_a[p]), normalize(script_b[c])) for c in candidates}
      good = {c: score_map[c] for c in candidates if score_map[c] >= 92}
      if not good:
        continue
      max_score = max(good.values())
      max_c = max(good, key=good.get)
      max_norm = get_norm_text_b(max_c)
      top_cands = [c for c in good if good[c] == max_score]

      if len(top_cands) == 1 or all(max_norm == get_norm_text_b(c) for c in top_cands):
        single_matches[p] = max_c
      else:
        llm_match = llm_cache.get(p)
        if llm_match and llm_match.get('selected_id') is not None:
          single_matches[p] = llm_match['selected_id']
        else:
          multiple_matches[p] = list(good.keys())

  store_cached_llm_segment(llm_cache)

  final_matches = {k:[v] for k,v in single_matches.items()}
  final_matches.update(multiple_matches)

  return final_matches
