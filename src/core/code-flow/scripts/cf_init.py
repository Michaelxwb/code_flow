#!/usr/bin/env python3
import difflib
import json
import os
import subprocess
import sys

from cf_core import estimate_tokens, load_config


def try_import_yaml():
    try:
        import yaml  # type: ignore

        return yaml
    except Exception:
        pass

    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyyaml"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None

    try:
        import yaml  # type: ignore

        return yaml
    except Exception:
        return None


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read()
    except Exception:
        return ""


def write_text(path: str, content: str) -> bool:
    try:
        with open(path, "w", encoding="utf-8") as file:
            file.write(content)
        return True
    except Exception:
        return False


def merge_list(existing: list, template: list) -> list:
    merged = list(existing)
    seen = set()
    for item in merged:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item)
        seen.add(key)
    for item in template:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item)
        if key in seen:
            continue
        merged.append(item)
        seen.add(key)
    return merged


def merge_dict(existing: dict, template: dict) -> dict:
    for key, value in template.items():
        if key not in existing:
            existing[key] = value
            continue
        if isinstance(value, dict) and isinstance(existing.get(key), dict):
            existing[key] = merge_dict(existing.get(key) or {}, value)
        elif isinstance(value, list) and isinstance(existing.get(key), list):
            existing[key] = merge_list(existing.get(key) or [], value)
    return existing


def merge_yaml(path: str, template: dict, yaml_module):
    if os.path.exists(path):
        if yaml_module is None:
            return None, "yaml_missing"
        try:
            with open(path, "r", encoding="utf-8") as file:
                existing = yaml_module.safe_load(file) or {}
        except Exception:
            existing = {}
        merged = merge_dict(existing, template)
        if merged == existing:
            return existing, "skipped"
        try:
            with open(path, "w", encoding="utf-8") as file:
                yaml_module.safe_dump(merged, file, sort_keys=False, allow_unicode=True)
            return merged, "updated"
        except Exception:
            return existing, "write_failed"
    else:
        if yaml_module is None:
            try:
                with open(path, "w", encoding="utf-8") as file:
                    json.dump(template, file, ensure_ascii=False, indent=2)
                return template, "created"
            except Exception:
                return None, "write_failed"
        try:
            with open(path, "w", encoding="utf-8") as file:
                yaml_module.safe_dump(template, file, sort_keys=False, allow_unicode=True)
            return template, "created"
        except Exception:
            return None, "write_failed"


def merge_json(path: str, template: dict):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as file:
                existing = json.load(file)
        except Exception:
            existing = {}
        merged = merge_dict(existing, template)
        if merged == existing:
            return existing, "skipped"
        try:
            with open(path, "w", encoding="utf-8") as file:
                json.dump(merged, file, ensure_ascii=False, indent=2)
            return merged, "updated"
        except Exception:
            return existing, "write_failed"
    try:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(template, file, ensure_ascii=False, indent=2)
        return template, "created"
    except Exception:
        return None, "write_failed"


def split_sections(template: str) -> list:
    sections = []
    current = []
    for line in template.splitlines():
        if line.startswith("## "):
            if current:
                sections.append("\n".join(current).rstrip())
            current = [line]
        else:
            if current:
                current.append(line)
    if current:
        sections.append("\n".join(current).rstrip())
    return sections


def merge_markdown(path: str, template: str):
    if not os.path.exists(path):
        if write_text(path, template.rstrip() + "\n"):
            return "created"
        return "write_failed"

    existing = read_text(path).rstrip()
    if not existing:
        if write_text(path, template.rstrip() + "\n"):
            return "updated"
        return "write_failed"

    existing_headings = {
        line.strip() for line in existing.splitlines() if line.strip().startswith("## ")
    }
    sections = split_sections(template)
    additions = []
    for section in sections:
        heading = section.splitlines()[0].strip()
        if heading not in existing_headings:
            additions.append(section.strip())
    if not additions:
        return "skipped"
    updated = existing + "\n\n" + "\n\n".join(additions).rstrip() + "\n"
    if write_text(path, updated):
        return "updated"
    return "write_failed"


def build_unified_diff(original: str, template: str, from_label: str, to_label: str) -> str:
    original_lines = original.rstrip().splitlines()
    template_lines = template.rstrip().splitlines()
    diff_lines = difflib.unified_diff(
        original_lines,
        template_lines,
        fromfile=from_label,
        tofile=to_label,
        lineterm="",
    )
    return "\n".join(diff_lines)


def detect_stack(project_root: str, override: str):
    frontend = False
    backend = False
    frameworks = []
    backend_types = []

    if override in {"frontend", "backend", "fullstack"}:
        frontend = override in {"frontend", "fullstack"}
        backend = override in {"backend", "fullstack"}
        return frontend, backend, frameworks, backend_types, True

    pkg_path = os.path.join(project_root, "package.json")
    if os.path.exists(pkg_path):
        frontend = True
        try:
            with open(pkg_path, "r", encoding="utf-8") as file:
                pkg = json.load(file)
            deps = {}
            deps.update(pkg.get("dependencies") or {})
            deps.update(pkg.get("devDependencies") or {})
            if "react" in deps:
                frameworks.append("react")
            if "vue" in deps:
                frameworks.append("vue")
            if "@angular/core" in deps:
                frameworks.append("angular")
        except Exception:
            pass

    if os.path.exists(os.path.join(project_root, "pyproject.toml")) or os.path.exists(
        os.path.join(project_root, "requirements.txt")
    ):
        backend = True
        backend_types.append("python")

    if os.path.exists(os.path.join(project_root, "go.mod")):
        backend = True
        backend_types.append("go")

    detected = frontend or backend
    return frontend, backend, frameworks, backend_types, detected


def format_stack(frontend: bool, backend: bool, frameworks: list, backend_types: list, detected: bool) -> str:
    if not detected:
        return "generic"
    stack = []
    if frontend:
        stack.append("frontend")
    if backend:
        stack.append("backend")
    details = []
    if frameworks:
        details.append("frameworks=" + ",".join(sorted(set(frameworks))))
    if backend_types:
        details.append("backend=" + ",".join(sorted(set(backend_types))))
    if details:
        stack.append("(" + "; ".join(details) + ")")
    return " ".join(stack)


def hooks_ready(settings: dict) -> bool:
    hooks = settings.get("hooks") or {}
    pre = hooks.get("PreToolUse") or []
    session = hooks.get("SessionStart") or []
    if not pre or not session:
        return False
    pre_ok = any(
        isinstance(item, dict)
        and any(
            isinstance(hook, dict)
            and hook.get("command") == "python3 .code-flow/scripts/cf_inject_hook.py"
            for hook in (item.get("hooks") or [])
        )
        for item in pre
    )
    session_ok = any(
        isinstance(item, dict)
        and any(
            isinstance(hook, dict)
            and hook.get("command") == "python3 .code-flow/scripts/cf_session_hook.py"
            for hook in (item.get("hooks") or [])
        )
        for item in session
    )
    return pre_ok and session_ok


def main() -> None:
    project_root = os.getcwd()
    override = ""
    if len(sys.argv) > 1:
        override = sys.argv[1].strip().lower()

    yaml_module = try_import_yaml()
    warnings = []
    if yaml_module is None:
        warnings.append("pyyaml not available; yaml merge skipped")

    frontend, backend, frameworks, backend_types, detected = detect_stack(project_root, override)
    if not detected and override not in {"frontend", "backend", "fullstack"}:
        frontend = True
        backend = True

    ensure_dir(os.path.join(project_root, ".code-flow"))
    ensure_dir(os.path.join(project_root, ".code-flow", "scripts"))
    if frontend:
        ensure_dir(os.path.join(project_root, ".code-flow", "specs", "frontend"))
    if backend:
        ensure_dir(os.path.join(project_root, ".code-flow", "specs", "backend"))
    ensure_dir(os.path.join(project_root, ".claude", "skills"))

    config_template = {
        "version": 1,
        "budget": {"total": 2500, "l0_max": 800, "l1_max": 1700},
        "inject": {
            "auto": True,
            "code_extensions": [
                ".py",
                ".go",
                ".ts",
                ".tsx",
                ".js",
                ".jsx",
                ".java",
                ".rs",
                ".rb",
                ".vue",
                ".svelte",
            ],
            "skip_extensions": [
                ".md",
                ".txt",
                ".json",
                ".yml",
                ".yaml",
                ".toml",
                ".lock",
                ".csv",
                ".xml",
                ".svg",
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".ico",
                ".pdf",
                ".zip",
                ".gz",
                ".tar",
            ],
            "skip_paths": [
                "docs/**",
                "*.config.*",
                ".code-flow/**",
                ".claude/**",
                "node_modules/**",
                "dist/**",
                "build/**",
                "out/**",
                "coverage/**",
                ".next/**",
                ".cache/**",
                ".venv/**",
                "venv/**",
                "__pycache__/**",
                ".git/**",
            ],
        },
        "path_mapping": {
            "frontend": {
                "patterns": [
                    "src/components/**",
                    "src/pages/**",
                    "src/hooks/**",
                    "src/styles/**",
                    "**/*.tsx",
                    "**/*.jsx",
                    "**/*.css",
                    "**/*.scss",
                ],
                "specs": [
                    "frontend/directory-structure.md",
                    "frontend/quality-standards.md",
                    "frontend/component-specs.md",
                ],
                "spec_priority": {
                    "frontend/directory-structure.md": 1,
                    "frontend/quality-standards.md": 2,
                    "frontend/component-specs.md": 3,
                },
            },
            "backend": {
                "patterns": [
                    "services/**",
                    "api/**",
                    "models/**",
                    "**/*.py",
                    "**/*.go",
                ],
                "specs": [
                    "backend/directory-structure.md",
                    "backend/logging.md",
                    "backend/database.md",
                    "backend/platform-rules.md",
                    "backend/code-quality-performance.md",
                ],
                "spec_priority": {
                    "backend/directory-structure.md": 1,
                    "backend/database.md": 2,
                    "backend/logging.md": 3,
                    "backend/code-quality-performance.md": 4,
                    "backend/platform-rules.md": 5,
                },
            },
        },
    }

    validation_template = {
        "validators": [
            {
                "name": "Python 语法检查",
                "trigger": "**/*.py",
                "command": "python3 -m py_compile {files}",
                "timeout": 30000,
                "on_fail": "检查语法错误",
            },
            {
                "name": "TypeScript 类型检查",
                "trigger": "**/*.{ts,tsx}",
                "command": "npx tsc --noEmit",
                "timeout": 30000,
                "on_fail": "检查类型定义，参见 specs/frontend/quality-standards.md",
            },
            {
                "name": "ESLint",
                "trigger": "**/*.{ts,tsx,js,jsx}",
                "command": "npx eslint {files}",
                "timeout": 15000,
                "on_fail": "运行 npx eslint --fix 自动修复",
            },
            {
                "name": "Python 类型检查",
                "trigger": "**/*.py",
                "command": "python3 -m mypy {files}",
                "timeout": 30000,
                "on_fail": "检查类型注解，参见 specs/backend/code-quality-performance.md",
            },
            {
                "name": "Pytest",
                "trigger": "**/*.py",
                "command": "python3 -m pytest --tb=short -q",
                "timeout": 60000,
                "on_fail": "测试失败，检查断言和 mock 是否需要更新",
            },
        ]
    }

    claude_template = """# Project Guidelines

## Team Identity
- Team: [team name]
- Project: [project name]
- Language: [primary language]

## Core Principles
- All changes must include tests
- Single responsibility per function (<= 50 lines)
- No loose typing or silent exception handling
- Handle errors explicitly

## Forbidden Patterns
- Hard-coded secrets or credentials
- Unparameterized SQL
- Network calls inside tight loops

## Spec Loading
This project uses the code-flow layered spec system.
Specs live in .code-flow/specs/ and are injected on demand.

## Learnings
"""

    spec_templates = {
        "frontend/directory-structure.md": """# Frontend Directory Structure

## Rules
- Define where components, pages, and hooks live.

## Patterns
- Keep module boundaries explicit and predictable.

## Anti-Patterns
- Avoid ad-hoc folders without owners.

## Learnings
""",
        "frontend/quality-standards.md": """# Frontend Quality Standards

## Rules
- Enforce consistent typing and error handling.

## Patterns
- Use shared utilities for validation and formatting.

## Anti-Patterns
- Avoid side effects during render.

## Learnings
""",
        "frontend/component-specs.md": """# Component Specs

## Rules
- Define Props with interface types.

## Patterns
- Split container and presentational logic.

## Anti-Patterns
- Do not mutate props.

## Learnings
""",
        "backend/directory-structure.md": """# Backend Directory Structure

## Rules
- Keep service entrypoints and APIs separated.

## Patterns
- Organize by bounded context.

## Anti-Patterns
- Avoid dumping scripts in root.

## Learnings
""",
        "backend/logging.md": """# Backend Logging

## Rules
- Emit structured logs for critical paths.

## Patterns
- Include request_id and latency in logs.

## Anti-Patterns
- Avoid noisy logs in tight loops.

## Learnings
""",
        "backend/database.md": """# Backend Database

## Rules
- Use parameterized queries only.

## Patterns
- Keep migrations idempotent.

## Anti-Patterns
- Avoid external calls inside transactions.

## Learnings
""",
        "backend/platform-rules.md": """# Backend Platform Rules

## Rules
- Ensure API changes are backward compatible.

## Patterns
- Use feature flags for gradual rollouts.

## Anti-Patterns
- Avoid debug configs in production.

## Learnings
""",
        "backend/code-quality-performance.md": """# Backend Code Quality & Performance

## Rules
- Require structured logging on critical paths.

## Patterns
- Add timeouts and retries for external calls.

## Anti-Patterns
- Do not swallow exceptions.

## Learnings
""",
    }

    skills_templates = {
        "cf-init.md": """# cf-init

Initialize code-flow specs, config, skills, and hooks.

## Usage
- /cf-init
- /cf-init frontend|backend|fullstack

## Command
- python3 .code-flow/scripts/cf_init.py [frontend|backend|fullstack]
""",
        "cf-scan.md": """# cf-scan

Audit spec tokens and redundancy.

## Usage
- /cf-scan
- /cf-scan --json
- /cf-scan --only-issues
- /cf-scan --limit=10

## Command
- python3 .code-flow/scripts/cf_scan.py [--json] [--only-issues] [--limit=N]
""",
        "cf-inject.md": """# cf-inject

Manual spec injection (fallback when hooks do not fire).

## Usage
- /cf-inject frontend|backend
- /cf-inject path/to/file.ext
- /cf-inject --list-specs --domain=frontend

## Command
- python3 .code-flow/scripts/cf_inject.py [domain|file_path]
- python3 .code-flow/scripts/cf_inject.py --list-specs --domain=frontend
""",
        "cf-validate.md": """# cf-validate

Run validators based on changed files.

## Usage
- /cf-validate
- /cf-validate path/to/file.py
- /cf-validate --files=src/a.ts,src/b.ts

## Command
- python3 .code-flow/scripts/cf_validate.py [file_path] [--files=...] [--only-failed] [--json-short] [--output=table]
""",
        "cf-stats.md": """# cf-stats

Report L0/L1 token utilization.

## Usage
- /cf-stats
- /cf-stats --human
- /cf-stats --domain=frontend

## Command
- python3 .code-flow/scripts/cf_stats.py [--human] [--domain=frontend]
""",
        "cf-learn.md": """# cf-learn

Append learnings to a spec file or CLAUDE.md.

## Usage
- /cf-learn --scope=global --content="..."
- /cf-learn --scope=frontend --content="..." --file=frontend/component-specs.md
- /cf-learn --scope=backend --content="..." --file=backend/logging.md

## Command
- python3 .code-flow/scripts/cf_learn.py --scope=global|frontend|backend --content="..." [--file=spec] [--dry-run]
""",
    }

    settings_template = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Edit|Write|MultiEdit",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 .code-flow/scripts/cf_inject_hook.py",
                            "timeout": 5,
                        }
                    ],
                }
            ],
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 .code-flow/scripts/cf_session_hook.py",
                        }
                    ]
                }
            ],
        }
    }

    created = []
    updated = []
    skipped = []

    config_path = os.path.join(project_root, ".code-flow", "config.yml")
    _, status = merge_yaml(config_path, config_template, yaml_module)
    if status == "created":
        created.append(".code-flow/config.yml")
    elif status == "updated":
        updated.append(".code-flow/config.yml")
    elif status == "skipped":
        skipped.append(".code-flow/config.yml")
    elif status == "yaml_missing":
        warnings.append("config.yml merge skipped (pyyaml missing)")
        skipped.append(".code-flow/config.yml")

    validation_path = os.path.join(project_root, ".code-flow", "validation.yml")
    _, status = merge_yaml(validation_path, validation_template, yaml_module)
    if status == "created":
        created.append(".code-flow/validation.yml")
    elif status == "updated":
        updated.append(".code-flow/validation.yml")
    elif status == "skipped":
        skipped.append(".code-flow/validation.yml")
    elif status == "yaml_missing":
        warnings.append("validation.yml merge skipped (pyyaml missing)")
        skipped.append(".code-flow/validation.yml")

    claude_path = os.path.join(project_root, "CLAUDE.md")
    claude_exists = os.path.exists(claude_path)
    claude_original = read_text(claude_path) if claude_exists else ""
    claude_diff = ""
    if claude_exists:
        claude_diff = build_unified_diff(
            claude_original,
            claude_template,
            "CLAUDE.md (current)",
            "CLAUDE.md (template)",
        )
    status = merge_markdown(claude_path, claude_template)
    if status == "created":
        created.append("CLAUDE.md")
    elif status == "updated":
        updated.append("CLAUDE.md")
    elif status == "skipped":
        skipped.append("CLAUDE.md")

    for rel, template in spec_templates.items():
        domain = rel.split("/", 1)[0]
        if domain == "frontend" and not frontend:
            continue
        if domain == "backend" and not backend:
            continue
        spec_path = os.path.join(project_root, ".code-flow", "specs", rel)
        status = merge_markdown(spec_path, template)
        if status == "created":
            created.append(os.path.join(".code-flow", "specs", rel))
        elif status == "updated":
            updated.append(os.path.join(".code-flow", "specs", rel))
        elif status == "skipped":
            skipped.append(os.path.join(".code-flow", "specs", rel))

    for name, template in skills_templates.items():
        skill_path = os.path.join(project_root, ".claude", "skills", name)
        status = merge_markdown(skill_path, template)
        rel = os.path.join(".claude", "skills", name)
        if status == "created":
            created.append(rel)
        elif status == "updated":
            updated.append(rel)
        elif status == "skipped":
            skipped.append(rel)

    settings_path = os.path.join(project_root, ".claude", "settings.local.json")
    settings, status = merge_json(settings_path, settings_template)
    if status == "created":
        created.append(".claude/settings.local.json")
    elif status == "updated":
        updated.append(".claude/settings.local.json")
    elif status == "skipped":
        skipped.append(".claude/settings.local.json")

    tokens = []
    config = load_config(project_root)
    specs_root = os.path.join(project_root, ".code-flow", "specs")
    if config.get("path_mapping"):
        for domain_cfg in (config.get("path_mapping") or {}).values():
            for rel in domain_cfg.get("specs") or []:
                full_path = os.path.join(specs_root, rel)
                content = read_text(full_path).strip()
                if not content:
                    continue
                tokens.append(
                    {
                        "path": f"specs/{rel}".replace(os.sep, "/"),
                        "tokens": estimate_tokens(content),
                    }
                )
    elif os.path.isdir(specs_root):
        for root, _, filenames in os.walk(specs_root):
            for name in filenames:
                if not name.endswith(".md"):
                    continue
                full_path = os.path.join(root, name)
                content = read_text(full_path).strip()
                if not content:
                    continue
                rel_path = os.path.relpath(full_path, os.path.join(project_root, ".code-flow"))
                rel_path = rel_path.replace(os.sep, "/")
                tokens.append(
                    {
                        "path": rel_path,
                        "tokens": estimate_tokens(content),
                    }
                )

    settings_loaded = settings if isinstance(settings, dict) else {}
    hooks_ok = hooks_ready(settings_loaded)

    summary = {
        "stack": format_stack(frontend, backend, frameworks, backend_types, detected),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "tokens": tokens,
        "hooks_ready": hooks_ok,
        "warnings": warnings,
    }
    if claude_exists:
        summary["suggestions"] = [{"file": "CLAUDE.md", "diff": claude_diff}]

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
