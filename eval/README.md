# code-flow eval (thin)

A small, explicitly non-CI harness for comparing three ways of giving a coding agent the same task:

- **full**: the code-flow v1 workflow (requirement documents, one multi-TASK document, declared tests, `task start` / `task finish`);
- **hook**: `init` + spec injection + a minimal task document with `task start` / `task finish`, but no PRD/design/scenarios;
- **minimal**: the task brief only, no code-flow.

It is a decision aid, not a benchmark. A single run per cell is noisy; use `--runs 3` for signal.

## What it measures

| Metric | Source |
|---|---|
| `verify` | hidden acceptance test copied after the agent finishes |
| duration | wall clock of the agent command |
| cost / turns / tokens | best-effort parse of the agent's JSON output |
| CLI calls / finish calls / injected bytes | wrapper log for the full path |
| task done / requirement docs | `code-flow task status` and `.code-flow/tasks` for the full path |

The hidden tests are outside the fixture workspace, so the agent cannot read or edit them.

## Dry run (no model, no cost)

```bash
node eval/run.js --dry-run --all
```

This runs all three fixtures on both paths with `eval/fake-agent.js`, which applies a known solution and, for `full`, creates the documents and runs `task start` / `task finish`. It validates the harness; it says nothing about model quality.

## Real run

The harness passes the prompt file and workspace through `EVAL_PROMPT_FILE` and `EVAL_WORKSPACE`. `cwd` is the workspace.

Claude Code (safer allowlist):

```bash
AGENT_CMD='claude -p "$(cat "$EVAL_PROMPT_FILE")" --output-format json \
  --allowedTools "Read Edit Write Glob Grep Bash(node --test *) Bash(code-flow *) Bash(npm test*) Bash(mkdir *)"' \
  node eval/run.js --all --runs 1
```

Or, only inside a disposable sandbox, bypass permissions:

```bash
AGENT_CMD='claude -p "$(cat "$EVAL_PROMPT_FILE")" --output-format json --dangerously-skip-permissions' \
  node eval/run.js --all --runs 1
```

Codex:

```bash
AGENT_CMD='codex exec --json --skip-git-repo-check -s workspace-write -C "$EVAL_WORKSPACE" "$(cat "$EVAL_PROMPT_FILE")"' \
  node eval/run.js --all --runs 1
```

Workspaces, prompt files, CLI logs and the installed code-flow package live under the OS temp dir; the repository path is not exposed in the agent environment or PATH. The harness is not a security sandbox: a determined agent could still guess paths. Use a container or VM for untrusted models.

Use `--fixture <name>`, `--path full|minimal`, `--runs <n>`, `--timeout <seconds>`, `--keep`, and `--out <dir>` as needed.

**Safety**: the agent command runs with your user permissions inside a temporary copy of the fixture. `--dangerously-skip-permissions` is only reasonable in a disposable sandbox; the harness does not add it for you. Workspaces are deleted unless `--keep` is set.

## Fixtures

| Fixture | Requirement | Hidden test focus |
|---|---|---|
| `unique-words` | add `uniqueWords(text)` | case-insensitive dedupe, first spelling, empty input |
| `csv-line` | parse one CSV record | quoted commas, `""` escapes, empty fields |
| `rate-limit` | replace fixed window with sliding window | boundary at `(now - windowMs, now]`, per-key isolation |
| `event-bus` | add `once`, error isolation and dispatch snapshots | ordering, removal/adding during emit, `AggregateError` |
| `pagination` | cursor pagination with stable id order | limit clamping, invalid cursor, additions between pages |

## Results

Each run writes `eval/results/<stamp>/<fixture>-<path>-r<run>.json`. Full/hook runs also produce `capture/` through `code-flow process collect` (events, task status, doctor, spec list, specs/tasks snapshots, hashes, git). The same directory has:

- `prompt.md` — the exact prompt;
- `agent.stdout` / `agent.stderr` — the raw agent output;
- `cli.jsonl` — full-path CLI calls and stdout byte counts (for injection accounting);
- `summary.md` / `summary.json` — the cross-run table.

`eval/results/` and `eval/work/` are gitignored. The package's `files` list does not include `eval/`, so the harness never ships in the npm package or runs in `npm test`.
