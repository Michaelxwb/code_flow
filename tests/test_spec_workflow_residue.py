#!/usr/bin/env python3
"""S-11/E-10 coverage for the Context-first runtime and legacy residue."""

import io
import json
from pathlib import Path
import subprocess
import sys
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_context import BindingInput, bind_specs, new_context, save_context, start_active_task
from cf_spec_resolver import resolve_candidates
from cf_spec_session import context_sha256
from cf_user_prompt_hook import main


SPEC = """---
id: runtime-rules
description: Runtime rules
stages: [code]
enforcement: required
verifiers:
  - rule: RULE-runtime-001
    type: regex
    config:
      pattern: SAFE
---
# Runtime
## Rules
- [RULE-runtime-001] Always emit SAFE code.
"""


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def _project(root: Path) -> Path:
    spec = root / ".code-flow/specs/app/rules.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(SPEC, encoding="utf-8")
    config = {
        "spec_workflow": {"schema_version": 1, "enforcement": "required", "catalog": {"dedup_window": 5}},
        "budget": {"catalog_max": 200},
        "path_mapping": {"app": {"patterns": ["src/*.py"], "specs": [{"path": "app/rules.md"}]}},
    }
    (root / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    task_dir = root / ".code-flow/tasks/demo"
    task_dir.mkdir(parents=True)
    candidate = resolve_candidates(str(root), "code", ("src/app.py",))[0]
    context = bind_specs(new_context("demo", (("test", "runtime"),)), (BindingInput(candidate, "plan", "required"),))
    save_context(str(task_dir / "spec-context.yml"), context)
    task_file = task_dir / "demo.md"
    task_file.write_text(
        "# Tasks\n\n## TASK-001: Runtime\n- **Spec-Refs**: runtime-rules#RULE-runtime-001\n"
        "### Acceptance Contract\n| S-11 | integration | hook | exact Context |\n",
        encoding="utf-8",
    )
    source = root / "src/app.py"
    source.parent.mkdir()
    source.write_text("SAFE = True\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    start_active_task(str(root), ".code-flow/tasks/demo", "TASK-001", context_sha256(context))
    return task_dir


def _prompt(root: Path, prompt: str) -> dict:
    output = io.StringIO()
    with mock.patch("sys.stdin", io.StringIO(json.dumps({"prompt": prompt, "session_id": "s1"}))), mock.patch("sys.stdout", output), mock.patch("os.getcwd", return_value=str(root)):
        main()
    return json.loads(output.getvalue())


def test_s_11_active_task_injects_exact_task_projection(tmp_path: Path) -> None:
    _project(tmp_path)
    text = _prompt(tmp_path, "implement the next step")["hookSpecificOutput"]["additionalContext"]
    assert "TASK-001 Spec Context" in text
    assert "RULE-runtime-001" in text
    assert "Spec Catalog" not in text


def test_s_11_no_task_uses_path_then_catalog(tmp_path: Path) -> None:
    _project(tmp_path)
    (tmp_path / ".code-flow/.active-task.json").unlink()
    path_text = _prompt(tmp_path, "edit src/app.py")["hookSpecificOutput"]["additionalContext"]
    assert "Always emit SAFE code" in path_text
    catalog_text = _prompt(tmp_path, "explain this project")["hookSpecificOutput"]["additionalContext"]
    assert "Spec Catalog" in catalog_text
    assert "Always emit SAFE code" not in catalog_text


def test_path_injection_applies_lossless_compression(tmp_path: Path) -> None:
    _project(tmp_path)
    spec = tmp_path / ".code-flow/specs/app/rules.md"
    spec.write_text(
        SPEC.replace(
            "# Runtime",
            "# Runtime\n\n<!-- injection-only note -->\n\n## Notes\n- repeated\n- repeated",
        ),
        encoding="utf-8",
    )
    (tmp_path / ".code-flow/.active-task.json").unlink()

    text = _prompt(tmp_path, "edit src/app.py")["hookSpecificOutput"]["additionalContext"]

    assert "injection-only note" not in text
    assert text.count("- repeated") == 1

    config_path = tmp_path / ".code-flow/config.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["quality_loop"] = {"compress": False}
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    uncompressed = _prompt(tmp_path, "edit src/app.py")["hookSpecificOutput"]["additionalContext"]

    assert "injection-only note" in uncompressed
    assert uncompressed.count("- repeated") == 2


def test_s_11_corrupt_active_marker_fails_closed(tmp_path: Path) -> None:
    _project(tmp_path)
    (tmp_path / ".code-flow/.active-task.json").write_text("{broken", encoding="utf-8")
    text = _prompt(tmp_path, "edit src/app.py")["hookSpecificOutput"]["additionalContext"]
    assert "SPEC_WORKFLOW_BLOCKED" in text
    assert "Always emit SAFE code" not in text


def test_e_10_runtime_has_no_legacy_router_symbols() -> None:
    files = ("cf_user_prompt_hook.py", "cf_post_hook.py", "cf_stop_hook.py", "cf_core.py")
    forbidden = ("fallback_domains_for_context", "extract_prompt_tags", "resolve_inject_mode", "injected_specs", "load_inject_state", "save_inject_state")
    found = []
    for name in files:
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        found.extend(f"{name}:{token}" for token in forbidden if token in text)
    assert found == []


def test_e_10_scripts_map_has_only_context_first_entrypoints() -> None:
    text = (ROOT / ".code-flow/specs/scripts/_map.md").read_text(encoding="utf-8")
    forbidden = ("cf_session_hook.py", "cf_scan.py", "load_inject_state", "save_inject_state", "resolve_inject_mode")
    assert all(token not in text for token in forbidden)
    assert all(token in text for token in ("cf_pre_tool_hook.py", "cf_spec_router.py", "cf_spec_context.py", "cf_spec_gate.py"))
