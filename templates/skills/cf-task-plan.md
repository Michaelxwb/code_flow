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

`### Spec Delta` schema (copy the shape from `.code-flow/templates/task.md`):

```json
[
  { "id": "DELTA-001", "op": "add", "target": "cli/runtime", "rule": "完整规则", "evidence": "依据" },
  { "id": "DELTA-002", "op": "update", "target": "cli/runtime", "ref": "RULE-001", "before": "当前规则全文", "rule": "新规则", "evidence": "依据" },
  { "id": "DELTA-003", "op": "remove", "target": "cli/runtime", "ref": "RULE-002", "before": "当前规则全文", "evidence": "依据" }
]
```

- `target` is the Spec path relative to `.code-flow/specs`;
- add needs `rule` + `evidence`; update/remove also need `ref` + exact `before`;
- IDs are unique inside the TASK; applied payloads are immutable.

Do not create one file per Task. Do not create an acceptance manifest. Do not run old scenario/quality/Stage Gate commands. Verify the result with `code-flow task status --json`.

Stop after writing the task document. Ask the user to review TASK boundaries, Spec-Refs, Scenarios and declared tests; do not implement or run `cf-task:start` until the user explicitly confirms.
