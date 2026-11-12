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

Before `finish`, update the TASK Checklist to reflect only work that is actually complete. A successful `finish` checks any remaining `- [ ]` items in that TASK section; do not mark work you did not do.

Batch (dependency layer):

0. The coordinator worktree must be clean before `prepare`; commit or stash user changes. `init_user_content` means a managed/shared file has uncommitted user content — commit or remove it and retry.

1. Read `Depends`, choose the next ready layer, and create worktrees:

```bash
code-flow task parallel prepare --task-file <task-document>.md --tasks TASK-001,TASK-002 --run-id <id> --workers 2
```

2. Read `workers` and each worker `env` from the run ledger. Dispatch no more than `workers` workers at once (default 2), one worker per Task. Give each worker its ledger `CF_*` environment. Workers use the global CLI; prepare does not install tool files into them. Add `--init` only when a host session must run inside a worker.

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

Keep the run ledger after each batch for audit; `cf-task:archive` clears completed run ledgers for the requirement. Use `--purge` only for manual early cleanup. Always inspect `task parallel status --run-id <id>` before cleanup.

If merge or integration fails, stop and keep the worktrees, branches and ledger for inspection. Do not run `task archive` inside a worker; archive only in the coordinator worktree after the run is complete. After every TASK is done, use `cf-task:archive` in the coordinator worktree. E2E and full regression stay in CI.
