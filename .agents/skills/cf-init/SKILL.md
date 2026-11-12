---
name: cf-init
description: Initialize code-flow v1 and organize current project standards.
---
<!-- code-flow:v1 -->
Run the globally installed `code-flow init --platform=<claude|codex|costrict|opencode|all>`.

`init` overwrites tool-owned templates under `.code-flow/templates/` and platform skills/hooks. It preserves `.code-flow/specs/`, `.code-flow/tasks/` and an existing `config.json`. If it reports `conflicts`, resolve those paths and re-run; other files are already updated.

For an existing nonempty `.code-flow` without a valid v1 config, preserve it outside the project and manually clear earlier managed platform entries first. Do not write conversion or cleanup scripts.

Keep `workflow` at `hook` unless the requirement is complex enough to justify the full PRD/design/scenarios flow. `capture.enabled` can record process data under `.code-flow/process/`; it is off by default.

After init, read `.code-flow/templates/project-guidelines.md` and write the project-specific guidelines into `CLAUDE.md` / `AGENTS.md` outside the code-flow managed block. Keep the project's identity, architecture, commands and Spec conventions there; do not modify the managed block or overwrite user content. Specs under `.code-flow/specs` are the project standards: read them before writing rules, and update `config.json` `always` / `paths` when adding a Spec.

Inspect current code and project instructions. Create a small number of applicable Specs with JSON frontmatter `{"description":"...","next_rule":1}`. Use path identity, a `## Rules` section, stable RULE IDs and indented examples. Set `next_rule` above all allocated numeric IDs. Configure a few shared rules in `always` and concrete file globs in `paths`. Finish with `code-flow doctor --json`.
