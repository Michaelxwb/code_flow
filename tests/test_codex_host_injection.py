"""Opt-in real Codex host test using deterministic localhost model responses."""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import threading
from typing import Iterator

import pytest
from test_codex_native_hook import _project

ROOT = Path(__file__).resolve().parents[1]
MODEL = "code-flow-hook-test"
PATCH = "*** Begin Patch\n*** Add File: src/host-probe.py\n+VALUE = 2\n*** End Patch"
CACHE = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "models_cache.json"
pytestmark = pytest.mark.skipif(
    os.environ.get("CODE_FLOW_HOST_TESTS") != "1" or not shutil.which("codex") or not CACHE.is_file(),
    reason="requires explicit CODE_FLOW_HOST_TESTS=1, Codex CLI and its existing model metadata cache",
)


def _model_metadata() -> dict[str, object]:
    """Reuse host-compatible public metadata, without account configuration."""
    model = dict(json.loads(CACHE.read_text())["models"][0])
    model.update(slug=MODEL, tool_mode=None, node_repl_disabled=True, use_responses_lite=False)
    return model


def _response(first: bool) -> dict[str, object]:
    if first:
        item = {"type": "custom_tool_call", "id": "ctc_test", "call_id": "call_test",
                "name": "apply_patch", "input": PATCH}
    else:
        item = {"type": "message", "id": "msg_test", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": "Finished.", "annotations": []}]}
    return {"id": "resp_test", "object": "response", "model": MODEL, "status": "completed",
            "output": [item], "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}


@contextmanager
def _model_server() -> Iterator[tuple[int, list[dict[str, object]]]]:
    metadata = _model_metadata()
    requests: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"models": [metadata]}).encode())

        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(payload)
            response = _response(len(requests) == 1)
            events = [
                {"type": "response.created", "response": dict(response, status="in_progress", output=[])},
                {"type": "response.output_item.done", "output_index": 0, "item": response["output"][0]},
                {"type": "response.completed", "response": response},
            ]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for event in events:
                self.wfile.write(("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode())
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_port, requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=1)


def _host_args(root: Path, port: int) -> list[str]:
    command = shlex.join([sys.executable, str(ROOT / "src/core/code-flow/scripts/cf_codex_hook.py")])
    hook = '[{matcher="^apply_patch$",hooks=[{type="command",command=' + json.dumps(command) + ',timeout=5}]}]'
    config = [
        f'model="{MODEL}"', 'model_provider="hooktest"', 'web_search="disabled"',
        'model_providers.hooktest.name="Local hook test"',
        f'model_providers.hooktest.base_url="http://127.0.0.1:{port}/v1"',
        'model_providers.hooktest.wire_api="responses"',
        'model_providers.hooktest.requires_openai_auth=false', "hooks.PreToolUse=" + hook,
    ]
    args = ["codex", "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
            "--skip-git-repo-check", "--json", "--dangerously-bypass-hook-trust",
            "-s", "workspace-write", "-C", str(root), "--enable", "hooks"]
    for value in config:
        args.extend(("-c", value))
    return args + ["Exercise the deterministic injected patch call."]


@pytest.mark.parametrize("blocked", [False, True])
def test_real_codex_host_obeys_pre_tool_decision(tmp_path: Path, blocked: bool) -> None:
    _project(tmp_path)
    if blocked:
        (tmp_path / ".code-flow/.active-task.json").write_text("{}")
    with _model_server() as (port, requests):
        result = subprocess.run(_host_args(tmp_path, port), input="", cwd=tmp_path,
                                capture_output=True, text=True, timeout=40, check=False)
    assert result.returncode == 0, result.stderr + result.stdout
    assert len(requests) >= 2
    assert any(tool.get("name") == "apply_patch" for tool in requests[0]["tools"])
    target = tmp_path / "src/host-probe.py"
    assert target.exists() is not blocked
    if blocked:
        assert "Command blocked by PreToolUse hook: SPEC_WORKFLOW_BLOCKED" in result.stderr
    else:
        assert target.read_text() == "VALUE = 2\n"
