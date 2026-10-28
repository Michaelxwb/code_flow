"""Regression coverage for newline-safe transactions and real TASK discovery."""
from functools import partial
from pathlib import Path
import sys
from typing import Optional

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from codeflow.core import cf_fs
from codeflow.spec import cf_workflow_transaction as transaction
from codeflow.spec.cf_workflow_service import (
    WorkflowError, block_task, locate_task_file, resume_task, start_task,
)
from cf_task_workflow import finish_task, verify_layers
from test_audit_mainline_e2e import _git, _repo


def _windows_text_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """Emulate Windows' default text newline while retaining real file writes."""
    monkeypatch.setattr(cf_fs.tempfile, "NamedTemporaryFile", partial(
        cf_fs.tempfile.NamedTemporaryFile, newline="\r\n",
    ))


def _crlf_file(path: Path) -> None:
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))


def test_crlf_marker_supports_block_resume_and_finish(tmp_path: Path) -> None:
    root, directory = _repo(tmp_path)
    task = directory / "work.md"
    marker = root / ".code-flow/.active-task.json"
    start_task(str(root), str(directory), str(task), "TASK-001")
    _crlf_file(marker)
    assert block_task(str(root), str(directory), str(task), "TASK-001", "review")["ok"]
    _crlf_file(marker)
    assert resume_task(str(root), str(directory), str(task), "TASK-001")["ok"]
    _crlf_file(marker)
    (root / "src/app.py").write_text("VALUE = 1\n# verified change\n", encoding="utf-8")
    finished = finish_task(str(root), str(directory), str(task), "TASK-001")
    assert finished["decision"] == "pass", finished
    assert not marker.exists()
    assert "**Status**: done" in task.read_text(encoding="utf-8")


@pytest.mark.parametrize("text", ["first\nsecond\n", "first\r\nsecond\r\n"])
def test_atomic_text_preserves_bytes_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str,
) -> None:
    _windows_text_files(monkeypatch)
    target = tmp_path / "state.txt"
    cf_fs.atomic_write_text(target, text)
    assert target.read_bytes() == text.encode("utf-8")


@pytest.mark.parametrize("interrupted", [False, True], ids=["rollback", "recovery"])
def test_windows_start_transaction_preserves_exact_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupted: bool,
) -> None:
    directory = tmp_path / ".code-flow/tasks/demo"
    directory.mkdir(parents=True)
    task, context = directory / "demo.md", directory / "spec-context.yml"
    marker = tmp_path / ".code-flow/.active-task.json"
    journal = marker.parent / ".workflow-transition.json"
    before = ("draft\r\n", "context: old\r\n")
    after = ("in-progress\n", "context: new\n", '{"status": "active"}\n')
    task.write_bytes(before[0].encode("utf-8"))
    context.write_bytes(before[1].encode("utf-8"))
    _windows_text_files(monkeypatch)
    original = transaction._write

    def fail_marker(path: Path, value: Optional[str]) -> None:
        if path == marker and value is not None:
            if interrupted:
                raise KeyboardInterrupt()
            raise OSError("simulated full disk")
        original(path, value)

    monkeypatch.setattr(transaction, "_write", fail_marker)
    with pytest.raises(KeyboardInterrupt if interrupted else OSError):
        transaction.commit_transition(str(tmp_path), task, before[0], after[0], None, after[2],
                                      context_change=(context, before[1], after[1]))
    monkeypatch.setattr(transaction, "_write", original)
    assert journal.exists() == interrupted
    assert not marker.exists()
    if interrupted:
        assert transaction.recover_transition(str(tmp_path))
        assert marker.read_bytes() == after[2].encode("utf-8")
    expected = after if interrupted else before
    assert task.read_bytes() == expected[0].encode("utf-8")
    assert context.read_bytes() == expected[1].encode("utf-8")
    assert not journal.exists()
    assert not transaction.recover_transition(str(tmp_path))


def _finished_requirement(root: Path) -> tuple[Path, Path]:
    directory = root / ".code-flow/tasks/demo"
    directory.mkdir(parents=True)
    task = directory / "demo.md"
    task.write_text("# Tasks\n## TASK-001: Demo\n- **Status**: done\n"
                    "- **Spec-Refs**: N/A\n- **Acceptance-Refs**: N/A\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "finished requirement")
    return directory, task


@pytest.mark.parametrize(("filename", "example"), [
    ("demo.scenarios.md", "## TASK-001: Scenario description\n"),
    ("demo.scenarios.md", "```markdown\n## TASK-001: Example\n```\n"),
    ("notes.md", "```markdown\n## TASK-001: Example\n```\n"),
    ("notes.md", "Example heading: `## TASK-001: Demo`\n"),
])
def test_full_verification_ignores_non_task_examples(
    tmp_path: Path, filename: str, example: str,
) -> None:
    directory, task = _finished_requirement(tmp_path)
    (directory / filename).write_text(example, encoding="utf-8")
    result = verify_layers(str(tmp_path), str(directory), profile="full")
    assert result["decision"] == "pass", result
    assert all(layer["decision"] == "pass" for layer in result["layers"].values())
    assert locate_task_file(str(directory), "TASK-001") == task
    assert "**Status**: verified" in task.read_text(encoding="utf-8")


def test_task_discovery_still_rejects_real_duplicates(tmp_path: Path) -> None:
    directory, task = _finished_requirement(tmp_path)
    duplicate = directory / "other.md"
    duplicate.write_bytes(task.read_bytes())
    assert locate_task_file(str(directory), "TASK-001") is None
    with pytest.raises(ValueError, match="duplicate task id"):
        verify_layers(str(tmp_path), str(directory), profile="full")
    duplicate.unlink()
    task.write_bytes(task.read_bytes() * 2)
    with pytest.raises(WorkflowError, match="duplicate_task_id"):
        locate_task_file(str(directory), "TASK-001")
    assert "**Status**: verified" not in task.read_text(encoding="utf-8")
