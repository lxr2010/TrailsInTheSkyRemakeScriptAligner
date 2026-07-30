# KuroTools 未定义 Command 的 fallback 修复

某些脚本包含未收录命令时，KuroTools 可能在命令名映射阶段报错。建议加入 fallback：

- `KuroTools/disasm/ED9InstructionsSet.py:1735`
  - 对 `commands_dict` 查找增加兜底，未知命令统一回退为：
  - `Cmd_unknown_{structID:02X}_{opCode:02X}`

- `KuroTools/disasm/ED9Assembler.py:890`
  - 对 `reverse_commands_dict` 查找增加兜底；
  - 能解析 `Cmd_unknown_XX_YY` 时直接反算回 `(XX, YY)`；
  - 否则 fallback 到 `(0xFF, 0xFF)` 并输出警告。
