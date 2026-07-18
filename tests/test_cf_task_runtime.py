#!/usr/bin/env python3
"""S-05/S-07/E-05 E2E coverage for active diff runtime gates."""

from pathlib import Path
import subprocess
import sys

import yaml


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_context import BindingInput, bind_specs, load_context, new_context, save_context, start_active_task
from cf_spec_resolver import resolve_candidates
from cf_task_runtime import evaluate_scope, run_done_gate


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def _spec(spec_id: str, rule: str, pattern: str) -> str:
    return f"""---
id: {spec_id}
description: runtime rule
stages: [code, review]
enforcement: required
verifiers:
  - rule: {rule}
    type: regex
    config:
      pattern: '{pattern}'
      files: '*.py'
---
# Rule
## Rules
- [{rule}] Runtime constraint.
"""


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    app = tmp_path / "src/app.py"
    app.parent.mkdir()
    app.write_text("VALUE = 1\n", encoding="utf-8")
    specs = tmp_path / ".code-flow/specs"
    (specs / "app").mkdir(parents=True)
    (specs / "db").mkdir()
    (specs / "app/rules.md").write_text(_spec("app-runtime", "RULE-app-001", "^print\\("), encoding="utf-8")
    (specs / "db/rules.md").write_text(_spec("db-runtime", "RULE-db-001", "^DROP "), encoding="utf-8")
    config = {"path_mapping": {
        "app": {"patterns": ["src/*"], "specs": [{"path": "app/rules.md"}]},
        "db": {"patterns": ["db/*"], "specs": [{"path": "db/rules.md"}]},
    }}
    (tmp_path / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    task_dir = tmp_path / ".code-flow/tasks/demo"
    task_dir.mkdir(parents=True)
    candidate = resolve_candidates(str(tmp_path), "code", ["src/app.py"])[0]
    context = bind_specs(new_context("demo", (("test", "runtime"),)), (BindingInput(candidate, "plan", "app task"),))
    save_context(str(task_dir / "spec-context.yml"), context)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "initial")
    start_active_task(str(tmp_path), ".code-flow/tasks/demo", "TASK-001", "ctx")
    return tmp_path, task_dir


def test_s_05_required_violation_blocks_done_until_verified(tmp_path: Path) -> None:
    root, task_dir = _repo(tmp_path)
    app = root / "src/app.py"
    app.write_text("print('bad')\n", encoding="utf-8")
    blocked = run_done_gate(str(root), str(task_dir))
    assert blocked.decision == "block"
    assert blocked.evidence[0]["error_code"] == "regex_violation"
    app.write_text("VALUE = 2\n", encoding="utf-8")
    passed = run_done_gate(str(root), str(task_dir))
    assert passed.decision == "pass"
    assert load_context(str(task_dir / "spec-context.yml")).bindings[0].rules[0].stage_status["code"].status == "verified"


def test_s_07_e_05_new_path_pauses_and_adds_pending_binding(tmp_path: Path) -> None:
    root, task_dir = _repo(tmp_path)
    model = root / "db/model.py"
    model.parent.mkdir()
    model.write_text("MODEL = 1\n", encoding="utf-8")
    result = evaluate_scope(str(root), str(task_dir))
    context = load_context(str(task_dir / "spec-context.yml"))
    assert result.decision == "pause"
    assert result.new_specs == ("db-runtime",)
    assert {item.spec_id for item in context.bindings} == {"app-runtime", "db-runtime"}
    assert next(item for item in context.bindings if item.spec_id == "db-runtime").rules[0].stage_status["code"].status == "pending"
    assert "局部 Plan" in result.message and "Align" in result.message
