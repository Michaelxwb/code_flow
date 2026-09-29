#!/usr/bin/env python3
"""Regression guards for design-to-test traceability in cf-task skills."""
import json
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "core" / "code-flow" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_context import BindingInput, bind_specs, new_context, save_context  # noqa: E402
from cf_spec_resolver import resolve_candidates  # noqa: E402
from cf_task_workflow import verify_e2e  # noqa: E402

CODEX_TASK_ROOT = ROOT / "src" / "adapters" / "codex" / "skills"
COMMAND_ROOTS = [
    ROOT / "src" / "adapters" / platform / "commands" / "cf-task"
    for platform in ("claude", "opencode")
]


def _task_docs(command: str) -> list[Path]:
    docs = [CODEX_TASK_ROOT / f"cf-task-{command}" / "SKILL.md"]
    docs.extend(root / f"{command}.md" for root in COMMAND_ROOTS)
    return docs


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_plan_generates_scenario_level_acceptance_contracts() -> None:
    for path in _task_docs("plan"):
        text = _read(path)
        for phrase in (
            "验收契约拆解（硬约束）",
            "## Acceptance Coverage",
            "Acceptance-Refs",
            "### Acceptance Contract",
            "不得把 design 的 E2E 自行降级",
            "Checklist 禁止使用泛化的“编写测试”",
        ):
            assert phrase in text, f"{path}: missing {phrase}"


def test_start_requires_test_first_and_verified_evidence() -> None:
    for path in _task_docs("start"):
        text = _read(path)
        for phrase in (
            "在修改任何生产代码前",
            "先编写验收测试",
            "记录 RED",
            "### 3.2 GREEN 与验收证据",
            "Acceptance Evidence",
            "不能标记为 `done`",
            "cf_task_workflow.py finish",
            "e2e_deferred",
            "禁止手动设置 done",
        ):
            assert phrase in text, f"{path}: missing {phrase}"


def test_archive_blocks_traceability_gaps_and_cleans_empty_date_dir() -> None:
    for path in _task_docs("archive"):
        text = _read(path)
        for phrase in (
            "执行四维校验",
            "**验收追溯**",
            "cf_acceptance_runner.py",
            "--include-e2e --write-evidence",
            "--verify-plan",
            "归档后统一收尾（布局 A/B 都必须执行）",
            'rmdir "$source_date_dir"',
            "如果源日期目录仍存在但为空，视为归档未完成",
        ):
            assert phrase in text, f"{path}: missing {phrase}"


def test_design_templates_declare_test_level_boundary_and_risk_mapping() -> None:
    template_root = ROOT / "src" / "core" / "code-flow" / "specs" / "shared" / "design"
    for name in ("design-lite.md", "design-full.md", "design-frontend.md"):
        text = _read(template_root / name)
        assert "测试层级" in text, name
        assert "关键真实边界" in text, name
        assert "验证场景" in text, name
        assert "E2E" in text, name


def test_align_preserves_acceptance_test_boundaries() -> None:
    paths = [
        CODEX_TASK_ROOT / "cf-task-align" / "SKILL.md",
        *(root / "align.md" for root in COMMAND_ROOTS),
    ]
    for path in paths:
        text = _read(path)
        assert "为每个场景指定测试层级" in text, path
        assert "RULE 与高影响 RISK 必须映射" in text, path
        assert "不得把 E2E 自行降级" in text, path


def test_changed_workflow_deploy_copies_match_sources() -> None:
    mappings = []
    for command in ("align", "plan", "start", "archive"):
        mappings.append((
            CODEX_TASK_ROOT / f"cf-task-{command}" / "SKILL.md",
            ROOT / ".agents" / "skills" / f"cf-task-{command}" / "SKILL.md",
        ))
        for platform in ("claude", "costrict", "opencode"):
            mappings.append((
                ROOT / "src" / "adapters" / platform / "commands" / "cf-task" / f"{command}.md",
                ROOT / f".{platform}" / "commands" / "cf-task" / f"{command}.md",
            ))
    for source, deployed in mappings:
        assert _read(source) == _read(deployed), f"out of sync: {deployed}"


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def _stage_gate(root: Path, task_dir: Path, stage: str) -> dict:
    result = subprocess.run(
        (sys.executable, str(SCRIPTS / "cf_spec_gate.py"), "--task-dir", str(task_dir), "--stage", stage, "--json"),
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode in (0, 3), result.stderr
    return json.loads(result.stdout)


def test_s_04_review_gate_blocks_archive_until_verification(tmp_path: Path) -> None:
    """S-04: review 未验证时归档前置门禁阻断；verify-e2e 终验后放行。"""
    for path in _task_docs("archive"):
        text = _read(path)
        assert "--stage review" in text, f"{path}: archive 缺少 review 门禁"
        assert "verify-e2e" in text, f"{path}: archive 缺少终验入口"
    for path in _task_docs("verify-e2e"):
        text = _read(path)
        assert "需求级终验" in text and "review" in text, f"{path}: verify-e2e 未声明 review 终验职责"

    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "src").mkdir()
    (root / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    spec_dir = root / ".code-flow" / "specs" / "review"
    spec_dir.mkdir(parents=True)
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
        "    config:\n"
        f"      argv: {json.dumps([sys.executable, '-c', 'pass'])}\n"
        "      timeout: 30\n"
        "---\n\n# Review Rules\n\n## Rules\n- [RULE-review-001] review rule.\n",
        encoding="utf-8",
    )
    config = {"path_mapping": {"review": {"patterns": ["src/*"], "specs": [{"path": "review/rules.md"}]}}}
    (root / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    req = root / ".code-flow" / "tasks" / "req"
    req.mkdir(parents=True)
    (req / "req.md").write_text(
        "# Tasks: req\n\n- **Source**: req.design.md\n\n"
        "## TASK-001: A\n\n- **Status**: done\n- **Acceptance-Refs**:\n",
        encoding="utf-8",
    )
    candidate = resolve_candidates(str(root), "design", ["src/app.py"])[0]
    context = new_context("req", (("test", "S-04"),))
    context = bind_specs(context, (BindingInput(candidate, "path+agent", "review gate"),))
    save_context(str(req / "spec-context.yml"), context)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")

    assert _stage_gate(root, req, "code")["decision"] == "pass"
    blocked = _stage_gate(root, req, "review")
    assert blocked["decision"] == "block"
    assert any(issue["rule_ref"] == "RULE-review-001" for issue in blocked["errors"])

    result = verify_e2e(str(root), str(req))

    assert result["decision"] == "pass", result
    assert _stage_gate(root, req, "review")["decision"] == "pass"
