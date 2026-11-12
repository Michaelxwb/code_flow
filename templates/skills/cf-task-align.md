---
name: cf-task-align
description: Produce frontend/backend design and manual acceptance scenarios.
---
<!-- code-flow:v1 -->
Read the requirement PRD or user brief. Read `.code-flow/templates/design-lite.md`, `design-full.md`, or `design-frontend.md` as appropriate. Write:

- `.code-flow/tasks/<date>/<requirement>/<requirement>.frontend.design.md`
- `.code-flow/tasks/<date>/<requirement>/<requirement>.backend.design.md`
- or one `<requirement>.design.md` for a single domain
- `.code-flow/tasks/<date>/<requirement>/<requirement>.scenarios.md`

Design rules:
- full-stack requirements keep frontend and backend design separate;
- scenarios use S-/E-/B- IDs for traceability, but are written for a human tester: goal, preconditions, numbered user steps, observable expected result and owner;
- do not write E2E code, selectors, internal API codes or implementation details unless the user can observe them;
- scenarios are manual acceptance assets, not a manifest or blocking gate;
- do not run or copy old manifest/design-lint/Stage Gate/E2E commands from templates.

Stop after writing design and scenarios. Ask the user to review them; do not start planning or code until the user explicitly confirms. When confirmed, continue with `cf-task:plan`.
