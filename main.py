from pydantic import TypeAdapter, BaseModel
from models import RemakeLine, Line
from script_searcher import ScriptSearcher
from anchors import process_with_anchors
from synonyms import get_potential_synonyms
from line_solver import top_k_match
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


class Script :
  def __init__(self, file:str) -> None:
    with open(file, "r") as f:
      adapter = TypeAdapter(list[Line])
      self.lines = adapter.validate_json(f.read())

    self.texts = [line.text for line in self.lines]

class RemakeScript :
  NEW_ID_START=50001
  def __init__(self, file:str) -> None:
    self.lines = []
    with open(file, "r") as f:
        commands: list[dict] = json.load(f)
        for i, entry in enumerate(commands):
            remake_line = RemakeLine(id=self.NEW_ID_START + i, **entry)
            self.lines.append(remake_line)
    self.texts = [line.text for line in self.lines]

def refresh_matches(script_a, script_b):
  searcher = ScriptSearcher(threshold=0.3, window_size=3)
  searcher.build_b_index(script_b.texts)
  matches = searcher.search_from_a(script_a.texts, top_k=3)
  with open("matches.json", "w") as f:
    json.dump(matches, f, indent=2)

def optimize_with_anchors(script_a, script_b, matches):
  final_mapping = process_with_anchors(script_a.texts, script_b.texts, matches)
  with open("anchors.json", "w") as f:
    json.dump(final_mapping, f, indent=2)

def solve_gaps(script_a, script_b, matches, anchors):
  final_mapping = top_k_match(script_a.texts, script_b.texts, matches, anchors)
  with open("top_k_matches.json", "w") as f:
    json.dump(final_mapping, f, indent=2)

def main():
  # 剧本 A：原始顺序
  script_a = RemakeScript("scena_data_jp_Command.json")
  # 剧本 B: 乱序
  script_b = Script("script_data.json")

  # refresh_matches(script_a, script_b)

  with open("matches.json","r") as f:
    matches = json.loads(f.read())

  # optimize_with_anchors(script_a, script_b, matches)

  with open("anchors.json", "r") as f:
    final_mapping = json.loads(f.read())
    final_mapping = { int(k):v for k,v in final_mapping.items() }

  solve_gaps(script_a, script_b, matches, final_mapping)

  with open("top_k_matches.json", "r") as f:
    top_k_matches = json.loads(f.read())

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
  logger.info(f"Top-K匹配数: {len(top_k_matches)}")

if __name__ == "__main__":
  main()