#!/usr/bin/env python3
"""[S-09][E-09][E-10] 唯一 deadline 与 argv 执行收敛回归测试。

真实边界：真实子进程 + 真实 validator/Runner 入口。
"""
import sys
import time
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_acceptance_runner import run_manifest  # noqa: E402
from cf_stop_hook import run_validators  # noqa: E402


def _manifest(tmp_path: Path, command: list) -> str:
    import json

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"scenarios": [{"id": "S-01", "kind": "functional", "command": command}]}),
        encoding="utf-8",
    )
    return str(manifest)


def test_expired_deadline_never_executes(tmp_path: Path) -> None:
    """[S-09] 预算耗尽的场景不得执行，标 incomplete。"""
    marker = tmp_path / "ran.txt"
    code = "import sys; open(sys.argv[1], 'w').write('ran'); import time; time.sleep(5)"
    manifest = _manifest(tmp_path, [sys.executable, "-c", code, str(marker)])
    started = time.monotonic()
    from cf_acceptance_runner import run_manifest as run

    result = run(manifest, str(tmp_path), deadline=started - 1.0)
    assert result["decision"] == "block"
    assert result["results"][0]["status"] == "incomplete"
    assert not marker.exists(), "过期 deadline 不得启动子进程"
    assert time.monotonic() - started < 2.0


def test_validators_past_deadline_marked_incomplete(tmp_path: Path) -> None:
    """[E-09] 预算耗尽未跑的 validator 标 incomplete，不报 pass。"""
    validators = [
        {"name": "slow", "trigger": "**/*.py", "command": "python3 -c pass {files}", "timeout": 60000},
        {"name": "never", "trigger": "**/*.py", "command": "python3 -c pass {files}", "timeout": 60000},
    ]
    failures, truncated = run_validators(
        str(tmp_path), validators, ["a.py"], "sid", deadline=time.monotonic() - 1.0
    )
    assert truncated is True
    assert any(item.get("incomplete") for item in failures)
    assert all(item.get("name") in ("slow", "never") for item in failures)


def test_argv_handles_spaces_and_shell_metachars(tmp_path: Path) -> None:
    """[E-10] 文件名含空格/`$()` 时逐文件 argv 传递。"""
    weird = tmp_path / "src" / "a b.py"
    weird.parent.mkdir(parents=True)
    weird.write_text("VALUE = 1\n", encoding="utf-8")
    tricky = tmp_path / "src" / "x$(y).py"
    tricky.write_text("VALUE = 2\n", encoding="utf-8")
    validators = [
        {
            "name": "compile",
            "trigger": "**/*.py",
            "command": "python3 -m py_compile {files}",
            "timeout": 30000,
            "on_fail": "语法错误",
        }
    ]
    failures, truncated = run_validators(
        str(tmp_path), validators, ["src/a b.py", "src/x$(y).py"], "sid"
    )
    assert truncated is False
    assert failures == [], failures
