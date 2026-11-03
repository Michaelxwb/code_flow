"""TASK-001 verification reporting across real processes and Git state."""
import json
import os
from pathlib import Path
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from codeflow.task.cf_requirement_verification import verify_layers
from codeflow.cli.cf_acceptance_runner import run_manifest
from codeflow.core.cf_exec_base import execution_session, run_command


def _project(root: Path, failing: bool = False) -> Path:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for key, value in (("user.name", "Tester"), ("user.email", "test@example.invalid")):
        subprocess.run(["git", "-C", str(root), "config", key, value], check=True)
    (root / ".code-flow").mkdir()
    (root / ".gitignore").write_text("runs.txt\n.code-flow/\n", encoding="utf-8")
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    script = "import os, pathlib, sys\np = pathlib.Path('runs.txt')\np.write_text((p.read_text() if p.exists() else '') + 'x')\n"
    if failing:
        script += "sys.stderr.write(os.environ['TEST_REPORT_SECRET'])\nsys.exit(1)\n"
    (root / "check.py").write_text(script, encoding="utf-8")
    (root / ".code-flow/validation.yml").write_text(
        f'validators:\n  - name: check\n    trigger: "*.py"\n    command: "{sys.executable} check.py"\n    timeout: 30000\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "baseline"], check=True)
    return root / ".code-flow"


def test_s01_timing_and_selection_report(tmp_path: Path, monkeypatch) -> None:
    demand = _project(tmp_path)
    first = verify_layers(str(tmp_path), str(demand), layers="validators", profile="full")
    second = verify_layers(str(tmp_path), str(demand), layers="validators", profile="full")
    assert first["decision"] == second["decision"] == "pass"
    assert (tmp_path / "runs.txt").read_text(encoding="utf-8") == "x"
    assert first["executed"] == 1 and second["executed"] == 0 and second["reused"] == 1
    for result in (first, second):
        assert result["selection_reason"] and result["reuse_reason"] and result["scope"]
        assert "validator" in result["summary"]
        assert result["execution_identities"]
        assert result["input_change_category"]
        assert all(result["timings"][key] >= 0 for key in
                   ("planning_ms", "preflight_ms", "execution_ms", "evidence_ms", "elapsed_ms"))
    assert second["timings"]["execution_ms"] == 0
    assert first["execution_identities"] == second["execution_identities"]
    assert first["input_change_category"] == ["no_baseline"]
    assert second["input_change_category"] == ["unchanged"]
    (tmp_path / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    changed = verify_layers(str(tmp_path), str(demand), layers="validators", profile="full")
    assert changed["input_change_category"] == ["worktree_changed"]
    assert changed["execution_identities"] != first["execution_identities"]
    assert (tmp_path / "runs.txt").read_text(encoding="utf-8") == "xx"
    monkeypatch.setenv("TEST_REPORT_SECRET", "environment-change-12345")
    unchanged_env = verify_layers(str(tmp_path), str(demand), layers="validators", profile="full")
    assert unchanged_env["input_change_category"] == ["unchanged"]
    assert unchanged_env["execution_identities"] == changed["execution_identities"]
    assert "environment-change-12345" not in json.dumps(unchanged_env)
    assert (tmp_path / "runs.txt").read_text(encoding="utf-8") == "xx"
    monkeypatch.setenv("DATABASE_URL", "postgresql://environment-change-12345")
    changed_env = verify_layers(str(tmp_path), str(demand), layers="validators", profile="full")
    assert changed_env["input_change_category"] == ["execution_context_changed"]
    assert changed_env["execution_identities"] != changed["execution_identities"]
    assert "environment-change-12345" not in json.dumps(changed_env)
    assert (tmp_path / "runs.txt").read_text(encoding="utf-8") == "xxx"


def test_e01_report_preserves_protocol_and_redacts_secrets(tmp_path: Path) -> None:
    demand = _project(tmp_path, failing=True)
    env = {**os.environ, "TEST_REPORT_SECRET": "private-value-762490"}
    command = ["node", str(SCRIPTS.parents[2] / "cli.js"), "task", "verify", "--root", str(tmp_path), "--task-dir", str(demand),
               "--layers", "validators", "--profile", "full", "--json"]
    result = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
    payload = json.loads(result.stdout)
    assert result.returncode != 0 and payload["decision"] == "block"
    assert env["TEST_REPORT_SECRET"] not in result.stdout + result.stderr
    hook = subprocess.run([sys.executable, str(SCRIPTS / "cf_codex_hook.py")],
                          input=json.dumps({"cwd": "relative", "session_id": "test",
                                            "hook_event_name": "PreToolUse"}),
                          env=env, text=True, capture_output=True, check=False)
    hook_payload = json.loads(hook.stdout)
    assert hook.returncode == 0
    assert hook_payload["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert hook.stderr and env["TEST_REPORT_SECRET"] not in hook.stdout + hook.stderr
    leaky_root = tmp_path / env["TEST_REPORT_SECRET"]
    (leaky_root / ".code-flow").mkdir(parents=True)
    (leaky_root / ".code-flow/config.yml").write_text("{}\n", encoding="utf-8")
    hook_failure = subprocess.run([sys.executable, str(SCRIPTS / "cf_codex_hook.py")],
        input=json.dumps({"cwd": str(leaky_root), "session_id": "test", "hook_event_name": "PreToolUse"}),
        env=env, text=True, capture_output=True, check=False)
    assert json.loads(hook_failure.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert env["TEST_REPORT_SECRET"] not in hook_failure.stdout + hook_failure.stderr
    manifest = demand / "failure.json"
    failure_command = [sys.executable, "-c", "import os,sys; sys.stderr.write(os.environ['TEST_REPORT_SECRET']); sys.exit(1)",
                       "--api-key", "literal-private-key-4731"]
    manifest.write_text(json.dumps({"schema": 3, "checks": [{"id": "CHK-FAIL", "command": failure_command}],
                                   "scenarios": [{"id": "S-FAIL", "kind": "functional",
                                                  "check": "CHK-FAIL", "command": failure_command}]}),
        encoding="utf-8")
    acceptance = subprocess.run(["node", str(SCRIPTS.parents[2] / "cli.js"), "acceptance", "run",
                                 "--root", str(tmp_path), "--manifest", str(manifest)],
                                env=env, text=True, capture_output=True, check=False)
    assert acceptance.returncode != 0 and json.loads(acceptance.stdout)["decision"] == "block"
    assert env["TEST_REPORT_SECRET"] not in acceptance.stdout + acceptance.stderr
    assert "literal-private-key-4731" not in acceptance.stdout + acceptance.stderr


def test_baseline_records_three_real_runs_per_scenario(tmp_path: Path) -> None:
    benchmark = Path(__file__).with_name("benchmark_verification_efficiency.py")
    subprocess.run([sys.executable, str(benchmark), str(tmp_path)], check=True, capture_output=True)
    raw = json.loads((tmp_path / "baseline-raw.json").read_text(encoding="utf-8"))
    summary = json.loads((tmp_path / "baseline-summary.json").read_text(encoding="utf-8"))
    assert len(raw) == 12
    assert set(summary) == {"cold", "unchanged", "unrelated", "shared_dependency"}
    assert all(row["samples"] == 3 and row["median_elapsed_ms"] >= 0 for row in summary.values())
    assert summary["cold"]["executed"] == [1, 1, 1]
    assert summary["unchanged"]["executed"] == [0, 0, 0]
    assert summary["unchanged"]["reused"] == [1, 1, 1]


def test_legacy_cache_without_execution_identity_is_not_reused(tmp_path: Path) -> None:
    demand = _project(tmp_path)
    verify_layers(str(tmp_path), str(demand), layers="validators", profile="full")
    cache_path = demand / ".validation-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    for entry in cache.values():
        entry.pop("execution_identity")
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    result = verify_layers(str(tmp_path), str(demand), layers="validators", profile="full")
    assert result["executed"] == 1 and result["reused"] == 0
    assert result["input_change_category"] == ["execution_context_changed"]
    assert (tmp_path / "runs.txt").read_text(encoding="utf-8") == "xx"


def test_session_reuse_does_not_count_validator_execution_twice(tmp_path: Path) -> None:
    demand = _project(tmp_path)
    with execution_session():
        assert run_command([sys.executable, "check.py"], str(tmp_path), 30)["returncode"] == 0
        result = verify_layers(str(tmp_path), str(demand), layers="validators", profile="full")
    assert result["executed"] == 0 and result["reused"] == 1
    assert result["timings"]["execution_ms"] == 0
    assert (tmp_path / "runs.txt").read_text(encoding="utf-8") == "x"


def test_failed_command_is_not_reused_within_session(tmp_path: Path) -> None:
    command = [sys.executable, "-c", "from pathlib import Path; p=Path('runs.txt'); "
               "p.write_text((p.read_text() if p.exists() else '')+'x'); raise SystemExit(1)"]
    with execution_session():
        first = run_command(command, str(tmp_path), 30)
        second = run_command(command, str(tmp_path), 30)
    assert first["returncode"] == second["returncode"] == 1
    assert not second["execution_reused"]
    assert (tmp_path / "runs.txt").read_text(encoding="utf-8") == "xx"


def test_session_cache_distinguishes_inherited_environment(tmp_path: Path, monkeypatch) -> None:
    command = [sys.executable, "-c", "import os; from pathlib import Path; Path('runs.txt').write_text(os.environ['TEST_VERSION'])"]
    monkeypatch.setenv("TEST_VERSION", "first")
    with execution_session():
        assert run_command(command, str(tmp_path), 30)["returncode"] == 0
        monkeypatch.setenv("TEST_VERSION", "second")
        result = run_command(command, str(tmp_path), 30)
    assert not result["execution_reused"]
    assert (tmp_path / "runs.txt").read_text(encoding="utf-8") == "second"


def test_multilayer_verify_reports_validator_observations(tmp_path: Path) -> None:
    demand = _project(tmp_path)
    (demand / "demo.md").write_text("# Demo\n\n## TASK-001: Check\n- **Status**: done\n", encoding="utf-8")
    result = verify_layers(str(tmp_path), str(demand), layers="validators,e2e", profile="full")
    assert result["decision"] == "pass"
    assert result["execution_identities"]
    assert result["scope"]["layers"] == ["validators", "e2e"]
    assert result["timings"]["execution_ms"] > 0


def test_acceptance_execution_reports_phases_and_reuse(tmp_path: Path) -> None:
    demand = _project(tmp_path)
    (demand / "demo.md").write_text("# Demo\n\n## TASK-001: Check\n- **Status**: done\n", encoding="utf-8")
    manifest = demand / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({"schema": 3, "task_file": "demo.md", "checks": [{"id": "CHK-A",
        "command": [sys.executable, "check.py"], "cwd": ".", "timeout": 30,
        "inputs": ["app.py", "check.py"]}], "scenarios": [{"id": "S-A",
        "kind": "e2e", "owner": "TASK-001", "check": "CHK-A", "status": "planned",
        "command": [sys.executable, "check.py"]}]}),
        encoding="utf-8")
    first = run_manifest(str(manifest), str(tmp_path), write_evidence=True, owner="TASK-001", include_e2e=True)
    second = run_manifest(str(manifest), str(tmp_path), write_evidence=True, owner="TASK-001", include_e2e=True)
    assert first["decision"] == second["decision"] == "pass"
    assert (tmp_path / "runs.txt").read_text(encoding="utf-8") == "x"
    assert first["executed"] == 1 and second["executed"] == 0 and second["reused"] == 1
    assert first["selection_reason"] and second["reuse_reason"]
    assert "acceptance" in first["summary"]
    assert first["timings"]["execution_ms"] > 0
    assert second["timings"]["execution_ms"] == 0
    assert len(first["execution_identities"]) == 1
    assert second["execution_identities"] == []
    assert first["input_change_category"] == {"CHK-A": "no_baseline"}
    assert second["input_change_category"] == {"CHK-A": "unchanged"}
    combined = verify_layers(str(tmp_path), str(demand), layers="validators,e2e", profile="full")
    assert combined["decision"] == "pass", json.dumps(combined)
    assert combined["timings_scope"] == ["validators", "e2e"]
    assert combined["timings"]["elapsed_ms"] >= combined["layers"]["e2e"]["acceptance"]["timings"]["elapsed_ms"]
