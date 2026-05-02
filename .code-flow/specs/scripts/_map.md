# Python Scripts Retrieval Map

> code-flow Python 脚本层导航。定位脚本职责与入口，快速判断应改哪个文件。

## Entrypoints

- PreToolUse（Claude/Costrict）：`cf_inject_hook.py`
- UserPromptSubmit（Claude/Codex/Costrict/OpenCode）：`cf_user_prompt_hook.py`
  - OpenCode 经 `.opencode/plugins/code-flow/index.js` 在 `chat.message` 转发，`experimental.chat.system.transform` 注入
- SessionStart：`cf_session_hook.py`；审计：`cf_scan.py`；统计：`cf_stats.py`
- Hook stdout 必须 `json.dumps(payload, ensure_ascii=False)`，否则中文 spec 被 escape 吃掉 token 预算

## Core Module: `cf_core.py`

- `load_config()` / `load_inject_state()` / `save_inject_state()`
- `extract_context_tags(path)`：路径 → tag；`extract_prompt_tags(text)`：关键词 → canonical（见 `_TAG_ALIASES`）
- `match_domains(path)` / `match_specs_by_tags(specs, ctx_tags, prompt_tags=None)`
- `read_matched_specs(..., compress=True)` / `select_specs_tiered()` / `assemble_context()`：约束声明在输出顶部
- `compress_content(text)` / `resolve_compress(inject_cfg)`：注入时无损压缩（注释/空白/重复 bullet），幂等、异常回退
- `resolve_session_id(hook_data)`：hook id 优先、回退 PID（PreToolUse 与 UserPromptSubmit 共享 inject-state）
- `debug_log(msg)`：仅 `CF_DEBUG=1` 写 `.code-flow/.debug.log`

## Quick Navigation

- 改 tag / 别名：`cf_core.py::extract_context_tags|extract_prompt_tags|_TAG_ALIASES`
- 改匹配 / 预算：`cf_core.py::match_specs_by_tags|select_specs_tiered`
- 改压缩：`cf_core.py::compress_content`；cf-stats 聚合 `compression_summary`
- 改注入：`cf_inject_hook.py::main` / `cf_user_prompt_hook.py::main|extract_paths_from_prompt`
- 调试：`CF_DEBUG=1` → `.code-flow/.debug.log`（建议加入 `.gitignore`）
