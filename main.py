from models import RemakeLine, Line, Script, RemakeScript, UnscriptedConversation 
from script_searcher import ScriptSearcher
from anchors import process_with_anchors
from synonyms import get_potential_synonyms
from line_solver import single_match
from gen_result import gen_csv, explain_llm_alignments
import json

import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(message)s')
fh = logging.FileHandler('match.log', mode='w', encoding='utf-8')
fh.setLevel(logging.INFO)
fh.setFormatter(formatter)
logger.addHandler(fh)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(formatter)
logger.addHandler(ch)



def refresh_matches(script_a, script_b):
  searcher = ScriptSearcher(threshold=0.3, window_size=3)
  searcher.build_b_index(script_b.texts)
  matches = searcher.search_from_a(script_a.texts, top_k=3)
  with open("matches.json", "w", encoding="utf-8") as f:
    json.dump(matches, f, indent=2, ensure_ascii=False)

def optimize_with_anchors(script_a, script_b, matches):
  final_mapping = process_with_anchors(script_a.texts, script_b.texts, matches)
  with open("anchors.json", "w", encoding="utf-8") as f:
    json.dump(final_mapping, f, indent=2, ensure_ascii=False)

def solve_gaps(script_a, script_b, matches, anchors):
  final_mapping = single_match(script_a.texts, script_b.texts, matches, anchors)
  with open("top_k_matches.json", "w", encoding="utf-8") as f:
    json.dump(final_mapping, f, indent=2, ensure_ascii=False)

def add_unscripted_conversations(script_a, unscripted_b, matches):
  single_line_searcher = ScriptSearcher(threshold=0.3, window_size=1)
  single_line_searcher.build_b_index(unscripted_b.texts)
  unmatched_lines_a = [ (i, l) for i , l in enumerate(script_a.texts) if i not in matches ]
  if not unmatched_lines_a:
    additional_mapping = {}
  else:
    hit_in_unscripted = single_line_searcher.search_from_a(list(zip(*unmatched_lines_a))[1], top_k=1, score_of_fake_match=92)
    hit_in_unscripted = [r for r in hit_in_unscripted if any(m['score'] >= 92 for m in r['matches'])]
    for r in hit_in_unscripted:
      r['matches'] = [m for m in r['matches'] if m['score'] >= 92]
    for r in hit_in_unscripted:
      logger.info(f"\n[剧本 A 第 {unmatched_lines_a[r['pos_a']][0]} 行起点]")
      logger.info(f"  内容: {r['text_a']}")
      for i, m in enumerate(r['matches']):
          logger.info(f"  Top-{i+1} 匹配 (附加音频B第 {m['pos_b']} 行, 分数 {m['score']}%):")
          logger.info(f"    {m['text_b']}")
    additional_mapping = {}
    for match in hit_in_unscripted:
      additional_mapping[unmatched_lines_a[match["pos_a"]][0]] = match["matches"][0]["pos_b"]
  with open("unscripted_matches.json", "w", encoding="utf-8") as f:
    json.dump(additional_mapping, f, indent=2, ensure_ascii=False)

def gen_output(script_a, script_b, trans_a, unscripted_b, matches, unscripted_matches, output_filename):
  expl = explain_llm_alignments(script_a, script_b)
  gen_csv(script_a, script_b, trans_a, unscripted_b, matches, unscripted_matches, expl, output_filename)

def main():
  # 剧本 A：原始顺序
  script_a = RemakeScript("scena_data_jp_Command.json")
  # 剧本 B: 乱序
  script_b = Script("script_data.json")
  # 剧本 A 翻译文本
  trans_a = RemakeScript("scena_data_sc_Command.json")
  # 剧本 B 中未记录的语音
  unscripted_b = UnscriptedConversation("whisperx_fc_missing_simple.json")

  # refresh_matches(script_a, script_b)

  with open("matches.json","r", encoding="utf-8") as f:
    matches = json.loads(f.read())

  # optimize_with_anchors(script_a, script_b, matches)

  with open("anchors.json", "r", encoding="utf-8") as f:
    final_mapping = json.loads(f.read())
    final_mapping = { int(k):v for k,v in final_mapping.items() }

  # solve_gaps(script_a, script_b, matches, final_mapping)

  with open("top_k_matches.json", "r", encoding="utf-8") as f:
    top_k_matches = json.loads(f.read())
    top_k_matches = { int(k):v for k,v in top_k_matches.items() }

  add_unscripted_conversations(script_a, unscripted_b, top_k_matches)

  with open("unscripted_matches.json", "r", encoding="utf-8") as f:
    unscripted_matches = json.loads(f.read())
    unscripted_matches = { int(k):v for k,v in unscripted_matches.items() }

  gen_output(script_a, script_b, trans_a, unscripted_b, top_k_matches, unscripted_matches, "match_result.csv")

  # logger.info("\n--- 匹配结果 ---")
  # for r in matches:
  #   logger.info(f"\n[剧本 A 第 {r['pos_a']} 行起点]")
  #   logger.info(f"  内容: {r['text_a']}")
  #   for i, m in enumerate(r['matches']):
  #       logger.info(f"  Top-{i+1} 匹配 (B第 {m['pos_b']} 行, 分数 {m['score']}%):")
  #       logger.info(f"    {m['text_b']}")

  # logger.info("\n--- 锚点映射 ---")
  # for pos_a, pos_b in final_mapping.items():
  #   logger.info(f"  A[{pos_a}] -> B[{pos_b}]")
  #   logger.info(f"    A: {" / ".join(script_a.texts[pos_a:pos_a+3])}")
  #   logger.info(f"    B: {" / ".join(script_b.texts[pos_b:pos_b+3])}")

  logger.info("\n--- 匹配统计 ---")
  logger.info(f"剧本A总台词数: {len(script_a.texts)}")
  logger.info(f"包含重复的匹配数: {len(matches)}")
  logger.info(f"锚点映射数: {len(final_mapping)}")
  logger.info(f"唯一匹配数: {len([m for m,v  in top_k_matches.items() if len(v) == 1])}")
  logger.info(f"多个匹配数: {len([m for m,v  in top_k_matches.items() if len(v) > 1])}")
  logger.info(f"脚本外语音贡献的匹配数: {len(unscripted_matches)}")
  logger.info(f"总匹配数（唯一/多个匹配+脚本外语音）: {len(unscripted_matches) + len([m for m,v  in top_k_matches.items() if len(v) >= 1])}")


if __name__ == "__main__":
  main()