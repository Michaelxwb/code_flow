#!/usr/bin/env python3
"""Stage workflow integration from real Specs into task artifacts and Context."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "core" / "code-flow" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_context import load_context
from cf_spec_gate import validate_plan_coverage, validate_stage


PRD_SPEC = """---
id: product-compat
description: Product compatibility
stages: [prd, design, plan]
enforcement: required
verifiers:
  - rule: RULE-product-001
    type: document
    config:
      heading: Existing Spec Constraints
      text: Existing clients remain compatible
---

# Product Compatibility

## Rules
- [RULE-product-001] Existing clients remain compatible.
"""

CODE_SPEC = """---
id: python-style
description: Python style
stages: [code, review]
enforcement: required
verifiers:
  - rule: RULE-code-001
    type: ast
    config:
      check: typed-functions
---

# Python Style

## Rules
- [RULE-code-001] Every function is typed.
"""


def _project(tmp_path: Path) -> tuple[Path, Path]:
    specs = tmp_path / ".code-flow" / "specs" / "product"
    specs.mkdir(parents=True)
    (specs / "compat.md").write_text(PRD_SPEC, encoding="utf-8")
    (specs / "code.md").write_text(CODE_SPEC, encoding="utf-8")
    config = {
        "path_mapping": {
            "product": {
                "patterns": ["src/*"],
                "specs": [{"path": "product/compat.md"}, {"path": "product/code.md"}],
            }
        }
    }
    (tmp_path / ".code-flow" / "config.yml").write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )
    task_dir = tmp_path / ".code-flow" / "tasks" / "2026-07-16" / "demo"
    task_dir.mkdir(parents=True)
    return tmp_path, task_dir


def _context_cli(root: Path, *arguments: str, payload: object = None) -> dict[str, object]:
    result = subprocess.run(
        (sys.executable, str(SCRIPTS / "cf_spec_context.py"), *arguments),
        cwd=root,
        input=json.dumps(payload) if payload is not None else None,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_s_01_prd_resolve_bind_artifact_and_gate(tmp_path: Path) -> None:
    root, task_dir = _project(tmp_path)
    catalog = _context_cli(
        root,
        "catalog",
        "--root",
        str(root),
        "--stage",
        "prd",
        "--paths",
        "src/app.py",
        "--json",
    )
    assert [item["spec_id"] for item in catalog["candidates"]] == ["product-compat"]

    prd = task_dir / "demo.prd.md"
    prd.write_text(
        "# PRD: Demo\n\n## Existing Spec Constraints\n\n"
        "| Spec/Rule | 约束 | 对范围/验收的影响 | 状态 |\n"
        "|---|---|---|---|\n"
        "| product-compat#RULE-product-001 | Existing clients remain compatible | "
        "In Scope + compatibility acceptance | applied |\n",
        encoding="utf-8",
    )
    payload = {
        "task": "demo",
        "paths": ["src/app.py"],
        "selections": [
            {
                "spec_id": "product-compat",
                "selected_by": "path+agent",
                "reason": "Existing client behavior is in PRD scope",
            }
        ],
        "applications": [
            {
                "spec_id": "product-compat",
                "rule_ref": "RULE-product-001",
                "stage": "prd",
                "artifact": "demo.prd.md",
                "section_id": "existing-spec-constraints",
                "item_id": "product-compat#RULE-product-001",
            }
        ],
    }
    _context_cli(
        root,
        "bind",
        "--task-dir",
        str(task_dir),
        "--root",
        str(root),
        "--stage",
        "prd",
        "--json",
        payload=payload,
    )

    context = load_context(str(task_dir / "spec-context.yml"))
    binding = context.bindings[0]
    status = binding.rules[0].stage_status["prd"]
    assert binding.reason == "Existing client behavior is in PRD scope"
    assert binding.hashes.file_sha256
    assert status.status == "applied"
    assert status.refs[0].artifact_sha256 == hashlib.sha256(prd.read_bytes()).hexdigest()
    assert status.refs[0].section_id == "existing-spec-constraints"
    assert validate_stage(context, "prd").decision == "pass"


def test_prd_workflow_documents_required_context_first_contract() -> None:
    command = (ROOT / "src" / "adapters" / "claude" / "commands" / "cf-task" / "prd.md").read_text(encoding="utf-8")
    skill = (ROOT / "src" / "adapters" / "codex" / "skills" / "cf-task-prd" / "SKILL.md").read_text(encoding="utf-8")
    template = (ROOT / "src" / "core" / "code-flow" / "specs" / "shared" / "prd-template.md").read_text(encoding="utf-8")

    for text in (command, skill):
        assert "catalog --stage prd" in text
        assert "Existing Spec Constraints" in text
        assert "code-only" in text
        assert "Agent 不得代确认" in text
        assert "cf_spec_gate.py" in text
    assert "## 8. Existing Spec Constraints" in template
    assert "对范围/验收的影响" in template


def _bind_prd_context(root: Path, task_dir: Path) -> None:
    prd = task_dir / "demo.prd.md"
    prd.write_text(
        "# PRD: Demo\n\n## Existing Spec Constraints\n\n"
        "| product-compat#RULE-product-001 | compatibility | FEAT-01 | applied |\n",
        encoding="utf-8",
    )
    _context_cli(
        root,
        "bind",
        "--task-dir",
        str(task_dir),
        "--root",
        str(root),
        "--stage",
        "prd",
        "--json",
        payload={
            "task": "demo",
            "paths": ["src/app.py"],
            "selections": [
                {
                    "spec_id": "product-compat",
                    "selected_by": "prd:path",
                    "reason": "PRD compatibility scope",
                }
            ],
            "applications": [
                {
                    "spec_id": "product-compat",
                    "rule_ref": "RULE-product-001",
                    "stage": "prd",
                    "artifact": "demo.prd.md",
                    "section_id": "existing-spec-constraints",
                    "item_id": "product-compat#RULE-product-001",
                }
            ],
        },
    )


def test_s_02_align_inherits_context_and_closes_design_matrix(tmp_path: Path) -> None:
    root, task_dir = _project(tmp_path)
    _bind_prd_context(root, task_dir)
    _context_cli(
        root,
        "refresh",
        "--task-dir",
        str(task_dir),
        "--root",
        str(root),
        "--json",
    )
    design = task_dir / "demo.design.md"
    design.write_text(
        "# Design: Demo\n\n## Spec Compliance Matrix\n\n"
        "| Spec/Rule | enforcement | 设计影响 | 设计落点 | 验证场景 | 状态/N/A 理由 |\n"
        "|---|---|---|---|---|---|\n"
        "| product-compat#RULE-product-001 | required | preserve clients | "
        "§3.3 compatibility adapter | S-02 / document verifier | applied |\n",
        encoding="utf-8",
    )
    _context_cli(
        root,
        "bind",
        "--task-dir",
        str(task_dir),
        "--root",
        str(root),
        "--stage",
        "design",
        "--json",
        payload={
            "paths": ["src/app.py"],
            "selections": [
                {
                    "spec_id": "product-compat",
                    "selected_by": "design:inherited",
                    "reason": "Inherited from PRD Context",
                }
            ],
            "applications": [
                {
                    "spec_id": "product-compat",
                    "rule_ref": "RULE-product-001",
                    "stage": "design",
                    "artifact": "demo.design.md",
                    "section_id": "spec-compliance-matrix",
                    "item_id": "product-compat#RULE-product-001",
                }
            ],
        },
    )

    context = load_context(str(task_dir / "spec-context.yml"))
    rule = context.bindings[0].rules[0]
    assert rule.stage_status["prd"].status == "applied"
    assert rule.stage_status["design"].status == "applied"
    assert rule.stage_status["design"].refs[0].item_id == "product-compat#RULE-product-001"
    assert rule.verifier_ref == "product-compat#RULE-product-001"
    assert validate_stage(context, "design").decision == "pass"


def test_align_workflow_and_templates_require_spec_compliance_matrix() -> None:
    command = (ROOT / "src/adapters/claude/commands/cf-task/align.md").read_text(encoding="utf-8")
    skill = (ROOT / "src/adapters/codex/skills/cf-task-align/SKILL.md").read_text(encoding="utf-8")
    templates = (
        ROOT / "src/core/code-flow/specs/shared/design/design-lite.md",
        ROOT / "src/core/code-flow/specs/shared/design/design-full.md",
        ROOT / "src/core/code-flow/specs/shared/design/design-frontend.md",
    )
    for text in (command, skill):
        assert "refresh --task-dir" in text
        assert "Spec Compliance Matrix" in text
        assert "不得重新选择" in text
        assert "batch" in text
        assert "--stage design" in text
    for template in templates:
        text = template.read_text(encoding="utf-8")
        assert "## Spec Compliance Matrix" in text
        assert "状态/N/A 理由" in text


def test_s_03_plan_assigns_each_required_rule_to_one_verifiable_task(tmp_path: Path) -> None:
    root, task_dir = _project(tmp_path)
    _bind_prd_context(root, task_dir)
    context = load_context(str(task_dir / "spec-context.yml"))
    task_file = task_dir / "demo.md"
    task_file.write_text(
        "# Tasks: Demo\n\n"
        "## TASK-001: Compatibility adapter\n\n"
        "- **Spec-Refs**: product-compat#RULE-product-001\n"
        "- **Acceptance-Refs**: S-03\n\n"
        "### Checklist\n"
        "- [ ] [RULE-product-001] run product-compat#RULE-product-001 document verifier\n"
        "- [ ] [S-03][integration] real Design, Context and Task Markdown boundary\n\n"
        "### Acceptance Contract\n"
        "| S-03 | integration | Design, Context, Task Markdown | verifier passes |\n",
        encoding="utf-8",
    )

    assert validate_plan_coverage(context, str(task_file)).decision == "pass"

    duplicate = task_file.read_text(encoding="utf-8") + (
        "\n## TASK-002: Duplicate owner\n\n"
        "- **Spec-Refs**: product-compat#RULE-product-001\n"
        "### Checklist\n- [ ] RULE-product-001 verifier\n"
        "### Acceptance Contract\n| S-03 | integration | real boundary | pass |\n"
    )
    task_file.write_text(duplicate, encoding="utf-8")
    blocked = validate_plan_coverage(context, str(task_file))
    assert blocked.decision == "block"
    assert {issue.code for issue in blocked.errors} == {"plan_owner_duplicate"}


def test_plan_workflow_requires_spec_refs_verifier_and_unique_owner() -> None:
    command = (ROOT / "src/adapters/claude/commands/cf-task/plan.md").read_text(encoding="utf-8")
    skill = (ROOT / "src/adapters/codex/skills/cf-task-plan/SKILL.md").read_text(encoding="utf-8")
    for text in (command, skill):
        assert "Spec-Refs" in text
        assert "有且仅有一个责任 TASK" in text
        assert "verifier_ref" in text
        assert "--stage plan" in text
        assert "不得降级" in text
