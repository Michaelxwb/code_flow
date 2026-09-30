#!/usr/bin/env python3
"""[S-07][E-07] E2E 状态分离与 verify-e2e 贯通回归测试。

真实边界：真实 Runner 子进程 + 真实四平台命令文档。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_manifest import write_manifest  # noqa: E402
from cf_acceptance_runner import run_manifest  # noqa: E402
from cf_spec_context import BindingInput, bind_specs, load_context, new_context, save_context  # noqa: E402
from cf_spec_resolver import resolve_candidates  # noqa: E402
from cf_stop_hook import _acceptance_gap  # noqa: E402
from cf_task_workflow import confirm_manual, verify_e2e  # noqa: E402


def _manifest(tmp_path: Path, functional: list, e2e: list) -> str:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"scenarios": [
            {"id": "S-01", "kind": "functional", "command": functional},
            {"id": "E-01", "kind": "e2e", "command": e2e},
        ]}),
        encoding="utf-8",
    )
    return str(manifest)


def test_only_e2e_runs_e2e_and_skips_functional(tmp_path: Path) -> None:
    """[S-07] --only-e2e 只跑 E2E，functional 零执行。"""
    func_marker = tmp_path / "func.txt"
    e2e_marker = tmp_path / "e2e.txt"
    touch = "import sys; open(sys.argv[1], 'w').write('x')"
    manifest = _manifest(
        tmp_path,
        [sys.executable, "-c", touch, str(func_marker)],
        [sys.executable, "-c", touch, str(e2e_marker)],
    )
    result = run_manifest(manifest, str(tmp_path), only_e2e=True)
    assert result["decision"] == "pass"
    assert not func_marker.exists(), "only-e2e 不得执行 functional"
    assert e2e_marker.is_file()
    by_id = {item["id"]: item["status"] for item in result["results"]}
    assert by_id["E-01"] == "passed" and by_id["S-01"] == "not_included"


def test_include_e2e_runs_everything(tmp_path: Path) -> None:
    """[S-07] --include-e2e 保留含 functional 语义。"""
    func_marker = tmp_path / "func.txt"
    e2e_marker = tmp_path / "e2e.txt"
    touch = "import sys; open(sys.argv[1], 'w').write('x')"
    manifest = _manifest(
        tmp_path,
        [sys.executable, "-c", touch, str(func_marker)],
        [sys.executable, "-c", touch, str(e2e_marker)],
    )
    result = run_manifest(manifest, str(tmp_path), include_e2e=True)
    assert result["decision"] == "pass"
    assert func_marker.is_file() and e2e_marker.is_file()


def test_verify_e2e_docs_use_real_status_pattern() -> None:
    """[E-07] 四平台 verify-e2e 状态检查必须匹配真实格式；Codex 不得缺命令。"""
    docs = [
        ROOT / "src/adapters/claude/commands/cf-task/verify-e2e.md",
        ROOT / "src/adapters/costrict/commands/cf-task/verify-e2e.md",
        ROOT / "src/adapters/opencode/commands/cf-task/verify-e2e.md",
        ROOT / "src/adapters/codex/skills/cf-task-verify-e2e/SKILL.md",
        ROOT / ".claude/commands/cf-task/verify-e2e.md",
        ROOT / ".costrict/commands/cf-task/verify-e2e.md",
        ROOT / ".opencode/commands/cf-task/verify-e2e.md",
        ROOT / ".agents/skills/cf-task-verify-e2e/SKILL.md",
    ]
    for doc in docs:
        assert doc.is_file(), f"缺 verify-e2e 命令: {doc}"
        text = doc.read_text(encoding="utf-8")
        assert '"^Status:"' not in text and "'^Status:'" not in text, f"{doc} 仍用永远匹配不到的旧正则"
        assert "Status" in text and ("verified" in text or "done" in text)


def test_manual_scenario_defers_until_verify_e2e_in_stop_gap() -> None:
    """[E-07] done 任务确认前的 manual 场景不触发 Stop 缺口；verified 后必须闭环。"""
    section = (
        "## TASK-001: Demo\n- **Status**: done\n- **Acceptance-Refs**: S-01\n"
        "### Acceptance Contract\n| S-01 | manual | real | user | planned |\n"
        "### Acceptance Evidence\n- S-01: manual_pending — 待需求级终验确认\n"
    )
    coverage = "|S-01|src|manual|real|TASK-001|planned|\n"

    assert _acceptance_gap("TASK-001", section, coverage) == ""

    verified = section.replace("- **Status**: done", "- **Status**: verified")

    assert _acceptance_gap("TASK-001", verified, coverage) != ""


def test_verified_status_passes_stop_acceptance_gap() -> None:
    """[E-07] verified 终态与 done 同等对待；planned 仍阻断。"""
    section = (
        "## TASK-001: Demo\n- **Status**: verified\n- **Acceptance-Refs**: S-01\n"
        "### Acceptance Contract\n- S-01: verified x\n"
        "### Acceptance Evidence\n- S-01: verified ok\n"
    )
    coverage = "|S-01|src|integration|real|TASK-001|verified|\n"
    assert _acceptance_gap("TASK-001", section, coverage) == ""
    done_planned = section.replace("- **Status**: verified", "- **Status**: done").replace(
        "S-01: verified", "S-01: planned"
    )
    assert _acceptance_gap("TASK-001", done_planned, coverage) != ""


def _runs(marker: Path) -> int:
    return len(marker.read_text(encoding="utf-8")) if marker.exists() else 0


def _review_argv(marker: Path, flag: Path = None) -> list:
    code = (
        "from pathlib import Path; import sys; "
        f"p=Path({str(marker)!r}); p.write_text((p.read_text() if p.exists() else '') + 'x')"
    )
    if flag is not None:
        code += f"; sys.exit(0 if Path({str(flag)!r}).exists() else 1)"
    return [sys.executable, "-c", code]


def _write_review_spec(root: Path, argv: list) -> None:
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
        '    files: ["src/**"]\n'
        f"    config: {{argv: {json.dumps(argv)}, timeout: 30}}\n"
        "---\n\n# Review Rules\n\n## Rules\n- [RULE-review-001] review rule.\n",
        encoding="utf-8",
    )


def _review_task_text(e2e_command: list) -> str:
    command = json.dumps(e2e_command)
    return (
        "# Tasks: req\n\n- **Source**: req.design.md\n\n"
        "## Acceptance Coverage\n\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|\n"
        f"| E-99 | req.design.md#2.5 | E2E | real boundary | TASK-001 | planned | {command} |\n\n"
        "## TASK-001: A\n\n- **Status**: done\n- **Acceptance-Refs**: E-99\n\n"
        "### Acceptance Contract\n\n| E-99 | E2E | real | pass | planned | planned | planned |\n\n"
        "### Acceptance Evidence\n\n### Log\n- [2026-09-29] created (draft)\n\n"
        "## TASK-002: B\n\n- **Status**: done\n- **Acceptance-Refs**:\n\n"
        "### Acceptance Contract\n\n### Acceptance Evidence\n\n### Log\n- [2026-09-29] created (draft)\n"
    )


def _review_requirement(
    tmp_path: Path, argv: list, with_contexts: bool = True, with_manifest: bool = True
) -> tuple:
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=root, check=True)
    subprocess.run(("git", "config", "user.email", "t@t"), cwd=root, check=True)
    subprocess.run(("git", "config", "user.name", "t"), cwd=root, check=True)
    (root / "src").mkdir()
    (root / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    if with_contexts:
        _write_review_spec(root, argv)
    config = {"path_mapping": {"review": {"patterns": ["src/*"], "specs": [{"path": "review/rules.md"}]}}}
    (root / ".code-flow").mkdir(exist_ok=True)
    (root / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    req = root / ".code-flow" / "tasks" / "req"
    req.mkdir(parents=True)
    task_file = req / "req.md"
    task_file.write_text(_review_task_text([sys.executable, "-c", "pass"]), encoding="utf-8")
    if with_manifest:
        write_manifest(str(task_file), str(req / ".acceptance-manifest.json"))
    if with_contexts:
        candidate = resolve_candidates(str(root), "design", ["src/app.py"])[0]
        context = new_context("req", (("test", "S-02"),))
        context = bind_specs(context, (BindingInput(candidate, "path+agent", "review rule"),))
        save_context(str(req / "spec-context.yml"), context)
        nested = req / "nested"
        nested.mkdir()
        save_context(str(nested / "spec-context.yml"), context)
    subprocess.run(("git", "add", "-A"), cwd=root, check=True)
    subprocess.run(("git", "commit", "-qm", "init"), cwd=root, check=True)
    return root, req


def test_s_02_review_aggregation(tmp_path: Path) -> None:
    """S-02: 两个 task context 绑定同一 review rule → 只执行一次且两 context 均 verified。"""
    marker = tmp_path / "runs.txt"
    root, req = _review_requirement(tmp_path, _review_argv(marker))

    result = verify_e2e(str(root), str(req))

    assert result["decision"] == "pass", result
    assert _runs(marker) == 1, "同一 review rule 跨 context 只执行一次"
    assert result["executed"] == 1 and result["reused"] == 0
    for ctx_path in (req / "spec-context.yml", req / "nested/spec-context.yml"):
        status = load_context(str(ctx_path)).bindings[0].rules[0].stage_status["review"]
        assert status.status == "verified"


def test_e_01_review_failure_incremental(tmp_path: Path) -> None:
    """E-01: review 失败不写 verified、任务状态不反转；修复后增量重跑。"""
    marker = tmp_path / "runs.txt"
    flag = tmp_path / "ok.flag"
    root, req = _review_requirement(tmp_path, _review_argv(marker, flag))

    blocked = verify_e2e(str(root), str(req))

    assert blocked["decision"] == "block"
    assert blocked["failed"] == ["review-rules#RULE-review-001"]
    assert _runs(marker) == 1
    status = load_context(str(req / "spec-context.yml")).bindings[0].rules[0].stage_status["review"]
    assert status.status == "unverified", "失败不得写 verified"
    assert "- **Status**: done" in (req / "req.md").read_text(encoding="utf-8")

    flag.write_text("ok\n", encoding="utf-8")
    passed = verify_e2e(str(root), str(req))

    assert passed["decision"] == "pass", passed
    assert _runs(marker) == 2, "失败结果不得缓存，必须重跑"
    assert passed["executed"] == 1


def test_b_02_empty_noop(tmp_path: Path) -> None:
    """B-02: 无 review rules 且无 acceptance 时 verify-e2e 为 no-op pass。"""
    root, req = _review_requirement(
        tmp_path, _review_argv(tmp_path / "runs.txt"), with_contexts=False, with_manifest=False
    )

    result = verify_e2e(str(root), str(req))

    assert result["decision"] == "pass"
    assert result.get("reason") == "nothing_to_verify"


def _manual_review_requirement(tmp_path: Path) -> tuple:
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=root, check=True)
    subprocess.run(("git", "config", "user.email", "t@t"), cwd=root, check=True)
    subprocess.run(("git", "config", "user.name", "t"), cwd=root, check=True)
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
        "    type: manual\n"
        "    config:\n"
        "      checklist: Confirm the guidance items.\n"
        "      owner: project-owner\n"
        "---\n\n# Review Rules\n\n## Rules\n- [RULE-review-001] human review rule.\n",
        encoding="utf-8",
    )
    config = {"path_mapping": {"review": {"patterns": ["src/*"], "specs": [{"path": "review/rules.md"}]}}}
    (root / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    req = root / ".code-flow" / "tasks" / "req"
    req.mkdir(parents=True)
    task_file = req / "req.md"
    task_file.write_text(
        "# Tasks: req\n\n- **Source**: req.design.md\n\n"
        "## Acceptance Coverage\n\n"
        "| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |\n"
        "|--------|---------|---------|-------------|---------|------|---------|\n"
        "| S-01 | req.design.md#2.1 | manual | real boundary | TASK-001 | planned | |\n\n"
        "## TASK-001: A\n\n- **Status**: done\n- **Acceptance-Refs**: S-01\n\n"
        "### Acceptance Contract\n\n| S-01 | manual | real | user | planned | planned | planned |\n\n"
        "### Acceptance Evidence\n\n### Log\n- [2026-09-30] created (draft)\n",
        encoding="utf-8",
    )
    write_manifest(str(task_file), str(req / ".acceptance-manifest.json"))
    candidate = resolve_candidates(str(root), "design", ["src/app.py"])[0]
    context = new_context("req", (("test", "M-01"),))
    context = bind_specs(context, (BindingInput(candidate, "path+agent", "manual review rule"),))
    save_context(str(req / "spec-context.yml"), context)
    nested = req / "nested"
    nested.mkdir()
    save_context(str(nested / "spec-context.yml"), context)
    subprocess.run(("git", "add", "-A"), cwd=root, check=True)
    subprocess.run(("git", "commit", "-qm", "init"), cwd=root, check=True)
    return root, req


def _write_code_spec(root: Path, marker: Path) -> None:
    spec_dir = root / ".code-flow" / "specs" / "code"
    spec_dir.mkdir(parents=True)
    code = (
        "from pathlib import Path; import sys; "
        f"p=Path({str(marker)!r}); p.write_text((p.read_text() if p.exists() else '') + 'x')"
    )
    (spec_dir / "rules.md").write_text(
        "---\n"
        "id: code-rules\n"
        "description: code rules\n"
        "stages: [design, plan, code, review]\n"
        "enforcement: required\n"
        "verifiers:\n"
        "  - rule: RULE-code-001\n"
        "    type: test\n"
        f"    config: {{argv: {json.dumps([sys.executable, '-c', code])}, timeout: 30}}\n"
        "---\n\n# Code Rules\n\n## Rules\n- [RULE-code-001] code rule.\n",
        encoding="utf-8",
    )
    config = root / ".code-flow/config.yml"
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["path_mapping"]["code"] = {"patterns": ["src/*"], "specs": [{"path": "code/rules.md"}]}
    config.write_text(yaml.safe_dump(data), encoding="utf-8")


def _deferred_code_requirement(tmp_path: Path) -> tuple:
    root = tmp_path / "proj_code"
    root.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=root, check=True)
    subprocess.run(("git", "config", "user.email", "t@t"), cwd=root, check=True)
    subprocess.run(("git", "config", "user.name", "t"), cwd=root, check=True)
    (root / "src").mkdir()
    (root / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / ".code-flow").mkdir()
    (root / ".code-flow/config.yml").write_text(yaml.safe_dump({"path_mapping": {}}), encoding="utf-8")
    marker = tmp_path / "code-runs.txt"
    _write_code_spec(root, marker)
    req = root / ".code-flow" / "tasks" / "req"
    req.mkdir(parents=True)
    (req / "req.md").write_text(
        "# Tasks: req\n\n- **Source**: req.design.md\n\n"
        "## TASK-001: A\n\n- **Status**: done\n- **Acceptance-Refs**:\n",
        encoding="utf-8",
    )
    candidate = resolve_candidates(str(root), "design", ["src/app.py"])[0]
    context = new_context("req", (("test", "C-01"),))
    context = bind_specs(context, (BindingInput(candidate, "path+agent", "code rule"),))
    save_context(str(req / "spec-context.yml"), context)
    subprocess.run(("git", "add", "-A"), cwd=root, check=True)
    subprocess.run(("git", "commit", "-qm", "init"), cwd=root, check=True)
    return root, req, marker


def test_verify_e2e_runs_deferred_code_rules(tmp_path: Path) -> None:
    """需求终验全量补跑 code 层规则（任务层 deferred 的也一并执行）。"""
    root, req, marker = _deferred_code_requirement(tmp_path)

    result = verify_e2e(str(root), str(req))

    assert result["decision"] == "pass", result
    assert _runs(marker) == 1, "code 规则必须在终验执行一次"
    status = load_context(str(req / "spec-context.yml")).bindings[0].rules[0].stage_status["code"]
    assert status.status == "verified"


def test_manual_confirmation_batch_flow(tmp_path: Path) -> None:
    """S-08: manual 规则与场景在需求级终验一次性批量确认；确认前只提示不执行。"""
    root, req = _manual_review_requirement(tmp_path)

    blocked = verify_e2e(str(root), str(req))

    assert blocked["decision"] == "block"
    assert blocked["reason"] == "manual_confirmation_required"
    assert [item["ref"] for item in blocked["manual_rules"]] == ["review-rules#RULE-review-001"]
    assert blocked["manual_rules"][0]["checklist"] == "Confirm the guidance items."
    assert blocked["manual_rules"][0]["bound_contexts"] == 2
    assert [item["id"] for item in blocked["manual_scenarios"]] == ["S-01"]
    status = load_context(str(req / "spec-context.yml")).bindings[0].rules[0].stage_status["review"]
    assert status.status == "pending", "确认前不得写入 verified"

    recorded = confirm_manual(
        str(root), str(req), [], [], "user:jahan", "确认：人工验收清单已核对，接受。",
        reason="需求级人工验收确认",
    )

    assert recorded["rules"] == ["review-rules#RULE-review-001"]
    assert recorded["scenarios"] == ["S-01"]

    passed = verify_e2e(str(root), str(req))

    assert passed["decision"] == "pass", passed
    for ctx_path in (req / "spec-context.yml", req / "nested/spec-context.yml"):
        status = load_context(str(ctx_path)).bindings[0].rules[0].stage_status["review"]
        assert status.status == "verified"
        assert status.decision is not None and status.decision.confirmed_by == "user:jahan"
    assert "- **Status**: verified" in (req / "req.md").read_text(encoding="utf-8")


def test_manual_confirmation_rejects_agent_and_unknown_refs(tmp_path: Path) -> None:
    """Agent 不得代确认；未知 ref 必须报错且不写任何确认。"""
    root, req = _manual_review_requirement(tmp_path)

    with pytest.raises(ValueError):
        confirm_manual(str(root), str(req), [], [], "codex", "确认")
    with pytest.raises(ValueError):
        confirm_manual(str(root), str(req), ["review-rules#RULE-nope-001"], [], "user:jahan", "确认")

    status = load_context(str(req / "spec-context.yml")).bindings[0].rules[0].stage_status["review"]
    assert status.status == "pending", "非法确认不得留下痕迹"
