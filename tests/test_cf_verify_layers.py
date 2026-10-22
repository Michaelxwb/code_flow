#!/usr/bin/env python3
"""[S-02][B-03] Layered requirement verification and empty no-op regressions.

真实边界：真实 verify runner 子进程 + 真实 acceptance manifest + 真实临时 git 仓库。
"""
import json
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_manifest import write_manifest  # noqa: E402
from cf_spec_context import BindingInput, bind_specs, new_context, save_context  # noqa: E402
from cf_spec_resolver import resolve_candidates  # noqa: E402


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def _touch_command(marker: Path) -> list:
    code = f"from pathlib import Path; Path({str(marker)!r}).write_text('x')"
    return [sys.executable, "-c", code]


def _review_spec(root: Path, marker: Path) -> None:
    spec_dir = root / ".code-flow" / "specs" / "review"
    spec_dir.mkdir(parents=True)
    argv = _touch_command(marker)
    (spec_dir / "rules.md").write_text(
        "---\n"
        "id: review-rules\n"
        "description: review rules\n"
        "stages: [design, plan, code, review]\n"
        "enforcement: required\n"
        "verifiers:\n"
        "  - rule: RULE-review-001\n"
        "    type: test\n"
        "    stage: review\n"
        f"    config: {{argv: {json.dumps(argv)}, timeout: 30}}\n"
        "---\n\n# Review Rules\n\n## Rules\n- [RULE-review-001] review rule.\n",
        encoding="utf-8",
    )


def _config(root: Path) -> None:
    config = {
        "path_mapping": {
            "review": {"patterns": ["src/*"], "specs": [{"path": "review/rules.md"}]}
        }
    }
    (root / ".code-flow").mkdir(exist_ok=True)
    (root / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")


def _task_text(root: Path, functional: Path, e2e: Path) -> str:
    functional_argv = json.dumps(_touch_command(functional))
    e2e_argv = json.dumps(_touch_command(e2e))
    return (
        "# Tasks: req\n\n- **Source**: req.design.md\n\n"
        "## Acceptance Coverage\n\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|\n"
        f"| S-01 | req.design.md#2.1 | integration | real process | TASK-001 | planned | {functional_argv} |\n"
        f"| E-01 | req.design.md#2.2 | E2E | real browser | TASK-001 | planned | {e2e_argv} |\n\n"
        "## TASK-001: A\n\n"
        "- **Status**: done\n"
        "- **Acceptance-Refs**: S-01, E-01\n\n"
        "### Acceptance Contract\n\n"
        "| S-01 | integration | real | pass | planned |\n"
        "| E-01 | E2E | real | pass | planned |\n\n"
        "### Acceptance Evidence\n\n"
        "### Log\n- [2026-10-22] created (draft)\n"
    )


def _requirement(
    tmp_path: Path,
    *,
    validator_exit: int = 0,
    with_review: bool = True,
    with_manifest: bool = True,
) -> dict:
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "src").mkdir()
    (root / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / ".code-flow").mkdir()
    _config(root)
    validator_marker = tmp_path / "validators.txt"
    review_marker = tmp_path / "review.txt"
    functional_marker = tmp_path / "functional.txt"
    e2e_marker = tmp_path / "e2e.txt"
    validator_command = (
        f"python3 -c \"from pathlib import Path; "
        f"Path({str(validator_marker)!r}).write_text('x'); "
        f"raise SystemExit({validator_exit})\""
    )
    (root / ".code-flow/validation.yml").write_text(
        yaml.safe_dump({
            "validators": [{
                "name": "unit",
                "trigger": "**/*.py",
                "command": validator_command,
                "timeout": 5000,
                "heavy": False,
                "on_fail": "fix",
            }]
        }),
        encoding="utf-8",
    )
    req = root / ".code-flow" / "tasks" / "req"
    req.mkdir(parents=True)
    task_file = req / "req.md"
    task_file.write_text(_task_text(root, functional_marker, e2e_marker), encoding="utf-8")
    if with_review:
        _review_spec(root, review_marker)
        candidate = resolve_candidates(str(root), "design", ["src/app.py"])[0]
        context = new_context("req", (("test", "S-02"),))
        context = bind_specs(context, (BindingInput(candidate, "path+agent", "review rule"),))
        save_context(str(req / "spec-context.yml"), context)
    if with_manifest:
        write_manifest(str(task_file), str(req / ".acceptance-manifest.json"))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return {
        "root": root,
        "req": req,
        "task_file": task_file,
        "validator_marker": validator_marker,
        "review_marker": review_marker,
        "functional_marker": functional_marker,
        "e2e_marker": e2e_marker,
    }


def _cli(fixture: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "cf_task_workflow.py"), *args],
        cwd=fixture["root"], input="{}", text=True, capture_output=True, timeout=60,
    )


def test_layers_cli_runs_only_requested_e2e(tmp_path: Path) -> None:
    """[S-02] --layers e2e 只执行 e2e 层；validators/review 与 functional 零执行。"""
    fixture = _requirement(tmp_path)

    completed = _cli(fixture, "verify", "--task-dir", str(fixture["req"]), "--layers", "e2e", "--json")

    assert completed.returncode == 0, completed.stderr + completed.stdout
    result = json.loads(completed.stdout)
    assert result["profile"] == "changed", "默认 profile 必须是 changed"
    assert set(result["layers"]) == {"e2e"}
    layer = result["layers"]["e2e"]
    assert layer["decision"] == "pass"
    assert layer["executed"] == 1 and layer["reused"] == 0
    assert layer["failed"] == []
    assert fixture["e2e_marker"].is_file(), "e2e 层必须真实执行 E2E 命令"
    assert not fixture["validator_marker"].exists(), "e2e 层不得触发 validators"
    assert not fixture["review_marker"].exists(), "e2e 层不得触发 review"
    assert not fixture["functional_marker"].exists(), "e2e 层不得执行 functional 场景"
    assert "**Status**: done" in fixture["task_file"].read_text(encoding="utf-8"), \
        "非 full 全层通过不得提升 verified"


def test_layers_keep_independent_results_after_layer_failure(tmp_path: Path) -> None:
    """某层失败不影响其他层：validators 失败仍返回 e2e 层结果并执行 E2E。"""
    fixture = _requirement(tmp_path, validator_exit=1)

    completed = _cli(fixture, "verify", "--task-dir", str(fixture["req"]),
                     "--layers", "validators,e2e", "--json")

    assert completed.returncode == 3, completed.stderr + completed.stdout
    result = json.loads(completed.stdout)
    assert result["decision"] == "block"
    assert result["reason"] == "validation_failed"
    assert set(result["layers"]) == {"validators", "e2e"}
    assert result["layers"]["validators"]["decision"] == "block"
    assert result["layers"]["validators"]["failed"] == ["unit"]
    assert result["layers"]["e2e"]["decision"] == "pass"
    assert result["layers"]["e2e"]["executed"] == 1
    assert fixture["e2e_marker"].is_file(), "validators 失败后 e2e 层仍须执行并回报"


def test_empty_noop_returns_nothing_to_verify_without_execution(tmp_path: Path) -> None:
    """[B-03] 无 required 检查/无 E2E：nothing_to_verify pass，不伪造执行。"""
    fixture = _requirement(tmp_path, with_review=False, with_manifest=False)
    (fixture["root"] / ".code-flow/validation.yml").unlink()

    completed = _cli(fixture, "verify", "--task-dir", str(fixture["req"]), "--json")

    assert completed.returncode == 0, completed.stderr + completed.stdout
    result = json.loads(completed.stdout)
    assert result["decision"] == "pass"
    assert result["reason"] == "nothing_to_verify"
    assert result["executed"] == 0 and result["reused"] == 0
    assert result["failed"] == [] and result["env_blocked"] == 0 and result["incomplete"] == 0
    for name in ("validators", "review", "e2e"):
        layer = result["layers"][name]
        assert layer["decision"] == "pass"
        assert layer["reason"] == "nothing_to_verify"
        assert layer["executed"] == 0 and layer["reused"] == 0
    assert not fixture["e2e_marker"].exists()


def test_empty_noop_manifest_without_e2e_scenarios(tmp_path: Path) -> None:
    """[B-03] manifest 只有 functional 场景时 e2e 层仍为空操作。"""
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "src").mkdir()
    (root / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / ".code-flow").mkdir()
    (root / ".code-flow/config.yml").write_text(yaml.safe_dump({"path_mapping": {}}), encoding="utf-8")
    marker = tmp_path / "functional.txt"
    req = root / ".code-flow" / "tasks" / "req"
    req.mkdir(parents=True)
    task = req / "req.md"
    task.write_text(
        "# Tasks: req\n\n- **Source**: req.design.md\n\n"
        "## Acceptance Coverage\n\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|\n"
        f"| S-01 | req.design.md#2.1 | integration | real process | TASK-001 | planned | {json.dumps(_touch_command(marker))} |\n\n"
        "## TASK-001: A\n\n- **Status**: done\n- **Acceptance-Refs**: S-01\n\n"
        "### Acceptance Contract\n\n| S-01 | integration | real | pass | planned |\n\n"
        "### Acceptance Evidence\n\n### Log\n- [2026-10-22] created (draft)\n",
        encoding="utf-8",
    )
    write_manifest(str(task), str(req / ".acceptance-manifest.json"))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")

    completed = _cli(
        {"root": root}, "verify", "--task-dir", str(req), "--layers", "e2e", "--json"
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    result = json.loads(completed.stdout)
    assert result["decision"] == "pass"
    assert result["layers"]["e2e"]["reason"] == "nothing_to_verify"
    assert result["layers"]["e2e"]["executed"] == 0
    assert not marker.exists(), "无 E2E 场景不得执行 functional"


def test_layers_runtime_contract_alias_and_four_platform_docs() -> None:
    """运行时契约暴露 task verify 并保留 verify-e2e 别名，四平台文档同步。"""
    canonical = json.loads((ROOT / "src/core/code-flow/runtime-commands.json").read_text(encoding="utf-8"))
    deployed = json.loads((ROOT / ".code-flow/runtime-commands.json").read_text(encoding="utf-8"))
    for registry in (canonical, deployed):
        commands = registry["commands"]
        assert commands["task verify"]["prefix"] == ["verify"]
        assert commands["task verify-e2e"]["prefix"] == ["verify-e2e"]
        assert "task verify" in registry["commands"]

    assert (ROOT / ".code-flow/scripts/cf_task_workflow.py").read_text(encoding="utf-8") == \
        (ROOT / "src/core/code-flow/scripts/cf_task_workflow.py").read_text(encoding="utf-8")

    docs = [
        "src/adapters/claude/commands/cf-task/verify-e2e.md",
        "src/adapters/costrict/commands/cf-task/verify-e2e.md",
        "src/adapters/opencode/commands/cf-task/verify-e2e.md",
        "src/adapters/codex/skills/cf-task-verify-e2e/SKILL.md",
        ".claude/commands/cf-task/verify-e2e.md",
        ".costrict/commands/cf-task/verify-e2e.md",
        ".opencode/commands/cf-task/verify-e2e.md",
        ".agents/skills/cf-task-verify-e2e/SKILL.md",
    ]
    for doc in docs:
        text = (ROOT / doc).read_text(encoding="utf-8")
        assert "code-flow task verify" in text, f"{doc}: 缺 task verify 命令"
        assert "别名" in text, f"{doc}: 缺 verify-e2e 别名说明"
