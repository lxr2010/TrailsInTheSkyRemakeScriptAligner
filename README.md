# Trails In The Sky Script Aligner

空之轨迹1st（Remake）与空之轨迹FC进化版（EVO）台词对齐工具。

最近为了更好地应用大模型能力，对原来的 [sora-scena-matcher](https://github.com/lxr2010/sora-scena-matcher) 进行了重构。
重构后的脚本设计上也可迁移到将来的空之轨迹 2nd，甚至零/碧轨脚本比对场景。

本项目核心流程：
- 从 1st Remake 的 scena 反编译结果中提取 `Cmd_text_00/06` 等价数据（`scena_data_*_Command.json`）。
- 从 EVO 文本提取 `script_data.json`。
- 通过 `main.py` 执行多阶段匹配并输出 `match_result.csv`。

## 历史匹配统计（参考）

以下是空之轨迹 1st 的一次完整匹配结果统计（用于衡量脚本质量）：

--- 匹配统计 ---
- 剧本A总台词数: 47063
- 包含重复的匹配数: 44970
- 锚点映射数: 25658
- 唯一匹配数: 28445
- 多个匹配数: 235
- 脚本外语音贡献的匹配数: 378
- 总匹配数（唯一/多个匹配+脚本外语音）: 29058


## 特点

- 位置敏感哈希算法 + 基于锚点的优化 + 最小编辑距离匹配
- 保留多候选项匹配
- 匹配项 `rapidfuzz WRatio` 分数超过 92
- 复杂匹配场景通过大模型预测候选项
- 处理相同的重置版与 EVO 台词，成功匹配数达到 29058，接近人工校对水平（27537）
- 精度相比原始版本有明显提高
- 识别片假名、轨迹系列专有名词、ED6 旧引擎 Gaiji
- 无 pytorch/GPU 需求

---

## 1. 环境准备（uv）

项目使用 `uv` 管理 Python 环境和依赖。

```bash
# 1) 初始化/创建虚拟环境并安装依赖
uv sync

# 2) 运行主流程
uv run python main.py
```

### Python 版本
- `pyproject.toml` 当前要求 `>=3.13`。

---

## 2. `.env` 配置说明

复制示例文件：

```bash
copy .env.example .env
```

`.env` 至少需要：

```env
OPENAI_API_KEY=sk-xxxxx
OPENAI_BASE_URL=https://api.openai.com/v1
```

说明：
- `OPENAI_BASE_URL` 只要兼容 OpenAI API 即可（官方/第三方网关均可）。
- 代码中默认模型名写在 `llm.py`（当前为 `gpt-4o-mini`），如需替换请在该文件中调整。

---

## 3. 文件与脚本说明

### scena 源文件来源与批量反编译

- `script.pac/scena/*.dat` 是 scena 文件的原始来源。
- `script.pac` 需要先解包（可用 `kuro_dlc_tool/sky_extract_pac.py` 或其他可用工具）后，才能拿到 `.dat`。
- 以下示例假设日语 `.dat` 位于 `extracted/script/scena`。

#### 使用 KuroTools 批量反编译为 Python（输出到 `disasm-py`）

```powershell
$src = "extracted/script/scena"
$out = "disasm-py"
New-Item -ItemType Directory -Force -Path $out | Out-Null

Get-ChildItem $src -Filter *.dat -File | ForEach-Object {
    uv run python .\KuroTools\dat2py.py --decompile True --markers False $_.FullName
    $generated = Join-Path (Get-Location) ($_.BaseName + ".py")
    if (Test-Path $generated) {
        Move-Item -Force $generated (Join-Path $out ($_.BaseName + ".py"))
    }
}
```

#### 使用 Ingert 批量解析为 `.ing`（输出到 `disasm`）

```powershell
$src = "extracted/script/scena"
$out = "disasm"
New-Item -ItemType Directory -Force -Path $out | Out-Null

Get-ChildItem $src -Filter *.dat -File | ForEach-Object {
    .\ingert.exe --mode tree --no-called -o (Join-Path $out ($_.BaseName + ".ing")) $_.FullName
}
```

说明：Ingert 使用 `--no-called` 可以保留 call table 相关信息，便于后续 `add_struct` / `line_corr` 对齐。

### 主脚本
- `main.py`
  - 输入：
    - 必需：`scena_data_jp_Command.json`（1st 日文）
    - 必需：`script_data.json`（EVO）
    - 可选：`scena_data_sc_Command.json`（1st 简中翻译）
    - 可选：`additional_voice_fc.json`（脚本外语音转录）
  - 主流程：
    1. `load_required_inputs` / `load_optional_inputs`
    2. `run_core_matching_flow` 生成 `matches.json` / `anchors.json` / `top_k_matches.json`
    3. `run_additional_voice_flow` 生成 `unscripted_matches.json`（若存在附加语音输入）
    4. `run_output_flow` 生成最终 `match_result.csv`

### 三个新增辅助脚本
- `scena_voice_kuro_extractor.py`
  - 用途：处理 **KuroTools 反编译得到的 Python 格式** scena 脚本，提取 `Cmd_text_00/06`。
  - 结果：输出 `scena_data_{jp|sc}.json` 及按类型拆分的 `*_Command.json` / `*_add_struct.json`。

- `ingert_voice_kuro_extractor.py`
  - 用途：处理 **Ingert 反编译得到的 Ingert 格式** scena 脚本，提取与上面相同结构的数据。
  - 映射关系：
    - `system[5,0] -> Cmd_text_00`
    - `system[5,6] -> Cmd_text_06`
    - calltable 对应 Python 版本中的 `add_struct`
  - 结果命名与 `scena_voice_kuro_extractor.py` 保持一致（支持 `jp/sc` 批量导出）。

- `extract_voice_data.py`
  - 用途：处理 EVO 文本脚本（`SoraVoiceScripts\cn.fc\out.msg`）并生成：
    - `script_data.json`（按 `script_id` 去重）
    - `voice_data.json`（按 `voice_id` 去重）

---

## 4. Ingert 与 KuroTools 选择说明

`ingert_voice_kuro_extractor.py` 与 `scena_voice_kuro_extractor.py` 都是为了生成同一套 `scena_data_*` 数据。

- Ingert 路线：输入是 `.ing`（Ingert 格式）
- KuroTools 路线：输入是 `.py`（Python 格式）

两种反编译结果语义一致，**二选一即可**，不需要同时使用。

### Ingert 反编译注意项
- 反编译 `.dat` 到 `.ing` 时需要带 `--no-called`，确保输出 calltable。
- 若没有 calltable，会影响 `add_struct` 侧数据与 `line_corr` 关联。

---

## 5. KuroTools 未定义 Command 的 fallback 修复

某些脚本包含未收录命令时，KuroTools 可能在命令名映射阶段报错。建议加入 fallback：

- `KuroTools/disasm/ED9InstructionsSet.py:1735`
  - 对 `commands_dict` 查找增加兜底，未知命令统一回退为：
  - `Cmd_unknown_{structID:02X}_{opCode:02X}`

- `KuroTools/disasm/ED9Assembler.py:890`
  - 对 `reverse_commands_dict` 查找增加兜底；
  - 能解析 `Cmd_unknown_XX_YY` 时直接反算回 `(XX, YY)`；
  - 否则 fallback 到 `(0xFF, 0xFF)` 并输出警告。

---

## 6. 推荐执行顺序

1. `uv sync`
2. 配置 `.env`
3. 生成 1st scena 数据（二选一）：
   - KuroTools 路线：`uv run python scena_voice_kuro_extractor.py`
   - Ingert 路线：`uv run python ingert_voice_kuro_extractor.py --jp-input <jp_ing_dir_or_file> --sc-input <sc_ing_dir_or_file> --output-dir .`
4. 生成 EVO 文本数据：`uv run python extract_voice_data.py`
5. 跑匹配主流程：`uv run python main.py`

`main.py` 当前的输入分为：
- 必需输入：
  - `scena_data_jp_Command.json`
  - `script_data.json`
- 可选输入：
  - `scena_data_sc_Command.json`（中文翻译）
  - `additional_voice_fc.json`（脚本外语音转录）

`main.py` 内部已拆分为几个清晰流程：
- `load_required_inputs`：加载必需输入
- `load_optional_inputs`：加载可选输入
- `run_core_matching_flow`：执行 `matches -> anchors -> top_k`
- `run_additional_voice_flow`：处理脚本外语音补充匹配
- `run_output_flow`：生成 `match_result.csv`
- `log_matching_stats`：输出统计信息

### `main.py` 默认行为

直接运行：

```powershell
uv run python main.py
```

默认逻辑：
- 会先检查各步骤输出文件是否已存在。
- 若输出已存在，则自动跳过对应步骤。
- 若输出不存在，则执行该步骤。
- 若 `scena_data_sc_Command.json` 不存在，则跳过中文翻译。
- 若 `additional_voice_fc.json` 不存在，则跳过脚本外语音补充匹配。

### 从指定步骤开始

可以通过 `--from-step` 指定从某一步开始：

```powershell
uv run python main.py --from-step top_k
```

可用步骤名：
- `matches`
- `anchors`
- `top_k`
- `additional`
- `output`

说明：
- 如果你指定从某一步开始，但前置所需的 `.json` 中间文件不存在，程序会自动回退到最早缺失的前置步骤开始执行。

### 常用参数

- `--remake-jp`
  - Remake 日文输入
  - 默认：`scena_data_jp_Command.json`

- `--script-data`
  - EVO Script 文本输入
  - 默认：`script_data.json`

- `--translation`
  - Remake 中文翻译输入，可选
  - 默认：`scena_data_sc_Command.json`

- `--additional-voice`
  - 脚本外语音转录输入，可选
  - 默认：`additional_voice_fc.json`

- `--matches-json`
  - `matches` 步骤输出
  - 默认：`matches.json`

- `--anchors-json`
  - `anchors` 步骤输出
  - 默认：`anchors.json`

- `--top-k-json`
  - `top_k` 步骤输出
  - 默认：`top_k_matches.json`

- `--unscripted-matches-json`
  - `additional` 步骤输出
  - 默认：`unscripted_matches.json`

- `--output-csv`
  - 最终输出 CSV
  - 默认：`match_result.csv`

输出核心文件：
- `match_result.csv`
- `matches.json` / `anchors.json` / `top_k_matches.json`
- `unscripted_matches.json`（存在附加语音输入时）
- `llm_*.json`（LLM缓存）

## 7. 脚本外语音转录 JSON（`additional_voice_fc.json`）

为了补充 **EVO 版本中存在、但没有出现在 `script_data.json` / Script 文本中的语音**，当前流程支持额外读取一份脚本外语音转录 JSON。

这些语音的来源与处理方式如下：
- 先分析补丁音频目录，找出存在于 EVO 音频文件中、但未被 Script 文本收录的语音编号。
- 再使用 WhisperX 的 `large-v2` 模型、`ja` 语言，对这些音频逐条转录。
- 最终将 `voice_id` 与对应转录文本 `text` 保存为 `additional_voice_fc.json`。

说明：
- `main.py` 当前默认直接读取工作目录下的 `additional_voice_fc.json`：
  - `unscripted_b = UnscriptedConversation("additional_voice_fc.json")`
- 这个输入是**可选的**。
- 如果文件不存在，程序会自动跳过脚本外语音补充匹配流程。
- 如果你的文件实际放在其他目录，可以通过 `--additional-voice <path>` 指定。

### JSON 格式示例

```json
[
  {
    "voice_id": "0010000782V",
    "text": "おはよう、リノンさん!"
  },
  {
    "voice_id": "0010000785V",
    "text": "えっ、新しいの入ってるの?"
  },
  {
    "voice_id": "0010060643V",
    "text": ""
  }
]
```

字段说明：
- `voice_id`
  - EVO 语音编号。
  - 当前数据中一般保留结尾的 `V`，例如 `0010000782V`。
- `text`
  - WhisperX 转录得到的日文文本。
  - 允许为空字符串，表示该音频未能得到有效文本，或内容主要为喘息、语气词、杂音等。

使用方式：
- 当 `main.py` 执行到 `add_unscripted_conversations(...)` 时，会把这份 JSON 作为剧本外语音集合参与匹配。
- 这些额外命中的结果会输出到：
  - `unscripted_matches.json`
- 同时也会体现在最终的：
  - `match_result.csv`
- 匹配统计中的 `脚本外语音贡献的匹配数`，就是来自这部分数据。

适用场景：
- EVO 有音频，但 `script_data.json` 中没有对应文本记录。
- 需要尽量把 Remake 中的额外语音也补配到旧版 EVO 音频。
- 想把原本 `unmatched` 的一部分台词，进一步通过转录文本召回。

---

## 8. 生成音频匹配校验 HTML

`build_match_result_html.py` 可以把 `match_result.csv` 转成一个本地 HTML 检查页，方便人工校验匹配结果与音频是否对应。

功能概览：
- 按 `OldVoiceFilename` 优先定位 EVO 音频；
- 若 `OldVoiceFilename` 为空，则 fallback 到 `RemakeVoiceID -> ch<id>.ogg`；
- 在 HTML 中写入绝对 `file:///...` 音频地址，避免 `game-file-fc` 为软链接时相对路径失效；
- 提供筛选、分页、全局播放器，以及音频是否存在的检查结果。

### 基本用法

在项目目录执行：

```powershell
uv run python build_match_result_html.py
```

默认行为：
- 输入 CSV：`match_result.csv`
- 音频目录：`..\game-file-fc\voice\ogg`
- 输出 HTML：`match_result_review.html`

生成后，直接用浏览器打开 `match_result_review.html` 即可。

### 参数说明

- `--csv`
  - 输入的匹配结果 CSV 路径。
  - 默认值：`match_result.csv`

- `--voice-dir`
  - EVO `ogg` 音频目录。
  - 脚本会根据 CSV 中的 `OldVoiceFilename` 或 `RemakeVoiceID` 去这里查找音频文件。
  - 默认值：`..\game-file-fc\voice\ogg`

- `--html`
  - 输出 HTML 路径。
  - 默认值：`match_result_review.html`

### 指定参数示例

```powershell
uv run python build_match_result_html.py \
  --csv .\match_result.csv \
  --voice-dir ..\game-file-fc\voice\ogg \
  --html .\output\match_result_review.html
```

### 常用用法

- 重新生成默认检查页：

```powershell
uv run python build_match_result_html.py
```

- 指定其他 CSV：

```powershell
uv run python build_match_result_html.py --csv .\some_other_match_result.csv
```

- 指定其他音频目录：

```powershell
uv run python build_match_result_html.py --voice-dir F:\path\to\voice\ogg
```

- 把 HTML 输出到单独目录：

```powershell
uv run python build_match_result_html.py --html .\output\review\match_result_review.html
```
### 调用流程图（Mermaid）

#### 整体数据流程图

```mermaid
flowchart LR
    A[script.pac] --> B[解包工具\n如 sky_extract_pac.py]
    B --> C[extracted/script/scena/*.dat]

    C --> D1[KuroTools/dat2py.py 批量反编译]
    C --> D2[Ingert 批量解析\n--mode tree --no-called]

    D1 --> E1[disasm-py/*.py]
    D2 --> E2[disasm/*.ing]

    E1 --> F1[scena_voice_kuro_extractor.py]
    E2 --> F2[ingert_voice_kuro_extractor.py]

    F1 --> G[scena_data_jp_Command.json\n必需输入]
    F2 --> G

    H[SoraVoiceScripts EVO 文本] --> I[extract_voice_data.py]
    I --> J[script_data.json\n必需输入]

    AA[补丁音频目录分析 + WhisperX large-v2/ja] --> AB[additional_voice_fc.json\n可选输入]

    G --> K[main.py]
    J --> K
    L[scena_data_sc_Command.json\n可选输入] --> K
    AB --> K

    K --> M[matches.json]
    K --> N[anchors.json]
    K --> O[top_k_matches.json]
    K --> R[unscripted_matches.json\n可选输出]
    K --> P[match_result.csv]
    K --> Q[llm_*.json 缓存]
```

#### main.py 内部流程图

```mermaid
flowchart TD
    A1[读取必需输入\nJP scena + EVO script] --> A2[读取可选输入\n中文翻译 + additional_voice_fc.json]
    A2 --> B1[检查已有中间产物\n并根据 --from-step 决定起点]
    B1 --> C1[refresh_matches\n生成或读取 matches.json]
    C1 --> C2[optimize_with_anchors\n生成或读取 anchors.json]
    C2 --> C3[solve_gaps\n生成或读取 top_k_matches.json]
    C3 --> D2[add_unscripted_conversations\n生成或读取 unscripted_matches.json]
    D2 --> E1[gen_output]
    A2 --> E1
    E1 --> E2[输出 match_result.csv]
    E2 --> E3[输出匹配统计]
```

---

## 空之轨迹1st 简中翻译错位清单（历史备注）

目前大模型暂时无法完全自动对齐中文翻译与日语原文。`match_result.csv` 中已知会出现如下错位项：

- `74423-74428`（次元模组台词修改）：中文翻译比日语原文多一句；需删除其中一行及对应翻译单元格并上移。
- `79491`：`抽、抽一根之后，我就会放回去的…… / 马上就会放回去…… / 工房长…………` 中间这句中文翻译为额外增加，需删除。
- `79508`：`我一直在拼命思考解决办法，不知为何，突然就非常想抽烟。 / 我一直在拼命思考解决办法…… / 唉…………` 中间这句中文翻译为额外增加，需删除。

---

## SC / 3rd 迁移说明

当前流程不依赖 1st 专属格式，迁移到 SC / 3rd 的关键是替换输入数据并做少量参数调优。

### 1) 准备输入数据
- Remake 侧（A）：沿用本仓库的提取流程，生成对应作品的 `scena_data_jp_Command.json` 与 `scena_data_sc_Command.json`。
- EVO/原版侧（B）：用 `extract_voice_data.py`（或同结构脚本）生成对应作品的 `script_data.json`。
- 要求：A/B 两侧都应保持同一作品、同一区域版本（避免混用不同补丁源）。

### 2) 文件名与路径适配
- 最简单做法：直接把 SC/3rd 生成的数据文件命名成 `main.py` 当前固定读取的三个文件名：
  - `scena_data_jp_Command.json`
  - `scena_data_sc_Command.json`
  - `script_data.json`
- 或者修改 `main.py` 中 `RemakeScript(...)` / `Script(...)` 的输入路径，分别建立 SC、3rd 的独立入口脚本（推荐）。

### 3) 验证步骤
- 先看 `matches.json`：确认召回是否足够。
- 再看 `anchors.json`：确认锚点是否覆盖关键剧情段。
- 最后看 `match_result.csv`：抽查章节开头、分支段、战斗后对白等高风险区。

---

## 鸣谢

本项目开发与数据处理流程，受以下开源项目启发或直接受益，感谢各位作者：

- KuroTools  
  https://github.com/nnguyen259/KuroTools

- kuro_dlc_tool  
  https://github.com/eArmada8/kuro_dlc_tool

- Ingert  
  https://github.com/Aureole-Suite/Ingert

- SoraVoiceScripts  
  https://github.com/ZhenjianYang/SoraVoiceScripts

---

## 版权声明

- 本项目处理涉及的游戏脚本文本、语音、图像及其他资源，其著作权与相关权利归原游戏公司及权利人所有。
- 本仓库提供的代码仅用于学习、研究与非商业交流，按宽松开源方式提供。
- 严禁将本项目代码、处理结果或衍生资源用于任何商业用途（包括但不限于售卖、付费分发、商业化服务）。
- 使用者应自行确保其行为符合所在地法律法规及相关游戏/平台协议；由使用行为产生的责任由使用者自行承担。

---

## English Translation

`Trails In The Sky Remake Script Aligner` is a dialogue alignment toolkit for **Trails in the Sky the 1st (Remake)** and **Trails in the Sky FC Evolution (EVO)**.

This project is a refactor of [sora-scena-matcher](https://github.com/lxr2010/sora-scena-matcher), rebuilt to better leverage LLM-based matching.
The same architecture is also intended to be portable to SC / 3rd and potentially Zero/Ao workflows.

Core pipeline:
- Extract `Cmd_text_00/06`-equivalent data from the Remake scena decompilation output (`scena_data_*_Command.json`).
- Extract `script_data.json` from EVO text scripts.
- Run multi-stage alignment via `main.py` and produce `match_result.csv`.

### Historical Matching Stats (Reference)

One full run on Trails in the Sky the 1st produced:

--- Matching Stats ---
- Total lines in Script A: 47063
- Matches with duplicates: 44970
- Anchor mappings: 25658
- Unique matches: 28445
- Multi-candidate matches: 235
- Script-outside-voice contributions: 378
- Total matches (unique + multi + script-outside-voice): 29058

### Features

- Position-aware hashing + anchor-based optimization + minimum-edit-distance matching
- Preserves multi-candidate matches
- `rapidfuzz WRatio` score typically above 92 for matched items
- Uses LLM to handle hard/ambiguous matching cases
- On Remake vs EVO alignment, achieved 29058 matched lines (close to manual proofreading result: 27537)
- Significantly improved precision over the original version
- Handles katakana, Trails-specific terms, and ED6 gaiji text patterns
- No PyTorch/GPU dependency

---

### 1. Environment Setup (`uv`)

This project uses `uv` for environment and dependency management.

```bash
# 1) Create/sync virtual environment and install dependencies
uv sync

# 2) Run the main pipeline
uv run python main.py
```

Python version:
- `pyproject.toml` currently requires `>=3.13`.

---

### 2. `.env` Configuration

Copy the example file:

```bash
copy .env.example .env
```

Required fields:

```env
OPENAI_API_KEY=sk-xxxxx
OPENAI_BASE_URL=https://api.openai.com/v1
```

Notes:
- Any OpenAI-compatible endpoint works for `OPENAI_BASE_URL`.
- Default model names are configured in `llm.py` (currently `gpt-4o-mini`).

---

### 3. Files and Scripts

#### Scena source files and batch decompilation

- `script.pac/scena/*.dat` are the source files for scena scripts.
- You need to unpack `script.pac` first (e.g., `kuro_dlc_tool/sky_extract_pac.py`, or any equivalent unpacking tool) to obtain `.dat` files.
- The examples below assume JP `.dat` files are under `extracted/script/scena`.

#### Batch decompile with KuroTools to Python (output to `disasm-py`)

```powershell
$src = "extracted/script/scena"
$out = "disasm-py"
New-Item -ItemType Directory -Force -Path $out | Out-Null

Get-ChildItem $src -Filter *.dat -File | ForEach-Object {
    uv run python .\KuroTools\dat2py.py --decompile True --markers False $_.FullName
    $generated = Join-Path (Get-Location) ($_.BaseName + ".py")
    if (Test-Path $generated) {
        Move-Item -Force $generated (Join-Path $out ($_.BaseName + ".py"))
    }
}
```

#### Batch parse with Ingert to `.ing` (output to `disasm`)

```powershell
$src = "extracted/script/scena"
$out = "disasm"
New-Item -ItemType Directory -Force -Path $out | Out-Null

Get-ChildItem $src -Filter *.dat -File | ForEach-Object {
    .\ingert.exe --mode tree --no-called -o (Join-Path $out ($_.BaseName + ".ing")) $_.FullName
}
```

Note: using Ingert with `--no-called` preserves call table related information, which helps downstream `add_struct` / `line_corr` alignment.

#### Main script
- `main.py`
  - Inputs:
    - Required: `scena_data_jp_Command.json` (1st Japanese)
    - Required: `script_data.json` (EVO)
    - Optional: `scena_data_sc_Command.json` (1st Simplified Chinese)
    - Optional: `additional_voice_fc.json` (out-of-script voice transcripts)
  - Pipeline:
    1. `refresh_matches` -> `matches.json`
    2. `optimize_with_anchors` -> `anchors.json`
    3. `solve_gaps` -> `top_k_matches.json`
    4. `add_unscripted_conversations` -> `unscripted_matches.json` (optional)
    5. `gen_output` -> `match_result.csv`

#### Three helper scripts
- `scena_voice_kuro_extractor.py`
  - Parses **KuroTools Python-format** scena output.
  - Extracts `Cmd_text_00/06` and outputs `scena_data_{jp|sc}.json`, plus `*_Command.json` / `*_add_struct.json`.

- `ingert_voice_kuro_extractor.py`
  - Parses **Ingert-format** scena output (`.ing`).
  - Mapping:
    - `system[5,0] -> Cmd_text_00`
    - `system[5,6] -> Cmd_text_06`
    - calltable corresponds to Python-side `add_struct`
  - Output naming is aligned with `scena_voice_kuro_extractor.py` (supports jp/sc batch mode).

- `extract_voice_data.py`
  - Parses EVO text scripts (`SoraVoiceScripts\cn.fc\out.msg`) and generates:
    - `script_data.json` (deduplicated by `script_id`)
    - `voice_data.json` (deduplicated by `voice_id`)

---

### 4. Ingert vs KuroTools

`ingert_voice_kuro_extractor.py` and `scena_voice_kuro_extractor.py` produce the same `scena_data_*` schema.

- Ingert route: input is `.ing` (Ingert format)
- KuroTools route: input is `.py` (Python format)

They are semantically equivalent for this workflow, so you only need one route.

Ingert note:
- Use `--no-called` when decompiling `.dat` to `.ing` so calltable is included.
- Missing calltable reduces `add_struct`-side extraction and weakens `line_corr` linking.

---

### 5. Fallback for Undefined KuroTools Commands

When scripts contain unregistered commands, KuroTools may fail during command-name resolution.
It is recommended to add fallbacks at:

- `KuroTools/disasm/ED9InstructionsSet.py:1735`
  - Add a fallback around `commands_dict` lookup:
  - `Cmd_unknown_{structID:02X}_{opCode:02X}`

- `KuroTools/disasm/ED9Assembler.py:890`
  - Add a fallback around `reverse_commands_dict` lookup.
  - If name matches `Cmd_unknown_XX_YY`, convert back to `(XX, YY)`.
  - Otherwise fallback to `(0xFF, 0xFF)` with a warning.

---

### 6. Recommended Run Order

1. `uv sync`
2. Configure `.env`
3. Generate 1st scena data (choose one route):
   - KuroTools route: `uv run python scena_voice_kuro_extractor.py`
   - Ingert route: `uv run python ingert_voice_kuro_extractor.py --jp-input <jp_ing_dir_or_file> --sc-input <sc_ing_dir_or_file> --output-dir .`
4. Generate EVO text data: `uv run python extract_voice_data.py`
5. Run alignment: `uv run python main.py`

`main.py` currently uses:
- Required inputs:
  - `scena_data_jp_Command.json`
  - `script_data.json`
- Optional inputs:
  - `scena_data_sc_Command.json` (Chinese translation)
  - `additional_voice_fc.json` (out-of-script voice transcripts)

Default behavior:
- Existing step outputs are skipped automatically.
- Missing step outputs are generated automatically.
- If `scena_data_sc_Command.json` is missing, Chinese translation is skipped.
- If `additional_voice_fc.json` is missing, the additional voice matching step is skipped.

Start from a specific step:

```powershell
uv run python main.py --from-step top_k
```

Available step names:
- `matches`
- `anchors`
- `top_k`
- `additional`
- `output`

Note:
- If you request a later step but prerequisite `.json` files are missing, the program automatically falls back to the earliest required previous step.

Common arguments:
- `--remake-jp`
  - Remake JP input
  - Default: `scena_data_jp_Command.json`
- `--script-data`
  - EVO script input
  - Default: `script_data.json`
- `--translation`
  - Optional Remake Chinese translation input
  - Default: `scena_data_sc_Command.json`
- `--additional-voice`
  - Optional out-of-script voice transcript input
  - Default: `additional_voice_fc.json`
- `--matches-json`
  - Output for the `matches` step
  - Default: `matches.json`
- `--anchors-json`
  - Output for the `anchors` step
  - Default: `anchors.json`
- `--top-k-json`
  - Output for the `top_k` step
  - Default: `top_k_matches.json`
- `--unscripted-matches-json`
  - Output for the `additional` step
  - Default: `unscripted_matches.json`
- `--output-csv`
  - Final CSV output
  - Default: `match_result.csv`

Main outputs:
- `match_result.csv`
- `matches.json` / `anchors.json` / `top_k_matches.json`
- `unscripted_matches.json` (when additional voice input is available)
- `llm_*.json` (LLM cache)

### Flow Diagrams (Mermaid)

#### Overall Data Flow

```mermaid
flowchart LR
    A[script.pac] --> B[Unpack tool\ne.g. sky_extract_pac.py]
    B --> C[extracted/script/scena/*.dat]

    C --> D1[KuroTools/dat2py.py\nBatch decompile]
    C --> D2[Ingert batch parse\n--mode tree --no-called]

    D1 --> E1[disasm-py/*.py]
    D2 --> E2[disasm/*.ing]

    E1 --> F1[scena_voice_kuro_extractor.py]
    E2 --> F2[ingert_voice_kuro_extractor.py]

    F1 --> G[scena_data_jp_Command.json\nrequired input]
    F2 --> G

    H[SoraVoiceScripts EVO text] --> I[extract_voice_data.py]
    I --> J[script_data.json\nrequired input]

    AA[Patch audio scan + WhisperX large-v2/ja] --> AB[additional_voice_fc.json\noptional input]

    G --> K[main.py]
    J --> K
    L[scena_data_sc_Command.json\noptional input] --> K
    AB --> K

    K --> M[matches.json]
    K --> N[anchors.json]
    K --> O[top_k_matches.json]
    K --> R[unscripted_matches.json\noptional output]
    K --> P[match_result.csv]
    K --> Q[llm_*.json cache]
```

#### `main.py` Internal Flow

```mermaid
flowchart TD
    A1[Load required inputs\nJP scena + EVO script] --> A2[Load optional inputs\nChinese translation + additional_voice_fc.json]
    A2 --> B1[Check existing intermediate files\nand resolve the effective start step]
    B1 --> C1[refresh_matches\ncreate or reuse matches.json]
    C1 --> C2[optimize_with_anchors\ncreate or reuse anchors.json]
    C2 --> C3[solve_gaps\ncreate or reuse top_k_matches.json]
    C3 --> D2[add_unscripted_conversations\ncreate or reuse unscripted_matches.json]
    D2 --> E1[gen_output]
    A2 --> E1
    E1 --> E2[Write match_result.csv]
    E2 --> E3[Print matching statistics]
```

---

### Migration Notes for SC / 3rd

The pipeline is not 1st-exclusive. For SC / 3rd, the key step is replacing the input data.

1) Prepare input data:
- Remake side (A): generate `scena_data_jp_Command.json` and `scena_data_sc_Command.json` for the target game.
- EVO/original side (B): generate `script_data.json` with `extract_voice_data.py` (or a structurally equivalent tool).
- Keep A/B from the same game and region baseline to avoid patch-source mixing.

2) Adapt file paths:
- Easiest: rename generated files to what `main.py` expects by default.
- Better: create separate entry scripts (SC/3rd) and change input paths in `RemakeScript(...)` / `Script(...)`.

3) Validation:
- Check `matches.json` for recall.
- Check `anchors.json` for anchor coverage.
- Spot-check `match_result.csv` on chapter starts, branching events, and post-battle dialogues.

---

### Acknowledgements

Many thanks to the authors and maintainers of these open-source projects:

- KuroTools  
  https://github.com/nnguyen259/KuroTools

- kuro_dlc_tool  
  https://github.com/eArmada8/kuro_dlc_tool

- Ingert  
  https://github.com/Aureole-Suite/Ingert

- SoraVoiceScripts  
  https://github.com/ZhenjianYang/SoraVoiceScripts

---

### Copyright Notice

- The ownership and rights of all game scripts, voices, images, and related assets processed by this project belong to the original game companies and rights holders.
- The code in this repository is provided in a permissive open-source spirit for learning, research, and non-commercial use.
- Commercial use is strictly prohibited, including but not limited to selling, paid redistribution, or commercial services based on this project, its outputs, or derivatives.
- Users are responsible for ensuring compliance with applicable laws, regulations, and game/platform agreements in their own jurisdictions.
