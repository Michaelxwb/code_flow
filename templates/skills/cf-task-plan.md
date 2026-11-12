---
name: cf-task-plan
description: Split a requirement into one multi-TASK document.
---
<!-- code-flow:v1 -->
Read `.code-flow/config.json` `workflow` first:

- `hook` (default): write one task document with TASK sections and declared tests; do not require or read PRD/design/scenarios; leave Source/Scenarios empty.
- `full`: read the requirement's design files and scenarios first; fill Source/Scenarios.

Read `.code-flow/templates/task.md`. Write exactly one task document:

```text
.code-flow/tasks/<date>/<requirement>/<requirement>.md
```

Start with JSON frontmatter naming the requirement:

```markdown
---
{"version":1,"requirement":"<requirement>"}
---
```

Inside it create `## TASK-NNN` sections. Keep each Task small enough to demonstrate a capability. For every Task declare:

- Status, Depends, Source, Scenarios, Spec-Refs, Paths;
- a `### Tests` JSON array of fast unit/integration commands;
- a `### Spec Delta` JSON array (empty is valid).

Do not create one file per Task. Do not create an acceptance manifest. Do not run old scenario/quality/Stage Gate commands. Verify the result with `code-flow task status --json`, then use `cf-task:start`.
