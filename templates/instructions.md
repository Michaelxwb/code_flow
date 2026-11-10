Use the global code-flow CLI and current project data in `.code-flow/config.json`, `.code-flow/specs/`, `.code-flow/tasks/` and `.code-flow/templates/`.

A requirement has one task document `<requirement>.md` with multiple `## TASK-NNN` sections. Select a Task by task-document path + TASK ID, or by the session token supplied by the prompt Hook; never infer it from status.

Read the current Task's Spec references before implementation. Spec references are paths relative to `.code-flow/specs` without `.md`.

Use `task finish <task-document>.md --task TASK-NNN` to execute declared tests before marking done. Keep tests scoped to meaningful unit/integration regressions; prefer one framework invocation with its own workers.

Archive applies declared Spec Deltas and moves the requirement; CI runs full regression and E2E separately. Use `cf-task:prd`, `cf-task:align` and `cf-task:plan` for document flow; do not create one file per Task.

Hook diagnostics never prohibit work. Missing bindings require an explicit task document + TASK ID or another task start.
