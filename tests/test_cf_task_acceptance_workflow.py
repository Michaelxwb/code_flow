#!/usr/bin/env python3
"""Regression guards for design-to-test traceability in cf-task skills."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
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
            "否则恢复为 `in-progress`",
        ):
            assert phrase in text, f"{path}: missing {phrase}"


def test_archive_blocks_traceability_gaps_and_cleans_empty_date_dir() -> None:
    for path in _task_docs("archive"):
        text = _read(path)
        for phrase in (
            "执行四维校验",
            "**验收追溯**",
            "重新执行契约中所有唯一验收命令",
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
