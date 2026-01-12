import json
from dotenv import load_dotenv
from openai import OpenAI
import os
import logging 

logger = logging.getLogger()

# 默认配置（可根据你的服务商修改）
load_dotenv()
client = OpenAI(
    base_url=os.getenv("OPENAI_BASE_URL"),
    api_key=os.getenv("OPENAI_API_KEY")
)

def call_llm_for_local_alignment(sub_a, sub_b):
    """
    sub_a: 剧本A的子列表 (list of strings)
    sub_b: 剧本B的子列表 (list of strings)
    """
    
    # 构建输入文本，带上索引以便LLM引用
    formatted_a = "\n".join([f"A[{i}]: {text}" for i, text in enumerate(sub_a)])
    formatted_b = "\n".join([f"B[{j}]: {text}" for j, text in enumerate(sub_b)])

    system_prompt = """你是一个游戏剧本对齐专家。你的任务是分析两组日文剧本片段，并找出它们之间的对应关系。
注意：
1. 忽略《》、☆、符号差异以及Ruby括号（振假名）。
2. 匹配的内容需要高度一致，仅仅允许个别表达或同义词汇的使用不同。
3. 可能会出现多行对应一行（合并），或一行对应多行（拆分）的情况。
4. 如果某一行在对方剧本中完全不存在，对应索引设为 null。

请仅返回 JSON 格式结果，格式如下：
{"alignment": [{"a": [0], "b": [0]}, {"a": [1], "b": [1, 2]}]}"""

    user_prompt = f"""请对齐以下剧本片段：

### 剧本 A:
{formatted_a}

### 剧本 B:
{formatted_b}

输出 JSON 对齐结果："""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini", # 或 deepseek-chat, qwen-turbo 等小模型
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"}, # 强制要求返回 JSON
            temperature=0.1 # 降低随机性，保证稳定性
        )
        
        # 解析返回内容
        result = json.loads(response.choices[0].message.content)
        logger.info(f"LLM Alignment Result: {result}")
        return result.get("alignment", [])

    except Exception as e:
        logger.error(f"LLM Alignment Error: {e}")
        return None

# --- 使用示例 ---
if __name__ == "__main__":
    # sub_a = [
    #     "やったねヨシュア!これで晴れてあたしたちも協会の一员よ",
    #     "そうか、僕が遊撃士か......"
    # ]
    # sub_b = [
    #     "やったねヨシュア!これで晴れてあたしたちも協会の一员よ☆そうか、僕が遊撃士か......"
    # ]
#  A[19517]: メーヴェ海道沿いの砂浜にガケに囲まれた窪地のような場所があってね。
#  A[19518]: その場所こそ──ズバリこの△印で描かれている地点だと思うんだ。
#  B[12693]: メーヴェ海道沿いの砂浜にガケに囲まれた窪地のような場所があるんだけど……
#  B[12694]: 宝の地図にはその窪地が目印として描かれているんだ。
    sub_a = [
        "メーヴェ海道沿いの砂浜にガケに囲まれた窪地のような場所があってね。",
        "その場所こそ──ズバリこの△印で描かれている地点だと思うんだ。"
    ]
    sub_b = [
        "メーヴェ海道沿いの砂浜にガケに囲まれた窪地のような場所があるんだけど……",
        "宝の地図にはその窪地が目印として描かれているんだ。"
    ]

    alignment = call_llm_for_local_alignment(sub_a, sub_b)
    print(alignment)
    # 输出预想: [{"a": [0, 1], "b": [0]}]
