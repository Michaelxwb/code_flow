#!/usr/bin/env python3
"""[TASK-001] 0.8 执行型门禁的规模基线 fixture。

这不是一个“性能必须越来越快”的断言测试，而是把 0.7 的真实形态固化下来：
119 个 TASK、190 条场景、62 条 E2E、7 条唯一命令、1 MB+ 的 spec-context。

基线数字记录在 `docs/plans/0.8-baseline.md`；本测试只保证 fixture 可重复、
命令级去重可测量、context 规模可测量，方便后续 TASK 对比。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping

import yaml

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_runner import run_manifest  # noqa: E402
from cf_spec_context import (  # noqa: E402
    BindingInput,
    RuleBinding,
    RuleStageStatus,
    SpecBinding,
    SpecContext,
    bind_specs,
    load_active_task,
    new_context,
    save_context,
    start_active_task,
)
from cf_spec_gate import validate_stage  # noqa: E402
from cf_spec_metadata import SpecHashes  # noqa: E402
from cf_spec_resolver import resolve_candidates  # noqa: E402
from cf_task_workflow import finish_task  # noqa: E402
from cf_workflow_service import read_task_section, section_status  # noqa: E402


TASK_COUNT = 119
SCENARIO_COUNT = 190
E2E_COUNT = 62
E2E_COMMAND_COUNTS = (15, 14, 11, 10, 4, 4, 4)
CONTEXT_BINDINGS = 20
CONTEXT_EVIDENCE_PER_RULE = 122


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def _git_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "scale@test")
    _git(root, "config", "user.name", "scale")
    (root / "src").mkdir()
    (root / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / ".gitignore").write_text("runs.txt\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")


def _task_doc(root: Path) -> Path:
    req = root / ".code-flow/tasks/2026-10-22/scale"
    req.mkdir(parents=True)
    lines = ["# Tasks: scale baseline", "", "## Acceptance Coverage", "",
             "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |",
             "|--------|---------|---------|-------------|---------|------|---------|"]
    for index in range(SCENARIO_COUNT):
        sid = f"S-{index + 1:03d}"
        lines.append(f"| {sid} | design#2.5 | integration | runner | TASK-{index % TASK_COUNT + 1:03d} | planned | - |")
    lines.append("")
    for index in range(TASK_COUNT):
        lines.extend([
            f"## TASK-{index + 1:03d}: capability {index + 1}",
            "",
            "- **Status**: draft",
            f"- **Priority**: {'P0' if index % 3 == 0 else 'P1'}",
            "- **Depends**:",
            "- **Source**: scale.design.md#2.5 验收条件",
            "- **Spec-Refs**:",
            "- **Acceptance-Refs**:",
            "",
            "### Checklist",
            "- [ ] 实现并验证本能力。",
            "",
        ])
    path = req / "scale.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _manifest(root: Path) -> Path:
    manifest_dir = root / ".code-flow/tasks/2026-10-22/scale"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    marker = root / "runs.txt"
    scenarios: list[dict[str, object]] = []
    for index in range(SCENARIO_COUNT - E2E_COUNT):
        scenarios.append({
            "id": f"F-{index + 1:03d}",
            "kind": "functional",
            "owner": f"TASK-{index % TASK_COUNT + 1:03d}",
            "command": [sys.executable, "-c", "pass"],
            "cwd": ".",
            "timeout": 30,
            "depends_on": [],
            "status": "planned",
        })
    cursor = 0
    for command_index, count in enumerate(E2E_COMMAND_COUNTS, start=1):
        command = [
            sys.executable,
            "-c",
            "from pathlib import Path; "
            f"p=Path({str(marker)!r}); "
            "p.write_text((p.read_text() if p.exists() else '') + "
            f"'e2e-{command_index}\\n')",
        ]
        for _ in range(count):
            cursor += 1
            scenarios.append({
                "id": f"E-{cursor:03d}",
                "kind": "e2e",
                "owner": f"TASK-{cursor % TASK_COUNT + 1:03d}",
                "command": command,
                "cwd": ".",
                "timeout": 30,
                "depends_on": [],
                "status": "planned",
            })
    assert len(scenarios) == SCENARIO_COUNT
    path = manifest_dir / ".acceptance-manifest.json"
    path.write_text(json.dumps({"scenarios": scenarios}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _context(root: Path) -> Path:
    req = root / ".code-flow/tasks/2026-10-22/scale"
    req.mkdir(parents=True, exist_ok=True)
    evidence = [
        {
            "verifier_ref": "scale#RULE-001",
            "executed_at": f"2026-10-01T00:{index % 60:02d}:00+00:00",
            "status": "unverified",
            "rule_text_sha256": "a" * 64,
            "artifact_sha256": None,
            "diff_sha256": "b" * 64,
            "result_sha256": "c" * 64,
            "error_code": "deferred_to_review",
            "details": {"reason": "over_finish_budget", "deferred_to_review": True,
                        "note": "baseline fixture: repeated deferral evidence for context growth"},
        }
        for index in range(CONTEXT_EVIDENCE_PER_RULE)
    ]
    bindings = []
    for index in range(CONTEXT_BINDINGS):
        bindings.append({
            "spec_id": f"scale-{index:02d}",
            "path": f"scale/spec-{index:02d}.md",
            "status": "active",
            "hashes": {"file_sha256": "d" * 64, "metadata_sha256": "e" * 64, "rules_sha256": "f" * 64},
            "selected_by": "design",
            "reason": "baseline fixture for context growth",
            "enforcement": "required",
            "stages": ["design", "plan", "code", "review"],
            "rules": [{
                "ref": "RULE-001",
                "summary": "baseline rule with repeated deferral evidence",
                "text_sha256": "1" * 64,
                "enforcement": "required",
                "verifier_ref": f"scale-{index:02d}#RULE-001",
                "verifier_stage": "code",
                "stage_status": {
                    "design": {"status": "applied", "refs": [], "decision": None, "evidence": []},
                    "plan": {"status": "applied", "refs": [], "decision": None, "evidence": []},
                    "code": {"status": "unverified", "refs": [], "decision": None, "evidence": evidence},
                    "review": {"status": "pending", "refs": [], "decision": None, "evidence": []},
                },
            }],
        })
    data = {
        "version": 1,
        "task": "scale",
        "enforcement": "required",
        "updated_at": "2026-10-22T00:00:00+00:00",
        "sources": [],
        "bindings": bindings,
    }
    path = req / "spec-context.yml"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _fixture(root: Path) -> tuple[Path, Path, Path]:
    _git_repo(root)
    return _task_doc(root), _manifest(root), _context(root)


def _count_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def baseline_metrics(root: Path) -> Mapping[str, object]:
    """Measure the current 0.7-scale fixture without asserting desired behavior."""
    task, manifest, context = _fixture(root)
    marker = root / "runs.txt"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    e2e = [item for item in data["scenarios"] if item["kind"] == "e2e"]
    commands = {tuple(item["command"]) for item in e2e}

    started = time.perf_counter()
    first = run_manifest(str(manifest), str(root), only_e2e=True)
    first_seconds = time.perf_counter() - started
    first_runs = _count_lines(marker)

    # 0.7 baseline: global worktree fingerprint means an unrelated tracked
    # change invalidates every E2E scenario. Recorded, not asserted as desired.
    (root / "src/app.py").write_text("VALUE = 2\n", encoding="utf-8")
    started = time.perf_counter()
    second = run_manifest(str(manifest), str(root), only_e2e=True)
    second_seconds = time.perf_counter() - started
    second_runs = _count_lines(marker) - first_runs

    context_text = context.read_text(encoding="utf-8")
    return {
        "task_count": task.read_text(encoding="utf-8").count("## TASK-"),
        "scenario_count": len(data["scenarios"]),
        "e2e_count": len(e2e),
        "unique_e2e_commands": len(commands),
        "first_decision": first["decision"],
        "first_executions": first_runs,
        "first_seconds": round(first_seconds, 3),
        "second_after_unrelated_change_seconds": round(second_seconds, 3),
        "second_executions": second_runs,
        "second_decision": second["decision"],
        "context_bytes": len(context_text.encode("utf-8")),
        "context_evidence_entries": context_text.count('"error_code": "deferred_to_review"'),
    }


def test_workflow_scale_fixture_shape(tmp_path: Path) -> None:
    task, manifest, context = _fixture(tmp_path)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    e2e = [item for item in data["scenarios"] if item["kind"] == "e2e"]
    assert task.read_text(encoding="utf-8").count("## TASK-") == TASK_COUNT
    assert len(data["scenarios"]) == SCENARIO_COUNT
    assert len(e2e) == E2E_COUNT
    assert len({tuple(item["command"]) for item in e2e}) == len(E2E_COMMAND_COUNTS)
    assert len(context.read_text(encoding="utf-8").encode("utf-8")) > 500_000


def test_workflow_scale_duplicate_commands_execute_once(tmp_path: Path) -> None:
    task, manifest, context = _fixture(tmp_path)
    marker = tmp_path / "runs.txt"
    result = run_manifest(str(manifest), str(tmp_path), only_e2e=True)
    assert result["decision"] == "pass"
    assert _count_lines(marker) == len(E2E_COMMAND_COUNTS), "同一命令只能执行一次"
    assert len([item for item in result["results"] if item["kind"] == "e2e"]) == E2E_COUNT


def test_workflow_scale_baseline_metrics_are_measurable(tmp_path: Path) -> None:
    metrics = baseline_metrics(tmp_path)
    assert metrics["task_count"] == TASK_COUNT
    assert metrics["scenario_count"] == SCENARIO_COUNT
    assert metrics["e2e_count"] == E2E_COUNT
    assert metrics["unique_e2e_commands"] == len(E2E_COMMAND_COUNTS)
    assert metrics["first_decision"] == "pass"
    assert metrics["first_executions"] == len(E2E_COMMAND_COUNTS)
    assert metrics["second_decision"] == "pass"
    assert metrics["context_evidence_entries"] == CONTEXT_BINDINGS * CONTEXT_EVIDENCE_PER_RULE
    assert metrics["context_bytes"] > 500_000
    assert metrics["first_seconds"] >= 0
    assert metrics["second_after_unrelated_change_seconds"] >= 0



def test_baseline_interrupt_loses_progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """0.7 基线：runner 只在全部场景结束后写证据，中断会丢掉已完成场景。"""
    task, manifest, context = _fixture(tmp_path)
    marker = tmp_path / "runs.txt"
    import cf_acceptance_runner as runner

    real = runner.run_command
    calls = 0

    def interrupted(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls > 3:
            raise KeyboardInterrupt
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "run_command", interrupted)
    with pytest.raises(KeyboardInterrupt):
        runner.run_manifest(str(manifest), str(tmp_path), only_e2e=True, write_evidence=True)
    assert _count_lines(marker) == 3
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert all(item["status"] == "planned" for item in saved["scenarios"]), "中断不得写部分 verified"

    monkeypatch.setattr(runner, "run_command", real)
    result = runner.run_manifest(str(manifest), str(tmp_path), only_e2e=True)
    assert result["decision"] == "pass"
    assert _count_lines(marker) == 10, "0.7 基线：中断后从 0 重跑，7 条全部再执行"


# --- TASK-003 S-01: truthful deferral semantics and Done Gate ---

_TRUTHFUL_COMMAND = [
    sys.executable,
    "-c",
    "from pathlib import Path; Path('gate-ran.txt').write_text('x')",
]


def _truthful_gate_repo(
    root: Path,
    *,
    timeout: int = 30,
    budget: float = 300.0,
    command: list[str] | None = None,
) -> tuple[Path, Path, Path]:
    """Real temp repo + task md + spec-context + command verifier (no mocks)."""
    _git_repo(root)
    spec_dir = root / ".code-flow/specs/truthful"
    spec_dir.mkdir(parents=True)
    metadata = {
        "id": "truthful-runtime",
        "description": "truthful gate rule",
        "stages": ["code", "review"],
        "enforcement": "required",
        "verifiers": [{
            "rule": "RULE-truthful-001",
            "type": "test",
            "config": {"argv": command or _TRUTHFUL_COMMAND, "timeout": timeout},
        }],
    }
    spec_text = (
        "---\n" + yaml.safe_dump(metadata, sort_keys=False)
        + "---\n# Truthful Rules\n## Rules\n- [RULE-truthful-001] required command must execute.\n"
    )
    (spec_dir / "rules.md").write_text(spec_text, encoding="utf-8")
    config = {
        "path_mapping": {"truthful": {"patterns": ["src/*"], "specs": [{"path": "truthful/rules.md"}]}},
        "quality_loop": {"enabled": True, "finish_verifier_budget": budget},
    }
    (root / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")

    task_dir = root / ".code-flow/tasks/2026-10-22/truthful"
    task_dir.mkdir(parents=True)
    task_file = task_dir / "truthful.md"
    task_file.write_text(
        "# Tasks: truthful gate\n\n"
        "## TASK-001: Truthful gate\n"
        "- **Status**: in-progress\n"
        "- **Priority**: P0\n"
        "- **Depends**:\n"
        "- **Source**: truthful.design.md#2.5\n"
        "- **Spec-Refs**: truthful-runtime#RULE-truthful-001\n"
        "- **Acceptance-Refs**: S-01\n\n"
        "### Checklist\n- [ ] required code check executed.\n",
        encoding="utf-8",
    )
    candidate = resolve_candidates(str(root), "code", ["src/app.py"])[0]
    context = bind_specs(new_context("truthful", (("test", "truthful"),)),
                         (BindingInput(candidate, "plan", "truthful task"),))
    save_context(str(task_dir / "spec-context.yml"), context)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "truthful gate fixture")
    start_active_task(str(root), ".code-flow/tasks/2026-10-22/truthful", "TASK-001", "ctx")
    (root / "src/app.py").write_text("VALUE = 2\n", encoding="utf-8")
    return root, task_dir, task_file


def _set_finish_budget(root: Path, budget: float) -> None:
    path = root / ".code-flow/config.yml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config.setdefault("quality_loop", {})["finish_verifier_budget"] = budget
    path.write_text(yaml.safe_dump(config), encoding="utf-8")


def _task_status(task_file: Path) -> str:
    return section_status(read_task_section(str(task_file), "TASK-001"))


def test_truthful_gate_unexecuted_required_check_is_provisional_and_recoverable(tmp_path: Path) -> None:
    root, task_dir, task_file = _truthful_gate_repo(tmp_path, budget=1e-6)

    result = finish_task(str(root), str(task_dir), str(task_file), "TASK-001")

    assert result["decision"] == "provisional"
    assert not (root / "gate-ran.txt").exists(), "预算耗尽时 required check 未真实执行"
    assert _task_status(task_file) == "provisional", "未执行 required check 的任务不得变成 done"
    assert load_active_task(str(root)).status == "active", "provisional 必须可恢复，不得清掉 active marker"
    missing = {item["ref"]: item["kind"] for item in result["missing_checks"]}
    assert missing == {"truthful-runtime#RULE-truthful-001": "budget"}
    assert result["reason"].startswith("required code checks not executed")
    assert "重新运行 task finish" in result["next"]

    _set_finish_budget(root, 300)
    recovered = finish_task(str(root), str(task_dir), str(task_file), "TASK-001")

    assert recovered["decision"] == "pass", recovered.get("reason")
    assert (root / "gate-ran.txt").exists(), "预算恢复后必须真实执行 required check"
    assert _task_status(task_file) == "done"
    assert not (root / ".code-flow/.active-task.json").exists()


def test_truthful_gate_declared_timeout_over_budget_is_not_a_deferral(tmp_path: Path) -> None:
    root, task_dir, task_file = _truthful_gate_repo(tmp_path, timeout=9999, budget=300)

    result = finish_task(str(root), str(task_dir), str(task_file), "TASK-001")

    assert result["decision"] == "pass", result.get("reason")
    assert (root / "gate-ran.txt").exists(), "声明 timeout 超预算但预算未耗尽时必须执行"
    assert result["deferred_budget"] == 0


def test_runtime_metrics_count_live_risks_and_actual_deferred_evidence(tmp_path: Path) -> None:
    from cf_stats import _runtime_usage
    directory = tmp_path / ".code-flow/tasks/demo"
    directory.mkdir(parents=True)
    (tmp_path / ".code-flow/.active-task.json").write_text(json.dumps({"task_dir": str(directory)}))
    save_context(str(directory / "spec-context.yml"), _gate_context({
        "status": "unverified", "error_code": "deferred_to_review",
        "details": {"deferral_kind": "review_stage"},
    }))
    risk = {"owner": "TASK-001", "reason": "limitation", "confirmed_by": "user",
            "confirmed_at": "2026-01-01", "source": "user reply", "expires_at": "2999-01-01"}
    checks = [{"id": "A", "accepted_risk": risk},
              {"id": "B", "accepted_risk": {**risk, "expires_at": "2000-01-01"}}]
    rows = [{"id": "S-01", "owner": "TASK-001", "checks": ["A", "B"],
             "status": "stale", "stale_checks": ["A", "B"]}]
    (directory / ".acceptance-manifest.json").write_text(json.dumps({"checks": checks, "scenarios": rows}))
    metrics = _runtime_usage(str(tmp_path))
    assert metrics["deferred_rules"] == 1
    assert metrics["stale_checks"] == 2
    assert metrics["accepted_risks"] == 1
    assert metrics["recorded_risks"] == 2
    assert metrics["inactive_risks"] == 1


def _gate_context(evidence: dict[str, object]) -> SpecContext:
    code = RuleStageStatus("unverified", (), None, (evidence,))
    review = RuleStageStatus("pending", (), None, ())
    rule = RuleBinding(
        "RULE-truthful-001",
        "required command must execute",
        "r" * 64,
        "required",
        "truthful-runtime#RULE-truthful-001",
        {"code": code, "review": review},
        verifier_stage="code",
    )
    binding = SpecBinding(
        "truthful-runtime",
        "truthful/rules.md",
        SpecHashes("f" * 64, "m" * 64, "s" * 64),
        "path+agent",
        "truthful gate test",
        "required",
        ("design", "plan", "code", "review"),
        (rule,),
    )
    return SpecContext(
        1,
        "truthful",
        "required",
        "2026-10-22T00:00:00+00:00",
        (),
        (binding,),
    )


def test_truthful_gate_deferred_skips_accept_only_review_stage() -> None:
    cases = (
        (
            "review_stage",
            {"status": "unverified", "error_code": "deferred_to_review",
             "details": {"reason": "out_of_task_scope", "deferral_kind": "review_stage"}},
            "pass",
        ),
        (
            "budget",
            {"status": "unverified", "error_code": "verifier_budget_exhausted",
             "details": {"deferral_kind": "budget"}},
            "block",
        ),
        (
            "env",
            {"status": "unverified", "error_code": "env_blocked",
             "details": {"deferral_kind": "env"}},
            "block",
        ),
        (
            "legacy_budget",
            {"status": "unverified", "error_code": "deferred_to_review",
             "details": {"reason": "over_finish_budget"}},
            "block",
        ),
    )
    for label, evidence, expected in cases:
        result = validate_stage(_gate_context(evidence), "code", allow_deferred_skips=True)
        assert result.decision == expected, f"{label}: {result.errors}"


def test_truthful_gate_actual_failure_still_blocks(tmp_path: Path) -> None:
    root, task_dir, task_file = _truthful_gate_repo(
        tmp_path, command=[sys.executable, "-c", "raise SystemExit(1)"]
    )

    result = finish_task(str(root), str(task_dir), str(task_file), "TASK-001")

    assert result["decision"] == "block"
    assert "missing_checks" not in result
    assert _task_status(task_file) == "in-progress", "真实失败不得伪装成 provisional/done"
    assert load_active_task(str(root)).status == "active"
