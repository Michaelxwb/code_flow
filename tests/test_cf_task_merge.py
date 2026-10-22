#!/usr/bin/env python3
"""[merge] 并行状态文件确定性并集的回归测试。

覆盖 cf-task:start 4.4 的合并规则：任务 md 的覆盖状态并集与任务区归属、
spec-context.yml 只保留每个 rule 最新状态、acceptance manifest 的 checks 并集 /
冲突 fail-closed / revision 合并，以及 merge 后 input_hash 变化的 stale 降级。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest  # noqa: E402
import yaml  # noqa: E402


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_manifest import write_manifest  # noqa: E402
from cf_acceptance_runner import run_manifest  # noqa: E402
from cf_task_merge import (  # noqa: E402
    MergeConflictError,
    merge_context_docs,
    merge_context_text,
    merge_manifest_docs,
    merge_manifest_text,
    merge_task_markdown,
)
from cf_task_parallel import merge, prepare  # noqa: E402


# --- task markdown -----------------------------------------------------------


def test_task_markdown_takes_branch_owned_section_and_unions_coverage() -> None:
    main = (
        "# demo\n\n## Acceptance Coverage\n\n"
        "| 场景ID | 状态 |\n|--------|------|\n| S-01 | verified |\n\n---\n\n"
        "## TASK-001: A\n\n- **Status**: done\n"
    )
    branch = (
        "# demo\n\n## Acceptance Coverage\n\n"
        "| 场景ID | 状态 |\n|--------|------|\n| S-01 | planned |\n\n---\n\n"
        "## TASK-001: A\n\n- **Status**: draft\n"
    )
    merged = merge_task_markdown(main, branch, "TASK-001")
    assert "| S-01 | verified |" in merged
    assert "## TASK-001: A\n\n- **Status**: draft\n" in merged
    assert "<<<<<<<" not in merged and ">>>>>>>" not in merged


def test_task_markdown_keeps_main_owned_sections_and_appends_new_rows() -> None:
    main = (
        "# demo\n\n## Acceptance Coverage\n\n"
        "| 场景ID | 状态 |\n|--------|------|\n| S-01 | planned |\n\n---\n\n"
        "## TASK-001: A\n\n- **Status**: done\n\n---\n\n"
        "## TASK-002: B\n\n- **Status**: draft\n"
    )
    branch = (
        "# demo\n\n## Acceptance Coverage\n\n"
        "| 场景ID | 状态 |\n|--------|------|\n"
        "| S-01 | verified |\n| S-02 | verified |\n\n---\n\n"
        "## TASK-001: A\n\n- **Status**: draft\n\n---\n\n"
        "## TASK-002: B\n\n- **Status**: done\n"
    )
    merged = merge_task_markdown(main, branch, "TASK-002")
    assert "| S-01 | verified |" in merged
    assert "| S-02 | verified |" in merged
    assert "## TASK-001: A\n\n- **Status**: done\n" in merged
    assert "## TASK-002: B\n\n- **Status**: done\n" in merged
    # 结构保持：每个标题仍独占一行，文件以换行结尾
    assert merged.endswith("\n")
    assert "---\n\n## TASK-002" in merged


def test_task_markdown_prefers_higher_status_when_both_verified() -> None:
    main = (
        "## Acceptance Coverage\n\n| 场景ID | 状态 |\n|--------|------|\n"
        "| S-01 | e2e_deferred |\n"
    )
    branch = (
        "## Acceptance Coverage\n\n| 场景ID | 状态 |\n|--------|------|\n"
        "| S-01 | verified |\n"
    )
    merged = merge_task_markdown(main, branch, "TASK-001")
    assert "| S-01 | verified |" in merged


# --- spec-context.yml --------------------------------------------------------


def _stage(status: str, evidence: list, decision=None) -> dict:
    return {"status": status, "refs": [], "decision": decision, "evidence": evidence}


def _evidence(tag: str, status: str = "passed", error_code=None,
              executed_at: str = "2026-10-04T00:00:00+00:00") -> dict:
    return {
        "verifier_ref": "app#RULE-app-001",
        "status": status,
        "result_sha256": f"sha-{tag}",
        "diff_sha256": f"diff-{tag}",
        "error_code": error_code,
        "executed_at": executed_at,
    }


def _context(rule_status: str, evidence: list, decision=None) -> dict:
    return {
        "version": 1,
        "task": "demo",
        "enforcement": "required",
        "updated_at": "2026-10-04T00:00:00+00:00",
        "sources": [{"type": "cli", "ref": "bind"}],
        "bindings": [{
            "spec_id": "app",
            "path": "app/rules.md",
            "status": "active",
            "hashes": {"file_sha256": "f", "metadata_sha256": "m", "rules_sha256": "r"},
            "selected_by": "plan",
            "reason": "demo",
            "enforcement": "required",
            "stages": ["code"],
            "rules": [{
                "ref": "RULE-app-001",
                "summary": "demo rule",
                "text_sha256": "t",
                "enforcement": "required",
                "verifier_ref": "app#RULE-app-001",
                "stage_status": {"code": _stage(rule_status, evidence, decision)},
            }],
        }],
    }


def _code_stage(context: dict) -> dict:
    return context["bindings"][0]["rules"][0]["stage_status"]["code"]


def test_context_keeps_latest_status_without_unioning_evidence() -> None:
    main = _context("verified", [_evidence("main", executed_at="2026-10-04T00:00:00+00:00")])
    branch = _context(
        "unverified", [_evidence("branch", status="failed", executed_at="2026-10-05T00:00:00+00:00")]
    )
    stage = _code_stage(merge_context_docs(main, branch))
    assert stage["status"] == "unverified"
    assert [item["result_sha256"] for item in stage["evidence"]] == ["sha-branch"]


def test_context_keeps_newer_verified_state_with_single_evidence() -> None:
    main = _context("verified", [_evidence("main", executed_at="2026-10-06T00:00:00+00:00")])
    branch = _context(
        "unverified", [_evidence("branch", status="failed", executed_at="2026-10-05T00:00:00+00:00")]
    )
    stage = _code_stage(merge_context_docs(main, branch))
    assert stage["status"] == "verified"
    assert [item["result_sha256"] for item in stage["evidence"]] == ["sha-main"]


def test_context_input_hash_change_downgrades_verified_to_stale() -> None:
    main = _context("verified", [_evidence("main")])
    branch = _context("unverified", [_evidence("branch", status="failed")])
    merged = merge_context_docs(main, branch, input_hash="new-input-hash")
    stage = _code_stage(merged)
    assert stage["status"] == "stale"
    assert stage["evidence"], "stale must retain the old proof for audit"
    assert stage["evidence"][-1]["result_sha256"] == "sha-main"


def test_context_matching_input_hash_keeps_verified() -> None:
    main = _context("verified", [_evidence("main")])
    merged = merge_context_docs(main, main, input_hash="diff-main")
    assert _code_stage(merged)["status"] == "verified"


def test_context_one_sided_rule_keeps_latest_evidence_and_goes_stale() -> None:
    branch = _context("verified", [
        _evidence("old", executed_at="2026-10-04T00:00:00+00:00"),
        _evidence("new", executed_at="2026-10-05T00:00:00+00:00"),
    ])
    merged = merge_context_docs({}, branch, input_hash="changed")
    stage = _code_stage(merged)
    assert stage["status"] == "stale"
    assert [item["result_sha256"] for item in stage["evidence"]] == ["sha-new"]


def test_context_decision_prefers_non_null_and_dedupes_sources() -> None:
    main = _context("pending", [], decision=None)
    branch = _context("waived", [], decision="用户豁免")
    merged = merge_context_docs(main, branch)
    assert _code_stage(merged)["decision"] == "用户豁免"
    assert _code_stage(merged)["status"] == "waived"
    assert merged["sources"] == [{"type": "cli", "ref": "bind"}]


def test_context_text_roundtrip_and_parse_error() -> None:
    text = merge_context_text(
        "version: 1\ntask: demo\nupdated_at: '2026-10-04T00:00:00+00:00'\nbindings: []\n",
        "version: 1\ntask: demo\nupdated_at: '2026-10-05T00:00:00+00:00'\nbindings: []\n",
    )
    assert "updated_at: '2026-10-05T00:00:00+00:00'" in text
    with pytest.raises(ValueError):
        merge_context_text("{", "{}")


# --- .acceptance-manifest.json ----------------------------------------------


def _scenario(sid: str, status: str, revision: int, runs: list, check: str = "") -> dict:
    row = {"id": sid, "status": status, "revision": revision, "runs": runs}
    if check:
        row["check"] = check
    return row


def _check(check_id: str, command: list[str], **overrides) -> dict:
    row = {
        "id": check_id,
        "command": command,
        "cwd": ".",
        "timeout": 60,
        "env": "none",
        "inputs": [],
    }
    row.update(overrides)
    return row


def test_manifest_unions_checks_by_id() -> None:
    main = {"schema": 3, "checks": [_check("CHK-01", ["pytest", "-q"])], "scenarios": []}
    branch = {
        "schema": 3,
        "checks": [_check("CHK-02", ["pytest", "-q", "e2e"])],
        "scenarios": [],
    }
    merged = merge_manifest_docs(main, branch)
    assert [item["id"] for item in merged["checks"]] == ["CHK-01", "CHK-02"]
    assert merged["schema"] == 3


def test_check_conflict_fails_closed_and_lists_check_and_fields() -> None:
    main = {
        "schema": 3,
        "checks": [_check("CHK-01", ["pytest", "-q"], inputs=["src/**"])],
        "scenarios": [],
    }
    branch = {
        "schema": 3,
        "checks": [_check("CHK-01", ["pytest", "-x"], env="browser", inputs=["e2e/**"])],
        "scenarios": [],
    }
    with pytest.raises(MergeConflictError) as info:
        merge_manifest_docs(main, branch)
    assert info.value.code == "check_conflict"
    conflict = info.value.conflicts[0]
    assert conflict["check_id"] == "CHK-01"
    assert set(conflict["fields"]) == {"command", "env", "inputs"}
    assert "CHK-01" in str(info.value) and "command" in str(info.value)


def test_check_same_identity_defaults_are_not_a_conflict() -> None:
    main = {"checks": [_check("CHK-01", ["pytest"], timeout=60)], "scenarios": []}
    branch = {"checks": [_check("CHK-01", ["pytest"], timeout=60.0, cwd=".")], "scenarios": []}
    merged = merge_manifest_docs(main, branch)
    assert len(merged["checks"]) == 1


def test_scenario_check_mapping_conflict_fails_closed() -> None:
    main = {
        "schema": 3,
        "checks": [_check("CHK-01", ["pytest"]), _check("CHK-02", ["pytest", "e2e"])],
        "scenarios": [_scenario("S-01", "planned", 0, [], check="CHK-01")],
    }
    branch = {
        "schema": 3,
        "checks": [_check("CHK-01", ["pytest"]), _check("CHK-02", ["pytest", "e2e"])],
        "scenarios": [_scenario("S-01", "planned", 0, [], check="CHK-02")],
    }
    with pytest.raises(MergeConflictError) as info:
        merge_manifest_docs(main, branch)
    assert info.value.code == "scenario_check_conflict"
    assert info.value.conflicts[0]["scenario_id"] == "S-01"


def test_manifest_prefers_verified_and_unions_runs() -> None:
    main = {
        "schema": 2,
        "scenarios": [
            _scenario("S-01", "verified", 2, [{"run_id": "r1", "revision": 2}]),
            _scenario("S-02", "planned", 0, []),
        ],
    }
    branch = {
        "schema": 2,
        "scenarios": [
            _scenario("S-01", "planned", 0, []),
            _scenario("S-02", "planned", 1, [{"run_id": "r2", "revision": 1}]),
        ],
    }
    merged = merge_manifest_docs(main, branch)
    rows = {row["id"]: row for row in merged["scenarios"]}
    assert rows["S-01"]["status"] == "verified"
    assert rows["S-02"]["revision"] == 1
    assert rows["S-02"]["runs"] == [{"run_id": "r2", "revision": 1}]


def test_manifest_verified_beats_higher_revision() -> None:
    main = _scenario("S-01", "verified", 1, [{"run_id": "r1", "revision": 1}])
    branch = _scenario("S-01", "unverified", 3, [{"run_id": "r2", "revision": 3}])
    merged = merge_manifest_docs({"scenarios": [main]}, {"scenarios": [branch]})
    row = merged["scenarios"][0]
    assert row["status"] == "verified"
    assert [item["run_id"] for item in row["runs"]] == ["r1", "r2"]


def test_manifest_text_roundtrip_and_parse_error() -> None:
    text = merge_manifest_text(
        json.dumps({"schema": 2, "scenarios": [_scenario("S-01", "planned", 0, [])]}),
        json.dumps({"schema": 2, "scenarios": [_scenario("S-01", "verified", 1, [])]}),
    )
    assert text.endswith("\n")
    assert json.loads(text)["scenarios"][0]["status"] == "verified"
    with pytest.raises(ValueError):
        merge_manifest_text("[1]", "{}")
    with pytest.raises(MergeConflictError):
        merge_manifest_text(
            json.dumps({"checks": [_check("CHK-01", ["pytest"])], "scenarios": []}),
            json.dumps({"checks": [_check("CHK-01", ["pytest", "-x"])], "scenarios": []}),
        )


# --- real worktree merge acceptance (E-02 / E-05) ----------------------------

_REPO_TASK_FILE = ".code-flow/tasks/2026-10-22/demo/demo.md"

_REPO_TASK_BODY = """# merge demo

## Acceptance Coverage

| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |
|--------|---------|---------|-------------|---------|------|---------|
| S-01 | demo.design.md#2.5 | integration | real runner | TASK-001 | planned | ["python3", "-c", "print('ok')"] |
| S-02 | demo.design.md#2.5 | integration | real runner | TASK-002 | planned | ["python3", "-c", "print('ok')"] |

---

## TASK-001: A

- **Status**: draft
- **Depends**:
- **Acceptance-Refs**: S-01

### Log
- [2026-10-22] created (draft)

---

## TASK-002: B

- **Status**: draft
- **Depends**:
- **Acceptance-Refs**: S-02

### Log
- [2026-10-22] created (draft)
"""

_REPO_GITIGNORE = """.active-task.json
.active-task.lock
.debug.log
specs/_session/
worktrees/
"""


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", *arguments), cwd=str(root), text=True, encoding="utf-8",
        capture_output=True, check=False,
    )
    assert result.returncode == 0, f"git {' '.join(arguments)}: {result.stderr}"
    return result.stdout


def _merge_repo(tmp_path: Path) -> Path:
    root = tmp_path / "merge-proj"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "cf@test")
    _git(root, "config", "user.name", "cf-test")
    (root / ".code-flow").mkdir()
    (root / ".code-flow/.gitignore").write_text(_REPO_GITIGNORE, encoding="utf-8")
    task_path = root / _REPO_TASK_FILE
    task_path.parent.mkdir(parents=True)
    task_path.write_text(_REPO_TASK_BODY, encoding="utf-8")
    write_manifest(str(task_path), str(task_path.parent / ".acceptance-manifest.json"))
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init merge repo")
    return root


def _set_status(worktree: Path, task: str, status: str) -> None:
    path = worktree / _REPO_TASK_FILE
    text = path.read_text(encoding="utf-8")
    index = text.index(f"## {task}:")
    head, tail = text[:index], text[index:]
    tail = tail.replace("- **Status**: draft", f"- **Status**: {status}", 1)
    path.write_text(head + tail, encoding="utf-8")


def _manifest_path(root: Path) -> Path:
    return root / Path(_REPO_TASK_FILE).parent / ".acceptance-manifest.json"


def _commit(worktree: Path, message: str) -> None:
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-q", "-m", message)


def _context_body(status: str = "verified", diff_sha256: str = "old-diff") -> str:
    return yaml.safe_dump({
        "version": 1,
        "task": "demo",
        "enforcement": "required",
        "updated_at": "2026-10-22T00:00:00+00:00",
        "sources": [{"type": "cli", "ref": "bind"}],
        "bindings": [{
            "spec_id": "app",
            "path": "app/rules.md",
            "status": "active",
            "hashes": {"file_sha256": "f", "metadata_sha256": "m", "rules_sha256": "r"},
            "selected_by": "plan",
            "reason": "demo",
            "enforcement": "required",
            "stages": ["code"],
            "rules": [{
                "ref": "RULE-app-001",
                "summary": "demo rule",
                "text_sha256": "t",
                "enforcement": "required",
                "verifier_ref": "app#RULE-app-001",
                "stage_status": {
                    "code": {
                        "status": status,
                        "refs": [],
                        "decision": None,
                        "evidence": [{
                            "verifier_ref": "app#RULE-app-001",
                            "executed_at": "2026-10-22T00:00:00+00:00",
                            "status": "passed",
                            "rule_text_sha256": "t",
                            "artifact_sha256": None,
                            "diff_sha256": diff_sha256,
                            "result_sha256": "result-old",
                            "error_code": None,
                            "details": {},
                        }],
                    },
                },
            }],
        }],
    }, sort_keys=False, allow_unicode=True)


def test_check_conflict_blocks_real_merge_and_lists_check_and_field(tmp_path: Path) -> None:
    """E-02: 两个 worktree 修改同一 check command，merge fail closed 并报字段。"""
    root = _merge_repo(tmp_path)
    prepared = prepare(root, _REPO_TASK_FILE, ["TASK-001", "TASK-002"], "run-check")
    assert prepared["ok"] is True
    commands = {"TASK-001": ["pytest", "-q"], "TASK-002": ["pytest", "-x"]}
    for item in prepared["worktrees"]:
        task = item["task"]
        worktree = Path(item["path"])
        manifest = json.loads(_manifest_path(worktree).read_text(encoding="utf-8"))
        manifest["checks"][0]["id"] = "CHK-01"
        manifest["checks"][0]["command"] = commands[task]
        for row in manifest["scenarios"]:
            row["check"] = "CHK-01"
        _manifest_path(worktree).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _set_status(worktree, task, "done")
        _commit(worktree, f"cf-task({task}): change check command")

    result = merge(root, "run-check", None)

    assert result["ok"] is False
    failed = result["results"][-1]
    assert failed["code"] == "check_conflict"
    assert "CHK-01" in failed["message"] and "command" in failed["message"]
    conflict = failed["conflicts"][0]
    assert conflict["check_id"] == "CHK-01"
    assert "command" in conflict["fields"]
    # 保留现场：失败分支的 worktree 仍可排查
    assert (root / ".code-flow/worktrees/run-check" / failed["task"]).is_dir()


def test_stale_after_merge_downgrades_verified_and_changed_reruns(tmp_path: Path) -> None:
    """E-05: merge 后 input_hash 变化，旧 verified 降 stale；changed 重跑受影响 check。"""
    root = _merge_repo(tmp_path)
    manifest_path = _manifest_path(root)
    first = run_manifest(str(manifest_path), str(root), write_evidence=True, owner="TASK-001")
    assert first["decision"] == "pass", first
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "baseline verified")
    cached = run_manifest(str(manifest_path), str(root), owner="TASK-001")
    assert cached["results"][0].get("cache_reused") is True

    prepared = prepare(root, _REPO_TASK_FILE, ["TASK-001"], "run-stale")
    assert prepared["ok"] is True
    worktree = Path(prepared["worktrees"][0]["path"])
    (worktree / "impl-TASK-001.txt").write_text("merged code\n", encoding="utf-8")
    (worktree / Path(_REPO_TASK_FILE).parent / "spec-context.yml").write_text(
        _context_body(), encoding="utf-8"
    )
    _set_status(worktree, "TASK-001", "done")
    _commit(worktree, "cf-task(TASK-001): verified context")

    result = merge(root, "run-stale", None)
    assert result["ok"] is True, result

    context_path = root / Path(_REPO_TASK_FILE).parent / "spec-context.yml"
    context = yaml.safe_load(context_path.read_text(encoding="utf-8"))
    stage = context["bindings"][0]["rules"][0]["stage_status"]["code"]
    assert stage["status"] == "stale"
    assert stage["evidence"][0]["result_sha256"] == "result-old"

    rerun = run_manifest(str(manifest_path), str(root), owner="TASK-001")
    assert rerun["decision"] == "pass", rerun
    assert rerun["results"][0].get("cache_reused") is not True
    assert rerun["results"][0]["exit_code"] == 0
