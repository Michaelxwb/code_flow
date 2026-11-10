---
name: cf-task-prd
description: Produce a concise PRD for one requirement.
---
<!-- code-flow:v1 -->
Read `.code-flow/templates/prd.md`. Ask only questions that block scope, users, or acceptance. Write one requirement PRD to `.code-flow/tasks/<date>/<requirement>/<requirement>.prd.md`.

Keep it short:
- problem, goal, users, user stories;
- functional requirements and boundaries;
- non-functional constraints only when real;
- risks and open questions.

Do not create Task files here. Do not run old manifest, scenario, design-lint, Stage Gate, or E2E gates. When the PRD is accepted, continue with `cf-task:align`.
