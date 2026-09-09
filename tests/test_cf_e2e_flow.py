#!/usr/bin/env python3
"""[S-07][E-07] E2E 状态分离与 verify-e2e 贯通回归测试。

真实边界：真实 Runner 子进程 + 真实四平台命令文档。
"""
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_runner import run_manifest  # noqa: E402
from cf_stop_hook import _acceptance_gap  # noqa: E402


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
