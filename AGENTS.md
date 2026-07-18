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
- Hook 脚本 stdout 输出非 JSON（破坏 Claude Code / Codex 协议）
- CLI 引入 npm 外部依赖

<!-- code-flow:spec-loading schema=1 start -->
## Spec Workflow (schema 1)

- If `.code-flow/.active-task.json` exists, validate it and `spec-context.yml`, then use only the active TASK's `Spec-Refs`, Design refs, and Acceptance Contract. Never reselect Specs from Catalog.
- Without an active TASK, explicit file paths use deterministic `path_mapping` constraints; prompts without paths receive the Spec Catalog for exploration or creation of the next Context.
- PRD, Design, Plan, Start, Coding, and Done inherit one persisted Context. Required rules must be applied and verified before their stage gate passes.
- A corrupt marker, Context hash drift, or required scope expansion is `SPEC_WORKFLOW_BLOCKED`; run `cf-spec refresh/doctor` instead of falling back.
- Tier 0 `_map.md` files are navigation only. Rule constraints live in metadata-bearing Tier 1 Specs.

Do NOT ask the user which Specs to load—the Context-first router is authoritative.
<!-- code-flow:spec-loading schema=1 end -->

## Task Documents (cf-task workflow)

- `.code-flow/specs/shared/` holds PRD/design templates（含前端 `design-frontend.md`）used by `/cf-task:prd` and `/cf-task:align`
- 一个需求的 prd / design / tasks 同放需求目录 `.code-flow/tasks/<日期>/<需求>/`；全栈需求可有 `<需求>.frontend.design.md` + `<需求>.backend.design.md`，`/cf-task:plan <需求目录>` 合并拆解，`/cf-task:archive` 按整个需求目录归档（旧扁平布局仍兼容）
- Workflow: `/cf-task:prd` → `.prd.md` → `/cf-task:align <.prd.md>` → `.design.md`(s) → `/cf-task:plan <需求目录>` → tasks
- Templates are read by the commands themselves; you do not need to pre-load them
