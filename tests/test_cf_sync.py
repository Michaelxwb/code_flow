#!/usr/bin/env python3
"""cf-sync dual-copy sync tool coverage."""

import io
from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_sync import _included, main


def _repo(tmp_path: Path) -> Path:
    core = tmp_path / "src/core/code-flow"
    (core / "scripts").mkdir(parents=True)
    (core / "scripts/a.py").write_text("A = 1\n", encoding="utf-8")
    live = tmp_path / ".code-flow"
    (live / "scripts").mkdir(parents=True)
    (live / "scripts/a.py").write_text("A = 2\n", encoding="utf-8")
    (live / "scripts/b.py").write_text("B = 1\n", encoding="utf-8")  # deploy-only within prefix
    return tmp_path


def test_include_prefixes() -> None:
    assert _included("scripts/a.py", ("scripts/",))
    assert _included("hooks.json", ("hooks.json",))
    assert _included("commands/cf-spec.md", ("commands/",))
    assert _included("anything.md", ("*",))
    assert not _included("tasks/x.md", ("scripts/",))
    assert not _included("specs/cli/a.md", ("scripts/",))


def test_check_reports_drift(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    out = io.StringIO()

    code = main(["check", "--root", str(root)], stdout=out)

    assert code == 1
    assert ".code-flow/scripts/a.py" in out.getvalue()


def test_sync_copies_canonical_and_preserves_deploy_only(tmp_path: Path) -> None:
    root = _repo(tmp_path)

    main(["sync", "--root", str(root)], stdout=io.StringIO())

    assert (root / ".code-flow/scripts/a.py").read_text(encoding="utf-8") == "A = 1\n"
    assert (root / ".code-flow/scripts/b.py").exists(), "deploy-only files must survive sync"
    assert main(["check", "--root", str(root)], stdout=io.StringIO()) == 0


def test_pycache_in_source_is_never_copied(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    cache = root / "src/core/code-flow/scripts/__pycache__"
    cache.mkdir(parents=True)
    (cache / "cf_core.cpython-39.pyc").write_bytes(b"x")

    main(["sync", "--root", str(root)], stdout=io.StringIO())

    assert not (root / ".code-flow/scripts/__pycache__").exists()


def test_project_owned_trees_are_not_synced(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "src/core/code-flow/specs/shared").mkdir(parents=True)
    (root / "src/core/code-flow/specs/shared/template.md").write_text("t", encoding="utf-8")

    main(["sync", "--root", str(root)], stdout=io.StringIO())

    assert not (root / ".code-flow/specs/shared/template.md").exists()
