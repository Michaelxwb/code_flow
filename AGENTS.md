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

## Spec Loading
This project uses the code-flow two-tier spec system.

**Two-tier architecture**:
- **Tier 0 `_map.md` (Navigation Map)**: Project structure, key files, data flow. Read manually when you need to understand where code lives.
- **Tier 1 Constraint Specs**: Coding rules, patterns, anti-patterns. Auto-injected by the UserPromptSubmit Hook based on files referenced in your prompt.

**Your responsibility**:
1. Determine domain from the question:
   - **cli**: mentions CLI, init, upgrade, merge, version, or references `src/cli.js`
   - **scripts**: mentions hook, inject, config, spec, tag, scan, stats, or references `.py` files
2. Read `.code-flow/specs/<domain>/_map.md` for navigation context when needed
3. Constraint specs are auto-injected by Hook when your prompt references relevant files — do NOT manually load them
4. If question spans multiple domains, read all matching `_map.md` files
5. If no domain matches, skip spec loading

Do NOT ask the user which specs to load — the system handles constraint injection automatically.
