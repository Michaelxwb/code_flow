---
name: cf-check
description: Run read-only code-flow health checks.
---
<!-- code-flow:v1 -->
Run:

```bash
code-flow doctor --json
```

Report:
- hook/launcher entry and template status;
- config and Spec parse errors;
- Task document errors and dependency problems;
- worktree run ledger state;
- the next safe action.

`doctor` is read-only. Do not repair or mutate project files from this skill unless the user explicitly asks.
