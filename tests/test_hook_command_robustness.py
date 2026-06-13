#!/usr/bin/env python3
"""Regression tests for hook command robustness (cwd-independent resolution).

Bug: hook commands resolved the script path via `git rev-parse || pwd` at
runtime. When the hook process cwd was outside the project repo, python3
failed with exit 2, which blocks UserPromptSubmit / PreToolUse in Claude
Code. Commands must now resolve via $CLAUDE_PROJECT_DIR (fallback: git
toplevel), guard on script existence, and no-op with exit 0 otherwise.
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TEMPLATES = {
    "claude": ROOT / "src" / "adapters" / "claude" / "settings.local.json",
    "costrict": ROOT / "src" / "adapters" / "costrict" / "settings.local.json",
    "codex": ROOT / "src" / "adapters" / "codex" / "hooks.json",
}

STUB = (
    "import os, json\n"
    "print(json.dumps({'cwd': os.getcwd()}))\n"
)


def _commands(template_path: Path) -> list:
    data = json.loads(template_path.read_text(encoding="utf-8"))
    cmds = []
    for groups in data["hooks"].values():
        for group in groups:
            for hook in group["hooks"]:
                cmds.append(hook["command"])
    return cmds


def _env_without_project_dir() -> dict:
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    return env


def _run(cmd: str, cwd: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["/bin/sh", "-c", cmd], cwd=cwd, env=env,
        capture_output=True, text=True, timeout=10,
    )


def _make_project(root: Path) -> Path:
    scripts = root / ".code-flow" / "scripts"
    scripts.mkdir(parents=True)
    for name in (
        "cf_inject_hook.py", "cf_session_hook.py", "cf_user_prompt_hook.py",
        "cf_post_hook.py", "cf_stop_hook.py",
    ):
        (scripts / name).write_text(STUB, encoding="utf-8")
    return root


def _command_for(template_path: Path, script_name: str) -> str:
    for cmd in _commands(template_path):
        if script_name in cmd:
            return cmd
    raise AssertionError(f"{script_name} not registered in {template_path}")


def test_templates_are_valid_json_with_guarded_commands() -> None:
    for platform, path in TEMPLATES.items():
        for cmd in _commands(path):
            assert "CLAUDE_PROJECT_DIR" in cmd, f"{platform}: missing env var resolution"
            assert "git rev-parse --show-toplevel" in cmd, f"{platform}: missing git fallback"
            assert 'if [ -f "$f" ]' in cmd, f"{platform}: missing existence guard"
            assert 'cd "$d"' in cmd, f"{platform}: missing cd to project root"


def test_noop_outside_any_project() -> None:
    # Regression: previously exit 2 ("can't open file") blocked the prompt.
    env = _env_without_project_dir()
    with tempfile.TemporaryDirectory() as tmp:
        for platform, path in TEMPLATES.items():
            for cmd in _commands(path):
                result = _run(cmd, tmp, env)
                assert result.returncode == 0, f"{platform}: {result.stderr}"
                assert result.stdout == "", f"{platform}: unexpected stdout noise"


def test_noop_when_project_dir_lacks_code_flow() -> None:
    env = _env_without_project_dir()
    with tempfile.TemporaryDirectory() as tmp:
        env["CLAUDE_PROJECT_DIR"] = tmp
        for path in TEMPLATES.values():
            for cmd in _commands(path):
                result = _run(cmd, tmp, env)
                assert result.returncode == 0, result.stderr
                assert result.stdout == ""


def test_resolves_via_claude_project_dir_from_foreign_cwd() -> None:
    env = _env_without_project_dir()
    with tempfile.TemporaryDirectory() as proj, tempfile.TemporaryDirectory() as elsewhere:
        project = _make_project(Path(proj))
        env["CLAUDE_PROJECT_DIR"] = str(project)
        cmd = _command_for(TEMPLATES["claude"], "cf_inject_hook.py")
        result = _run(cmd, elsewhere, env)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        # cd "$d" must make the script run from the project root
        assert os.path.realpath(payload["cwd"]) == os.path.realpath(proj)


def test_resolves_via_git_toplevel_without_env() -> None:
    env = _env_without_project_dir()
    with tempfile.TemporaryDirectory() as tmp:
        project = _make_project(Path(tmp))
        subprocess.run(
            ["git", "init", "-q"], cwd=tmp, check=True, capture_output=True,
        )
        subdir = project / "src" / "deep"
        subdir.mkdir(parents=True)
        cmd = _command_for(TEMPLATES["codex"], "cf_session_hook.py")
        result = _run(cmd, str(subdir), env)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert os.path.realpath(payload["cwd"]) == os.path.realpath(tmp)
