"""说话人（角色）约束辅助。

remake 脚本的 args[0] 是角色索引，EVO 脚本 voice_id 前三位是角色码。
speaker_map.json 记录 args[0] -> 角色码 的固定映射（由全量游戏数据推导）。
"""
import json
import os

_MAP_PATH = os.path.join(os.path.dirname(__file__), "speaker_map.json")


def load_speaker_map() -> dict[int, str]:
    try:
        with open(_MAP_PATH, "r", encoding="utf-8") as f:
            return {int(k): v for k, v in json.load(f).items()}
    except Exception:
        return {}


SPEAKER_MAP = load_speaker_map()


def args0_to_code(args0) -> str | None:
    """remake args[0] -> EVO 角色码（三位字符串），未知返回 None。"""
    if args0 is None:
        return None
    return SPEAKER_MAP.get(int(args0))


def voice_id_to_code(voice_id: str) -> str:
    """EVO voice_id -> 角色码（前三位）。"""
    if not voice_id:
        return ""
    return voice_id[:3]

def voice_id_to_scene(voice_id: str) -> str:
    """EVO voice_id -> 场景码（第4-6位）。"""
    if len(voice_id) < 6:
        return ""
    return voice_id[3:6]

def voice_id_to_seq(voice_id: str) -> int:
    """EVO voice_id -> 场景内序号（第7-10位）。"""
    try:
        return int(voice_id[6:10]) if len(voice_id) >= 10 else 0
    except ValueError:
        return 0
