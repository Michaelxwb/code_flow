"""Four-platform workflow and real compatibility acceptance."""
from pathlib import Path
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))
ROOT = SCRIPTS.parents[3]


def _run(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=ROOT, text=True, capture_output=True, check=False)


def test_s10_platform_workflows_agree() -> None:
    generated = _run("node", "src/render-runtime-contract.js", "--check")
    assert generated.returncode == 0, generated.stdout + generated.stderr
    sync = _run("code-flow", "sync", "check")
    assert sync.returncode == 0, sync.stdout + sync.stderr
    for platform, prefix in (("claude", "commands/cf-task"), ("costrict", "commands/cf-task"),
                             ("opencode", "commands/cf-task"), ("codex", "skills")):
        root = ROOT / "src/adapters" / platform / prefix
        start = root / ("cf-task-start/SKILL.md" if platform == "codex" else "start.md")
        archive = root / ("cf-task-archive/SKILL.md" if platform == "codex" else "archive.md")
        text = start.read_text(encoding="utf-8")
        assert "相关批次" in text and "--tasks" in text
        assert "E2E 留到终验执行" not in text and "E2E 只登记" not in text
        content = archive.read_text(encoding="utf-8")
        assert "code-flow task archive" in content and "执行 review 终验：" not in content
    guidance = (ROOT / "src/core/code-flow/specs/shared/scenarios-template.md").read_text(encoding="utf-8")
    assert all(term in guidance for term in ("CAS", "聚合", "关系绑定", "Cookie", "SSE", "✅", "❌"))


def test_e07_legacy_cli_install_and_hooks_preserved() -> None:
    command = [sys.executable, "-m", "pytest", "-q",
        "tests/test_cli_spec_workflow.py::test_four_platform_fresh_and_upgrade_keep_install_and_summary",
        "tests/test_cli_spec_workflow.py::test_package_manifest_includes_migrator_without_new_dependency",
        "tests/test_runtime_contract.py::test_runtime_migration_preserves_user_content_and_rolls_back",
        "tests/test_runtime_contract.py::test_failed_transaction_restores_files_and_version",
        "tests/test_hook_command_robustness.py::test_noop_outside_any_project",
        "tests/test_cf_acceptance_manifest.py::test_legacy_annotated_e2e_manifest_is_healed"]
    result = _run(*command)
    assert result.returncode == 0, result.stdout + result.stderr
    plugin = _run("node", "tests/test_opencode_plugin.js")
    assert plugin.returncode == 0, plugin.stdout + plugin.stderr
