# Python Scripts Retrieval Map

> code-flow Python 脚本层导航（Hook 注入 / 审计 / 统计）。

## Purpose

定位脚本职责与入口，快速判断应修改哪个文件。

## Entrypoints

- Claude PreToolUse：`.code-flow/scripts/cf_inject_hook.py`
- Codex UserPromptSubmit：`.code-flow/scripts/cf_codex_user_prompt_hook.py`
- SessionStart（共用）：`.code-flow/scripts/cf_session_hook.py`
- 审计工具：`.code-flow/scripts/cf_scan.py`
- 统计工具：`.code-flow/scripts/cf_stats.py`

## Core Module

- `.code-flow/scripts/cf_core.py`
  - `load_config()`：读取 `.code-flow/config.yml`（含缓存）
  - `extract_context_tags()`：路径提取标签
  - `match_domains()`：路径匹配 domain
  - `match_specs_by_tags()`：按标签匹配 spec
  - `read_matched_specs()`：读取命中的 spec
  - `select_specs_tiered()`：按 Tier0/Tier1 + budget 选取
  - `assemble_context()`：拼装注入上下文
  - `load_inject_state()` / `save_inject_state()`：会话注入状态

## Data Flow

### Claude

`file_path -> match_domains/tags -> match_specs -> select_specs_tiered -> assemble_context -> stdout JSON`

### Codex

`prompt -> extract_paths_from_prompt -> match_domains/tags -> match_specs -> select_specs_tiered -> assemble_context -> stdout JSON`

## Quick Navigation

- 改标签提取：`cf_core.py` `extract_context_tags()`
- 改匹配策略：`cf_core.py` `match_specs_by_tags()`
- 改预算：`cf_core.py` `select_specs_tiered()`
- 改 Claude 注入：`cf_inject_hook.py` `main()`
- 改 Codex 注入：`cf_codex_user_prompt_hook.py` `extract_paths_from_prompt()` / `main()`
- 改审计输出：`cf_scan.py`
- 改统计输出：`cf_stats.py`
