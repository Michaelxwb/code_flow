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
- 只改双副本结构的一侧：`src/core/code-flow/` ↔ `.code-flow/`、`src/adapters/<p>/` ↔ `.<platform>/` 必须同步提交（模板源与部署副本分裂 = 测试过但 live 行为不变）

## Compression & Budget
- Token 估算公式：`len(text) // 4`（cf_core.py:38-39）
- `compress_content()` 5 个无损变换：去除 HTML 注释、尾空白、3+ 空行合并、去重 bullet、首尾空行；幂等，异常回退原文（cf_core.py:403-437）
- `resolve_compress()` 仅 literal `False` 禁用；`None`/缺失/其他值均启用（cf_core.py:637-649）

## Spec Loading
This project uses the code-flow two-tier spec system.

**Two-tier architecture**:
- **Tier 0 `_map.md`（导航地图）**：项目结构、关键文件、数据流。你手动读取，帮助理解代码在哪里。
- **Tier 1 约束规范**：编码规则、模式、反模式。编辑代码时（PreToolUse）自动注入；prompt 无明确路径时注入 **Spec Catalog**，由你按场景自行读取（`inject.mode: catalog`，`cf_core.py::build_spec_catalog`）。

**Your responsibility**:
1. Determine domain from the question:
   - **cli**: mentions CLI, init, upgrade, merge, version, or references src/cli.js
   - **scripts**: mentions hook, inject, config, spec, tag, scan, stats, or references .py files
2. Read `.code-flow/specs/<domain>/_map.md` for navigation context
3. Constraint specs are auto-injected by PreToolUse Hook when you edit code. On prompts without explicit file paths you receive a **Spec Catalog** instead — Read the matching spec(s) listed there before coding
4. If question spans multiple domains, read all matching `_map.md` files
5. If no domain matches, skip spec loading

Do NOT ask the user which specs to load — the system handles constraint injection automatically.

## 合规反馈协议（quality_loop）

1. 编辑代码后收到 **Spec 合规反馈 (auto-check)** 时，先按提示修正违规，再继续当前任务
2. 用户表示某条反馈是误报时，代为执行 `python3 .code-flow/scripts/cf_feedback.py ignore <check-id>`（check-id 见反馈中的 `规则: <spec>#<check-id>`）
3. 会话收尾被 cf-stop 校验拦回时，修复未过项后再结束
4. 新增/修改规范优先用 ✅/❌ 代码对照示例表达

## Task Documents (cf-task workflow)

- `.code-flow/specs/shared/` holds PRD/design templates used by `/cf-task:prd` and `/cf-task:align`
- Workflow: `/cf-task:prd` → `.prd.md` → `/cf-task:align <.prd.md>` → `.design.md` → `/cf-task:plan <.design.md>` → tasks
- Templates are read by the commands themselves; you do not need to pre-load them
