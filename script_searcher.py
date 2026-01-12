from datasketch import MinHash, MinHashLSH
from rapidfuzz import fuzz
from synonyms import katakana_to_kanji, replace_kiseki_terms, normalize
import jaconv
import re
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

class ScriptSearcher:
    def __init__(self, threshold=0.4, window_size=3):
        self.threshold = threshold
        self.window_size = int(window_size)
        if self.window_size < 1:
            raise ValueError("window_size must be >= 1")
        self.lsh = MinHashLSH(threshold=threshold, num_perm=128)
        self.b_windows = {} # 存放剧本 B 的窗口内容
        self.script_b_raw = []

    def _clean(self, text):
        """日语清洗：转半角、去空格、去括号内容、去角色名"""
        if not text: return ""
        text = jaconv.normalize(text, 'NFKC')
        text = replace_kiseki_terms(text)
        text = re.sub(r'[（\(].*?[）\)]', '', text) # 去括号
        text = re.sub(r'^.*?[:：]', '', text)      # 去角色名
        return "".join(c for c in text if c.isalnum())

    def _get_minhash(self, text):
        m = MinHash(num_perm=128)
        shingles = [text[i:i+2] for i in range(len(text)-1)]
        if not shingles: shingles = [text]
        for s in shingles:
            m.update(s.encode('utf8'))
        return m

    def build_b_index(self, script_b):
        """对剧本 B 建立全量滑动窗口索引"""
        self.script_b_raw = script_b
        logger.info(f"正在索引剧本 B (共 {len(script_b)} 行)...")
        
        for i in range(len(script_b) - self.window_size + 1):
            # 组合三行作为搜索单位
            combined = "".join([self._clean(line) for line in script_b[i:i+self.window_size]])
            if len(combined) < 3: continue
            
            m = self._get_minhash(combined)
            window_id = f"B_pos_{i}"
            self.lsh.insert(window_id, m)
            self.b_windows[window_id] = combined

    def search_from_a(self, script_a, top_k=3):
        """遍历剧本 A，寻找 B 中最匹配的 Top-K"""
        all_results = []
        
        logger.info(f"开始在 B 中检索 A 的内容...")
        # 为了覆盖所有台词，我们每行都作为起始点取 3 行窗口进行检索
        for i in range(len(script_a) - self.window_size + 1):
            raw_a_lines = script_a[i:i+self.window_size]
            clean_a = "".join([self._clean(line) for line in raw_a_lines])
            
            if len(clean_a) < 3: continue

            # 1. 粗筛
            m_query = self._get_minhash(clean_a)
            candidates = self.lsh.query(m_query)

            # 2. 精算得分
            scored_candidates = []
            for cand_id in candidates:
                clean_b = self.b_windows[cand_id]
                pos_b = int(cand_id.split('_')[-1])
                
                # 使用 WRatio，它对顺序敏感且对长短句匹配较好
                score = fuzz.WRatio(clean_a, clean_b)

                if score == 100 :
                    norm_a = normalize(raw_a_lines)
                    norm_b = normalize(self.script_b_raw[pos_b:pos_b+self.window_size])
                    if norm_a != norm_b :
                      logger.info(f"发现不匹配的100分: {norm_a} -> {norm_b}")
                      score = 85
                
                
                scored_candidates.append({
                    "pos_b": pos_b,
                    "score": round(score, 2),
                    "text_b": " / ".join(self.script_b_raw[pos_b:pos_b+self.window_size])
                })
                

            # 3. 排序取 Top-K
            scored_candidates.sort(key=lambda x: x['score'], reverse=True)
            top_matches = scored_candidates[:top_k]

            if top_matches:
                all_results.append({
                    "pos_a": i,
                    "text_a": " / ".join(raw_a_lines),
                    "matches": top_matches
                })
        
        return all_results

# --- 运行验证 ---
if __name__ == "__main__":
  script_a = [
      # "田中：準備はいいか？",
      # "佐藤：いつでも行けるよ。",
      # "田中：よし、出発だ。",
      # "（足音が遠のく）",
      # "ナレーション：こうして物語は始まった。",
      "へ～、そうだったの。歴史のロマンを感じちゃうわね。",
      "それを伝えるのが今回の仕事だ。",
      "ドロシー。ローアングルで何枚か撮れ。",
      "…………",
      "……むにゃむにゃ。",
      "……ごろごろごろごろ。",
      "…………",
      "……むにゃむにゃ。"
  ]

  script_b = [
      # "ナレーター：こうして物語は始まったのだ。", # 对应 A4-5
      # "田中：おい、準備はいいか？",             # 对应 A0-2
      # "佐藤：いつでも行ける。",                 # 对应 A0-2
      # "田中：よし、出発しようぜ！",             # 对应 A0-2
      # "（ガサガサという音）",
      "へ〜、そうだったの。歴史のロマンを感じちゃうわね。",
      "それを伝えるのが今回の仕事だ。",
      "ドロシー。ローアングルで何枚か撮れ。",
      "…………",
      "……むにゃむにゃ。",
      "……ごろごろごろごろ。",
      "…………",
      "……むにゃむにゃ。"
  ]

  searcher = ScriptSearcher(threshold=0.3)
  searcher.build_b_index(script_b) # 注意是索引 B
  results = searcher.search_from_a(script_a, top_k=2)

  for r in results:
      print(f"\n[剧本 A 第 {r['pos_a']} 行起点]")
      print(f"  内容: {r['text_a']}")
      for i, m in enumerate(r['matches']):
          print(f"  Top-{i+1} 匹配 (B第 {m['pos_b']} 行, 分数 {m['score']}%):")
          print(f"    {m['text_b']}")
