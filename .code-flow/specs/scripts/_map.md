# Python Scripts Retrieval Map

> code-flow 核心 Python 脚本导航地图。

## Purpose

Python 脚本层，负责 spec 注入、token 审计、统计等运行时功能。通过 Claude Code 和 Codex CLI 的 Hook 机制触发。

## Architecture

- Runtime: Python 3.9+
- 依赖: pyyaml（用于解析 config.yml）
- 入口: Claude Code Hooks（PreToolUse / SessionStart）+ Codex Hooks（UserPromptSubmit / SessionStart）

## Key Files

| File | Purpose |
|------|---------|
| `src/core/code-flow/scripts/cf_core.py` | 核心工具库：配置加载、标签提取、spec 匹配、分层选择 |
| `src/core/code-flow/scripts/cf_inject_hook.py` | PreToolUse Hook（Claude）：编辑代码时自动注入匹配的 specs |
| `src/core/code-flow/scripts/cf_codex_user_prompt_hook.py` | UserPromptSubmit Hook（Codex）：prompt 提交时注入匹配的 specs |
| `src/core/code-flow/scripts/cf_session_hook.py` | SessionStart Hook（两者共用）：重置注入状态 |
| `src/core/code-flow/scripts/cf_scan.py` | Token 审计脚本：检测超长/冗余 spec 文件 |
| `src/core/code-flow/scripts/cf_stats.py` | 统计脚本：报告 L0/L1 token 使用率 |

## Module Map

```
cf_core.py (核心库，被所有 Hook 脚本导入)
├── load_config()              # YAML 配置加载（带 mtime 缓存）
├── extract_context_tags()     # 文件路径 → 上下文标签（安全去复数 + 语义映射）
├── match_domains()            # 文件路径 → 匹配的域列表
├── match_specs_by_tags()      # 标签交集匹配 specs
├── read_matched_specs()       # 按需读取匹配的 spec 文件
├── select_specs_tiered()      # Tier 0 + Tier 1 分层预算选择
├── assemble_context()         # 格式化输出（Navigation / Constraints 分段）
├── load_inject_state()        # 读取注入状态（JSON）
└── save_inject_state()        # 保存注入状态（含 session_id）

cf_inject_hook.py (Claude PreToolUse Hook)
└── main()    # stdin: {tool_name, tool_input.file_path}
              # 从文件路径提取标签 → 匹配 specs → stdout JSON

cf_codex_user_prompt_hook.py (Codex UserPromptSubmit Hook)
├── _session_id()              # 从 stdin JSON 读取 session_id，fallback pid
├── extract_paths_from_prompt()# 从 prompt 文本提取文件引用（@前缀/反引号/裸路径）
└── main()    # stdin: {session_id, prompt}
              # 从 prompt 提取路径 → 映射域 → 匹配 specs → stdout JSON

cf_session_hook.py (SessionStart Hook，两者共用)
└── main()    # 写入新 session_id，清空已注入列表
```

## Data Flow

### Claude（PreToolUse）
```
Edit/Write 触发 → cf_inject_hook.py(stdin: file_path)
  → load_config() (cached)
  → match_domains(file_path)
  → extract_context_tags(file_path)
  → match_specs_by_tags(tags) → fallback if no tier1 match
  → select_specs_tiered(budget)
  → assemble_context()
  → stdout: {hookSpecificOutput: {hookEventName, additionalContext}}
```

### Codex（UserPromptSubmit）
```
prompt 提交 → cf_codex_user_prompt_hook.py(stdin: {session_id, prompt})
  → extract_paths_from_prompt(prompt)
  → fallback to all domains if no paths found
  → match_domains(paths) → extract_context_tags()
  → match_specs_by_tags(tags)
  → select_specs_tiered(budget)
  → assemble_context()
  → stdout: {hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext}}
```

## Navigation Guide

- 修改标签提取逻辑 → `cf_core.py` 的 `extract_context_tags()` + `_SAFE_DEPLURALS` + `_DIR_SEMANTIC_TAGS`
- 修改 spec 匹配规则 → `cf_core.py` 的 `match_specs_by_tags()`
- 修改预算控制 → `cf_core.py` 的 `select_specs_tiered()`
- 修改 Claude 注入流程 → `cf_inject_hook.py` 的 `main()`
- 修改 Codex 注入流程 → `cf_codex_user_prompt_hook.py` 的 `main()`
- 修改 prompt 路径提取 → `cf_codex_user_prompt_hook.py` 的 `extract_paths_from_prompt()`
- 新增审计检查项 → `cf_scan.py`
- 新增统计维度 → `cf_stats.py`
