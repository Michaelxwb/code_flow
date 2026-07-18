#!/usr/bin/env python3
"""Read-only migration preflight and staging transformer."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from typing import IO, Mapping, Optional, Sequence

import yaml

from cf_spec_context import BindingInput, bind_specs, new_context, save_context
from cf_spec_metadata import SpecMetadata, SpecMetadataError, load_spec_metadata
from cf_spec_resolver import SCOPE_PRIORITY, SpecCandidate


TARGET_VERSION = "0.6.0"
TARGET_SCHEMA = 1
PACKAGE_ROOT = Path(__file__).resolve().parents[4]
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SUFFIXES = (".frontend.design.md", ".backend.design.md", ".design.md", ".prd.md", ".md")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _issue(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _version_tuple(value: str) -> Optional[tuple[int, int, int]]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value.strip())
    return tuple(int(item) for item in match.groups()) if match else None


def _source_version(flow: Path) -> str:
    path = flow / ".version"
    try:
        return path.read_text(encoding="utf-8").strip() if path.is_file() else "missing"
    except OSError:
        return "unreadable"


def _schema(flow: Path) -> Optional[int]:
    path = flow / "config.yml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    workflow = data.get("spec_workflow") if isinstance(data, dict) else None
    value = workflow.get("schema_version") if isinstance(workflow, dict) else 0
    return value if isinstance(value, int) else None


def _version_issues(version: str, schema: Optional[int]) -> list[dict[str, str]]:
    parsed = _version_tuple(version)
    if version in ("missing", "unreadable"):
        return []
    if parsed is None:
        return [_issue("invalid_version", ".code-flow/.version", version)]
    if parsed < (0, 4, 2):
        return [_issue("unsupported_version", ".code-flow/.version", version)]
    if parsed > (0, 6, 0) or (schema is not None and schema > TARGET_SCHEMA):
        return [_issue("future_version", ".code-flow/.version", version)]
    if parsed == (0, 6, 0) and schema != TARGET_SCHEMA:
        return [_issue("incomplete_target_schema", ".code-flow/config.yml", str(schema))]
    return []


def _scan_specs(root: Path, flow: Path) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    manifest: list[dict[str, object]] = []
    unresolved: list[dict[str, str]] = []
    seen: dict[str, str] = {}
    for path in sorted((flow / "specs").rglob("*.md")):
        relative = _relative(root, path)
        spec_relative = path.relative_to(flow / "specs").as_posix()
        if "/_session/" in f"/{relative}/" or path.name == "_map.md" or spec_relative.startswith("shared/"):
            continue
        try:
            metadata = load_spec_metadata(str(path))
        except SpecMetadataError as exc:
            unresolved.append(_issue("invalid_spec", relative, exc.message))
            continue
        if metadata.id in seen:
            unresolved.append(_issue("duplicate_spec_id", relative, metadata.id))
        seen[metadata.id] = relative
        manifest.append({"id": metadata.id, "path": relative, "sha256": metadata.hashes.file_sha256})
    return manifest, unresolved


def _demand_key(name: str) -> str:
    for suffix in _SUFFIXES:
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def _target_conflict(files: Sequence[Path], target: Path) -> bool:
    if not target.exists():
        return False
    for source in files:
        destination = target / source.name
        if destination.exists() and destination.read_bytes() != source.read_bytes():
            return True
    return False


def _flat_transforms(root: Path, date_dir: Path) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    groups: dict[str, list[Path]] = {}
    for path in sorted(date_dir.glob("*.md")):
        groups.setdefault(_demand_key(path.name), []).append(path)
    transforms: list[dict[str, object]] = []
    unresolved: list[dict[str, str]] = []
    for demand, files in sorted(groups.items()):
        target = date_dir / demand
        if _target_conflict(files, target):
            unresolved.append(_issue("target_conflict", _relative(root, target), demand))
        transforms.append({
            "demand": demand,
            "files": [_relative(root, path) for path in files],
            "target": _relative(root, target),
        })
    return transforms, unresolved


def _scan_tasks(root: Path, flow: Path) -> tuple[list[dict[str, object]], list[dict[str, str]], list[dict[str, object]]]:
    tasks = flow / "tasks"
    transforms: list[dict[str, object]] = []
    unresolved: list[dict[str, str]] = []
    active: list[dict[str, object]] = []
    if not tasks.is_dir():
        return transforms, unresolved, active
    for date_dir in sorted(path for path in tasks.iterdir() if path.is_dir() and _DATE_RE.fullmatch(path.name)):
        found, issues = _flat_transforms(root, date_dir)
        transforms.extend(found)
        unresolved.extend(issues)
        for demand_dir in sorted(path for path in date_dir.iterdir() if path.is_dir()):
            mains = [path for path in demand_dir.glob("*.md") if not path.name.endswith((".prd.md", ".design.md"))]
            if len(mains) > 1:
                unresolved.append(_issue("multiple_task_files", _relative(root, demand_dir), str(len(mains))))
            active.append({"path": _relative(root, demand_dir), "active": True})
    return transforms, unresolved, active


def _archived(root: Path, flow: Path) -> list[dict[str, object]]:
    path = flow / "tasks" / "archived"
    if not path.is_dir():
        return []
    return [
        {"path": _relative(root, item), "sha256": _sha256(item), "active": False}
        for item in sorted(path.rglob("*")) if item.is_file()
    ]


def preflight(root: str) -> dict[str, object]:
    project = Path(root).resolve()
    flow = project / ".code-flow"
    version, schema = _source_version(flow), _schema(flow)
    specs, spec_issues = _scan_specs(project, flow)
    transforms, task_issues, active = _scan_tasks(project, flow)
    unresolved = [*_version_issues(version, schema), *spec_issues, *task_issues]
    warnings = [] if version != "missing" else [_issue("version_mismatch", ".code-flow/.version", "missing")]
    return {
        "project_root": str(project),
        "source_package_version": version,
        "source_schema": schema,
        "target_package_version": TARGET_VERSION,
        "target_schema": TARGET_SCHEMA,
        "specs": specs,
        "layout_transforms": transforms,
        "active_demands": active,
        "archived": _archived(project, flow),
        "unresolved": unresolved,
        "warnings": warnings,
        "ready": not unresolved,
    }


def _copy_source(project: Path, staging: Path) -> None:
    source = project / ".code-flow"
    target = staging / ".code-flow"
    shutil.copytree(
        source,
        target,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("migrations", "_session", ".active-task.json", ".active-task.lock"),
    )


def _copy_runtime(staging: Path) -> None:
    source = PACKAGE_ROOT / "src/core/code-flow"
    target = staging / ".code-flow"
    shutil.copytree(source / "scripts", target / "scripts", dirs_exist_ok=True)
    shutil.copytree(source / "specs/shared", target / "specs/shared", dirs_exist_ok=True)


def _copy_adapter_tree(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)
    elif source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _clean_hook_config(data: dict[str, object]) -> None:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        for group in groups:
            commands = group.get("hooks") if isinstance(group, dict) else None
            if isinstance(commands, list):
                group["hooks"] = [
                    item for item in commands
                    if isinstance(item, dict) and not any(token in str(item.get("command", "")) for token in ("cf_inject_hook.py", "cf_session_hook.py"))
                ]
        hooks[event] = [group for group in groups if isinstance(group, dict) and group.get("hooks")]


def _merge_hook_config(current: dict[str, object], canonical: Mapping[str, object]) -> dict[str, object]:
    _clean_hook_config(current)
    target_hooks = current.setdefault("hooks", {})
    source_hooks = canonical.get("hooks")
    if not isinstance(target_hooks, dict) or not isinstance(source_hooks, dict):
        raise ValueError("invalid hook config")
    for event, source_groups in source_hooks.items():
        target_groups = target_hooks.setdefault(event, [])
        if not isinstance(source_groups, list) or not isinstance(target_groups, list):
            raise ValueError(f"invalid hook event: {event}")
        for source_group in source_groups:
            matcher = source_group.get("matcher", "") if isinstance(source_group, dict) else ""
            target = next((item for item in target_groups if isinstance(item, dict) and item.get("matcher", "") == matcher), None)
            if target is None:
                target_groups.append(source_group)
                continue
            known = {item.get("command") for item in target.get("hooks", []) if isinstance(item, dict)}
            target.setdefault("hooks", []).extend(item for item in source_group.get("hooks", []) if item.get("command") not in known)
    return current


def _write_hook_config(project: Path, canonical: Path, relative: str, staging: Path) -> None:
    source = project / relative
    current = json.loads(source.read_text(encoding="utf-8")) if source.is_file() else {}
    template = json.loads(canonical.read_text(encoding="utf-8"))
    merged = _merge_hook_config(current, template)
    target = staging / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_adapters(project: Path, staging: Path) -> None:
    adapters = PACKAGE_ROOT / "src/adapters"
    mappings = (
        (adapters / "claude/commands", staging / ".claude/commands"),
        (adapters / "costrict/commands", staging / ".costrict/commands"),
        (adapters / "codex/skills", staging / ".agents/skills"),
        (adapters / "opencode/commands", staging / ".opencode/commands"),
        (adapters / "opencode/plugins", staging / ".opencode/plugins"),
    )
    for source, target in mappings:
        _copy_adapter_tree(source, target)
    for canonical, relative in (
        (adapters / "claude/settings.local.json", ".claude/settings.local.json"),
        (adapters / "costrict/settings.local.json", ".costrict/settings.local.json"),
        (adapters / "codex/hooks.json", ".codex/hooks.json"),
    ):
        _write_hook_config(project, canonical, relative, staging)


def _managed_block(template: str) -> str:
    match = re.search(
        r"(?s)<!-- code-flow:spec-loading schema=1 start -->.*?<!-- code-flow:spec-loading schema=1 end -->",
        template,
    )
    if match is None:
        raise ValueError("canonical managed block missing")
    return match.group(0)


def _replace_managed(text: str, block: str) -> str:
    current = re.search(
        r"(?s)<!-- code-flow:spec-loading schema=\d+ start -->.*?<!-- code-flow:spec-loading schema=\d+ end -->",
        text,
    )
    if current is not None:
        return text[:current.start()] + block + text[current.end():]
    legacy = re.search(r"(?ms)^## Spec Loading\s*$.*?(?=^## |\Z)", text)
    if legacy is not None:
        return text[:legacy.start()] + block + "\n\n" + text[legacy.end():]
    return text.rstrip() + "\n\n" + block + "\n"


def _write_agent_files(project: Path, staging: Path) -> None:
    templates = {
        "AGENTS.md": PACKAGE_ROOT / "src/adapters/codex/AGENTS.md",
        "CLAUDE.md": PACKAGE_ROOT / "src/adapters/claude/CLAUDE.md",
    }
    for name, template_path in templates.items():
        source = project / name
        if not source.is_file():
            continue
        block = _managed_block(template_path.read_text(encoding="utf-8"))
        (staging / name).write_text(
            _replace_managed(source.read_text(encoding="utf-8"), block), encoding="utf-8"
        )


def _apply_layout(staging: Path, transforms: Sequence[Mapping[str, object]]) -> None:
    for transform in transforms:
        target_value = transform.get("target")
        files_value = transform.get("files")
        if not isinstance(target_value, str) or not isinstance(files_value, list):
            raise ValueError("invalid layout transform")
        target = staging / target_value
        target.mkdir(parents=True, exist_ok=True)
        for relative in files_value:
            if not isinstance(relative, str):
                raise ValueError("invalid layout file")
            source = staging / relative
            shutil.move(str(source), str(target / source.name))


def _demand_paths(staging: Path, plan: Mapping[str, object]) -> tuple[Path, ...]:
    paths: set[Path] = set()
    for item in plan.get("layout_transforms", []):
        if isinstance(item, dict) and isinstance(item.get("target"), str):
            paths.add(staging / str(item["target"]))
    for item in plan.get("active_demands", []):
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            paths.add(staging / str(item["path"]))
    return tuple(sorted(paths))


def _staged_metadata(staging: Path) -> tuple[dict[str, SpecMetadata], dict[str, SpecMetadata], dict[str, str]]:
    by_id: dict[str, SpecMetadata] = {}
    by_path: dict[str, SpecMetadata] = {}
    paths_by_id: dict[str, str] = {}
    root = staging / ".code-flow/specs"
    for path in root.rglob("*.md"):
        relative = path.relative_to(root).as_posix()
        if path.name == "_map.md" or relative.startswith(("shared/", "_session/")):
            continue
        metadata = load_spec_metadata(str(path))
        by_id[metadata.id] = metadata
        by_path[relative] = metadata
        paths_by_id[metadata.id] = relative
    return by_id, by_path, paths_by_id


def _normalized_refs(value: str, by_id: Mapping[str, SpecMetadata], by_path: Mapping[str, SpecMetadata]) -> tuple[str, ...]:
    refs: list[str] = []
    for raw in value.split(","):
        token = raw.strip().strip("`")
        if "#" in token and token.split("#", 1)[0] in by_id:
            refs.append(token)
            continue
        metadata = by_path.get(token)
        if metadata is not None:
            refs.extend(f"{metadata.id}#{rule.ref}" for rule in metadata.rules if rule.enforcement == "required")
    return tuple(refs)


def _rewrite_task_refs(demand: Path, by_id: Mapping[str, SpecMetadata], by_path: Mapping[str, SpecMetadata]) -> tuple[str, ...]:
    found: set[str] = set()
    pattern = re.compile(r"(?m)^- \*\*Spec-Refs\*\*:\s*(.+)$")
    for path in demand.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        def replace(match: re.Match[str]) -> str:
            refs = _normalized_refs(match.group(1), by_id, by_path)
            found.update(refs)
            return "- **Spec-Refs**: " + ", ".join(refs) if refs else match.group(0)
        updated = pattern.sub(replace, text)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
    return tuple(sorted(found))


def _write_contexts(staging: Path, plan: Mapping[str, object]) -> None:
    by_id, by_path, paths_by_id = _staged_metadata(staging)
    for demand in _demand_paths(staging, plan):
        demand.mkdir(parents=True, exist_ok=True)
        refs = _rewrite_task_refs(demand, by_id, by_path)
        spec_ids = tuple(sorted({item.split("#", 1)[0] for item in refs}))
        candidates = tuple(
            SpecCandidate(spec_id, paths_by_id[spec_id], "task", SCOPE_PRIORITY["task"], (), by_id[spec_id])
            for spec_id in spec_ids
        )
        context = new_context(demand.name, (("migration", "prepared-plan"),))
        selections = tuple(BindingInput(item, "migration", "legacy Spec-Refs") for item in candidates)
        save_context(str(demand / "spec-context.yml"), bind_specs(context, selections))


def _write_target_config(staging: Path) -> None:
    path = staging / ".code-flow/config.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("invalid config")
    inject = data.get("inject")
    quality = data.get("quality_loop")
    if not isinstance(quality, dict):
        quality = {}
    if isinstance(inject, dict):
        for key in ("compress", "code_extensions", "skip_extensions", "skip_paths"):
            if key in inject and key not in quality:
                quality[key] = inject[key]
    quality.pop("dedup_window", None)
    data.pop("inject", None)
    data["quality_loop"] = quality
    data["spec_workflow"] = {
        "schema_version": 1, "enforcement": "required", "drift_check": True,
        "scope_expansion_check": True, "metrics": True, "catalog": {"dedup_window": 5},
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _write_target_ignore(staging: Path) -> None:
    path = staging / ".code-flow/.gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    block = (
        "# >>> code-flow:runtime schema=1\n.active-task.json\n.active-task.lock\n"
        ".catalog-state.json\nmigrations/\nspecs/_session/\n"
        "# <<< code-flow:runtime schema=1\n"
    )
    lines = [line for line in existing.splitlines() if line != ".inject-state"]
    if "# >>> code-flow:runtime schema=1" not in existing:
        path.write_text("\n".join(lines).rstrip() + "\n" + block, encoding="utf-8")


def _target_manifest(staging: Path) -> list[dict[str, str]]:
    return [
        {"path": _relative(staging, path), "sha256": _sha256(path)}
        for path in sorted(staging.rglob("*")) if path.is_file()
    ]


def stage_plan(plan: Mapping[str, object], staging_root: str) -> dict[str, object]:
    unresolved = plan.get("unresolved")
    if not isinstance(unresolved, list) or unresolved:
        raise ValueError("prepared plan has unresolved items")
    project_value = plan.get("project_root")
    if not isinstance(project_value, str):
        raise ValueError("prepared plan missing project_root")
    staging = Path(staging_root).resolve()
    if not staging.is_dir() or any(staging.iterdir()):
        raise ValueError("staging root must be a pre-created empty directory")
    _copy_source(Path(project_value), staging)
    _copy_runtime(staging)
    _apply_layout(staging, plan.get("layout_transforms", []))
    _write_contexts(staging, plan)
    _write_target_config(staging)
    _write_target_ignore(staging)
    _write_agent_files(Path(project_value), staging)
    _write_adapters(Path(project_value), staging)
    inject_state = staging / ".code-flow/.inject-state"
    if inject_state.exists():
        inject_state.unlink()
    return {
        "targets": _target_manifest(staging),
        "deletions": [
            ".code-flow/.inject-state", ".code-flow/specs/_session",
            ".claude/commands/cf-inject.md", ".costrict/commands/cf-inject.md",
            ".opencode/commands/cf-inject.md", ".agents/skills/cf-inject",
        ],
        "residue": ["inject.mode", "injected_specs", "cf-inject"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cf_spec_migrate.py")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("preflight")
    command.add_argument("--root", required=True)
    command.add_argument("--json", action="store_true")
    stage = commands.add_parser("stage")
    stage.add_argument("--plan", required=True)
    stage.add_argument("--staging", required=True)
    stage.add_argument("--json", action="store_true")
    return parser


def _load_plan(path: str) -> Mapping[str, object]:
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("migration plan must be a mapping")
    return value


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    try:
        args = _parser().parse_args(argv)
        result = preflight(args.root) if args.command == "preflight" else stage_plan(_load_plan(args.plan), args.staging)
        stdout.write(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        stdout.write(json.dumps({"ready": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
