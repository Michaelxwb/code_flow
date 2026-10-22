from pathlib import Path
import json
import socket
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_runner import run_manifest
import pytest


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
    assert injected["CF_WORKTREE_ID"] == tmp_path.name
    assert injected["CF_TASK_ID"] == "TASK-008"
    assert injected["CF_RUN_ID"]
    assert int(injected["CF_PORT_OFFSET"]) >= 10000
    assert tmp_path.name.lower().replace("-", "_") in injected["CF_DB_SUFFIX"]
    assert json.loads(shared_out.read_text(encoding="utf-8")) == {}, "shared 环境不得注入命名空间"
    saved = json.loads(manifest.read_text(encoding="utf-8"))["scenarios"]
    assert saved[0]["evidence"]["run_id"] == injected["CF_RUN_ID"], "证据 run_id 与子进程一致"


def test_shared_env_scope_is_never_parallel_safe() -> None:
    from cf_worktree_env import effective_parallel_safe

    assert effective_parallel_safe({"env_scope": "shared", "parallel_safe": True}) is False
    assert effective_parallel_safe({"env_scope": "shared"}) is False
    assert effective_parallel_safe({"env_scope": "isolated"}) is True
    assert effective_parallel_safe({"env_scope": "isolated", "parallel_safe": False}) is False
