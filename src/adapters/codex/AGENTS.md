# Project Guidelines

## Team Identity
- Team: [team name]
- Project: [project name]
- Language: [primary language]

## Core Principles
- All changes must include tests
- Single responsibility per function (<= 50 lines)
- No loose typing or silent exception handling
- Handle errors explicitly

## Forbidden Patterns
- Hard-coded secrets or credentials
- Unparameterized SQL
- Network calls inside tight loops

## Spec Loading
This project uses the code-flow two-tier spec system.

**Two-tier architecture**:
- **Tier 0 `_map.md` (Navigation Map)**: Project structure, key files, data flow. Read manually when you need to understand where code lives.
- **Tier 1 Constraint Specs**: Coding rules, patterns, anti-patterns. Auto-injected by the UserPromptSubmit Hook based on files referenced in your prompt.

**Your responsibility**:
1. Determine domain from the question:
   - **frontend**: components, pages, hooks, styles, UI, .tsx/.jsx/.css
   - **backend**: services, API, database, models, logging, .py/.go
2. Read `.code-flow/specs/<domain>/_map.md` for navigation context when needed
3. Constraint specs are auto-injected by Hook when your prompt references relevant files — do NOT manually load them
4. If question spans multiple domains, read all matching `_map.md` files
5. If no domain matches, skip spec loading

Do NOT ask the user which specs to load — the system handles constraint injection automatically.

## Task Documents (cf-task workflow)

- `.code-flow/specs/shared/` holds PRD/design templates used by `cf-task-prd` and `cf-task-align`
- Workflow: `cf-task-prd` → `.prd.md` → `cf-task-align <.prd.md>` → `.design.md` → `cf-task-plan <.design.md>` → tasks
- Templates are read by the skills themselves; you do not need to pre-load them
