"""Native OpenCode event RPC plus an isolated v2 host smoke test."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
from typing import Iterator
import urllib.request

import pytest
from test_codex_native_hook import _project

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "src/core/code-flow/scripts/cf_opencode_event.py"


def invoke(root: Path, kind: str, event: dict[str, object]) -> dict[str, object]:
    result = subprocess.run([sys.executable, str(ENTRY)], cwd=root,
                            input=json.dumps({"directory": str(root), "kind": kind, "event": event}),
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_native_event_shapes_and_failed_tools(tmp_path: Path) -> None:
    import cf_log
    _project(tmp_path)
    result = invoke(tmp_path, "session.prompt", {"sessionID": "native", "prompt": {"text": "review src/a.py"}})
    assert "RULE-python-001" in result["context"] and not result["blocked"]
    event = {"sessionID": "native", "tool": "write", "input": {"path": "src/a.py", "content": "debug"}}
    assert "error" not in invoke(tmp_path, "tool.before", event)
    result = invoke(tmp_path, "tool.after", dict(event, status="error", error={"message": "write failed"}))
    assert result == {"context": "", "blocked": False}
    assert not cf_log.read_events(str(tmp_path), events=("edit",))
    assert cf_log.read_events(str(tmp_path), events=("degrade",))
    result = invoke(tmp_path, "tool.after", dict(event, status="completed", result={"content": "native result"}))
    assert "Remove debug printing" in result["context"]
    assert cf_log.read_events(str(tmp_path), events=("edit",))[0]["data"]["tool"] == "write"
    assert "hookSpecificOutput" not in result and "systemMessage" not in result


def test_native_entry_rejects_aliases_and_invalid_install(tmp_path: Path) -> None:
    _project(tmp_path)
    result = invoke(tmp_path, "tool.before", {"sessionID": "native", "tool": "edit", "input": {"filePath": "src/a.py"}})
    assert "input.path" in result["error"]
    (tmp_path / ".code-flow/.active-task.json").write_text("{}")
    result = invoke(tmp_path, "session.idle", {"sessionID": "native"})
    assert result["blocked"] and "SPEC_WORKFLOW_BLOCKED" in result["context"]
    (tmp_path / ".code-flow/.version").write_text("damaged")
    result = invoke(tmp_path, "session.idle", {"sessionID": "native"})
    assert "version is inconsistent" in result["error"]


def test_rule_text_cannot_be_mistaken_for_a_blocking_decision(tmp_path: Path) -> None:
    _project(tmp_path)
    spec = tmp_path / ".code-flow/specs/scripts/rules.md"
    spec.write_text(spec.read_text() + "\nDiscuss SPEC_WORKFLOW_BLOCKED and 未绑定 required Spec.\n")
    event = {"sessionID": "native", "tool": "edit", "input": {"path": "src/a.py"}}
    result = invoke(tmp_path, "tool.before", event)
    assert "SPEC_WORKFLOW_BLOCKED" in result["context"]
    assert not result["blocked"]
    (tmp_path / ".code-flow/.active-task.json").write_text("{}")
    result = invoke(tmp_path, "tool.before", event)
    assert result["blocked"]


def test_native_scope_expansion_is_advisory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import cf_edit_service
    from cf_opencode_event import dispatch
    _project(tmp_path)
    monkeypatch.setattr(cf_edit_service, "_active_expansion", lambda root, path: ("new-required",))
    result = dispatch({"directory": str(tmp_path), "kind": "tool.before", "event": {
        "sessionID": "expansion", "tool": "edit", "input": {"path": "src/a.py"},
    }})
    assert "new-required" in result["context"]
    assert result["blocked"] is False


@contextmanager
def isolated_host(binary: str, root: Path) -> Iterator[tuple[str, str]]:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {key: value for key, value in os.environ.items()
           if not any(part in key.upper() for part in ("TOKEN", "API_KEY", "SECRET", "PASSWORD", "OPENCODE"))}
    for name, area in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                       ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state")):
        env[name] = str(root / ".isolated" / area)
    log = root / ".host-test.log"
    with log.open("w+") as output:
        log.chmod(0o600)
        server = subprocess.Popen([binary, "serve", "--hostname", "127.0.0.1", "--port", str(port)],
                                  cwd=root, env=env, stdout=output, stderr=output)
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                output.seek(0)
                match = re.search(r"server password (\S+)", output.read())
                if match:
                    auth = base64.b64encode(("opencode:" + match[1]).encode()).decode()
                    yield f"http://127.0.0.1:{port}", "Basic " + auth
                    return
                assert server.poll() is None, "isolated OpenCode host exited during startup"
                time.sleep(0.05)
            pytest.fail("isolated OpenCode host did not start within 8 seconds")
        finally:
            server.terminate()
            try:
                server.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=2)
            output.seek(0)
            output.truncate()
    log.unlink(missing_ok=True)


def request(base: str, auth: str, endpoint: str, body: dict[str, object] | None = None) -> dict[str, object]:
    req = urllib.request.Request(base + endpoint, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": auth, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def test_installed_plugin_loads_and_receives_real_v2_prompt(tmp_path: Path) -> None:
    binary = shutil.which("opencode2")
    if not binary:
        pytest.skip("OpenCode v2 host not installed")
    version = subprocess.run([binary, "--version"], text=True, capture_output=True, check=True).stdout
    if not version.startswith("opencode v2."):
        pytest.skip("installed host is not OpenCode v2")
    subprocess.run(["node", str(ROOT / "src/cli.js"), "init", "--platform=opencode"], cwd=tmp_path,
                   capture_output=True, text=True, check=True, timeout=30)
    with isolated_host(binary, tmp_path) as (base, auth):
        info = request(base, auth, "/api/session", {"location": {"directory": str(tmp_path)},
                       "model": {"providerID": "native-test-unavailable", "id": "disabled"}})
        sid = info["data"]["id"]
        request(base, auth, f"/api/session/{sid}/prompt", {"text": "review src/a.py"})
        from urllib.parse import urlencode
        plugins = request(base, auth, "/api/plugin?" + urlencode({"location[directory]": str(tmp_path)}))
        found = next(item for item in plugins["data"] if item["id"] == "code-flow")
        assert found["state"]["status"] == "active", found
        assert found["source"]["type"] == "local"
        events = [json.loads(line) for line in (tmp_path / ".code-flow/.session-log.jsonl").read_text().splitlines()]
        assert any(event["sid"] == sid and event["event"] == "inject" for event in events)
