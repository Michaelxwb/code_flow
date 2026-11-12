---
name: cf-task-archive
description: Archive a completed requirement after applying Spec Deltas.
---
<!-- code-flow:v1 -->
Read `code-flow task status <requirement-dir> --json`. Every TASK in the one requirement task document must be `done`. If a TASK's Spec Delta needs review or correction first, use `cf-spec` (`code-flow spec learn --dry-run`).

Preview and apply:

```bash
code-flow task archive <requirement-dir> --dry-run --json
code-flow task archive <requirement-dir> --json
```

Archive:
- applies each TASK's Spec Delta in the coordinator worktree;
- clears completed code-flow run ledgers for this requirement;
- moves the whole requirement directory;
- does not run tests, E2E, or scenarios.

Per-batch `task parallel cleanup` removes worker worktrees but keeps the run ledger for audit; archive clears those ledgers. If archive reports `worktree_not_cleaned`, run cleanup first. Do not run archive inside a worktree. Use the returned `archived_to` path. If Delta application fails, fix the Delta or explicitly use `--no-learn`; do not hand-edit the archive destination.
