import argparse
import json
import logging
from pathlib import Path
from typing import Any

from anchors import process_with_anchors
from gen_result import gen_csv, explain_llm_alignments
from line_solver import single_match
from models import RemakeScript, Script, UnscriptedConversation
from script_searcher import ScriptSearcher

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

STEP_ALIASES = {
  "matches": "matches",
  "refresh": "matches",
  "refresh_matches": "matches",
  "anchors": "anchors",
  "optimize": "anchors",
  "optimize_with_anchors": "anchors",
  "top_k": "top_k",
  "topk": "top_k",
  "solve": "top_k",
  "solve_gaps": "top_k",
  "additional": "additional",
  "unscripted": "additional",
  "additional_voice": "additional",
  "add_unscripted_conversations": "additional",
  "output": "output",
  "csv": "output",
  "gen_output": "output",
}

def refresh_matches(script_a, script_b, output_file: Path):
  searcher = ScriptSearcher(threshold=0.3, window_size=3)
  searcher.build_b_index(script_b.texts)
  matches = searcher.search_from_a(script_a.texts, top_k=3)
  with output_file.open("w", encoding="utf-8") as f:
    json.dump(matches, f, indent=2, ensure_ascii=False)

def optimize_with_anchors(script_a, script_b, matches, output_file: Path):
  final_mapping = process_with_anchors(script_a.texts, script_b.texts, matches)
  with output_file.open("w", encoding="utf-8") as f:
    json.dump(final_mapping, f, indent=2, ensure_ascii=False)

def solve_gaps(script_a, script_b, matches, anchors, output_file: Path):
  final_mapping = single_match(script_a.texts, script_b.texts, matches, anchors)
  with output_file.open("w", encoding="utf-8") as f:
    json.dump(final_mapping, f, indent=2, ensure_ascii=False)

def add_unscripted_conversations(script_a, unscripted_b, matches, output_file: Path):
  if unscripted_b is None or len(unscripted_b) == 0:
    additional_mapping = {}
  else:
    single_line_searcher = ScriptSearcher(threshold=0.3, window_size=1)
    single_line_searcher.build_b_index(unscripted_b.texts)
    unmatched_lines_a = [(i, l) for i, l in enumerate(script_a.texts) if i not in matches]
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
  with output_file.open("w", encoding="utf-8") as f:
    json.dump(additional_mapping, f, indent=2, ensure_ascii=False)

def gen_output(script_a, script_b, trans_a, unscripted_b, matches, unscripted_matches, output_filename: Path):
  expl = explain_llm_alignments(script_a, script_b) or {}
  gen_csv(script_a, script_b, trans_a, unscripted_b, matches, unscripted_matches, expl, str(output_filename))

def read_json_file(path: Path) -> Any:
  with path.open("r", encoding="utf-8") as f:
    return json.load(f)

def read_int_key_dict(path: Path) -> dict[int, Any]:
  data = read_json_file(path)
  return {int(k): v for k, v in data.items()}

def normalize_step_name(step: str | None) -> str | None:
  if step is None:
    return None
  normalized = STEP_ALIASES.get(step.strip().lower())
  if normalized is None:
    raise SystemExit(f"未知步骤: {step}")
  return normalized

def should_run_step(step: str, active_steps: list[str], forced_start: str | None, output_path: Path) -> bool:
  if step not in active_steps:
    return False
  if forced_start is not None:
    return active_steps.index(step) >= active_steps.index(forced_start)
  return not output_path.exists()

def resolve_effective_start(requested_step: str | None, active_steps: list[str], output_paths: dict[str, Path]) -> str | None:
  if requested_step is None:
    return None
  if requested_step not in active_steps:
    raise SystemExit(f"步骤 {requested_step} 当前不可用。可用步骤: {', '.join(active_steps)}")
  requested_index = active_steps.index(requested_step)
  effective_index = requested_index
  for index in range(requested_index):
    step = active_steps[index]
    if not output_paths[step].exists():
      effective_index = index
      break
  return active_steps[effective_index]

def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description="运行台词匹配主流程。")
  parser.add_argument("--from-step", help="从指定步骤开始重跑，可选值如 matches/anchors/top_k/additional/output")
  parser.add_argument("--remake-jp", default="scena_data_jp_Command.json")
  parser.add_argument("--script-data", default="script_data.json")
  parser.add_argument("--translation", default="scena_data_sc_Command.json")
  parser.add_argument("--additional-voice", default="additional_voice_fc.json")
  parser.add_argument("--matches-json", default="matches.json")
  parser.add_argument("--anchors-json", default="anchors.json")
  parser.add_argument("--top-k-json", default="top_k_matches.json")
  parser.add_argument("--unscripted-matches-json", default="unscripted_matches.json")
  parser.add_argument("--output-csv", default="match_result.csv")
  return parser

def main():
  args = build_parser().parse_args()

  script_a = RemakeScript(args.remake_jp)
  if len(script_a) == 0:
    raise SystemExit(f"未能读取 Remake 日文数据: {args.remake_jp}")

  script_b = Script(args.script_data)

  translation_path = Path(args.translation)
  trans_a = None
  if translation_path.exists():
    trans_a = RemakeScript(str(translation_path))
  else:
    logger.info(f"未找到中文翻译文件，已跳过: {translation_path}")

  additional_voice_path = Path(args.additional_voice)
  unscripted_b = None
  if additional_voice_path.exists():
    unscripted_b = UnscriptedConversation(str(additional_voice_path))
  else:
    logger.info(f"未找到附加语音文件，已跳过: {additional_voice_path}")

  output_paths = {
    "matches": Path(args.matches_json),
    "anchors": Path(args.anchors_json),
    "top_k": Path(args.top_k_json),
    "additional": Path(args.unscripted_matches_json),
    "output": Path(args.output_csv),
  }

  active_steps = ["matches", "anchors", "top_k"]
  if unscripted_b is not None and len(unscripted_b) > 0:
    active_steps.append("additional")
  active_steps.append("output")

  requested_step = normalize_step_name(args.from_step)
  forced_start = resolve_effective_start(requested_step, active_steps, output_paths)
  if requested_step is not None and forced_start != requested_step:
    logger.info(f"指定从 {requested_step} 开始，但前置产物不足，自动回退到 {forced_start}。")

  if should_run_step("matches", active_steps, forced_start, output_paths["matches"]):
    logger.info("执行步骤: matches")
    refresh_matches(script_a, script_b, output_paths["matches"])
  else:
    logger.info(f"跳过步骤: matches，已存在 {output_paths['matches']}")
  matches = read_json_file(output_paths["matches"])

  if should_run_step("anchors", active_steps, forced_start, output_paths["anchors"]):
    logger.info("执行步骤: anchors")
    optimize_with_anchors(script_a, script_b, matches, output_paths["anchors"])
  else:
    logger.info(f"跳过步骤: anchors，已存在 {output_paths['anchors']}")
  final_mapping = read_int_key_dict(output_paths["anchors"])

  if should_run_step("top_k", active_steps, forced_start, output_paths["top_k"]):
    logger.info("执行步骤: top_k")
    solve_gaps(script_a, script_b, matches, final_mapping, output_paths["top_k"])
  else:
    logger.info(f"跳过步骤: top_k，已存在 {output_paths['top_k']}")
  top_k_matches = read_int_key_dict(output_paths["top_k"])

  unscripted_matches = {}
  if "additional" in active_steps:
    if should_run_step("additional", active_steps, forced_start, output_paths["additional"]):
      logger.info("执行步骤: additional")
      add_unscripted_conversations(script_a, unscripted_b, top_k_matches, output_paths["additional"])
    else:
      logger.info(f"跳过步骤: additional，已存在 {output_paths['additional']}")
    unscripted_matches = read_int_key_dict(output_paths["additional"])

  if should_run_step("output", active_steps, forced_start, output_paths["output"]):
    logger.info("执行步骤: output")
    gen_output(script_a, script_b, trans_a, unscripted_b, top_k_matches, unscripted_matches, output_paths["output"])
  else:
    logger.info(f"跳过步骤: output，已存在 {output_paths['output']}")

  logger.info("\n--- 匹配统计 ---")
  logger.info(f"剧本A总台词数: {len(script_a.texts)}")
  logger.info(f"包含重复的匹配数: {len(matches)}")
  logger.info(f"锚点映射数: {len(final_mapping)}")
  logger.info(f"唯一匹配数: {len([m for m, v in top_k_matches.items() if len(v) == 1])}")
  logger.info(f"多个匹配数: {len([m for m, v in top_k_matches.items() if len(v) > 1])}")
  logger.info(f"脚本外语音贡献的匹配数: {len(unscripted_matches)}")
  logger.info(f"总匹配数（唯一/多个匹配+脚本外语音）: {len(unscripted_matches) + len([m for m, v in top_k_matches.items() if len(v) >= 1])}")

if __name__ == "__main__":
  main()