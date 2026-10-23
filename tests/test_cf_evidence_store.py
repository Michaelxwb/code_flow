#!/usr/bin/env python3
"""[S-05][B-02][S-10] Central evidence sidecar, CI import and compaction.

The tests use real git repositories / worktrees, real JUnit/Playwright
reports and the real acceptance runner; no store, git, report or compaction
behaviour is mocked.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src/core/code-flow/scripts"
CI_SCRIPT = SCRIPTS / "cf_evidence_import.py"
CI_RUN_URL = "https://ci.example.com/actions/runs/4242"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_manifest import write_manifest  # noqa: E402
from cf_acceptance_runner import run_manifest  # noqa: E402
from cf_acceptance_schema import verified_evidence  # noqa: E402
from cf_evidence_store import (  # noqa: E402
    DEFAULT_HISTORY_LIMIT,
    EvidenceStore,
    EvidenceStoreError,
    compact_context,
    compact_evidence,
    evidence_root,
)
from cf_exec_base import worktree_fingerprint  # noqa: E402
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


# ---------------------------------------------------------------------------
# [S-10] CI evidence import: real JUnit / Playwright reports, central sidecar.
# ---------------------------------------------------------------------------


def _ci_task_document() -> str:
    """Locked plan with three independent checks and real executable commands."""
    scenarios = (
        ("S-01", "TASK-001", [sys.executable, "-c", "pass"]),
        ("S-02", "TASK-002", [sys.executable, "-c", "raise SystemExit(1)"]),
        ("S-03", "TASK-003", [sys.executable, "-c", "print('e2e')"]),
    )
    coverage = [
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任任务 | 状态 | 执行命令 | cwd | timeout | depends |",
        "|--------|---------|---------|-------------|---------|------|---------|-----|---------|---------|",
    ]
    sections = []
    for scenario_id, owner, argv in scenarios:
        encoded = json.dumps(argv)
        coverage.append(
            f"| {scenario_id} | demo.design.md#2.5 | integration | real report | {owner} | planned | {encoded} | . | 30 | |"
        )
        sections.append(
            f"## {owner}: Demo {scenario_id}\n\n"
            f"- **Status**: draft\n- **Acceptance-Refs**: {scenario_id}\n\n"
            "### Acceptance Contract\n\n"
            "| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |\n"
            "|--------|---------|--------------------|---------|----------------|---------|------|\n"
            f"| {scenario_id} | integration | real report | maps to check | `tests/test_e2e.py` | {encoded} | planned |\n"
        )
    return "# Demo demand\n\n## Acceptance Coverage\n\n" + "\n".join(coverage) + "\n\n" + "\n".join(sections)


@pytest.fixture()
def ci_repo(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    repo = tmp_path / "repo"
    _git_repo(repo)
    task_dir = repo / ".code-flow" / "tasks" / "demo"
    task_dir.mkdir(parents=True)
    task = task_dir / "demo.md"
    task.write_text(_ci_task_document(), encoding="utf-8")
    manifest = task_dir / ".acceptance-manifest.json"
    write_manifest(str(task), str(manifest))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "lock acceptance plan")
    return repo, task, manifest, _git(repo, "rev-parse", "HEAD")


def _run_import(
    repo: Path,
    manifest: Path,
    report: Path,
    *,
    fmt: str = "junit",
    commit: str = "",
    run_url: str = CI_RUN_URL,
    extra: tuple[str, ...] = (),
) -> subprocess.CompletedProcess:
    argv = [
        sys.executable,
        str(CI_SCRIPT),
        "import",
        "--format", fmt,
        "--file", str(report),
        "--commit", commit,
        "--run-url", run_url,
        "--manifest", str(manifest),
        "--root", str(repo),
        "--json",
        *extra,
    ]
    return subprocess.run(argv, text=True, encoding="utf-8", capture_output=True, check=False)


def _rows(manifest: Path) -> dict[str, dict[str, object]]:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return {str(row["id"]): row for row in data["scenarios"]}


def test_s10_ci_import_junit_maps_checks_and_feeds_verify(ci_repo, tmp_path: Path) -> None:
    repo, unused_task, manifest, head = ci_repo
    del unused_task
    report = tmp_path / "junit.xml"
    report.write_text(
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
        "<testsuites name=\"ci\">\n"
        "  <testsuite name=\"pytest\" tests=\"3\" failures=\"1\" errors=\"0\" skipped=\"1\">\n"
        "    <testcase classname=\"tests.e2e.test_checkout\" name=\"test_acceptance[S-01]\"\n"
        "              file=\"tests/e2e/test_checkout.py\" line=\"12\" time=\"0.2\" />\n"
        "    <testcase classname=\"tests.e2e.test_checkout\" name=\"test_acceptance[S-02]\"\n"
        "              file=\"tests/e2e/test_checkout.py\" line=\"31\" time=\"0.3\">\n"
        "      <failure message=\"cart badge missing\">AssertionError: expected 1 badge</failure>\n"
        "    </testcase>\n"
        "    <testcase classname=\"tests.e2e.test_checkout\" name=\"test_acceptance[S-03]\"\n"
        "              file=\"tests/e2e/test_checkout.py\" line=\"48\" time=\"0.0\">\n"
        "      <skipped message=\"browser not available\" />\n"
        "    </testcase>\n"
        "  </testsuite>\n"
        "</testsuites>\n",
        encoding="utf-8",
    )

    completed = _run_import(repo, manifest, report, commit=head)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["source"] == "ci"
    assert payload["decision"] == "block", "one failed and one skipped check must not pass"
    assert payload["commit"] == head
    assert payload["run_url"] == CI_RUN_URL
    assert payload["input_hash"] == worktree_fingerprint(str(repo))
    assert payload["scenarios"] == ["S-01", "S-02", "S-03"]

    rows = _rows(manifest)
    assert rows["S-01"]["status"] == "verified"
    assert rows["S-02"]["status"] == "failed"
    assert rows["S-03"]["status"] == "incomplete", "skipped tests are not passes"
    assert verified_evidence(rows["S-01"]) is True
    assert verified_evidence(rows["S-02"]) is False

    store = EvidenceStore(repo, "demo")
    expected = {"S-01": ("passed", 0), "S-02": ("failed", 1), "S-03": ("incomplete", 1)}
    for scenario_id, (status, exit_code) in expected.items():
        latest = store.read_latest(str(rows[scenario_id]["check"]))
        assert latest is not None
        assert latest["status"] == status
        assert latest["exit_code"] == exit_code
        assert latest["source"] == "ci"
        assert latest["commit"] == head
        assert latest["run_url"] == CI_RUN_URL
        assert latest["input_hash"] == worktree_fingerprint(str(repo))

    # The passing check is consumed by the verify runner without re-execution.
    reused = run_manifest(str(manifest), str(repo), owner="TASK-001")
    assert reused["decision"] == "pass", reused
    assert reused["executed"] == 0
    assert reused["reused"] == 1
    assert reused["results"][0]["cache_reused"] is True


def test_s10_ci_import_playwright_failures_and_commit_mismatch(ci_repo, tmp_path: Path) -> None:
    repo, unused_task, manifest, head = ci_repo
    del unused_task
    report = tmp_path / "playwright.json"
    report.write_text(
        json.dumps(
            {
                "config": {"rootDir": "."},
                "suites": [
                    {
                        "title": "checkout.spec.ts",
                        "file": "e2e/checkout.spec.ts",
                        "specs": [
                            {
                                "title": "S-03 checkout completes",
                                "file": "e2e/checkout.spec.ts",
                                "line": 20,
                                "tests": [
                                    {
                                        "status": "unexpected",
                                        "results": [
                                            {"status": "failed", "duration": 120, "error": {"message": "timeout"}}
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
                "stats": {"expected": 0, "unexpected": 1, "flaky": 0, "skipped": 0},
            }
        ),
        encoding="utf-8",
    )

    imported = _run_import(repo, manifest, report, fmt="playwright", commit=head)
    assert imported.returncode == 0, imported.stderr
    payload = json.loads(imported.stdout)
    assert payload["decision"] == "block"
    assert payload["checks"][0]["check_id"] == _rows(manifest)["S-03"]["check"]
    assert payload["checks"][0]["status"] == "failed"

    rows = _rows(manifest)
    assert rows["S-03"]["status"] == "failed"
    store = EvidenceStore(repo, "demo")
    latest = store.read_latest(str(rows["S-03"]["check"]))
    assert latest is not None
    assert latest["status"] == "failed"
    assert latest["exit_code"] == 1
    assert latest["source"] == "ci"
    assert latest["commit"] == head
    assert latest["run_url"] == CI_RUN_URL

    # A later commit invalidates the CI report: importing it must be refused.
    (repo / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "advance")
    before = len(store.list_runs(str(rows["S-03"]["check"])))
    rejected = _run_import(repo, manifest, report, fmt="playwright", commit=head)
    assert rejected.returncode == 2, rejected.stdout
    error = json.loads(rejected.stdout)
    assert error["error_code"] == "commit_mismatch"
    assert error["field"] == "commit"
    assert len(store.list_runs(str(rows["S-03"]["check"]))) == before


def test_s10_ci_import_rejects_missing_provenance_and_unmapped_cases(ci_repo, tmp_path: Path) -> None:
    repo, unused_task, manifest, head = ci_repo
    del unused_task
    rows = _rows(manifest)
    check_id = str(rows["S-01"]["check"])
    store = EvidenceStore(repo, "demo")
    report = tmp_path / "junit.xml"
    report.write_text(
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
        "<testsuite name=\"pytest\">\n"
        "  <testcase classname=\"tests.e2e.test_checkout\" name=\"test_acceptance[S-01]\" />\n"
        "</testsuite>\n",
        encoding="utf-8",
    )

    missing_url = _run_import(repo, manifest, report, commit=head, run_url="")
    assert missing_url.returncode == 2
    assert json.loads(missing_url.stdout)["error_code"] == "missing_run_url"

    unmapped = tmp_path / "unmapped.xml"
    unmapped.write_text(
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
        "<testsuite name=\"pytest\">\n"
        "  <testcase classname=\"tests.unit.test_misc\" name=\"test_unrelated_behaviour\" />\n"
        "</testsuite>\n",
        encoding="utf-8",
    )
    rejected = _run_import(repo, manifest, unmapped, commit=head)
    assert rejected.returncode == 2
    error = json.loads(rejected.stdout)
    assert error["error_code"] == "unmapped_test_cases"
    assert "test_unrelated_behaviour" in error["message"]

    # The CI job exit code must agree with the report: no optimistic import.
    mismatch = _run_import(repo, manifest, report, commit=head, extra=("--exit-code", "1"))
    assert mismatch.returncode == 2
    assert json.loads(mismatch.stdout)["error_code"] == "exit_code_mismatch"
    assert store.list_runs(check_id) == []

    # The store itself refuses CI runs without provenance, even if called directly.
    with pytest.raises(EvidenceStoreError) as exc:
        store.write_run(
            check_id,
            {
                "run_id": "forged-ci-run",
                "source": "ci",
                "status": "passed",
                "exit_code": 0,
                "input_hash": "a" * 64,
                "run_url": CI_RUN_URL,
            },
        )
    assert exc.value.field == "commit"
    assert store.list_runs(check_id) == []


def test_ci_import_runtime_command_registry_entry() -> None:
    registry = json.loads((SCRIPTS.parent / "runtime-commands.json").read_text(encoding="utf-8"))
    entry = registry["commands"]["evidence import"]
    assert entry["module"] == "cf_evidence_import"
    assert entry["prefix"] == ["import"]
    script = SCRIPTS / f"{entry['module']}.py"
    assert script.is_file()
    # The deployed copy is what `code-flow evidence import` actually runs.
    assert (ROOT / ".code-flow" / "scripts" / script.name).read_bytes() == script.read_bytes()
    help_result = subprocess.run(
        [sys.executable, str(script), "import", "--help"],
        text=True, encoding="utf-8", capture_output=True, check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "--format" in help_result.stdout


def test_legacy_basename_evidence_is_migrated(tmp_path: Path) -> None:
    import subprocess
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    common = Path(subprocess.run(
        ("git", "rev-parse", "--git-common-dir"), cwd=tmp_path, check=True,
        capture_output=True, text=True,
    ).stdout.strip())
    if not common.is_absolute():
        common = tmp_path / common
    legacy = common / "code-flow/evidence/demo/CHK-1"
    legacy.mkdir(parents=True)
    run = {"run_id": "run-1", "check_id": "CHK-1", "status": "passed", "input_hash": "h"}
    (legacy / "run-1.json").write_text(json.dumps(run), encoding="utf-8")
    (legacy / "latest.json").write_text(json.dumps(run), encoding="utf-8")

    store = EvidenceStore(tmp_path, requirement="2026-10-20--demo")

    assert store.migrated_runs == 2
    assert [item["run_id"] for item in store.list_runs("CHK-1")] == ["run-1"]
    assert EvidenceStore(tmp_path, requirement="2026-10-20--demo").migrated_runs == 0


def test_ci_import_uses_per_check_input_hash(ci_repo, tmp_path: Path) -> None:
    repo, _task, manifest, head = ci_repo
    data = json.loads(manifest.read_text(encoding="utf-8"))
    for check in data["checks"]:
        check["inputs"] = ["src/app.py"]
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "scope checks")
    head = _git(repo, "rev-parse", "HEAD")
    report = tmp_path / "junit.xml"
    report.write_text(
        "<testsuites><testsuite name=\"pytest\">"
        "<testcase classname=\"tests.e2e\" name=\"test_acceptance[S-01]\" file=\"tests/e2e.py\" line=\"1\" />"
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    completed = _run_import(repo, manifest, report, commit=head)
    assert completed.returncode == 0, completed.stderr

    from cf_check_inputs import check_input_hash
    from cf_exec_base import worktree_fingerprint
    check = next(item for item in data["checks"] if item["id"] == data["scenarios"][0]["check"])
    fallback = worktree_fingerprint(str(repo), include_untracked=False)
    expected = check_input_hash(str(repo), check, fallback)["input_hash"]
    latest = EvidenceStore(repo, "demo").read_latest(check["id"])
    assert latest is not None
    assert latest["input_hash"] == expected
    assert latest["input_hash"] != fallback


def test_ci_import_does_not_attribute_one_check_to_multi_check_scenario(ci_repo, tmp_path: Path) -> None:
    repo, _task, manifest, _head = ci_repo
    data = json.loads(manifest.read_text(encoding="utf-8"))
    row = data["scenarios"][0]
    row["checks"] = ["CHK-A", "CHK-B"]
    row["check"] = "CHK-C"
    data["checks"][0]["id"] = "CHK-C"
    for check_id in ("CHK-A", "CHK-B"):
        data["checks"].append({
            "id": check_id, "command": data["checks"][0]["command"],
            "cwd": ".", "timeout": 30,
        })
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "multi check plan")
    head = _git(repo, "rev-parse", "HEAD")
    report = tmp_path / "junit.xml"
    report.write_text(
        "<testsuites><testsuite name=\"pytest\">"
        "<testcase classname=\"tests.e2e\" name=\"test_acceptance[CHK-C]\" file=\"tests/e2e.py\" line=\"1\" />"
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    completed = _run_import(repo, manifest, report, commit=head)
    assert completed.returncode != 0
    assert "check_without_scenarios" in completed.stdout


def test_ci_multi_check_rejects_ambiguous_case_and_accepts_explicit_ids(ci_repo, tmp_path: Path) -> None:
    repo, _task, manifest, _head = ci_repo
    data = json.loads(manifest.read_text())
    a_id, b_id = [data["scenarios"][index]["check"] for index in (0, 1)]
    data["scenarios"][0]["checks"] = [a_id, b_id]
    manifest.write_text(json.dumps(data))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "multi check coverage")
    head = _git(repo, "rev-parse", "HEAD")
    report = tmp_path / "report.xml"
    before = manifest.read_bytes()
    report.write_text(f'<testsuite><testcase name="{a_id} {b_id}"/></testsuite>')
    rejected = _run_import(repo, manifest, report, commit=head)
    assert rejected.returncode != 0
    assert "ambiguous_test_case" in rejected.stdout
    assert manifest.read_bytes() == before
    report.write_text(f'<testsuite><testcase name="{a_id}"/><testcase name="{b_id}"/></testsuite>')
    accepted = _run_import(repo, manifest, report, commit=head)
    assert accepted.returncode == 0, accepted.stdout
    assert _rows(manifest)["S-01"]["status"] == "verified"
    assert set(_rows(manifest)["S-01"]["evidence"]["check_hashes"]) == {a_id, b_id}
