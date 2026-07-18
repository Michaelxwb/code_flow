# Spec Workflow 0.6.0 Migration

0.6.0 replaces prompt-keyword/full injection with one Context-first runtime. It is a breaking, transactional migration; `code-flow init` will not overwrite a 0.4.2–0.5.x project before migration.

## Upgrade

```bash
code-flow migrate --spec-workflow --dry-run
code-flow migrate --spec-workflow --prepare
cf-spec migrate --plan .code-flow/migrations/<id>/migration-plan.json  # only when unresolved exists
code-flow migrate --spec-workflow --apply --plan .code-flow/migrations/<id>/migration-plan.json
code-flow init --platform=<claude|codex|costrict|opencode>
```

`--dry-run` performs no project writes. `--prepare` creates `.code-flow/migrations/<id>/backup/`, empty staging, a source-hash-bound plan, and `journal.json`. Apply refuses unresolved decisions or source hash drift. `.code-flow/.version` is written as `0.6.0` only after every target hash is committed.

## Backup and rollback

The backup stores the exact bytes present at prepare time, including dirty working-tree and user-managed files. Keep it until the migrated project has passed its normal tests.

```bash
code-flow migrate --spec-workflow --rollback <id>
```

Rename/EXDEV failures automatically roll back. If interruption leaves `committing`, rerunning apply finishes only when every target hash is proven; otherwise it restores the backup. `recovery_required` must be resolved before Hooks or task commands continue.

## Unsupported older projects

Projects older than 0.4.2 must first bridge through the previous release:

```bash
npx @michaelxwb/code-flow@0.5.2 init --platform=<platform>
```

Then run the 0.6.0 migration. Do not delete `.inject-state`, old commands, or task files manually before prepare—the transaction needs the original bytes for recovery and residue validation.

## Runtime changes

- Active tasks inject only their persisted `spec-context.yml` TASK projection.
- Without an active task, explicit paths use `path_mapping`; only pathless exploration receives Catalog.
- `cf-inject`, full/tag fallback, `.inject-state`, and SessionStart reset are removed.
- `cf-spec context/refresh/doctor` is available on Claude, Codex, Costrict, and OpenCode.
