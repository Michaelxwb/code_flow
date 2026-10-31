#!/usr/bin/env python3
"""[TASK-013][NFR-REL-01] 双 TASK 主线自动化：Plan→Start→提交→Complete→切 TASK→Done→终验。

真实边界：真实 git + 真实 service 状态机 + 真实 Done 门 + 真实 Runner。
覆盖的修复：范围并集(#2)、owner 过滤(#4)、注入版本(#5)、统一迁移(#6)。
"""
import json
import subprocess
import sys
from pathlib import Path

import yaml


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_manifest import validate_manifest, write_manifest  # noqa: E402
from cf_spec_context import (  # noqa: E402
    BindingInput,
    bind_specs,
    injection_version,
    load_context,
    new_context,
    save_context,
)
from codeflow.spec.cf_spec_resolver import resolve_candidates  # noqa: E402
from cf_spec_session import context_sha256  # noqa: E402
from codeflow.task.cf_task_runtime import run_done_gate  # noqa: E402
from codeflow.spec.cf_workflow_service import complete_task, start_task  # noqa: E402
from codeflow.cli.cf_task_workflow import finish_task  # noqa: E402
from codeflow.task.cf_requirement_verification import verify_layers  # noqa: E402


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    spec = tmp_path / ".code-flow/specs/app/rules.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        "---\nid: app-runtime\ndescription: rules\nstages: [code]\n"
        "enforcement: required\n"
        "verifiers:\n  - rule: RULE-app-001\n    type: regex\n"
        "    config:\n      pattern: 'VALUE = 2'\n      files: '*.py'\n"
        "---\n\n# Rule\n## Rules\n- [RULE-app-001] Value must stay constant.\n",
        encoding="utf-8",
    )
    (tmp_path / ".code-flow/config.yml").write_text(
        yaml.safe_dump({
            "spec_workflow": {"schema_version": 1, "enforcement": "required"},
            "path_mapping": {"app": {"patterns": ["src/*"], "specs": [{"path": "app/rules.md"}]}},
        }),
        encoding="utf-8",
    )
    ok = json.dumps([sys.executable, "-c", "pass"])
    task_dir = tmp_path / ".code-flow/tasks/demo"
    task_dir.mkdir(parents=True)
    (task_dir / "work.md").write_text(
        "## TASK-001: First\n- **Status**: draft\n- **Depends**: \n"
        "- **Spec-Refs**: app-runtime#RULE-app-001\n- **Acceptance-Refs**: S-01\n"
        "### Acceptance Contract\n- S-01: first\n### Acceptance Evidence\nnone\n"
        "### Log\n- [2026-01-01] created (draft)\n"
        "## TASK-002: Second\n- **Status**: draft\n- **Depends**: TASK-001\n"
        "- **Spec-Refs**: app-runtime#RULE-app-001\n- **Acceptance-Refs**: S-02\n"
        "### Acceptance Contract\n- S-02: second\n### Acceptance Evidence\nnone\n"
        "### Log\n- [2026-01-01] created (draft)\n"
        "## Acceptance Coverage\n"
        f"|S-01|src|integration|real|TASK-001|planned|{ok}|\n"
        f"|S-02|src|integration|real|TASK-002|planned|{ok}|\n"
        "|---|---|---|---|---|---|---|\n",
        encoding="utf-8",
    )
    candidate = resolve_candidates(str(tmp_path), "code", ["src/app.py"])[0]
    save_context(
        str(task_dir / "spec-context.yml"),
        bind_specs(new_context("demo", (("test", "mainline"),)), (BindingInput(candidate, "plan", "app"),)),
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    write_manifest(str(task_dir / "work.md"), str(task_dir / ".acceptance-manifest.json"))
    return tmp_path, task_dir


def test_dual_task_mainline_start_commit_complete_switch_done(tmp_path: Path) -> None:
    """[NFR-REL-01] 主线全绿，中间产物完整。"""
    root, task_dir = _repo(tmp_path)
    work = str(task_dir / "work.md")

    started_a = start_task(str(root), str(task_dir), work, "TASK-001", ())
    assert started_a["ok"] is True
    assert "- **Status**: in-progress" in Path(work).read_text(encoding="utf-8")
    version_a = injection_version(str(root), "s-main", started_a["context_sha256"])

    (root / "src" / "app.py").write_text("VALUE = 1\n# mainline touch\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "mainline change")
    done_a = run_done_gate(str(root), str(task_dir), task_id="TASK-001")
    assert done_a.decision == "pass", done_a.message
    assert "src/app.py" in done_a.files, "已提交变更不得丢出范围"

    completed = complete_task(str(root), str(task_dir), work, "TASK-001", True)
    assert completed["ok"] is True
    assert not (root / ".code-flow/.active-task.json").exists()

    started_b = start_task(str(root), str(task_dir), work, "TASK-002", ())
    assert started_b["ok"] is True
    version_b = injection_version(str(root), "s-main", started_b["context_sha256"])
    assert version_b != version_a, "切 TASK 必须产生新注入版本"

    (root / "src" / "app.py").write_text("VALUE = 1\n# second task\n", encoding="utf-8")
    done_b = run_done_gate(str(root), str(task_dir), task_id="TASK-002")
    assert done_b.decision == "pass", done_b.message
    text = Path(work).read_text(encoding="utf-8")
    assert "S-01: verified" in text and "S-02: verified" in text
    assert validate_manifest(work, str(task_dir / ".acceptance-manifest.json")) == (True, "")


def test_finish_reports_real_acceptance_work(tmp_path: Path) -> None:
    root, task_dir = _repo(tmp_path)
    work = str(task_dir / "work.md")
    assert start_task(str(root), str(task_dir), work, "TASK-001", ())["ok"]
    config_path = root / ".code-flow/config.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["quality_loop"] = {"enabled": True, "finish_check": True}
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    (root / ".code-flow/validation.yml").write_text(
        f'validators:\n  - name: check\n    trigger: "*.py"\n    command: "{sys.executable} -c pass"\n    timeout: 30000\n',
        encoding="utf-8")
    (root / "src/app.py").write_text("VALUE = 1\n# changed\n", encoding="utf-8")
    result = finish_task(str(root), str(task_dir), work, "TASK-001")
    assert result["decision"] == "pass", result
    assert result["verification"]["selection_reason"] == "profile_and_owner"
    assert result["verification"]["timings"]["execution_ms"] > 0
    assert set(result["verification"]["timings_scope"]) == {"acceptance", "spec", "validators"}
    assert any(item.get("kind") == "spec_check" for item in result["verification"]["layers"])
    assert result["verification"]["executed"] > 0
    assert result["verification"]["execution_identities"]
    assert "finish checks" in result["verification"]["summary"]
    assert result["executed"] == result["verification"]["executed"]
    assert result["timings"]["elapsed_ms"] >= 0
    phases = [item["timings"] for item in result["verification"]["layers"] if item.get("kind") == "spec_phases"]
    assert all(any(row.get(key, 0) > 0 for row in phases)
               for key in ("planning_ms", "preflight_ms", "evidence_ms"))


def test_review_reports_real_spec_execution(tmp_path: Path) -> None:
    root, task_dir = _repo(tmp_path)
    work = str(task_dir / "work.md")
    assert start_task(str(root), str(task_dir), work, "TASK-001", ())["ok"]
    (root / "src/app.py").write_text("VALUE = 1\n# changed\n", encoding="utf-8")
    assert finish_task(str(root), str(task_dir), work, "TASK-001")["decision"] == "pass"
    result = verify_layers(str(root), str(task_dir), layers="review", only_tasks=["TASK-001"])
    assert result["decision"] == "pass", result
    assert "spec" in result["timings_scope"]
    assert result["timings"]["execution_ms"] >= 0
    assert result["timings"]["planning_ms"] > 0
    assert result["timings"]["preflight_ms"] > 0
    assert result["timings"]["evidence_ms"] > 0
    assert result["spec_checks"]
    assert result["executed"] + result["reused"] == len(result["spec_checks"])
