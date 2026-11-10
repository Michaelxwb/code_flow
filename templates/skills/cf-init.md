---
name: cf-init
description: Initialize code-flow v1 and organize current project standards.
---
<!-- code-flow:v1 -->
Run the globally installed `code-flow init --platform=<claude|codex|costrict|opencode|all>`.

`init` overwrites tool-owned templates under `.code-flow/templates/` and platform skills/hooks. It preserves `.code-flow/specs/`, `.code-flow/tasks/` and an existing `config.json`.

For an existing nonempty `.code-flow` without a valid v1 config, preserve it outside the project and manually clear earlier managed platform entries first. Do not write conversion or cleanup scripts.

Inspect current code and project instructions. Create a small number of applicable Specs with JSON frontmatter `{"description":"...","next_rule":1}`. Use path identity, a `## Rules` section, stable RULE IDs and indented examples. Set `next_rule` above all allocated numeric IDs. Configure a few shared rules in `always` and concrete file globs in `paths`. Finish with `code-flow doctor --json`.
