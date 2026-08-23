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

def speaker_recall(norm_a, expected, norm_b_by_speaker, limit=200):
  """短文本补召回：按说话人查找归一化文本精确匹配的位置。"""
  if not norm_b_by_speaker:
    return []
  d = norm_b_by_speaker.get(expected)
  if not d:
    return []
  return d.get(norm_a, [])[:limit]

def _interp_pos(p, anchors_dict):
  """根据最近已确定的锚点线性插值，估算 p 应该对应的 B 位置。"""
  if not anchors_dict:
    return None
  items = sorted(anchors_dict.items())
  prev = None
  nxt = None
  for a, b in items:
    if a <= p:
      prev = (a, b)
    else:
      nxt = (a, b)
      break
  if prev is not None and nxt is not None:
    a0, b0 = prev
    a1, b1 = nxt
    if a1 > a0:
      return b0 + (b1 - b0) * (p - a0) / (a1 - a0)
  if prev is not None:
    return prev[1]
  if nxt is not None:
    return nxt[1]
  return None

def _nearest_anchor(p, anchors_dict):
  if not anchors_dict:
    return None, None
  items = sorted(anchors_dict.items())
  prev = None
  nxt = None
  for a, b in items:
    if a <= p:
      prev = (a, b)
    else:
      nxt = (a, b)
      break
  return prev, nxt

def _pick_by_context(p, top_cands, anchors_dict, b_scenes):
  """文本完全一致时，按场景优先 + 插值选位置最合理的候选。"""
  if len(top_cands) == 1:
    return top_cands[0]
  prev, nxt = _nearest_anchor(p, anchors_dict)
  scene = None
  if prev is not None and b_scenes is not None and prev[1] < len(b_scenes):
    scene = b_scenes[prev[1]]
  elif nxt is not None and b_scenes is not None and nxt[1] < len(b_scenes):
    scene = b_scenes[nxt[1]]
  if scene:
    same = [c for c in top_cands if b_scenes is not None and c < len(b_scenes) and b_scenes[c] == scene]
    if same:
      top_cands = same
  interp = _interp_pos(p, anchors_dict)
  if interp is not None:
    return min(top_cands, key=lambda c: abs(c - interp))
  return top_cands[0]

def single_match(script_a:list[str], script_b:list[str], matches:list[dict], anchors:dict[int,int], a_codes=None, b_codes=None, norm_b_by_speaker=None, b_scenes=None, speaker_positions=None):

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

    # 说话人补召回：补充同说话人精确文本匹配的候选
    if norm_b_by_speaker is not None:
      for p in [pos_a, pos_a + 1, pos_a + 2]:
        expected = a_codes[p] if a_codes is not None and p < len(a_codes) else None
        if expected is not None:
          candidates.update(speaker_recall(normalize(script_a[p]), expected, norm_b_by_speaker))

    for p in [pos_a, pos_a + 1, pos_a + 2]:
      if p in temp_single or p in llm_cache:
        continue
      score_map = {c : fuzz.WRatio(normalize(script_a[p]), normalize(script_b[c])) for c in candidates}
      good = {c: score_map[c] for c in candidates if score_map[c] >= 92}
      if not good:
        continue
      # 说话人约束：高分候选里优先选角色一致的
      expected = a_codes[p] if a_codes is not None and p < len(a_codes) else None
      if expected is not None and b_codes is not None:
        spk = {c: good[c] for c in good if c < len(b_codes) and b_codes[c] == expected}
        if spk:
          good = spk
      max_score = max(good.values())
      max_c = max(good, key=good.get)
      max_norm = get_norm_text_b(max_c)
      top_cands = [c for c in good if good[c] == max_score]

      if len(top_cands) == 1:
        temp_single[p] = top_cands[0]
      elif len({normalize(script_b[c]) for c in top_cands}) == 1:
        # 单行归一化文本一致（含窗口不同），场景优先 + 插值选位置
        temp_single[p] = _pick_by_context(p, top_cands, temp_single, b_scenes)
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
    with ThreadPoolExecutor(max_workers=32) as executor:
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

    # 说话人补召回：补充同说话人精确文本匹配的候选
    if norm_b_by_speaker is not None:
      for p in [pos_a, pos_a + 1, pos_a + 2]:
        expected = a_codes[p] if a_codes is not None and p < len(a_codes) else None
        if expected is not None:
          candidates.update(speaker_recall(normalize(script_a[p]), expected, norm_b_by_speaker))

    for p in [pos_a, pos_a + 1, pos_a + 2]:
      if p in single_matches:
        continue
      score_map = {c : fuzz.WRatio(normalize(script_a[p]), normalize(script_b[c])) for c in candidates}
      good = {c: score_map[c] for c in candidates if score_map[c] >= 92}
      if not good:
        continue
      # 说话人约束：高分候选里优先选角色一致的
      expected = a_codes[p] if a_codes is not None and p < len(a_codes) else None
      if expected is not None and b_codes is not None:
        spk = {c: good[c] for c in good if c < len(b_codes) and b_codes[c] == expected}
        if spk:
          good = spk
      max_score = max(good.values())
      max_c = max(good, key=good.get)
      max_norm = get_norm_text_b(max_c)
      top_cands = [c for c in good if good[c] == max_score]

      if len(top_cands) == 1:
        single_matches[p] = top_cands[0]
      elif len({normalize(script_b[c]) for c in top_cands}) == 1:
        # 单行归一化文本一致（含窗口不同），场景优先 + 插值选位置
        single_matches[p] = _pick_by_context(p, top_cands, single_matches, b_scenes)
      else:
        llm_match = llm_cache.get(p)
        if llm_match and llm_match.get('selected_id') is not None:
          single_matches[p] = llm_match['selected_id']
        else:
          multiple_matches[p] = list(good.keys())

  store_cached_llm_segment(llm_cache)

  # ── Phase 4: 最终补扫未匹配位置（说话人精确 + 模糊）──
  if norm_b_by_speaker is not None and speaker_positions is not None:
    norm_b_texts = [normalize(t) for t in script_b]
    swept = 0
    for p in range(len(script_a)):
      if p in single_matches or p in multiple_matches:
        continue
      expected = a_codes[p] if a_codes is not None and p < len(a_codes) else None
      if expected is None:
        continue
      na = normalize(script_a[p])
      cands = speaker_recall(na, expected, norm_b_by_speaker, limit=200)
      if not cands:
        scored = [(fuzz.WRatio(na, norm_b_texts[pos]), pos) for pos in speaker_positions.get(expected, [])]
        cands = [pos for s, pos in scored if s >= 92]
      if cands:
        single_matches[p] = _pick_by_context(p, cands, single_matches, b_scenes)
        swept += 1
    if swept:
      logger.info(f"最终补扫匹配了 {swept} 个未匹配位置")

  final_matches = {k:[v] for k,v in single_matches.items()}
  final_matches.update(multiple_matches)

  return final_matches
