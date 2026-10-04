#!/usr/bin/env python3
"""[merge] 并行状态文件确定性并集的纯函数回归测试。

覆盖 cf-task:start 4.4 的合并规则：任务 md 的覆盖状态并集与任务区归属、
spec-context.yml 证据并集与状态优先级、acceptance manifest 的 revision 合并。
"""
import json
import sys
from pathlib import Path

import pytest  # noqa: E402


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_task_merge import (  # noqa: E402
    merge_context_docs,
    merge_context_text,
    merge_manifest_docs,
    merge_manifest_text,
    merge_task_markdown,
)


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


def _evidence(tag: str, status: str = "passed", error_code=None) -> dict:
    return {
        "verifier_ref": "app#RULE-app-001",
        "status": status,
        "result_sha256": f"sha-{tag}",
        "diff_sha256": f"diff-{tag}",
        "error_code": error_code,
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


def test_context_unions_evidence_and_prefers_verified() -> None:
    main = _context("unverified", [_evidence("main", status="failed")])
    branch = _context("verified", [_evidence("branch")])
    merged = merge_context_docs(main, branch)
    stage = _code_stage(merged)
    assert stage["status"] == "verified"
    assert [item["result_sha256"] for item in stage["evidence"]] == ["sha-main", "sha-branch"]


def test_context_keeps_main_verified_when_branch_is_unverified() -> None:
    main = _context("verified", [_evidence("main")])
    branch = _context("unverified", [_evidence("branch", status="failed")])
    stage = _code_stage(merge_context_docs(main, branch))
    assert stage["status"] == "verified"
    assert len(stage["evidence"]) == 2


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


def _scenario(sid: str, status: str, revision: int, runs: list) -> dict:
    return {"id": sid, "status": status, "revision": revision, "runs": runs}


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
