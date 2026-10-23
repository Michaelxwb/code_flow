from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import time

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_runner import run_manifest
from cf_evidence_store import EvidenceStore
import pytest

RUNNER = SCRIPTS / "cf_acceptance_runner.py"


def _closed_port() -> int:
    """A real, currently-closed TCP port (bound then released)."""
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _service_probe(port: int) -> list[str]:
    """Real service probe: exit 0 only if the TCP endpoint accepts connections."""
    code = (
        "import socket, sys\n"
        "sock = socket.socket()\n"
        "sock.settimeout(1.0)\n"
        f"sys.exit(0 if sock.connect_ex(('127.0.0.1', {port})) == 0 else 1)\n"
    )
    return [sys.executable, "-c", code]


def test_runner_executes_functional_and_reports_manual(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "S-01", "kind": "functional", "command": [sys.executable, "-c", "pass"]},
        {"id": "E-01", "kind": "manual"},
    ]}), encoding="utf-8")
    result = run_manifest(str(manifest), str(tmp_path))
    assert result["decision"] == "pass"
    assert [item["status"] for item in result["results"]] == ["passed", "manual_pending"]


def test_runner_blocks_failed_command(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "S-01", "kind": "e2e_smoke", "command": [sys.executable, "-c", "raise SystemExit(2)"]},
    ]}), encoding="utf-8")
    assert run_manifest(str(manifest), str(tmp_path))["decision"] == "block"


def test_runner_blocks_unconfigured_automated_case_when_execution_is_enabled(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "S-01", "kind": "functional"},
        {"id": "S-02", "kind": "functional", "command": [sys.executable, "-c", "pass"]},
    ]}), encoding="utf-8")
    assert run_manifest(str(manifest), str(tmp_path))["decision"] == "block"


def test_runner_rejects_dependency_cycle(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "S-01", "kind": "functional", "depends_on": ["S-02"]},
        {"id": "S-02", "kind": "functional", "depends_on": ["S-01"]},
    ]}), encoding="utf-8")
    with pytest.raises(ValueError, match="dependency cycle"):
        run_manifest(str(manifest), str(tmp_path))


def _git(root: Path, *args: str) -> None:
    import subprocess
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)


def _git_repo(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    # 测试产物应被忽略：ignored 文件不参与内容指纹（与真实项目一致）
    (tmp_path / ".gitignore").write_text("*.txt\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")


def test_verified_scenario_reused_when_content_unchanged(tmp_path: Path) -> None:
    """[perf] 内容未变的已验证场景跨运行复用，不重复执行 E2E。"""
    _git_repo(tmp_path)
    marker = tmp_path / "runs.txt"
    command = [sys.executable, "-c",
               f"from pathlib import Path; p=Path({str(marker)!r}); "
               "p.write_text((p.read_text() if p.exists() else '') + 'x')"]
    manifest_dir = tmp_path / ".code-flow"
    manifest_dir.mkdir(exist_ok=True)
    manifest = manifest_dir / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "E-01", "kind": "e2e", "owner": "TASK-001", "command": command,
         "cwd": ".", "timeout": 30, "depends_on": [], "status": "planned"},
    ]}), encoding="utf-8")

    first = run_manifest(str(manifest), str(tmp_path), write_evidence=True, only_e2e=True)
    assert first["decision"] == "pass"
    assert marker.read_text(encoding="utf-8") == "x", "首次必须真实执行"

    second = run_manifest(str(manifest), str(tmp_path), write_evidence=True, only_e2e=True)
    assert second["decision"] == "pass"
    assert second["results"][0].get("cache_reused") is True, second
    assert marker.read_text(encoding="utf-8") == "x", "内容未变不得重复执行"

    saved = json.loads(manifest.read_text(encoding="utf-8"))["scenarios"][0]
    assert saved["status"] == "verified"
    assert len(saved["runs"]) == 1, "复用不得新增运行记录"


def test_content_change_invalidates_acceptance_cache(tmp_path: Path) -> None:
    """工作树内容变化必须使复用失效并重跑 E2E。"""
    _git_repo(tmp_path)
    marker = tmp_path / "runs.txt"
    command = [sys.executable, "-c",
               f"from pathlib import Path; p=Path({str(marker)!r}); "
               "p.write_text((p.read_text() if p.exists() else '') + 'x')"]
    manifest_dir = tmp_path / ".code-flow"
    manifest_dir.mkdir(exist_ok=True)
    manifest = manifest_dir / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "E-01", "kind": "e2e", "owner": "TASK-001", "command": command,
         "cwd": ".", "timeout": 30, "depends_on": [], "status": "planned"},
    ]}), encoding="utf-8")

    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True, only_e2e=True)["decision"] == "pass"
    (tmp_path / "src/app.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True, only_e2e=True)["decision"] == "pass"
    assert marker.read_text(encoding="utf-8") == "xx", "内容变化后必须重跑"


def test_no_cache_flag_forces_reexecution(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    marker = tmp_path / "runs.txt"
    command = [sys.executable, "-c",
               f"from pathlib import Path; p=Path({str(marker)!r}); "
               "p.write_text((p.read_text() if p.exists() else '') + 'x')"]
    manifest_dir = tmp_path / ".code-flow"
    manifest_dir.mkdir(exist_ok=True)
    manifest = manifest_dir / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "E-01", "kind": "e2e", "owner": "TASK-001", "command": command,
         "cwd": ".", "timeout": 30, "depends_on": [], "status": "planned"},
    ]}), encoding="utf-8")
    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True, only_e2e=True)["decision"] == "pass"
    forced = run_manifest(str(manifest), str(tmp_path), write_evidence=True, only_e2e=True, use_cache=False)
    assert forced["decision"] == "pass"
    assert marker.read_text(encoding="utf-8") == "xx", "--no-cache 必须强制重跑"


def test_dependent_scenario_never_reuses_across_runs(tmp_path: Path) -> None:
    """依赖场景（depends_on）不复用：依赖副作用不在指纹内。"""
    _git_repo(tmp_path)
    marker = tmp_path / "dep-runs.txt"
    command = [sys.executable, "-c",
               f"from pathlib import Path; p=Path({str(marker)!r}); "
               "p.write_text((p.read_text() if p.exists() else '') + 'x')"]
    manifest_dir = tmp_path / ".code-flow"
    manifest_dir.mkdir(exist_ok=True)
    manifest = manifest_dir / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "S-01", "kind": "functional", "owner": "TASK-001", "command": command,
         "cwd": ".", "timeout": 30, "depends_on": [], "status": "planned"},
        {"id": "S-02", "kind": "functional", "owner": "TASK-001", "command": command,
         "cwd": ".", "timeout": 30, "depends_on": ["S-01"], "status": "planned"},
    ]}), encoding="utf-8")
    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True)["decision"] == "pass"
    assert run_manifest(str(manifest), str(tmp_path), write_evidence=True)["decision"] == "pass"
    # S-01 复用一次；S-02 因 depends_on 每次执行 → 首次 2 次 + 第二次 1 次 = 3
    assert marker.read_text(encoding="utf-8") == "xxx"


def test_runner_orders_dependencies_and_can_write_evidence(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    task = tmp_path / "task.md"
    task.write_text("## TASK-001: Demo\n", encoding="utf-8")
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "S-01", "kind": "functional", "command": [sys.executable, "-c", "pass"], "owner": "TASK-001"},
        {"id": "S-02", "kind": "functional", "depends_on": ["S-01"], "command": [sys.executable, "-c", "pass"]},
    ], "task_file": str(task)}), encoding="utf-8")
    result = run_manifest(str(manifest), str(tmp_path), write_evidence=True)
    assert result["decision"] == "pass"
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert all(item["status"] == "verified" for item in saved["scenarios"])
    assert "S-01: verified" in task.read_text(encoding="utf-8")


def test_only_e2e_does_not_reuse_functional_not_included_result(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    failing = [sys.executable, "-c", "raise SystemExit(7)"]
    manifest.write_text(json.dumps({"scenarios": [
        {"id": "S-01", "kind": "functional", "command": failing},
        {"id": "E-01", "kind": "e2e", "command": failing},
    ]}), encoding="utf-8")

    result = run_manifest(str(manifest), str(tmp_path), only_e2e=True)

    statuses = {item["id"]: item["status"] for item in result["results"]}
    assert statuses["S-01"] == "not_included"
    assert statuses["E-01"] == "failed"
    assert result["decision"] == "block"


def test_runner_executes_each_check_once_and_reports_checks(tmp_path: Path) -> None:
    """[S-03] v3 manifest：3 个场景共享 2 个 check，命令只执行 2 次。"""
    root = tmp_path
    (root / "src").mkdir()
    (root / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    marker = root / "runs.txt"
    command = [sys.executable, "-c",
               f"from pathlib import Path; p=Path({str(marker)!r}); "
               "p.write_text((p.read_text() if p.exists() else '') + 'x')"]
    manifest = root / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({
        "schema": 3,
        "checks": [
            {"id": "CHK-A", "command": command, "cwd": ".", "timeout": 30},
            {"id": "CHK-B", "command": command + ["--other"], "cwd": ".", "timeout": 30},
        ],
        "scenarios": [
            {"id": "S-01", "kind": "functional", "check": "CHK-A", "command": command,
             "cwd": ".", "timeout": 30, "depends_on": [], "status": "planned"},
            {"id": "S-02", "kind": "functional", "check": "CHK-A", "command": command,
             "cwd": ".", "timeout": 30, "depends_on": [], "status": "planned"},
            {"id": "S-03", "kind": "functional", "check": "CHK-B", "command": command + ["--other"],
             "cwd": ".", "timeout": 30, "depends_on": [], "status": "planned"},
        ],
    }), encoding="utf-8")
    result = run_manifest(str(manifest), str(root))
    assert result["decision"] == "pass"
    assert marker.read_text(encoding="utf-8") == "xx", "每个 check 只执行一次"
    assert len(result["checks"]) == 2
    assert [item["status"] for item in result["checks"]] == ["passed", "passed"]


def test_env_blocked_preflight_failure_marks_env_blocked_not_verified(tmp_path: Path) -> None:
    """[E-01] 真实服务探测失败 → env_blocked；不执行产品命令、不写 verified、不算产品 failed。"""
    marker = tmp_path / "product-ran.txt"
    product = [sys.executable, "-c",
               f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')"]
    probe = _service_probe(_closed_port())
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema": 3,
        "checks": [{
            "id": "CHK-ENV", "command": product, "cwd": ".", "timeout": 30,
            "env": "browser", "env_scope": "isolated", "parallel_safe": True,
            "preflight": [probe],
        }],
        "scenarios": [{
            "id": "E-01", "kind": "functional", "owner": "TASK-008", "check": "CHK-ENV",
            "command": product, "cwd": ".", "timeout": 30, "depends_on": [], "status": "planned",
        }],
    }), encoding="utf-8")

    result = run_manifest(str(manifest), str(tmp_path), write_evidence=True)

    assert result["decision"] == "block"
    item = result["results"][0]
    assert item["status"] == "env_blocked"
    assert item["owner"] == "TASK-008"
    assert item["missing"][0]["command"] == probe
    assert item["missing"][0]["exit_code"] == 1
    assert marker.exists() is False, "preflight 失败不得执行产品命令"
    assert result["env_blocked"] == 1
    detail = result["env_blocked_details"][0]
    assert detail["check_id"] == "CHK-ENV"
    assert detail["owner"] == "TASK-008"
    assert detail["command"] == product
    assert detail["missing"][0]["command"] == probe
    assert "env_blocked:CHK-ENV" in result["error"]
    assert "failed:" not in result["error"], "环境失败不得冒充产品失败"
    assert [check["status"] for check in result["checks"]] == ["env_blocked"]

    saved = json.loads(manifest.read_text(encoding="utf-8"))["scenarios"][0]
    assert saved["status"] == "env_blocked"
    assert saved["evidence"]["status"] == "env_blocked"
    assert saved["status"] != "verified"


def test_env_blocked_preflight_success_executes_check(tmp_path: Path) -> None:
    """[E-01] 真实服务在线时 preflight 通过，check 正常执行并 verified。"""
    marker = tmp_path / "product-ran.txt"
    product = [sys.executable, "-c",
               f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')"]
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    probe = _service_probe(port)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema": 3,
        "checks": [{"id": "CHK-ENV", "command": product, "cwd": ".", "timeout": 30,
                    "env_scope": "shared", "preflight": [probe]}],
        "scenarios": [{"id": "S-01", "kind": "functional", "owner": "TASK-008", "check": "CHK-ENV",
                       "command": product, "cwd": ".", "timeout": 30, "status": "planned"}],
    }), encoding="utf-8")
    try:
        result = run_manifest(str(manifest), str(tmp_path), write_evidence=True)
    finally:
        listener.close()

    assert result["decision"] == "pass", result
    assert result["env_blocked"] == 0
    assert marker.read_text(encoding="utf-8") == "ran"
    saved = json.loads(manifest.read_text(encoding="utf-8"))["scenarios"][0]
    assert saved["status"] == "verified"


def test_isolated_check_injects_worktree_namespace(tmp_path: Path) -> None:
    """[isolation] isolated check 注入命名空间；shared check 不注入。"""
    isolated_out = tmp_path / "isolated-env.json"
    shared_out = tmp_path / "shared-env.json"
    capture = (
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(sys.argv[1]).write_text(json.dumps({k: v for k, v in os.environ.items() if k.startswith('CF_')}))\n"
    )
    isolated = [sys.executable, "-c", capture, str(isolated_out)]
    shared = [sys.executable, "-c", capture, str(shared_out)]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema": 3,
        "checks": [
            {"id": "CHK-ISO", "command": isolated, "cwd": ".", "timeout": 30,
             "env": "db", "env_scope": "isolated"},
            {"id": "CHK-SHARED", "command": shared, "cwd": ".", "timeout": 30,
             "env": "browser", "env_scope": "shared"},
        ],
        "scenarios": [
            {"id": "S-01", "kind": "functional", "owner": "TASK-008", "check": "CHK-ISO",
             "command": isolated, "cwd": ".", "timeout": 30, "status": "planned"},
            {"id": "S-02", "kind": "functional", "owner": "TASK-008", "check": "CHK-SHARED",
             "command": shared, "cwd": ".", "timeout": 30, "status": "planned"},
        ],
    }), encoding="utf-8")

    result = run_manifest(str(manifest), str(tmp_path), write_evidence=True)

    assert result["decision"] == "pass", result
    injected = json.loads(isolated_out.read_text(encoding="utf-8"))
    assert injected["CF_WORKTREE_ID"].startswith(tmp_path.name)
    assert injected["CF_WORKTREE_ID"] != tmp_path.name, "namespace 必须包含路径哈希以避免跨批次碰撞"
    assert injected["CF_TASK_ID"] == "TASK-008"
    assert injected["CF_RUN_ID"]
    assert int(injected["CF_PORT_OFFSET"]) >= 10000
    assert tmp_path.name.lower().replace("-", "_") in injected["CF_DB_SUFFIX"]
    shared_env = json.loads(shared_out.read_text(encoding="utf-8"))
    namespace_keys = {"CF_WORKTREE_ID", "CF_RUN_ID", "CF_TASK_ID", "CF_PORT_OFFSET", "CF_DB_SUFFIX"}
    assert not (set(shared_env) & namespace_keys), "shared 环境不得注入 worktree 命名空间"
    saved = json.loads(manifest.read_text(encoding="utf-8"))["scenarios"]
    assert saved[0]["evidence"]["run_id"] == injected["CF_RUN_ID"], "证据 run_id 与子进程一致"


def test_shared_env_scope_is_never_parallel_safe() -> None:
    from cf_worktree_env import effective_parallel_safe

    assert effective_parallel_safe({"env_scope": "shared", "parallel_safe": True}) is False
    assert effective_parallel_safe({"env_scope": "shared"}) is False
    assert effective_parallel_safe({"env_scope": "isolated"}) is False
    assert effective_parallel_safe({"env_scope": "isolated", "parallel_safe": True}) is True
    assert effective_parallel_safe({"env_scope": "isolated", "parallel_safe": False}) is False


def _checkpoint_repo(root: Path) -> None:
    """A real git worktree so resume freshness is content-addressed."""
    root.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=root, check=True)
    subprocess.run(("git", "config", "user.email", "t@t"), cwd=root, check=True)
    subprocess.run(("git", "config", "user.name", "t"), cwd=root, check=True)
    (root / "src").mkdir()
    (root / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(("git", "add", "-A"), cwd=root, check=True)
    subprocess.run(("git", "commit", "-qm", "init"), cwd=root, check=True)


def _ledger_command(ledger: Path, index: int, signal_file: Path = Path()) -> list[str]:
    """Append the check index to a shared ledger; optionally SIGINT the runner."""
    armed = str(signal_file) if str(signal_file) else ""
    code = (
        "import os, signal, sys, time\n"
        "from pathlib import Path\n"
        f"ledger = Path({str(ledger)!r})\n"
        f"index = {index}\n"
        f"armed = Path({armed!r}) if {armed!r} else None\n"
        "if index == 6 and armed is not None and armed.exists():\n"
        "    armed.unlink()\n"
        "    os.kill(os.getppid(), signal.SIGINT)\n"
        "    time.sleep(2)\n"
        "with ledger.open('a', encoding='utf-8') as handle:\n"
        "    handle.write(f'{index}\\n')\n"
    )
    return [sys.executable, "-c", code]


def _write_check_manifest(path: Path, commands: list[list[str]]) -> None:
    checks = []
    scenarios = []
    for index, command in enumerate(commands, start=1):
        check_id = f"CHK-{index:02d}"
        checks.append({"id": check_id, "command": command, "cwd": ".", "timeout": 30})
        scenarios.append({
            "id": f"S-{index:02d}",
            "kind": "functional",
            "owner": "TASK-007",
            "check": check_id,
            "command": command,
            "cwd": ".",
            "timeout": 30,
            "depends_on": [],
            "status": "planned",
        })
    path.write_text(json.dumps({"schema": 3, "checks": checks, "scenarios": scenarios}), encoding="utf-8")


def _runner_call(manifest: Path, root: Path, *extra: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS)}
    return subprocess.run(
        [sys.executable, str(RUNNER), "--manifest", str(manifest), "--root", str(root), *extra],
        capture_output=True, text=True, env=env, timeout=60,
    )


def test_resume_continues_after_interrupted_checkpoints(tmp_path: Path) -> None:
    """[S-04] 第 6 个 check 中断；resume 复用 1-5 并从第 6 个继续。"""
    root = tmp_path / "repo"
    _checkpoint_repo(root)
    ledger = tmp_path / "ledger.txt"
    armed = tmp_path / "armed"
    armed.write_text("1", encoding="utf-8")
    commands = [
        _ledger_command(ledger, index, armed if index == 6 else Path())
        for index in range(1, 11)
    ]
    manifest = root / ".code-flow/.acceptance-manifest.json"
    manifest.parent.mkdir()
    _write_check_manifest(manifest, commands)

    first = _runner_call(manifest, root, "--write-evidence")
    assert first.stdout.strip(), first.stderr
    payload = json.loads(first.stdout)
    assert first.returncode != 0
    assert payload["decision"] == "block"
    assert payload.get("interrupted") is True, payload
    assert [item["status"] for item in payload["results"][:5]] == ["passed"] * 5
    assert all(item["status"] == "incomplete" for item in payload["results"][5:])
    assert ledger.read_text(encoding="utf-8").splitlines() == ["1", "2", "3", "4", "5"]

    saved = json.loads(manifest.read_text(encoding="utf-8"))["scenarios"]
    assert all(item["status"] == "planned" for item in saved), "中断不得写部分 verified"
    checkpoint_dir = EvidenceStore(str(root), manifest.parent.name).directory.parent / "_checkpoints"
    checkpoints = list(checkpoint_dir.glob("*.json"))
    assert len(checkpoints) == 1, checkpoints
    checkpoint = json.loads(checkpoints[0].read_text(encoding="utf-8"))
    assert len(checkpoint["checks"]) == 5, checkpoint

    second = _runner_call(manifest, root, "--write-evidence", "--resume")
    assert second.stdout.strip(), second.stderr
    resumed = json.loads(second.stdout)
    assert second.returncode == 0, resumed
    assert resumed["decision"] == "pass", resumed
    assert [item.get("cache_reused") for item in resumed["results"][:5]] == [True] * 5
    assert all(item["status"] == "passed" for item in resumed["results"][5:])
    assert resumed["reused"] == 5
    assert ledger.read_text(encoding="utf-8").splitlines() == [str(index) for index in range(1, 11)]
    saved = json.loads(manifest.read_text(encoding="utf-8"))["scenarios"]
    assert [item["status"] for item in saved] == ["verified"] * 10


def test_deadline_incomplete_marks_unstarted_checks_without_failed_or_verified(tmp_path: Path) -> None:
    """[B-04] 全局 deadline 到期返回 incomplete；不标 failed/verified。"""
    slow_marker = tmp_path / "slow.txt"
    late_marker = tmp_path / "late.txt"
    slow = [
        sys.executable, "-c",
        "import time\n"
        "from pathlib import Path\n"
        "time.sleep(0.6)\n"
        f"Path({str(slow_marker)!r}).write_text('ran')\n",
    ]
    fast = [
        sys.executable, "-c",
        f"from pathlib import Path; Path({str(late_marker)!r}).write_text('ran')\n",
    ]
    manifest = tmp_path / ".acceptance-manifest.json"
    _write_check_manifest(manifest, [slow, fast, fast, fast])

    started = time.monotonic()
    result = run_manifest(str(manifest), str(tmp_path), write_evidence=True, deadline=started + 0.25)
    elapsed = time.monotonic() - started

    assert result["decision"] == "block"
    assert [item["status"] for item in result["results"]] == ["incomplete"] * 4
    assert result["incomplete"] == 4
    assert result["failed"] == []
    assert result["error"].startswith("incomplete:")
    assert [item["status"] for item in result["checks"]] == ["incomplete"] * 4
    assert elapsed < 2.0
    assert slow_marker.exists() is False, "deadline 到期必须终止正在运行的 check"
    assert late_marker.exists() is False, "deadline 后不得启动后续 check"

    saved = json.loads(manifest.read_text(encoding="utf-8"))["scenarios"]
    assert all(item.get("status") not in ("verified", "failed") for item in saved), saved


def test_independent_checks_parallelize_but_dependencies_serialize(tmp_path: Path) -> None:
    """[parallel] 独立 isolated check 并行；depends_on 串行。"""
    stamps = tmp_path / "stamps"
    stamps.mkdir()
    code = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "start = time.time()\n"
        "time.sleep(float(sys.argv[2]))\n"
        "Path(sys.argv[1]).write_text(f'{start} {time.time()}')\n"
    )

    def command(name: str, delay: float) -> list[str]:
        return [sys.executable, "-c", code, str(stamps / f"{name}.txt"), str(delay)]

    first, second, third = command("a", 0.5), command("b", 0.2), command("c", 0.05)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema": 3,
        "checks": [
            {"id": "CHK-A", "command": first, "env_scope": "isolated", "parallel_safe": True},
            {"id": "CHK-B", "command": second, "env_scope": "isolated", "parallel_safe": True},
            {"id": "CHK-C", "command": third, "env_scope": "isolated", "parallel_safe": True},
        ],
        "scenarios": [
            {"id": "S-A", "kind": "functional", "check": "CHK-A", "command": first},
            {"id": "S-B", "kind": "functional", "check": "CHK-B", "command": second},
            {"id": "S-C", "kind": "functional", "check": "CHK-C", "command": third,
             "depends_on": ["S-A"]},
        ],
    }), encoding="utf-8")

    result = run_manifest(str(manifest), str(tmp_path))

    assert result["decision"] == "pass", result
    assert [item["id"] for item in result["results"]] == ["S-A", "S-B", "S-C"]
    a_start, a_end = (float(value) for value in (stamps / "a.txt").read_text().split())
    b_start, b_end = (float(value) for value in (stamps / "b.txt").read_text().split())
    c_start, _ = (float(value) for value in (stamps / "c.txt").read_text().split())
    assert b_start < a_end and a_start < b_end, "独立 check 必须并行"
    assert c_start >= a_end, "depends_on 必须在依赖完成后串行执行"


def test_max_failures_stops_after_limit_and_keeps_completed_evidence(tmp_path: Path) -> None:
    """[max-failures] 达到上限后停止后续 check，已完成证据保留。"""
    ledger = tmp_path / "ledger.txt"
    passing = _ledger_command(ledger, 1)
    failing = [sys.executable, "-c",
               "from pathlib import Path\n"
               f"path = Path({str(ledger)!r})\n"
               "path.write_text((path.read_text() if path.exists() else '') + '2\\n', encoding='utf-8')\n"
               "raise SystemExit(3)\n"]
    later = [_ledger_command(ledger, index) for index in (3, 4)]
    manifest = tmp_path / ".acceptance-manifest.json"
    _write_check_manifest(manifest, [passing, failing, *later])

    result = run_manifest(str(manifest), str(tmp_path), write_evidence=True, max_failures=1)

    assert result["decision"] == "block"
    assert [item["status"] for item in result["results"]] == ["passed", "failed", "incomplete", "incomplete"]
    assert ledger.read_text(encoding="utf-8").splitlines() == ["1", "2"]
    assert result["failed"] == ["S-02"]
    assert result["incomplete"] == 2
    saved = json.loads(manifest.read_text(encoding="utf-8"))["scenarios"]
    assert saved[0]["status"] == "verified"
    assert saved[1]["status"] == "failed"
    assert all(item["status"] != "verified" for item in saved[2:])
    assert all("evidence" in item for item in saved[:2]), "已完成/失败的 check 必须保留证据"


def _per_check_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    _git_repo(tmp_path)
    (tmp_path / "src/b.py").write_text("OTHER = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "checks")
    return tmp_path, tmp_path / "a.marker", tmp_path / "b.marker"


def _marker_command(marker: Path) -> list[str]:
    return [sys.executable, "-c",
            f"from pathlib import Path; p=Path({str(marker)!r}); "
            "p.write_text((p.read_text() if p.exists() else '') + 'x')"]


def _per_check_manifest(root: Path, check_a: dict, check_b: dict) -> Path:
    manifest = root / ".acceptance-manifest.json"
    manifest.write_text(json.dumps({
        "schema": 3,
        "checks": [
            {"id": "CHK-A", "command": check_a["command"], "cwd": ".", "timeout": 30,
             "inputs": ["src/a.py"]},
            {"id": "CHK-B", "command": check_b["command"], "cwd": ".", "timeout": 30,
             "inputs": ["src/b.py"]},
        ],
        "scenarios": [
            {"id": "S-A", "kind": "functional", "check": "CHK-A",
             "command": check_a["command"], "cwd": ".", "timeout": 30,
             "depends_on": [], "status": "planned"},
            {"id": "S-B", "kind": "functional", "check": "CHK-B",
             "command": check_b["command"], "cwd": ".", "timeout": 30,
             "depends_on": [], "status": "planned"},
        ],
    }), encoding="utf-8")
    return manifest


def test_changed_input_reruns_only_affected_check(tmp_path: Path) -> None:
    root, marker_a, marker_b = _per_check_repo(tmp_path)
    manifest = _per_check_manifest(
        root,
        {"command": _marker_command(marker_a)},
        {"command": _marker_command(marker_b)},
    )
    assert run_manifest(str(manifest), str(root), write_evidence=True)["decision"] == "pass"
    (root / "src/a.py").write_text("VALUE = 2\n", encoding="utf-8")
    result = run_manifest(str(manifest), str(root), write_evidence=True)
    assert result["decision"] == "pass"
    assert marker_a.read_text(encoding="utf-8") == "xx"
    assert marker_b.read_text(encoding="utf-8") == "x"
    reused = {item["id"]: item.get("cache_reused") for item in result["results"]}
    assert reused == {"S-A": None, "S-B": True}


def test_unrelated_change_reuses_all_input_scoped_checks(tmp_path: Path) -> None:
    root, marker_a, marker_b = _per_check_repo(tmp_path)
    manifest = _per_check_manifest(
        root,
        {"command": _marker_command(marker_a)},
        {"command": _marker_command(marker_b)},
    )
    assert run_manifest(str(manifest), str(root), write_evidence=True)["decision"] == "pass"
    (root / "src/unrelated.py").write_text("NEW = 1\n", encoding="utf-8")
    result = run_manifest(str(manifest), str(root), write_evidence=True)
    assert result["decision"] == "pass"
    assert marker_a.read_text(encoding="utf-8") == "x"
    assert marker_b.read_text(encoding="utf-8") == "x"
    assert all(item.get("cache_reused") is True for item in result["results"])


def _risk_record(expires: str) -> dict[str, str]:
    return {
        "owner": "TASK-001",
        "reason": "known external limitation",
        "expires_at": expires,
        "confirmed_by": "user",
        "confirmed_at": "2026-01-01T00:00:00+00:00",
        "source": "user approved in chat",
    }


def test_accepted_risk_is_distinct_from_verified(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema": 3,
        "checks": [{
            "id": "CHK-RISK",
            "command": [sys.executable, "-c", "raise SystemExit(2)"],
            "cwd": ".", "timeout": 30,
            "accepted_risk": _risk_record("2999-01-01T00:00:00+00:00"),
        }],
        "scenarios": [{
            "id": "S-01", "kind": "functional", "owner": "TASK-001", "check": "CHK-RISK",
            "command": [sys.executable, "-c", "raise SystemExit(2)"],
            "cwd": ".", "timeout": 30, "status": "planned",
        }],
    }), encoding="utf-8")

    result = run_manifest(str(manifest), str(tmp_path), write_evidence=True)

    assert result["decision"] == "pass", result
    assert result["results"][0]["status"] == "accepted_risk"
    assert result["accepted_risk"] == 1
    assert result["accepted_risk_details"][0]["check_id"] == "CHK-RISK"
    saved = json.loads(manifest.read_text(encoding="utf-8"))["scenarios"][0]
    assert saved["status"] == "accepted_risk"
    assert saved["status"] != "verified"
    assert saved["evidence"]["status"] == "accepted_risk"
    assert "fingerprint" not in saved["evidence"]


def test_expired_accepted_risk_blocks(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema": 3,
        "checks": [{
            "id": "CHK-RISK",
            "command": [sys.executable, "-c", "raise SystemExit(2)"],
            "cwd": ".", "timeout": 30,
            "accepted_risk": _risk_record("2000-01-01T00:00:00+00:00"),
        }],
        "scenarios": [{
            "id": "S-01", "kind": "functional", "owner": "TASK-001", "check": "CHK-RISK",
            "command": [sys.executable, "-c", "raise SystemExit(2)"],
            "cwd": ".", "timeout": 30, "status": "planned",
        }],
    }), encoding="utf-8")
    result = run_manifest(str(manifest), str(tmp_path))
    assert result["decision"] == "block"
    assert result["results"][0]["status"] == "failed"
