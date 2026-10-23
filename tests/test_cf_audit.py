#!/usr/bin/env python3
"""[TASK-015] 只读审计：不变量、数据推导计数、owner 字段与自指场景拆分。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_manifest import write_manifest  # noqa: E402
from cf_audit import build_audit, render_markdown  # noqa: E402
from cf_evidence_store import EvidenceStore  # noqa: E402


DESIGN = """# Demo design

## 2. 需求分析

### 2.5 验收条件

#### 2.5.1 业务规则与约束

| ID | 类型 | 描述 | 验证场景 |
|----|------|------|---------|
| RULE-01 | 系统约束 | verified 必须有完整执行证据 | S-01 |
| RULE-02 | 系统约束 | 场景必须绑定可执行 check | S-01, E-01 |

#### 2.5.2 功能验收场景

**正常场景**

| 场景ID | 功能ID | 优先级 | 测试层级 | 执行方式(exec) | 环境(env) | 输入(inputs) | 关键真实边界 | 前置条件 | 操作步骤 | 预期结果 |
|--------|--------|--------|---------|----------------|-----------|--------------|-------------|---------|---------|---------|
| S-01 | FEAT-01 | P0 | integration | auto | none | tests/a.py | runner | | run | pass |

**异常场景**

| 场景ID | 功能ID | 测试层级 | 执行方式(exec) | 环境(env) | 输入(inputs) | 关键真实边界 | 触发条件 | 系统行为 | 用户感知 |
|--------|--------|---------|----------------|-----------|--------------|-------------|---------|---------|---------|
| E-01 | FEAT-01 | integration | aspirational | none | - | external | trigger | blocked | visible |

## 5. 风险与依赖

| 风险 | 等级 | 应对 |
|------|------|------|
| demo risk | 高 | keep it visible |
"""

DESIGN_ADDED = DESIGN.replace(
    "| RULE-02 | 系统约束 | 场景必须绑定可执行 check | S-01, E-01 |",
    "| RULE-03 | 系统约束 | 新增规则计数自动变化 | S-02 |\n"
    "| RULE-02 | 系统约束 | 场景必须绑定可执行 check | S-01, E-01 |",
).replace(
    "| S-01 | FEAT-01 | P0 | integration | auto | none | tests/a.py | runner | | run | pass |",
    "| S-01 | FEAT-01 | P0 | integration | auto | none | tests/a.py | runner | | run | pass |\n"
    "| S-02 | FEAT-01 | P1 | integration | auto | none | - | runner | | run | pass |",
).replace(
    "| demo risk | 高 | keep it visible |",
    "| extra risk | 中 | keep it visible |\n| demo risk | 高 | keep it visible |",
)

TASK = """# Tasks

## Acceptance Coverage

| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 | 优先级 | 执行方式 | 环境 | 输入 |
|--------|---------|---------|-------------|---------|------|---------|--------|---------|------|------|
| S-01 | demo.design.md#2.5 验收条件 | integration | runner | TASK-001 | planned | ["python3", "-c", "pass"] | P0 | auto | none | tests/a.py |
| E-01 | demo.design.md#2.5 验收条件 | integration | external | TASK-001 | planned | - | P1 | aspirational | none | - |

## TASK-001: Demo

- **Status**: in-progress
- **Acceptance-Refs**: S-01, E-01
"""

TASK_ADDED = TASK.replace(
    "| E-01 | demo.design.md#2.5 验收条件 | integration | external | TASK-001 | planned | - | P1 | aspirational | none | - |",
    "| S-02 | demo.design.md#2.5 验收条件 | integration | runner | TASK-001 | planned | "
    '["python3", "-c", "pass"] | P1 | auto | none | - |\n'
    "| E-01 | demo.design.md#2.5 验收条件 | integration | external | TASK-001 | planned | - | P1 | aspirational | none | - |",
)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    task_dir = tmp_path / "demo"
    task_dir.mkdir()
    (tmp_path / ".code-flow").mkdir()
    design = task_dir / "demo.design.md"
    task = task_dir / "demo.md"
    manifest = task_dir / ".acceptance-manifest.json"
    design.write_text(DESIGN, encoding="utf-8")
    task.write_text(TASK, encoding="utf-8")
    write_manifest(str(task), str(manifest))
    return design, task, manifest


def _audit(tmp_path: Path, design: Path, manifest: Path) -> dict[str, object]:
    return build_audit(str(design), str(manifest), root=str(tmp_path))


def _load(manifest: Path) -> dict[str, object]:
    return json.loads(manifest.read_text(encoding="utf-8"))


def _save(manifest: Path, data: dict[str, object]) -> None:
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _scenario(data: dict[str, object], scenario_id: str) -> dict[str, object]:
    return next(item for item in data["scenarios"] if item["id"] == scenario_id)


def _mark_verified(manifest: Path, scenario_id: str, evidence: dict[str, object]) -> str:
    data = _load(manifest)
    row = _scenario(data, scenario_id)
    row["status"] = "verified"
    row["evidence"] = evidence
    _save(manifest, data)
    return str(row["check"])


def _run(check_id: str, run_id: str, exit_code: int, input_hash: str = "hash-1",
         executed_at: str = "2026-10-22T00:00:00+00:00") -> dict[str, object]:
    return {
        "run_id": run_id,
        "check_id": check_id,
        "input_hash": input_hash,
        "exit_code": exit_code,
        "status": "passed" if exit_code == 0 else "failed",
        "executed_at": executed_at,
    }


def _codes(report: dict[str, object]) -> set[tuple[str, str]]:
    return {
        (str(item.get("scenario_id", "")), str(item.get("code", "")))
        for item in report.get("findings") or ()
    }


def test_invariants_counts_follow_design_and_manifest_data(tmp_path: Path) -> None:
    design, task, manifest = _fixture(tmp_path)
    report = _audit(tmp_path, design, manifest)

    assert report["decision"] == "pass", report["findings"]
    assert report["summary"]["design_scenarios"] == 2
    assert report["summary"]["manifest_scenarios"] == 2
    assert report["summary"]["rules"] == 2
    assert report["summary"]["risks"] == 1

    design.write_text(DESIGN_ADDED, encoding="utf-8")
    task.write_text(TASK_ADDED, encoding="utf-8")
    write_manifest(str(task), str(manifest))
    expanded = _audit(tmp_path, design, manifest)
    assert expanded["summary"]["design_scenarios"] == 3
    assert expanded["summary"]["manifest_scenarios"] == 3
    assert expanded["summary"]["rules"] == 3
    assert expanded["summary"]["risks"] == 2

    design.write_text(DESIGN, encoding="utf-8")
    task.write_text(TASK, encoding="utf-8")
    write_manifest(str(task), str(manifest))
    removed = _audit(tmp_path, design, manifest)
    assert removed["summary"]["design_scenarios"] == 2
    assert removed["summary"]["manifest_scenarios"] == 2
    assert removed["summary"]["rules"] == 2
    assert removed["summary"]["risks"] == 1


def test_invariants_verified_requires_run_id_exit_zero_and_input_hash(tmp_path: Path) -> None:
    design, _, manifest = _fixture(tmp_path)
    check = _mark_verified(
        manifest, "S-01",
        {"status": "passed", "run_id": "run-1", "exit_code": 0, "fingerprint": "hash-1"},
    )
    store = EvidenceStore(tmp_path, "demo")
    store.write_run(check, _run(check, "bad-exit", 1))
    failed = _audit(tmp_path, design, manifest)
    finding = next(
        item for item in failed["findings"]
        if item["code"] == "verified_evidence_incomplete" and item["scenario_id"] == "S-01"
    )
    assert "exit_code" in finding["fields"]
    assert finding["rule_ref"] == "RULE-01"

    store.write_run(check, _run(check, "missing-hash", 0, input_hash="",
                                executed_at="2026-10-22T00:00:01+00:00"))
    missing = _audit(tmp_path, design, manifest)
    finding = next(
        item for item in missing["findings"]
        if item["code"] == "verified_evidence_incomplete" and item["scenario_id"] == "S-01"
    )
    assert "input_hash" in finding["fields"]

    store.write_run(check, _run(check, "good", 0, input_hash="hash-1",
                                executed_at="2026-10-22T00:00:02+00:00"))
    passed = _audit(tmp_path, design, manifest)
    assert passed["decision"] == "pass", passed["findings"]


def test_invariants_verified_falls_back_to_manifest_evidence(tmp_path: Path) -> None:
    design, _, manifest = _fixture(tmp_path)
    _mark_verified(manifest, "S-01", {"status": "passed", "exit_code": 0, "fingerprint": "hash-1"})

    report = _audit(tmp_path, design, manifest)

    finding = next(
        item for item in report["findings"]
        if item["code"] == "verified_evidence_incomplete" and item["scenario_id"] == "S-01"
    )
    assert finding["source"] == "manifest"
    assert finding["fields"] == ["run_id"]


def test_invariants_owner_is_read_from_manifest_field_not_prose(tmp_path: Path) -> None:
    design, task, manifest = _fixture(tmp_path)
    data = _load(manifest)
    _scenario(data, "S-01")["owner"] = "TASK-001"
    _scenario(data, "E-01")["owner"] = ""
    _save(manifest, data)
    task.write_text(
        TASK.replace("## TASK-001: Demo", "## TASK-999: Decoy\n\n- **Acceptance-Refs**: S-01\n\n## TASK-001: Demo"),
        encoding="utf-8",
    )

    report = _audit(tmp_path, design, manifest)

    assert report["summary"]["owners"] == {"TASK-001": 1}
    assert next(item for item in report["scenarios"] if item["id"] == "S-01")["owner"] == "TASK-001"
    assert ("E-01", "owner_missing") in _codes(report)
    assert all("TASK-999" not in str(item.get("message", "")) for item in report["findings"])

    data = _load(manifest)
    _scenario(data, "E-01")["owner"] = "TASK-001, TASK-002"
    _save(manifest, data)
    ambiguous = _audit(tmp_path, design, manifest)
    assert ("E-01", "owner_not_unique") in _codes(ambiguous)


def test_invariants_design_and_manifest_scenario_sets_must_match(tmp_path: Path) -> None:
    design, task, manifest = _fixture(tmp_path)
    task.write_text(TASK_ADDED, encoding="utf-8")
    write_manifest(str(task), str(manifest))
    extra = _audit(tmp_path, design, manifest)
    assert ("S-02", "manifest_scenario_missing_in_design") in _codes(extra)

    task.write_text(TASK, encoding="utf-8")
    write_manifest(str(task), str(manifest))
    design.write_text(DESIGN_ADDED, encoding="utf-8")
    missing = _audit(tmp_path, design, manifest)
    assert ("S-02", "design_scenario_missing_in_manifest") in _codes(missing)


def test_invariants_audit_is_read_only_on_fixture_and_real_requirement(tmp_path: Path) -> None:
    design, _, manifest = _fixture(tmp_path)
    before = (design.read_bytes(), manifest.read_bytes())
    first = _audit(tmp_path, design, manifest)
    second = _audit(tmp_path, design, manifest)
    assert (design.read_bytes(), manifest.read_bytes()) == before
    assert first == second
    assert first["read_only"] is True

    requirement = ROOT / ".code-flow/tasks/2026-10-22/code-flow-0.8-optimization"
    real_design = requirement / "code-flow-0.8-optimization.design.md"
    real_manifest = requirement / ".acceptance-manifest.json"
    real_before = real_manifest.read_bytes()
    real = build_audit(str(real_design), str(real_manifest), root=str(ROOT))
    assert real_manifest.read_bytes() == real_before
    assert real["decision"] == "pass", real["findings"]
    assert real["read_only"] is True
    assert real["summary"]["design_scenarios"] == 20
    assert real["summary"]["manifest_scenarios"] == 20
    assert real["summary"]["rules"] == 10
    assert real["summary"]["risks"] == 7
    s09 = next(item for item in real["scenarios"] if item["id"] == "S-09")
    assert s09["owner"] == "TASK-015"
    assert s09["check"].startswith("CHK-")


def test_invariants_cli_emits_json_and_markdown(tmp_path: Path) -> None:
    design, _, manifest = _fixture(tmp_path)
    task_dir = manifest.parent
    command = [sys.executable, str(SCRIPTS / "cf_audit.py"),
               "--task-dir", str(task_dir), "--root", str(tmp_path), "--json"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["decision"] == "pass"
    assert data["read_only"] is True
    assert data["summary"]["design_scenarios"] == 2

    markdown = subprocess.run(command[:-1], capture_output=True, text=True, check=False)
    assert markdown.returncode == 0, markdown.stderr
    assert "code-flow audit" in markdown.stdout
    assert "Read-only" in markdown.stdout
    assert render_markdown(data).startswith("# code-flow audit")

    _mark_verified(manifest, "S-01", {"status": "passed", "exit_code": 0, "fingerprint": "hash-1"})
    blocked = subprocess.run(command, capture_output=True, text=True, check=False)
    assert blocked.returncode == 3
    assert json.loads(blocked.stdout)["decision"] == "block"


def test_scenario_source_three_way() -> None:
    from cf_scenarios import audit_scenario_source
    report = audit_scenario_source(
        [{"id": "S-01"}], [{"scenario_id": "S-01", "owner": "TASK-001"}], ["S-01"]
    )
    assert report["ok"] is True


def test_unknown_scenario_reported() -> None:
    from cf_scenarios import audit_scenario_source
    report = audit_scenario_source(
        [{"id": "S-01"}], [{"scenario_id": "S-99", "owner": "TASK-001"}]
    )
    assert report["ok"] is False
    assert "S-99" in report["unknown"]


def test_multiple_design_docs_merge_by_global_scenario_id(tmp_path: Path) -> None:
    task_dir = tmp_path / "demo"
    task_dir.mkdir()
    frontend = task_dir / "demo.frontend.design.md"
    backend = task_dir / "demo.backend.design.md"
    task = task_dir / "demo.md"
    manifest = task_dir / ".acceptance-manifest.json"

    frontend.write_text(
        "## 2.5 验收条件\n\n### 2.5.1 业务规则与约束\n"
        "| ID | 描述 | 验证场景 |\n|---|---|---|\n| RULE-01 | fe | S-01 |\n\n"
        "#### 2.5.2 功能验收场景\n"
        "| 场景ID | 测试层级 | 关键真实边界 |\n|---|---|---|\n"
        "| S-01 | integration | frontend |\n\n"
        "## 5. 风险与依赖\n| 风险 | 等级 |\n|---|---|\n| fe risk | 中 |\n",
        encoding="utf-8",
    )
    backend.write_text(
        "## 2.5 验收条件\n\n### 2.5.1 业务规则与约束\n"
        "| ID | 描述 | 验证场景 |\n|---|---|---|\n| RULE-02 | be | S-02 |\n\n"
        "#### 2.5.2 功能验收场景\n"
        "| 场景ID | 测试层级 | 关键真实边界 |\n|---|---|---|\n"
        "| S-02 | integration | backend |\n\n"
        "## 5. 风险与依赖\n| 风险 | 等级 |\n|---|---|\n| be risk | 高 |\n",
        encoding="utf-8",
    )
    task.write_text(
        "# Tasks\n\n## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|---|---|---|---|---|---|---|\n"
        '| S-01 | frontend#2.5 | integration | frontend | TASK-001 | planned | ["python3", "-c", "pass"] |\n'
        '| S-02 | backend#2.5 | integration | backend | TASK-001 | planned | ["python3", "-c", "pass"] |\n\n'
        "## TASK-001: A\n- **Status**: in-progress\n- **Acceptance-Refs**: S-01, S-02\n",
        encoding="utf-8",
    )
    write_manifest(str(task), str(manifest))

    report = build_audit(
        str(frontend), str(manifest), root=str(tmp_path),
        design_files=[str(frontend), str(backend)],
    )

    assert report["decision"] == "pass", report
    assert report["summary"]["design_scenarios"] == 2
    assert {item["id"] for item in report["scenarios"]} == {"S-01", "S-02"}
    assert report["summary"]["rules"] == 2
    assert report["summary"]["risks"] == 2
