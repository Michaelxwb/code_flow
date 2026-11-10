---
name: cf-spec
description: Inspect current code-flow v1 Specs and apply reviewed Task Spec Deltas.
---
<!-- code-flow:v1 -->
Use `code-flow spec list --json`, `code-flow spec inject --task-file <task-document>.md --task TASK-001 --json`, or `code-flow spec inject --path <file> --full`.

Spec identity is its path relative to `.code-flow/specs` without `.md`. Frontmatter is JSON with `description` and a positive `next_rule`. Rules use stable RULE IDs and complete indented explanations/examples.

Review applicability and semantic conflicts against current code before writing a Spec Delta. Prefer stable shared constraints over task-specific narration.

Delta operations are add/update/remove. Every item needs a stable ID, target Spec path and evidence; update/remove require the existing Rule ref and exact before text. New numeric IDs come from `next_rule`, never from the largest remaining Rule.

Use:

```bash
code-flow spec learn --from-task <task-document>.md --task TASK-001 --dry-run --json
```

Review the exact diff, then run without `--dry-run`. Repeating an already applied payload is safe; changed content requires a new Delta ID. A missing target or before mismatch is an error. Preserve Applied Deltas records so interrupted multi-file learning can resume.
