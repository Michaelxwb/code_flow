# Python Scripts Retrieval Map

> code-flow Python 脚本层导航。定位脚本职责与入口，快速判断应改哪个文件。

## Entrypoints

- PreToolUse（Claude/Costrict）：`cf_inject_hook.py`
- UserPromptSubmit（三端通用）：`cf_user_prompt_hook.py`
- SessionStart：`cf_session_hook.py`
- 审计：`cf_scan.py`；统计：`cf_stats.py`

## Core Module: `cf_core.py`

- `load_config()` / `load_inject_state()` / `save_inject_state()`
- `extract_context_tags(path)`：路径 → tag
- `extract_prompt_tags(text)`：中英文关键词 → canonical tag（见 `_TAG_ALIASES`）
- `match_domains(path)` / `match_specs_by_tags(specs, ctx_tags, prompt_tags=None)`
- `read_matched_specs(..., compress=True)` / `select_specs_tiered()` / `assemble_context()`：约束声明在输出顶部（强制）
- `compress_content(text)` / `resolve_compress(inject_cfg)`：注入时无损压缩（行尾空白、多空行、HTML 注释、重复 bullet），幂等、异常回退原文
- `resolve_session_id(hook_data)`：hook session_id 优先，回退 PID（PreToolUse / UserPromptSubmit 共享 inject-state）
- `debug_log(msg)`：仅 `CF_DEBUG=1` 写 `.code-flow/.debug.log`

## Data Flow

- PreToolUse：`file_path → ctx_tags → match_specs_by_tags → select → JSON`
- UserPromptSubmit：`prompt → paths+ctx_tags + prompt_tags → match → select → JSON`

## Quick Navigation

- 改 tag 提取 / 别名：`cf_core.py::extract_context_tags|extract_prompt_tags|_TAG_ALIASES`
- 改匹配 / 预算：`cf_core.py::match_specs_by_tags|select_specs_tiered`
- 改压缩：`cf_core.py::compress_content`；cf-stats 聚合 `compression_summary`
- 改 PreToolUse 注入：`cf_inject_hook.py::main`
- 改 UserPromptSubmit 注入：`cf_user_prompt_hook.py::main|extract_paths_from_prompt`
- 调试：`CF_DEBUG=1` → `.code-flow/.debug.log`（建议加入 `.gitignore`）
