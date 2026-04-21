# Project Guidelines

## Team Identity
- Project: code-flow
- Language: JavaScript (CLI) + Python (core scripts)

## Core Principles
- All changes must include tests
- Single responsibility per function (<= 50 lines)
- No loose typing or silent exception handling
- Handle errors explicitly

## Forbidden Patterns
- Hard-coded secrets or credentials
- Hook 脚本 stdout 输出非 JSON（破坏 Claude Code 协议）
- CLI 引入 npm 外部依赖

## Compression & Budget
- Token 估算公式：`len(text) // 4`（cf_core.py:38-39）
- `compress_content()` 5 个无损变换：去除 HTML 注释、尾空白、3+ 空行合并、去重 bullet、首尾空行；幂等，异常回退原文（cf_core.py:403-437）
- `resolve_compress()` 仅 literal `False` 禁用；`None`/缺失/其他值均启用（cf_core.py:637-649）

## Spec Loading
This project uses the code-flow two-tier spec system.

**Two-tier architecture**:
- **Tier 0 `_map.md`（导航地图）**：项目结构、关键文件、数据流。你手动读取，帮助理解代码在哪里。
- **Tier 1 约束规范**：编码规则、模式、反模式。由 Hook 根据文件路径标签自动注入，你无需手动加载。

**Your responsibility**:
1. Determine domain from the question:
   - **cli**: mentions CLI, init, upgrade, merge, version, or references src/cli.js
   - **scripts**: mentions hook, inject, config, spec, tag, scan, stats, or references .py files
2. Read `.code-flow/specs/<domain>/_map.md` for navigation context
3. Constraint specs are auto-injected by PreToolUse Hook when you edit code — do NOT manually read them
4. If question spans multiple domains, read all matching `_map.md` files
5. If no domain matches, skip spec loading

Do NOT ask the user which specs to load — the system handles constraint injection automatically.

## Task Documents (cf-task workflow)

- `.code-flow/specs/shared/` holds PRD/design templates used by `/cf-task:prd` and `/cf-task:align`
- Workflow: `/cf-task:prd` → `.prd.md` → `/cf-task:align <.prd.md>` → `.design.md` → `/cf-task:plan <.design.md>` → tasks
- Templates are read by the commands themselves; you do not need to pre-load them
