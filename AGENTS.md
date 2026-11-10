# Project Guidelines

## Team Identity

- Project: code-flow
- Language: JavaScript, Node.js >= 18, CommonJS core

## Core Principles

- All changes must include meaningful tests.
- Single responsibility per function (<= 50 lines).
- Validate external JSON and command inputs explicitly; no loose coercion.
- Handle errors explicitly; never silently swallow failures.
- Keep runtime dependencies empty; use Node built-ins.
- Hook stdout contains only native protocol JSON; diagnostics go to stderr.

## v1 Architecture

- Design authority: docs/v1-design.md.
- Core runtime lives in bin/ and lib/ in the global package; templates/ holds platform adapters and skills.
- Project config is .code-flow/config.json. Specs use path identity and JSON frontmatter.
- Select a Task by complete task-document path + TASK-NNN, or explicit temporary session binding. Never infer it from a lone in-progress state.
- Read current always/Task/path-selected Spec rules before implementation. Do not freeze hashes or create a Spec Context.
- A requirement has one task document with multiple TASK sections. Task sections hold state and declared tests. Use task finish to run tests before done; archive applies Deltas and moves documents without running tests.
- Numeric Rule IDs come from next_rule. Preserve Applied Deltas records for safe retries.
- Init manages v1 entries only and preserves user-owned content. Historical cleanup is manual, not product code.
- Existing .code-flow/worktrees are historical user workspaces; preserve their paths and contents.

## Development

- Run npm test for the complete Node contract suite.
- Run npm run test:performance for scale measurements.
- Tests use real temporary projects/processes where filesystem, command, packaging or protocol behavior matters.
- Keep full regression/E2E in CI. Task commands should declare meaningful related tests and use framework workers before adding CLI parallelism.

<!-- code-flow:v1 start -->
Use the global code-flow CLI and current project data in `.code-flow/config.json`, `.code-flow/specs/`, `.code-flow/tasks/` and `.code-flow/templates/`.

A requirement has one task document `<requirement>.md` with multiple `## TASK-NNN` sections. Select a Task by task-document path + TASK ID, or by the session token supplied by the prompt Hook; never infer it from status.

Read the current Task's Spec references before implementation. Spec references are paths relative to `.code-flow/specs` without `.md`.

Use `task finish <task-document>.md --task TASK-NNN` to execute declared tests before marking done. Keep tests scoped to meaningful unit/integration regressions; prefer one framework invocation with its own workers.

Archive applies declared Spec Deltas and moves the requirement; CI runs full regression and E2E separately. Use `cf-task:prd`, `cf-task:align` and `cf-task:plan` for document flow; do not create one file per Task.

Hook diagnostics never prohibit work. Missing bindings require an explicit task document + TASK ID or another task start.
<!-- code-flow:v1 end -->
