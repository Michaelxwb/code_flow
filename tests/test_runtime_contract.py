"""Public commands and the runtime transaction use real filesystem/process boundaries."""
import json
import os
from pathlib import Path
import subprocess
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "src/cli.js"


def cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["node", str(CLI), *args], cwd=root, text=True,
                          capture_output=True, timeout=40, env=dict(os.environ))


def install(root: Path, platform: str = "codex") -> None:
    result = cli(root, "init", f"--platform={platform}")
    assert result.returncode == 0, result.stderr + result.stdout


def test_npm_package_validates_source_install_with_macos_metadata(tmp_path: Path) -> None:
    source, project, packed = [tmp_path / name for name in ("source", "project", "packed")]
    source.mkdir()
    project.mkdir()
    packed.mkdir()
    shutil.copy2(ROOT / "package.json", source / "package.json")
    shutil.copytree(ROOT / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__"))
    (source / "src/adapters/claude/commands/.DS_Store").write_bytes(b"Finder metadata")
    for platform in ("claude", "codex", "costrict", "opencode"):
        result = subprocess.run(["node", str(source / "src/cli.js"), "init", f"--platform={platform}"],
                                cwd=project, capture_output=True, text=True, timeout=40)
        assert result.returncode == 0, result.stderr + result.stdout
    manifest = json.loads((project / ".code-flow/.runtime-install.json").read_text())
    assert not any(path.endswith(".DS_Store") for path in manifest["files"])
    result = subprocess.run(["npm", "pack", "--ignore-scripts", "--json"], cwd=source,
                            capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stderr
    archive = source / json.loads(result.stdout)[0]["filename"]
    subprocess.run(["tar", "-xzf", str(archive), "-C", str(packed)], check=True,
                   capture_output=True, text=True, timeout=40)
    result = subprocess.run(["node", str(packed / "package/src/cli.js"), "spec", "validate", "--help"],
                            cwd=project, capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()


def old_install(root: Path) -> None:
    install(root)
    (root / ".code-flow/.version").write_text("0.6.11\n")
    (root / ".code-flow/runtime-commands.json").unlink()
    (root / ".code-flow/.runtime-install.json").unlink()
    (root / ".agents/skills/cf-spec/SKILL.md").write_text("OLD SKILL")
    hooks = root / ".codex/hooks.json"
    data = json.loads(hooks.read_text())
    for event, groups in data["hooks"].items():
        for group in groups:
            if "matcher" in group:
                group["matcher"] = "Edit|Write|MultiEdit"
            for hook in group["hooks"]:
                hook["command"] = "python3 .code-flow/scripts/cf_pre_tool_hook.py"
    data["hooks"]["PreToolUse"][0]["hooks"].append({"type": "command", "command": "echo custom"})
    hooks.write_text(json.dumps(data))
    (root / "AGENTS.md").write_text((root / "AGENTS.md").read_text() + "\nUser rule: KEEP\n")


def test_every_public_command_uses_its_real_parser(tmp_path: Path) -> None:
    install(tmp_path)
    commands = json.loads((tmp_path / ".code-flow/runtime-commands.json").read_text())["commands"]
    for command in commands:
        result = cli(tmp_path, *command.split(), "--help")
        assert result.returncode == 0, (command, result.stderr)
        assert "usage:" in result.stdout.lower(), command
        assert result.stdout.startswith(f"usage: code-flow {command.split()[0]} "), (command, result.stdout)
        assert ".py" not in result.stdout.split("\n\n", 1)[0], (command, result.stdout)
        import shlex
        arguments = shlex.split(commands[command]["example_args"])
        for argument in arguments:
            if argument.startswith("--"):
                assert argument in result.stdout, (command, argument)
    invalid = cli(tmp_path, "spec", "validate", "--task-dir", "missing", "--root", str(tmp_path))
    assert invalid.returncode == 2
    assert "unrecognized arguments: --root" in invalid.stderr
    unknown = cli(tmp_path, "spec", "unknown")
    assert unknown.returncode == 2 and "Repair:" not in unknown.stderr


def test_drift_blocks_execution_and_migration_repairs_it(tmp_path: Path) -> None:
    install(tmp_path)
    target = tmp_path / ".code-flow/scripts/cf_spec_context.py"
    target.write_text("raise RuntimeError('must never execute')")
    result = cli(tmp_path, "spec", "validate", "--task-dir", "missing")
    assert result.returncode == 3
    assert "drifted" in result.stderr and "must never execute" not in result.stderr
    repair = cli(tmp_path, "migrate", "--runtime", "--apply")
    assert repair.returncode == 0, repair.stdout
    assert cli(tmp_path, "spec", "validate", "--help").returncode == 0


def test_runtime_migration_preserves_user_content_and_rolls_back(tmp_path: Path) -> None:
    old_install(tmp_path)
    originals = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert cli(tmp_path, "init", "--platform=codex").returncode == 3
    preview = cli(tmp_path, "migrate", "--runtime", "--dry-run")
    assert preview.returncode == 0, preview.stdout
    assert json.loads(preview.stdout)["status"] == "previewed"
    preview_dir = tmp_path / ".code-flow/migrations" / json.loads(preview.stdout)["migration_id"]
    assert not (preview_dir / "staging").exists()
    assert not (preview_dir / "backup").exists()
    assert (preview_dir / "journal.json").is_file()
    assert (tmp_path / ".code-flow/.version").read_text().strip() == "0.6.11"
    result = cli(tmp_path, "migrate", "--runtime", "--apply")
    assert result.returncode == 0, result.stdout
    data = json.loads(result.stdout)
    assert data["status"] == "committed"
    hooks = (tmp_path / ".codex/hooks.json").read_text()
    assert "echo custom" in hooks and "cf_codex_hook.py" in hooks
    assert "cf_pre_tool_hook.py" not in hooks
    assert "User rule: KEEP" in (tmp_path / "AGENTS.md").read_text()
    assert cli(tmp_path, "task", "finish", "--help").returncode == 0
    assert json.loads(cli(tmp_path, "migrate", "--runtime", "--apply").stdout)["status"] == "already_migrated"
    rollback = cli(tmp_path, "migrate", "--runtime", "--rollback", data["migration_id"])
    assert rollback.returncode == 4, rollback.stdout
    for relative, content in originals.items():
        assert (tmp_path / relative).read_bytes() == content, relative
    assert not (tmp_path / ".code-flow/runtime-commands.json").exists()


def test_newer_runtime_cannot_be_downgraded(tmp_path: Path) -> None:
    install(tmp_path)
    (tmp_path / ".code-flow/.version").write_text("99.0.0\n")
    for action in ("--dry-run", "--apply"):
        result = cli(tmp_path, "migrate", "--runtime", action)
        assert result.returncode != 0
        assert "Refusing runtime downgrade" in result.stdout + result.stderr
    assert (tmp_path / ".code-flow/.version").read_text() == "99.0.0\n"
    assert not (tmp_path / ".code-flow/.runtime-migration.lock").exists()
    assert not (tmp_path / ".code-flow/migrations").exists()


def test_usage_docs_only_expose_public_runtime_commands() -> None:
    text = (ROOT / "docs/USAGE.md").read_text()
    assert "python3 .code-flow/scripts/cf_feedback.py" not in text
    assert "python3 .code-flow/scripts/cf_sync.py" not in text
    assert "code-flow feedback ignore" in text
    assert "code-flow sync apply" in text


def test_failed_transaction_restores_files_and_version(tmp_path: Path) -> None:
    old_install(tmp_path)
    before = (tmp_path / ".code-flow/scripts/cf_core.py").read_bytes()
    program = """
const fs = require('fs');
const original = fs.copyFileSync;
let failed = false;
const root = process.argv[1];
fs.copyFileSync = function(source, target) {
  if (!failed && target === root + '/.code-flow/scripts/cf_core.py') {
    failed = true;
    throw new Error('injected write failure');
  }
  return original(source, target);
};
const migration = require(process.argv[2]);
process.stdout.write(JSON.stringify(migration.run(root, ['--apply'])));
"""
    result = subprocess.run(["node", "-e", program, str(tmp_path), str(ROOT / "src/migrate/runtime.js")],
                            capture_output=True, text=True, timeout=40)
    assert json.loads(result.stdout)["status"] == "rolled_back", result.stderr
    assert (tmp_path / ".code-flow/scripts/cf_core.py").read_bytes() == before
    assert (tmp_path / ".code-flow/.version").read_text().strip() == "0.6.11"


def test_user_hook_changes_do_not_invalidate_managed_contract(tmp_path: Path) -> None:
    install(tmp_path)
    target = tmp_path / ".codex/hooks.json"
    data = json.loads(target.read_text())
    data["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": "echo user"}]})
    target.write_text(json.dumps(data))
    assert cli(tmp_path, "stats", "--help").returncode == 0
    data["hooks"]["PreToolUse"][0]["matcher"] = "wrong"
    target.write_text(json.dumps(data))
    assert cli(tmp_path, "stats", "--help").returncode == 3


def test_interrupted_apply_requires_explicit_rollback(tmp_path: Path) -> None:
    old_install(tmp_path)
    before = (tmp_path / ".code-flow/scripts/cf_core.py").read_bytes()
    program = """
const fs = require('fs');
const original = fs.copyFileSync;
const root = process.argv[1];
fs.copyFileSync = function(source, target) {
  const result = original(source, target);
  if (target === root + '/.code-flow/scripts/cf_core.py') process.exit(76);
  return result;
};
require(process.argv[2]).run(root, ['--apply']);
"""
    result = subprocess.run(["node", "-e", program, str(tmp_path), str(ROOT / "src/migrate/runtime.js")],
                            capture_output=True, text=True, timeout=40)
    assert result.returncode == 76
    owner = json.loads((tmp_path / ".code-flow/.runtime-migration.lock/owner.json").read_text())
    assert cli(tmp_path, "migrate", "--runtime", "--apply").returncode == 3
    rollback = cli(tmp_path, "migrate", "--runtime", "--rollback", owner["id"])
    assert rollback.returncode == 4, rollback.stdout
    assert (tmp_path / ".code-flow/scripts/cf_core.py").read_bytes() == before
    assert (tmp_path / ".code-flow/.version").read_text().strip() == "0.6.11"


def test_all_installed_platforms_upgrade_together(tmp_path: Path) -> None:
    old_install(tmp_path)
    # A second platform is present from an earlier installation.
    import shutil
    shutil.copytree(ROOT / "src/adapters/claude/commands", tmp_path / ".claude/commands")
    shutil.copyfile(ROOT / "src/adapters/claude/settings.local.json", tmp_path / ".claude/settings.local.json")
    skill = tmp_path / ".claude/commands/cf-spec.md"
    skill.write_text("STALE CLAUDE")
    result = cli(tmp_path, "migrate", "--runtime", "--apply")
    assert result.returncode == 0, result.stdout
    assert set(json.loads(result.stdout)["platforms"]) == {"claude", "codex"}
    assert "code-flow spec validate" in skill.read_text()
    assert cli(tmp_path, "spec", "validate", "--help").returncode == 0


def test_public_start_native_edit_finish_and_review(tmp_path: Path) -> None:
    from test_audit_mainline_e2e import _repo
    import shutil
    install(tmp_path)
    shutil.rmtree(tmp_path / ".code-flow/specs")
    (tmp_path / "test_value.py").write_text("from src.app import VALUE\n\ndef test_value():\n    assert VALUE == 1\n")
    root, task_dir = _repo(tmp_path)
    for task in ("TASK-001", "TASK-002"):
        start = subprocess.run(["node", str(CLI), "task", "start", "--root", str(root),
                                "--task-dir", str(task_dir), "--task-file", str(task_dir / "work.md"),
                                "--task", task, "--json"], input='{"owned_paths":[]}', cwd=root,
                               capture_output=True, text=True, timeout=40)
        assert start.returncode == 0 and json.loads(start.stdout)["ok"], start.stdout + start.stderr
        event = {"cwd": str(root), "session_id": "public-mainline", "hook_event_name": "PreToolUse",
                 "tool_name": "apply_patch", "tool_input": {"command":
                 "*** Begin Patch\n*** Update File: src/app.py\n@@\n-VALUE = 1\n+VALUE = 1\n+# touch\n*** End Patch"}}
        hook = root / ".code-flow/scripts/cf_codex_hook.py"
        pre = subprocess.run(["python3", str(hook)], input=json.dumps(event), cwd=root,
                             text=True, capture_output=True, timeout=10)
        assert "TASK" in json.loads(pre.stdout)["hookSpecificOutput"]["additionalContext"]
        (root / "src/app.py").write_text(f"VALUE = 1\n# {task}\n")
        event.update(hook_event_name="PostToolUse", tool_response="Success. Updated the following files:\nM src/app.py")
        post = subprocess.run(["python3", str(hook)], input=json.dumps(event), cwd=root,
                              text=True, capture_output=True, timeout=10)
        assert post.returncode == 0 and "systemMessage" not in post.stdout, post.stdout + post.stderr
        if task == "TASK-001":
            (root / "src/app.py").write_text("VALUE = 2\n")
            rejected = cli(root, "task", "finish", "--root", str(root), "--task-dir", str(task_dir), "--task", task, "--json")
            assert rejected.returncode != 0 and (root / ".code-flow/.active-task.json").exists()
            (root / "src/app.py").write_text(f"VALUE = 1\n# {task}\n")
        finish = cli(root, "task", "finish", "--root", str(root), "--task-dir", str(task_dir), "--task", task, "--json")
        assert finish.returncode == 0, finish.stdout + finish.stderr
        assert not (root / ".code-flow/.active-task.json").exists()
        subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", task], cwd=root, check=True, capture_output=True)
    review = cli(root, "task", "verify-e2e", "--root", str(root), "--task-dir", str(task_dir), "--json")
    assert review.returncode == 0, review.stdout + review.stderr
    assert (task_dir / "work.md").read_text().count("- **Status**: verified") == 2


def test_skill_examples_are_generated_and_contain_no_direct_script_calls() -> None:
    import re
    files = [p for p in (ROOT / "src/adapters").rglob("*.md")
             if "skills" in p.parts or "commands" in p.parts]
    for path in files:
        assert not re.search(r"python3\s+\.code-flow/scripts/cf_\w+\.py", path.read_text())
    program = """
const fs = require('fs');
const render = require(process.argv[1]).render;
for (const file of process.argv.slice(2)) {
  const content = fs.readFileSync(file, 'utf8');
  if (render(content) !== content) throw new Error('Generated examples have drifted: ' + file);
}
"""
    result = subprocess.run(["node", "-e", program, str(ROOT / "src/render-runtime-contract.js"),
                             *map(str, files)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_real_parallel_worktree_has_an_independent_native_installation(tmp_path: Path) -> None:
    from test_cf_task_parallel import _repo, TASK_FILE
    root = _repo(tmp_path)
    install(root)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "install runtime"], cwd=root, check=True, capture_output=True)
    prepared = cli(root, "task", "parallel", "prepare", "--root", str(root),
                   "--task-file", TASK_FILE, "--tasks", "TASK-001", "--run-id", "native", "--json")
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    worktree = Path(json.loads(prepared.stdout)["worktrees"][0]["path"])
    assert (worktree / ".code-flow/.runtime-install.json").is_file()
    assert cli(worktree, "stats", "--help").returncode == 0
    event = {"cwd": str(worktree), "session_id": "worktree-native", "hook_event_name": "UserPromptSubmit", "prompt": "hello"}
    native = subprocess.run(["python3", str(worktree / ".code-flow/scripts/cf_codex_hook.py")],
                            cwd=worktree, input=json.dumps(event), text=True, capture_output=True, timeout=10)
    assert native.returncode == 0 and "systemMessage" not in native.stdout, native.stdout + native.stderr
    assert not (root / ".code-flow/.session-log.jsonl").exists()
