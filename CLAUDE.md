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
This project uses the code-flow layered spec system.

**Auto-inject rule**: Before answering any coding question, you MUST:
1. Determine domain(s) from the user's question:
   - **frontend**: mentions components, pages, hooks, styles, UI, CSS, React/Vue/Angular, or references .tsx/.jsx/.css/.scss files
   - **backend**: mentions services, API, database, models, logging, or references .py/.go files, SQL, ORM
2. Read `.code-flow/config.yml` → find matching domain's `specs` list
3. Read each spec file from `.code-flow/specs/` and apply as constraints
4. If question spans multiple domains, load all matching specs
5. If no domain matches, skip spec loading

Do NOT ask the user which specs to load — decide automatically based on context.

## Learnings
