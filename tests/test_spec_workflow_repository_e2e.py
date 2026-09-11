#!/usr/bin/env python3
"""Repository release gate: four adapters, exact TASK context, early Done block."""

import io
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "src/cli.js"
SCRIPTS = ROOT / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_context import BindingInput, bind_specs, load_context, new_context, refresh_context, save_context, start_active_task
from cf_spec_resolver import resolve_candidates
from cf_spec_router import route_prompt
from cf_spec_session import context_sha256
import cf_stop_hook
import cf_user_prompt_hook


SPEC = """---
id: release-rules
description: Release rules
stages: [code]
enforcement: required
verifiers:
  - rule: RULE-release-001
    type: regex
    config:
      pattern: FORBIDDEN
      files: src/*.py
---
# Release
## Rules
- [RULE-release-001] FORBIDDEN text must never enter source.
"""


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def _active_project(root: Path) -> None:
    spec = root / ".code-flow/specs/app/rules.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(SPEC, encoding="utf-8")
    config = {
        "spec_workflow": {"schema_version": 1, "enforcement": "required", "catalog": {"dedup_window": 5}},
        "quality_loop": {"enabled": True, "code_extensions": [".py"]},
        "path_mapping": {"app": {"patterns": ["src/*.py"], "specs": [{"path": "app/rules.md"}]}},
    }
    (root / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    task_dir = root / ".code-flow/tasks/release"
    task_dir.mkdir(parents=True)
    candidate = resolve_candidates(str(root), "code", ("src/app.py",))[0]
    context = bind_specs(new_context("release", (("test", "repository"),)), (BindingInput(candidate, "plan", "release"),))
    save_context(str(task_dir / "spec-context.yml"), context)
    (task_dir / "release.md").write_text(
        "# Tasks\n\n## TASK-001: Release\n- **Spec-Refs**: release-rules#RULE-release-001\n"
        "### Acceptance Contract\n| S-07 | E2E | Git diff and Stop | block violation | verified |\n", encoding="utf-8"
    )
    source = root / "src/app.py"
    source.parent.mkdir()
    source.write_text("SAFE = True\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "baseline")
    start_active_task(str(root), ".code-flow/tasks/release", "TASK-001", context_sha256(context))


def _prompt(root: Path, prompt: str) -> dict:
    output = io.StringIO()
    payload = json.dumps({"prompt": prompt, "session_id": "release-session"})
    with mock.patch("sys.stdin", io.StringIO(payload)), mock.patch("sys.stdout", output), mock.patch("os.getcwd", return_value=str(root)):
        cf_user_prompt_hook.main()
    return json.loads(output.getvalue())


def test_s_04_s_05_s_07_exact_context_and_done_blocks_violation(tmp_path: Path) -> None:
    _active_project(tmp_path)
    context = _prompt(tmp_path, "continue coding")["hookSpecificOutput"]["additionalContext"]
    assert "TASK-001 Spec Context" in context and "RULE-release-001" in context
    assert "Spec Catalog" not in context
    (tmp_path / "src/app.py").write_text("FORBIDDEN = True\n", encoding="utf-8")
    output = io.StringIO()
    with mock.patch("sys.stdin", io.StringIO(json.dumps({"session_id": "release-session"}))), mock.patch("sys.stdout", output), mock.patch("os.getcwd", return_value=str(tmp_path)):
        cf_stop_hook.main()
    result = json.loads(output.getvalue())
    assert result["decision"] == "block"
    assert "release-rules#RULE-release-001" in result["reason"]
    assert "unverified" in result["reason"]


def test_four_platform_fresh_init_routes_default_schema_one_specs(tmp_path: Path) -> None:
    for platform in ("claude", "codex", "costrict", "opencode"):
        project = tmp_path / platform
        project.mkdir()
        initialized = subprocess.run(("node", str(CLI), "init", f"--platform={platform}"), cwd=project, text=True, capture_output=True, check=False)
        assert initialized.returncode == 0, initialized.stderr
        hook = project / ".code-flow/scripts/cf_user_prompt_hook.py"
        routed = subprocess.run((sys.executable, str(hook)), cwd=project, input=json.dumps({"prompt": "edit src/components/Button.tsx", "session_id": platform}), text=True, capture_output=True, check=False)
        assert routed.returncode == 0 and routed.stderr == ""
        text = json.loads(routed.stdout)["hookSpecificOutput"]["additionalContext"]
        assert "RULE-frontend" in text
        assert yaml.safe_load((project / ".code-flow/config.yml").read_text(encoding="utf-8"))["spec_workflow"]["schema_version"] == 1


def test_router_and_resolver_hot_path_thresholds(tmp_path: Path) -> None:
    _active_project(tmp_path)
    resolver_ms = []
    router_ms = []
    refresh_ms = []
    for _ in range(30):
        start = time.perf_counter()
        resolve_candidates(str(tmp_path), "code", ("src/app.py",))
        resolver_ms.append((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        route_prompt(str(tmp_path), ("src/app.py",), "perf")
        router_ms.append((time.perf_counter() - start) * 1000)
        context = load_context(str(tmp_path / ".code-flow/tasks/release/spec-context.yml"))
        start = time.perf_counter()
        refresh_context(context, str(tmp_path), artifact_root=str(tmp_path / ".code-flow/tasks/release"))
        refresh_ms.append((time.perf_counter() - start) * 1000)
    assert statistics.median(resolver_ms) < 25
    assert statistics.median(router_ms) < 50
    assert statistics.median(refresh_ms) < 50
