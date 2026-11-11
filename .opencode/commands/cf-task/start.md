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

1. Read `Depends`, choose the next ready layer, and create worktrees:

```bash
code-flow task parallel prepare --task-file <task-document>.md --tasks TASK-001,TASK-002 --run-id <id> --workers 2
```

2. Read `workers` and each worker `env` from the run ledger. Dispatch no more than `workers` workers at once (default 2), one worker per Task. Give each worker its ledger `CF_*` environment.

3. In each worker: start → implement → **finish**. `finish` is the only test entry and runs the Task's declared tests; do not run those tests a second time before finish.

```bash
code-flow task start <task-document>.md --task TASK-001 --session <token>
code-flow task finish <task-document>.md --task TASK-001 --json
```

Commit the worker's business changes and its own TASK section after `finish`.

4. From the coordinator, collect, merge/integrate, then cleanup:

```bash
code-flow task parallel collect --run-id <id> --json
code-flow task parallel merge --run-id <id> --json
code-flow task parallel cleanup --run-id <id> --json
```

If merge or integration fails, stop and keep the worktrees, branches and ledger for inspection. Do not run `task archive` inside a worker; archive only in the coordinator worktree after the run is complete. E2E and full regression stay in CI.
