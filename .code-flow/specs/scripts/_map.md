# Python Scripts Retrieval Map

> code-flow 核心 Python 脚本导航地图。

## Purpose

Python 脚本层，负责 spec 注入、token 审计、统计等运行时功能。通过 Claude Code Hook 机制触发。

## Architecture

- Runtime: Python 3.x
- 依赖: pyyaml（用于解析 config.yml）
- 入口: Claude Code Hooks（PreToolUse / SessionStart）

## Key Files

| File | Purpose |
|------|---------|
| `src/core/code-flow/scripts/cf_core.py` | 核心工具库：配置加载、标签提取、spec 匹配、分层选择 |
| `src/core/code-flow/scripts/cf_inject_hook.py` | PreToolUse Hook：编辑代码时自动注入匹配的 specs |
| `src/core/code-flow/scripts/cf_session_hook.py` | SessionStart Hook：重置注入状态 |
| `src/core/code-flow/scripts/cf_scan.py` | Token 审计脚本：检测超长/冗余 spec 文件 |
| `src/core/code-flow/scripts/cf_stats.py` | 统计脚本：报告 L0/L1 token 使用率 |

## Module Map

```
cf_core.py (核心库)
├── load_config()              # YAML 配置加载（带 mtime 缓存）
├── extract_context_tags()     # 文件路径 → 上下文标签（安全去复数 + 语义映射）
├── match_specs_by_tags()      # 标签交集匹配 specs
├── read_matched_specs()       # 按需读取匹配的 spec 文件
├── select_specs_tiered()      # Tier 0 + Tier 1 分层预算选择
├── assemble_context()         # 格式化输出（Navigation / Constraints 分段）
├── load_inject_state()        # 读取注入状态（JSON）
└── save_inject_state()        # 保存注入状态（含 session_id）

cf_inject_hook.py (Hook 入口)
└── main()                     # stdin JSON → 域匹配 → 标签匹配 → 分层选择 → stdout JSON

cf_session_hook.py (会话重置)
└── main()                     # 写入新 session_id，清空已注入列表
```

## Data Flow

```
Edit/Write 触发 → cf_inject_hook.py(stdin)
  → load_config() (cached)
  → match_domains(file_path)
  → extract_context_tags(file_path)
  → match_specs_by_tags(tags) → fallback if no tier1 match
  → read_matched_specs() (only matched files)
  → select_specs_tiered(budget, map_max)
  → assemble_context()
  → stdout JSON (hookSpecificOutput)
```

## Navigation Guide

- 修改标签提取逻辑 → `cf_core.py` 的 `extract_context_tags()` + `_SAFE_DEPLURALS` + `_DIR_SEMANTIC_TAGS`
- 修改 spec 匹配规则 → `cf_core.py` 的 `match_specs_by_tags()`
- 修改预算控制 → `cf_core.py` 的 `select_specs_tiered()`
- 修改 Hook 注入流程 → `cf_inject_hook.py` 的 `main()`
- 新增审计检查项 → `cf_scan.py`
- 新增统计维度 → `cf_stats.py`
