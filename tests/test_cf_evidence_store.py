#!/usr/bin/env python3
"""[S-05][B-02] Central evidence sidecar and spec-context compaction.

The tests use real git repositories / worktrees and the real acceptance
runner; no store, git or compaction behaviour is mocked.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_manifest import write_manifest  # noqa: E402
from cf_acceptance_runner import run_manifest  # noqa: E402
from cf_evidence_store import (  # noqa: E402
    DEFAULT_HISTORY_LIMIT,
    EvidenceStore,
    compact_context,
    compact_evidence,
    evidence_root,
)
from cf_spec_context import (  # noqa: E402
    ContextSource,
    RuleBinding,
    RuleStageStatus,
    SpecBinding,
    SpecContext,
    save_context,
)
from cf_spec_metadata import SpecHashes  # noqa: E402


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments), cwd=root, text=True, encoding="utf-8", capture_output=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _git_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "evidence@test")
    _git(root, "config", "user.name", "evidence")
    source = root / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")


def _task_document(command: list[str]) -> str:
    encoded = json.dumps(command)
    return (
        "# Demo demand\n\n"
        "## Acceptance Coverage\n\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任任务 | 状态 | 执行命令 | cwd | timeout | depends |\n"
        "|--------|---------|---------|-------------|---------|------|---------|-----|---------|---------|\n"
        f"| S-01 | demo.design.md#2.5 | integration | real runner | TASK-001 | planned | {encoded} | . | 30 | |\n\n"
        "## TASK-001: Demo\n\n"
        "- **Status**: draft\n"
        "- **Spec-Refs**:\n"
        "- **Acceptance-Refs**: S-01\n\n"
        "### Acceptance Contract\n\n"
        "| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |\n"
        "|--------|---------|--------------------|---------|----------------|---------|------|\n"
        f"| S-01 | integration | real runner | runs | `tests/test_demo.py` | {encoded} | planned |\n"
    )


def _locked_manifest(root: Path, task_dir: Path) -> tuple[Path, Path]:
    task = task_dir / "demo.md"
    task.write_text(_task_document([sys.executable, "-c", "pass"]), encoding="utf-8")
    manifest = task_dir / ".acceptance-manifest.json"
    write_manifest(str(task), str(manifest))
    return task, manifest


def _evidence(index: int, total: int, check_id: str) -> dict[str, object]:
    return {
        "verifier_ref": check_id,
        "check_id": check_id,
        "run_id": f"run-{index:03d}",
        "scenario_id": "S-01",
        "status": "passed",
        "exit_code": 0,
        "result_sha256": f"{check_id}-result-{index:03d}",
        "diff_sha256": f"{index:064x}",
        "executed_at": f"2026-10-22T00:{index % 60:02d}:{index % 60:02d}+00:00",
        "details": {"output": ("history-" + str(index) + "-") * 80},
        "command": [sys.executable, "-c", "pass"],
        "cwd": ".",
        "timeout": 30,
        "input_hash": "f" * 64,
        "source": "local",
        "commit": "a" * 40,
    }


def _large_context(check_count: int = 12, history: int = 30) -> SpecContext:
    rules = []
    for check in range(check_count):
        check_id = f"demo-spec#RULE-{check:03d}"
        rules.append(
            RuleBinding(
                ref=f"RULE-{check:03d}",
                summary="Keep evidence bounded while preserving the latest verified state.",
                text_sha256=f"{check:064x}",
                enforcement="required",
                verifier_ref=check_id,
                stage_status={
                    "code": RuleStageStatus(
                        status="verified",
                        refs=(),
                        decision=None,
                        evidence=tuple(_evidence(index, history, check_id) for index in range(history)),
                    )
                },
            )
        )
    binding = SpecBinding(
        spec_id="demo-spec",
        path="demo/rules.md",
        hashes=SpecHashes("a" * 64, "b" * 64, "c" * 64),
        selected_by="test",
        reason="compaction fixture",
        enforcement="required",
        stages=("code",),
        rules=tuple(rules),
    )
    return SpecContext(
        version=1,
        task="demo",
        enforcement="required",
        updated_at="2026-10-22T00:00:00+00:00",
        sources=(ContextSource("cli", "bind"),),
        bindings=(binding,),
    )


def test_s05_relock_compaction_keeps_evidence_across_worktrees_and_bounds_context(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "-b", "side", str(linked))

    task_dir = repo / ".code-flow" / "tasks" / "demo"
    task_dir.mkdir(parents=True)
    _, manifest = _locked_manifest(repo, task_dir)

    first = run_manifest(str(manifest), str(repo), write_evidence=True)
    assert first["decision"] == "pass", first

    store = EvidenceStore(repo, "demo")
    check_id = json.loads(manifest.read_text(encoding="utf-8"))["scenarios"][0]["check"]
    latest = store.read_latest(check_id)
    assert latest is not None
    assert latest["status"] == "passed"
    assert latest["check_id"] == check_id
    assert latest["source"] == "local"
    assert len(latest["commit"]) == 40
    # The sidecar is central: a linked worktree resolves the same git common dir.
    assert EvidenceStore(linked, "demo").read_latest(check_id) == latest
    assert evidence_root(linked, "demo") == evidence_root(repo, "demo")
    assert store.directory == repo / ".git" / "code-flow" / "evidence" / "demo"

    # Re-locking the plan must not erase execution evidence.
    write_manifest(str(task_dir / "demo.md"), str(manifest))
    relocked = json.loads(manifest.read_text(encoding="utf-8"))
    assert relocked["scenarios"][0]["status"] == "verified"
    assert store.read_latest(check_id)["run_id"] == latest["run_id"]

    context = _large_context()
    compacted = compact_context(context, root=repo, requirement="demo", max_history=DEFAULT_HISTORY_LIMIT)
    for binding in compacted.bindings:
        for rule in binding.rules:
            for stage in rule.stage_status.values():
                assert len(stage.evidence) == 1, "each rule keeps only its latest state"
                assert stage.status == "verified"

    compacted_path = task_dir / "compacted-context.yml"
    save_context(str(compacted_path), compacted)
    assert compacted_path.stat().st_size < 100 * 1024, "compacted context must stay below 100 KB"

    history_file = store.history_path("demo-spec#RULE-000", "code")
    history = json.loads(history_file.read_text(encoding="utf-8"))
    previous = {entry["result_sha256"] for entry in history["entries"]}
    assert "demo-spec#RULE-000-result-000" in previous, "old verified evidence is archived, not erased"
    assert len(previous) == 29


def test_s05_compaction_history_is_capped(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    store = EvidenceStore(repo, "demo")
    entries = tuple(_evidence(index, 30, "demo-spec#RULE-001") for index in range(30))

    latest = compact_evidence(
        entries,
        root=repo,
        requirement="demo",
        check_id="demo-spec#RULE-001",
        max_history=5,
    )
    assert len(latest) == 1
    assert latest[0]["result_sha256"].endswith("-029")

    history_file = store.history_path("demo-spec#RULE-001", "code")
    history = json.loads(history_file.read_text(encoding="utf-8"))
    assert len(history["entries"]) == 5, "history sidecar must enforce its upper bound"
    assert history["entries"][-1]["result_sha256"].endswith("-028")


def test_s05_atomic_store_dedupes_run_id_and_roundtrips_export(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    store = EvidenceStore(repo, "demo")
    run = _evidence(0, 1, "CHK-01")

    created = store.write_run("CHK-01", run)
    duplicate = store.write_run("CHK-01", run)
    assert created["status"] == "created"
    assert duplicate["status"] == "duplicate"
    assert len(store.list_runs("CHK-01")) == 1
    assert store.read_latest("CHK-01")["run_id"] == run["run_id"]
    assert not list(store.check_directory("CHK-01").glob(".*.tmp")), "atomic write leaves no temp file"

    exported = tmp_path / "export.json"
    store.export(exported)
    target = EvidenceStore(repo, "imported")
    report = target.import_file(exported)
    assert report["imported"] == 1
    assert target.read_latest("CHK-01")["run_id"] == run["run_id"]

    newer = dict(_evidence(1, 1, "CHK-01"), executed_at="2026-10-23T00:00:00+00:00")
    store.write_run("CHK-01", newer)
    assert store.read_latest("CHK-01")["run_id"] == newer["run_id"]


def test_b02_non_git_fallback_store_and_runner(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    task_dir = root / ".code-flow" / "tasks" / "demo"
    task_dir.mkdir(parents=True)
    assert not (root / ".git").exists()

    store = EvidenceStore(root, "demo")
    assert store.directory == root / ".code-flow" / "evidence" / "demo"

    run = _evidence(0, 1, "CHK-01")
    store.write_run("CHK-01", run)
    assert store.read_latest("CHK-01")["run_id"] == run["run_id"]
    assert store.write_run("CHK-01", run)["status"] == "duplicate"

    _, manifest = _locked_manifest(root, task_dir)
    result = run_manifest(str(manifest), str(root), write_evidence=True)
    assert result["decision"] == "pass", result
    check_id = json.loads(manifest.read_text(encoding="utf-8"))["scenarios"][0]["check"]
    latest = store.read_latest(check_id)
    assert latest is not None and latest["status"] == "passed"
    assert latest["check_id"] == check_id


def test_spec_verifier_evidence_can_be_persisted_as_central_runs(tmp_path: Path) -> None:
    from cf_spec_verify import (
        VerificationEvidence,
        VerificationResult,
        VerificationScope,
        store_verification_evidence,
    )

    repo = tmp_path / "repo"
    _git_repo(repo)
    evidence = VerificationEvidence(
        verifier_ref="demo-spec#RULE-001",
        executed_at="2026-10-22T00:00:00+00:00",
        status="verified",
        rule_text_sha256="a" * 64,
        artifact_sha256=None,
        diff_sha256="b" * 64,
        result_sha256="c" * 64,
        error_code=None,
        details={"argv": [sys.executable, "-c", "pass"], "exit_code": 0},
    )
    scope = VerificationScope(str(repo), (), "b" * 64)
    first = store_verification_evidence(None, scope, VerificationResult((evidence,), True), requirement="demo")
    second = store_verification_evidence(None, scope, VerificationResult((evidence,), True), requirement="demo")
    assert first[0]["status"] == "created"
    assert second[0]["status"] == "duplicate"
    latest = EvidenceStore(repo, "demo").read_latest("demo-spec#RULE-001")
    assert latest is not None
    assert latest["status"] == "passed"
    assert latest["rule_text_sha256"] == "a" * 64


def test_s05_deferral_does_not_clear_previous_verified_state() -> None:
    from cf_task_runtime import _update_rule

    verified = {
        "verifier_ref": "demo-spec#RULE-001",
        "status": "verified",
        "result_sha256": "old-result",
        "diff_sha256": "a" * 64,
        "rule_text_sha256": "b" * 64,
        "executed_at": "2026-10-22T00:00:00+00:00",
    }
    deferred = {
        "verifier_ref": "demo-spec#RULE-001",
        "status": "unverified",
        "result_sha256": "deferred-result",
        "diff_sha256": "a" * 64,
        "rule_text_sha256": "b" * 64,
        "executed_at": "2026-10-22T00:01:00+00:00",
        "error_code": "deferred_to_review",
        "details": {"reason": "out_of_task_scope", "deferred_to_review": True},
    }
    rule = RuleBinding(
        ref="RULE-001",
        summary="verified rule",
        text_sha256="b" * 64,
        enforcement="required",
        verifier_ref="demo-spec#RULE-001",
        stage_status={"code": RuleStageStatus("verified", (), None, (verified,))},
    )
    updated = _update_rule(rule, deferred)
    stage = updated.stage_status["code"]
    assert stage.status == "verified", "deferral must not clear old verified evidence"
    assert list(stage.evidence) == [verified]


def test_s05_stale_verified_evidence_is_downgraded_by_deferral() -> None:
    """A deferral must not preserve verified evidence from a different diff."""
    from cf_task_runtime import _update_rule

    verified = {
        "verifier_ref": "demo-spec#RULE-001",
        "status": "verified",
        "result_sha256": "old-result",
        "diff_sha256": "a" * 64,
        "rule_text_sha256": "b" * 64,
        "executed_at": "2026-10-22T00:00:00+00:00",
    }
    deferred = {
        "verifier_ref": "demo-spec#RULE-001",
        "status": "unverified",
        "result_sha256": "deferred-result",
        "diff_sha256": "c" * 64,
        "rule_text_sha256": "b" * 64,
        "executed_at": "2026-10-22T00:01:00+00:00",
        "error_code": "deferred_to_review",
        "details": {"reason": "out_of_task_scope", "deferred_to_review": True},
    }
    rule = RuleBinding(
        ref="RULE-001",
        summary="verified rule",
        text_sha256="b" * 64,
        enforcement="required",
        verifier_ref="demo-spec#RULE-001",
        stage_status={"code": RuleStageStatus("verified", (), None, (verified,))},
    )
    updated = _update_rule(rule, deferred)
    stage = updated.stage_status["code"]
    assert stage.status == "unverified", "stale verified evidence must not survive a new diff"
    assert stage.evidence[-1]["error_code"] == "deferred_to_review"
