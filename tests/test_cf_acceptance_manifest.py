from pathlib import Path
import json
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_manifest import (
    _kind,
    _legacy_kind,
    extract_manifest,
    record_accepted_risk,
    record_manual_evidence,
    validate_manifest,
    write_manifest,
)
from codeflow.acceptance.cf_acceptance_schema import validate_checks


def test_legacy_annotated_e2e_manifest_is_healed(tmp_path: Path) -> None:
    """旧版精确匹配把带注解的 E2E 锁成 functional；内容未变时应自动升级并保留 evidence。"""
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(
        "# Tasks\n\n## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 |\n"
        "|--------|---------|---------|-------------|---------|------|\n"
        "| S-01 | design#1 | E2E（Playwright） | browser -> api | TASK-001 | planned |\n\n"
        "## TASK-001: Demo\n- **Acceptance-Refs**: S-01\n",
        encoding="utf-8",
    )
    legacy = extract_manifest(str(task), _legacy_kind)
    assert legacy["scenarios"][0]["kind"] == "functional", "旧解析确实会误判"
    legacy["task_file"] = "demo.md"
    legacy["scenarios"][0]["evidence"] = {"status": "passed", "exit_code": 0}
    manifest.write_text(json.dumps(legacy, ensure_ascii=False) + "\n", encoding="utf-8")

    assert validate_manifest(str(task), str(manifest)) == (True, "")
    healed = json.loads(manifest.read_text(encoding="utf-8"))
    assert healed["scenarios"][0]["kind"] == "e2e"
    assert healed["scenarios"][0]["evidence"]["exit_code"] == 0, "运行态 evidence 必须保留"
    assert validate_manifest(str(task), str(manifest)) == (True, "")

    task.write_text(task.read_text(encoding="utf-8").replace("browser -> api", "browser -> queue"), encoding="utf-8")
    valid, reason = validate_manifest(str(task), str(manifest))
    assert valid is False and reason == "acceptance_manifest_drift"


def test_kind_tolerates_level_annotations() -> None:
    """带注解的层级不得误判：E2E 误判成 functional 会导致每个 TASK 都触发 E2E 执行。"""
    assert _kind("E2E") == "e2e"
    assert _kind("e2e") == "e2e"
    assert _kind("E2E（Playwright）") == "e2e"
    assert _kind("e2e/chrome") == "e2e"
    assert _kind("端到端") == "e2e"
    assert _kind("end-to-end") == "e2e"
    assert _kind("manual") == "manual"
    assert _kind("manual(chrome)") == "manual"
    assert _kind("integration") == "functional"
    assert _kind("unit") == "functional"
    assert _kind("") == "functional"
    assert _kind("E2E 场景") == "e2e"


TASK = """# Tasks\n\n## Acceptance Coverage\n| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 |\n|--------|---------|---------|-------------|---------|------|\n| S-01 | design#1 | integration | service -> store | TASK-001 | planned |\n\n## TASK-001: Demo\n- **Acceptance-Refs**: S-01\n"""

TASK_WITH_COMMAND = """# Tasks\n\n## Acceptance Coverage\n| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n|--------|---------|---------|-------------|---------|------|---------|\n| S-01 | design#1 | integration | service -> store | TASK-001 | planned | ["python3", "-c", "pass"] |\n\n## TASK-001: Demo\n- **Acceptance-Refs**: S-01\n"""


def test_manifest_lock_and_detects_task_drift(tmp_path: Path) -> None:
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(TASK, encoding="utf-8")
    locked = write_manifest(str(task), str(manifest))
    assert len(locked["scenarios"]) == 1
    assert locked["scenarios"][0]["kind"] == "functional"
    assert locked["task_file"] == "demo.md"
    assert validate_manifest(str(task), str(manifest)) == (True, "")
    task.write_text(TASK.replace("service -> store", "service -> queue"), encoding="utf-8")
    assert validate_manifest(str(task), str(manifest))[0] is False


def test_manifest_requires_coverage_table(tmp_path: Path) -> None:
    task = tmp_path / "empty.md"
    task.write_text("# Tasks\n", encoding="utf-8")
    with pytest.raises(ValueError):
        extract_manifest(str(task))


def test_low_level_manifest_owner_matches_cli_entry(tmp_path: Path) -> None:
    """[S-03] 提取/校验由 acceptance 低层模块持有，CLI 入口逐字段一致。"""
    from codeflow.acceptance.cf_acceptance_manifest_core import (
        extract_manifest as core_extract,
        validate_manifest as core_validate,
    )

    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(TASK_WITH_COMMAND, encoding="utf-8")
    assert core_extract(str(task)) == extract_manifest(str(task))
    write_manifest(str(task), str(manifest))
    assert core_validate(str(task), str(manifest)) == validate_manifest(str(task), str(manifest))


def test_manual_evidence_requires_user_and_marks_verified(tmp_path: Path) -> None:
    task = tmp_path / "manual.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(TASK.replace("integration", "manual"), encoding="utf-8")
    write_manifest(str(task), str(manifest))
    with pytest.raises(ValueError):
        record_manual_evidence(str(manifest), "S-01", "agent:codex", "done")
    record_manual_evidence(str(manifest), "S-01", "user:jahan", "screenshot:/tmp/a.png")
    assert json.loads(manifest.read_text(encoding="utf-8"))["scenarios"][0]["status"] == "verified"
    assert "S-01: verified" in task.read_text(encoding="utf-8")


def test_manual_evidence_syncs_to_owning_task_section(tmp_path: Path) -> None:
    task = tmp_path / "multi.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(
        "# Tasks\n\n"
        "## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 |\n"
        "|--------|---------|---------|-------------|---------|------|\n"
        "| S-01 | design#1 | manual | real | TASK-002 | planned |\n\n"
        "## TASK-001: First\n- **Acceptance-Refs**:\n\n"
        "## TASK-002: Second\n- **Acceptance-Refs**: S-01\n",
        encoding="utf-8",
    )
    write_manifest(str(task), str(manifest))
    record_manual_evidence(str(manifest), "S-01", "user:jahan", "screenshot:/tmp/a.png")
    text = task.read_text(encoding="utf-8")
    before, after = text.split("## TASK-002:", 1)
    assert "S-01: verified" not in before
    assert "S-01: verified" in "## TASK-002:" + after


def test_checks_scenarios_manifest_v3_groups(tmp_path: Path) -> None:
    """[S-03] 同一命令的多个场景共享一个 check；不同命令生成不同 check。"""
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(
        "# Tasks\n\n## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|\n"
        '| S-01 | design#1 | integration | runner | TASK-001 | planned | ["python3", "-c", "pass"] |\n'
        '| S-02 | design#1 | integration | runner | TASK-001 | planned | ["python3", "-c", "pass"] |\n'
        '| S-03 | design#1 | integration | runner | TASK-001 | planned | ["python3", "-c", "print(1)"] |\n\n'
        "## TASK-001: Demo\n- **Status**: draft\n- **Acceptance-Refs**: S-01, S-02, S-03\n",
        encoding="utf-8",
    )
    locked = write_manifest(str(task), str(manifest))
    assert locked["schema"] == 3
    assert len(locked["checks"]) == 2
    by_id = {item["id"]: item for item in locked["scenarios"]}
    assert by_id["S-01"]["check"] == by_id["S-02"]["check"]
    assert by_id["S-01"]["check"] != by_id["S-03"]["check"]
    assert validate_manifest(str(task), str(manifest)) == (True, "")


def test_schema2_compat_manifest_remains_readable(tmp_path: Path) -> None:
    """[B-01] 旧 schema2 manifest 没有 checks/check 字段，仍可校验与运行。"""
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(
        "# Tasks\n\n## Acceptance Coverage\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|\n"
        '| S-01 | design#1 | integration | runner | TASK-001 | planned | ["python3", "-c", "pass"] |\n\n'
        "## TASK-001: Demo\n- **Status**: draft\n- **Acceptance-Refs**: S-01\n",
        encoding="utf-8",
    )
    locked = write_manifest(str(task), str(manifest))
    legacy = {key: value for key, value in locked.items() if key != "checks"}
    legacy["schema"] = 2
    for scenario in legacy["scenarios"]:
        scenario.pop("check", None)
    manifest.write_text(json.dumps(legacy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert validate_manifest(str(task), str(manifest)) == (True, "")


def test_check_preflight_env_schema_validation() -> None:
    """check 新字段 fail closed：env/env_scope/preflight/parallel_safe 类型明确。"""
    validate_checks([{
        "id": "CHK-1", "command": ["python3", "-c", "pass"],
        "env": "browser", "env_scope": "isolated", "parallel_safe": True,
        "preflight": [["python3", "-c", "pass"], "curl -f http://127.0.0.1:3000/health"],
    }])
    base = {"id": "CHK-1", "command": ["python3", "-c", "pass"]}
    invalid = (
        {"env": ""},
        {"env": 3},
        {"env_scope": "banana"},
        {"env_scope": None},
        {"parallel_safe": "yes"},
        {"preflight": "curl -f http://127.0.0.1:3000/health"},
        {"preflight": [[]]},
        {"preflight": [123]},
        {"preflight": [["python3", ""]]},
    )
    for extra in invalid:
        with pytest.raises(ValueError, match="invalid check CHK-1"):
            validate_checks([{**base, **extra}])


def test_derived_checks_default_shared_env_not_parallel_safe(tmp_path: Path) -> None:
    """shared 环境默认 parallel_safe: false（设计 §3.5.2）。"""
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(TASK_WITH_COMMAND, encoding="utf-8")
    locked = write_manifest(str(task), str(manifest))
    check = locked["checks"][0]
    assert check["env_scope"] == "shared"
    assert check["parallel_safe"] is False
    assert check["preflight"] == []


def test_relock_preserves_check_environment_config(tmp_path: Path) -> None:
    """重锁 plan 保留手写的 env/preflight，不静默丢用户配置。"""
    task = tmp_path / "demo.md"
    manifest = tmp_path / ".acceptance-manifest.json"
    task.write_text(TASK_WITH_COMMAND, encoding="utf-8")
    write_manifest(str(task), str(manifest))
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["checks"][0].update({
        "env": "browser", "env_scope": "isolated", "parallel_safe": True,
        "preflight": [["python3", "-c", "pass"]],
    })
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    write_manifest(str(task), str(manifest))

    check = json.loads(manifest.read_text(encoding="utf-8"))["checks"][0]
    assert check["env"] == "browser"
    assert check["env_scope"] == "isolated"
    assert check["parallel_safe"] is True
    assert check["preflight"] == [["python3", "-c", "pass"]]


def test_record_accepted_risk_requires_user_confirmation(tmp_path: Path) -> None:
    manifest = tmp_path / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({
        "schema": 3,
        "checks": [{"id": "CHK-1", "command": ["true"], "cwd": ".", "timeout": 30}],
        "scenarios": [{"id": "S-01", "kind": "functional", "owner": "TASK-1", "check": "CHK-1",
                       "command": ["true"], "cwd": ".", "timeout": 30, "status": "planned"}],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="user"):
        record_accepted_risk(str(manifest), "CHK-1", "TASK-1", "reason",
                             "2999-01-01", "agent", "user said ok")
    with pytest.raises(ValueError, match="future"):
        record_accepted_risk(str(manifest), "CHK-1", "TASK-1", "reason",
                             "2000-01-01", "user", "user said ok")

    result = record_accepted_risk(str(manifest), "CHK-1", "TASK-1", "reason",
                                  "2999-01-01", "user", "user said ok")
    assert result["ok"] is True
    stored = json.loads(manifest.read_text(encoding="utf-8"))["checks"][0]
    assert stored["accepted_risk"]["confirmed_by"] == "user"
    assert stored["accepted_risk"]["source"] == "user said ok"
    assert stored["accepted_risk"]["scenario_ids"] == ["S-01"]
    before = manifest.read_bytes()
    with pytest.raises(ValueError, match="owner"):
        record_accepted_risk(str(manifest), "CHK-1", "TASK-999", "reason",
                             "2999-01-01", "user", "user said ok")
    assert manifest.read_bytes() == before


def test_accepted_risk_date_only_expires_end_of_day_and_rejects_label(tmp_path: Path) -> None:
    manifest = tmp_path / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({
        "schema": 3,
        "checks": [{"id": "CHK-1", "command": ["true"], "cwd": ".", "timeout": 30}],
        "scenarios": [{"id": "S-01", "kind": "functional", "owner": "TASK-1", "check": "CHK-1",
                       "command": ["true"], "cwd": ".", "timeout": 30, "status": "planned"}],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="user"):
        record_accepted_risk(str(manifest), "CHK-1", "TASK-1", "reason",
                             "2999-01-01", "Claude Code", "user said ok")
    result = record_accepted_risk(str(manifest), "CHK-1", "TASK-1", "reason",
                                  "2999-01-01", "user", "user said ok")
    assert result["accepted_risk"]["expires_at"].endswith("23:59:59.999999+00:00")
