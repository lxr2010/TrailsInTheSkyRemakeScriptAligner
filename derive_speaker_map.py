# -*- coding: utf-8 -*-
"""从一次匹配结果推导 args[0] -> 角色码 映射（speaker_map.json）。

用法:
    python derive_speaker_map.py <scena_data_jp_Command.json> <match_result.csv> [-o speaker_map.json]

原理:
    - args[0]（remake 角色索引）来自 scena 数据里每个台词命令的第一个整数参数
    - 角色码（EVO ch 代码）来自匹配结果 OldVoiceFilename 的 ch 后 3 位
    - 对每个 args[0] 做多数投票；歧义（>=3 种角色码，或占比 < 80%）跳过

注意:
    - 建议从【未启用说话人约束】的一次匹配结果推导，避免自举循环；
      但多数投票对少量匹配误差很鲁棒（匹配精确率 >= 90% 即可）。
"""
import argparse
import csv
import json
from collections import Counter, defaultdict


def extract_args0(scena_path: str) -> list[int | None]:
    with open(scena_path, "r", encoding="utf-8") as f:
        scena = json.load(f)
    out = []
    for e in scena:
        a = e.get("args")
        out.append(a[0] if isinstance(a, list) and a and isinstance(a[0], int) else None)
    return out


def extract_ch_code(match_csv_path: str) -> list[str | None]:
    with open(match_csv_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        fn = r.get("OldVoiceFilename", "").strip()
        out.append(fn[2:5] if fn.startswith("ch") and len(fn) >= 5 else None)
    return out


def derive(args0_list: list[int | None], ch_list: list[str | None], min_ratio: float = 0.9):
    mp = defaultdict(Counter)
    for a, c in zip(args0_list, ch_list):
        if a is not None and c is not None:
            mp[a][c] += 1
    mapping = {}
    ambiguous = []
    for a, counter in sorted(mp.items()):
        total = sum(counter.values())
        code, cnt = counter.most_common(1)[0]
        ratio = cnt / total
        if ratio < min_ratio:
            ambiguous.append((a, dict(counter), ratio))
        else:
            mapping[a] = code
    return mapping, ambiguous


def main():
    parser = argparse.ArgumentParser(description="从匹配结果推导 speaker_map.json")
    parser.add_argument("scena", help="scena_data_jp_Command.json 路径")
    parser.add_argument("match_csv", help="match_result.csv 路径")
    parser.add_argument("-o", "--output", default="speaker_map.json")
    parser.add_argument("--min-ratio", type=float, default=0.9, help="多数占比阈值，低于则判为歧义跳过（默认 0.9）")
    args = parser.parse_args()

    args0 = extract_args0(args.scena)
    ch = extract_ch_code(args.match_csv)
    if len(args0) != len(ch):
        raise SystemExit(f"长度不一致: scena {len(args0)} 行 vs csv {len(ch)} 行")

    mapping, ambiguous = derive(args0, ch, args.min_ratio)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=0)

    print(f"推导出 {len(mapping)} 条映射，写入 {args.output}")
    print(f"歧义跳过 {len(ambiguous)} 个 args[0]:")
    for a, counter, ratio in ambiguous:
        print(f"  args[0]={a} -> {dict(counter)} (占比 {ratio:.0%})")


if __name__ == "__main__":
    main()
