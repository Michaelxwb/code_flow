---
name: cf-task-start
description: Start one TASK or the next dependency batch.
---
<!-- code-flow:v1 -->
Use `code-flow task status --json` to locate the task document and IDs. Never infer a Task from its status.

Single Task:

```bash
code-flow task start <task-document>.md --task TASK-001 --session <token>
```

Batch (dependency layer):
- read `Depends` and choose the next ready layer;
- create worktrees through the internal `task parallel prepare` flow with `--workers <n>` when needed;
- read `workers` and each worker `env` from the run ledger; dispatch no more than `workers` at once (default 2), one worker per Task;
- each worker runs start → implement → tests → finish using its ledger `CF_*` environment.

After tests pass in a worker, run:

```bash
code-flow task finish <task-document>.md --task TASK-001 --json
```

`finish` is the only test entry; do not call `task verify`. E2E and full regression stay in CI. If no session token is available, omit `--session` and use the printed brief; never invent a token. Do not run `task archive` inside a worker; archive only in the coordinator worktree after merge.
