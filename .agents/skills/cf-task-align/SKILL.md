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
- scenarios use S-/E-/B- IDs, level, boundary and expected result;
- scenarios are a manual tester reference, not a manifest or blocking gate;
- do not run or copy old manifest/design-lint/Stage Gate/E2E commands from templates.

When design and scenarios are ready, continue with `cf-task:plan`.
