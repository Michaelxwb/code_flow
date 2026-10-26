#!/usr/bin/env python3
"""[TASK-014] 生成式追溯矩阵：design §2.5 + manifest，不手工维护。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_manifest import write_manifest  # noqa: E402
from codeflow.acceptance.cf_traceability import (  # noqa: E402
    build_traceability,
    parse_design_scenarios,
    render_markdown,
)


DESIGN = """# Demo design

## 2. 需求分析

### 2.5 验收条件

#### 2.5.2 功能验收场景

**正常场景**

| 场景ID | 功能ID | 优先级 | 测试层级 | 执行方式(exec) | 环境(env) | 输入(inputs) | 关键真实边界 | 前置条件 | 操作步骤 | 预期结果 |
|--------|--------|--------|---------|----------------|-----------|--------------|-------------|---------|---------|---------|
| S-01 | FEAT-01 | P0 | integration | auto | none | tests/a.py | runner | | run | pass |

**异常场景**

| 场景ID | 功能ID | 优先级 | 测试层级 | 执行方式(exec) | 环境(env) | 输入(inputs) | 关键真实边界 | 触发条件 | 系统行为 | 用户感知 |
|--------|--------|--------|---------|----------------|-----------|--------------|-------------|---------|---------|---------|
| E-01 | FEAT-01 | P1 | integration | aspirational | none | - | external | trigger | blocked | visible |

#### 2.5.3 非功能指标

| 指标ID | 指标名称 | 目标值 | 测量方法 |
|--------|---------|-------|---------|
| NFR-01 | latency | <=1s | benchmark |
"""

TASK = """# Tasks

## Acceptance Coverage

| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 | 优先级 | 执行方式 | 环境 | 输入 |
|--------|---------|---------|-------------|---------|------|---------|--------|---------|------|------|
| S-01 | design.md#2.5 验收条件 | integration | runner | TASK-001 | planned | ["python3", "-c", "pass"] | P0 | auto | none | tests/a.py |
| E-01 | design.md#2.5 验收条件 | integration | external | TASK-001 | planned | - | P1 | aspirational | none | - |

## TASK-001: Demo

- **Status**: draft
- **Acceptance-Refs**: S-01, E-01
"""

UNBOUND_TASK = """# Tasks

## Acceptance Coverage

| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 | 优先级 | 执行方式 | 环境 | 输入 |
|--------|---------|---------|-------------|---------|------|---------|--------|---------|------|------|
| S-01 | design.md#2.5 验收条件 | integration | runner | TASK-001 | planned | - | P0 | auto | none | - |

## TASK-001: Demo

- **Status**: draft
- **Acceptance-Refs**: S-01
"""


def _fixture(tmp_path: Path, task_text: str = TASK) -> tuple[str, str]:
    design = tmp_path / "demo.design.md"
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    design.write_text(DESIGN, encoding="utf-8")
    task.write_text(task_text, encoding="utf-8")
    write_manifest(str(task), str(manifest))
    return str(design), str(manifest)


def test_design_metadata_and_manifest_metadata_are_both_captured(tmp_path: Path) -> None:
    design_file, manifest_file = _fixture(tmp_path)
    design = {item.id: item for item in parse_design_scenarios(design_file)}
    assert design["S-01"].priority == "P0"
    assert design["S-01"].exec == "auto"
    assert design["S-01"].inputs == "tests/a.py"
    assert design["E-01"].exec == "aspirational"

    manifest = json.loads(Path(manifest_file).read_text(encoding="utf-8"))
    scenarios = {item["id"]: item for item in manifest["scenarios"]}
    assert scenarios["S-01"]["priority"] == "P0"
    assert scenarios["S-01"]["exec"] == "auto"
    assert scenarios["S-01"]["env"] == "none"
    assert scenarios["S-01"]["inputs"] == ["tests/a.py"]
    check = next(item for item in manifest["checks"] if item["id"] == scenarios["S-01"]["check"])
    assert check["env"] == "none"
    assert check["inputs"] == ["tests/a.py"]


def test_traceability_matrix_is_generated_from_design_and_manifest(tmp_path: Path) -> None:
    design_file, manifest_file = _fixture(tmp_path)
    report = build_traceability(design_file, manifest_file)

    assert report["decision"] == "pass"
    assert report["generated"] is True
    assert report["summary"]["design_scenarios"] == 2
    assert report["summary"]["bound"] == 1
    assert report["summary"]["aspirational"] == 1

    rows = {row["id"]: row for row in report["scenarios"]}
    assert rows["S-01"]["check"].startswith("CHK-")
    assert rows["S-01"]["priority"] == "P0"
    assert rows["S-01"]["exec"] == "auto"
    assert rows["S-01"]["command"] == ["python3", "-c", "pass"]
    assert rows["S-01"]["owner"] == "TASK-001"
    assert rows["E-01"]["check"] == "-"
    assert rows["E-01"]["binding"] == "aspirational"

    markdown = render_markdown(report)
    assert "| 场景ID | 优先级 | 测试层级 | 执行方式 | 环境 | 输入 | 追溯 check | 执行命令 | 负责任务 | 状态 |" in markdown
    assert "S-01" in markdown and "CHK-" in markdown
    assert "E-01" in markdown and "aspirational" in markdown


def test_unbound_scenario_blocks_until_explicit_aspirational(tmp_path: Path) -> None:
    design_file, manifest_file = _fixture(tmp_path, UNBOUND_TASK)
    report = build_traceability(design_file, manifest_file)

    assert report["decision"] == "block"
    violation = next(item for item in report["violations"] if item["code"] == "unbound_scenario")
    assert violation["scenario"] == "S-01"
    assert "aspirational" in violation["message"]


def test_missing_design_scenario_in_manifest_blocks(tmp_path: Path) -> None:
    design_file = tmp_path / "demo.design.md"
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    design_file.write_text(DESIGN, encoding="utf-8")
    task.write_text(TASK.replace("| E-01 |", "| E-02 |"), encoding="utf-8")
    write_manifest(str(task), str(manifest))

    report = build_traceability(str(design_file), str(manifest))

    assert report["decision"] == "block"
    codes = {item["code"] for item in report["violations"]}
    assert {"missing_in_manifest", "extra_in_manifest"} <= codes


def test_cli_emits_json_and_exit_code(tmp_path: Path) -> None:
    design_file, manifest_file = _fixture(tmp_path)
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "codeflow/acceptance/cf_traceability.py"), "--design", design_file,
         "--manifest", manifest_file, "--json"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["decision"] == "pass"
    assert data["summary"]["design_scenarios"] == 2

    unbound_dir = tmp_path / "unbound"
    unbound_dir.mkdir()
    unbound_design, unbound_manifest = _fixture(unbound_dir, UNBOUND_TASK)
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "codeflow/acceptance/cf_traceability.py"), "--design", unbound_design,
         "--manifest", unbound_manifest, "--json"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 3
    assert json.loads(result.stdout)["decision"] == "block"


def test_conflicting_check_environment_fails_closed(tmp_path: Path) -> None:
    task = tmp_path / "conflict.md"
    task.write_text(
        "# Tasks\n\n## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 | 执行方式 | 环境 | 输入 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|---------|------|------|\n"
        '| S-01 | d#2.5 | integration | runner | TASK-001 | planned | ["python3", "-c", "pass"] | auto | browser | a.py |\n'
        '| S-02 | d#2.5 | integration | runner | TASK-001 | planned | ["python3", "-c", "pass"] | auto | database | b.py |\n\n'
        "## TASK-001: Demo\n- **Acceptance-Refs**: S-01, S-02\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="check configuration conflict"):
        write_manifest(str(task), str(tmp_path / ".acceptance-manifest.json"))
