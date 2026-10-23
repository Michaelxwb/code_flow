from pathlib import Path
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_check_inputs import check_input_hash, expand_inputs, match_path


def _repo(tmp_path: Path) -> Path:
    def git(*args: str) -> None:
        subprocess.run(("git", *args), cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (tmp_path / "a.py").write_text("A = 1\n", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/b.py").write_text("B = 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "init")
    return tmp_path


def test_double_star_matches_zero_directories(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    assert match_path("a.py", "**/*.py")
    assert match_path("pkg/b.py", "**/*.py")
    assert expand_inputs(str(root), ("**/*.py",)) == ("a.py", "pkg/b.py")


def test_check_without_inputs_falls_back_to_repo_scope(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = check_input_hash(str(root), {"command": ["true"]}, "repo-hash")
    assert result == {"input_hash": "repo-hash", "scope": "repo"}


def test_check_hash_changes_only_when_declared_input_changes(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    check = {"command": ["true"], "inputs": ["pkg/b.py"]}
    first = check_input_hash(str(root), check, "repo")["input_hash"]
    (root / "a.py").write_text("A = 2\n", encoding="utf-8")
    assert check_input_hash(str(root), check, "repo")["input_hash"] == first
    (root / "pkg/b.py").write_text("B = 2\n", encoding="utf-8")
    assert check_input_hash(str(root), check, "repo")["input_hash"] != first


def test_batch_hash_matches_union_and_isolates_checks(tmp_path: Path) -> None:
    from cf_check_inputs import check_input_hashes
    root = _repo(tmp_path)
    checks = {
        "A": {"command": ["true"], "inputs": ["a.py"]},
        "B": {"command": ["true"], "inputs": ["pkg/*.py"]},
        "R": {"command": ["true"]},
    }
    first = check_input_hashes(str(root), checks, "repo")
    assert first["A"]["scope"] == "inputs"
    assert first["B"]["scope"] == "inputs"
    assert first["R"] == {"input_hash": "repo", "scope": "repo"}
    (root / "pkg/b.py").write_text("B = 2\n", encoding="utf-8")
    second = check_input_hashes(str(root), checks, "repo")
    assert second["A"] == first["A"]
    assert second["B"] != first["B"]


def test_star_without_slash_matches_nested_paths(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    assert match_path("pkg/b.py", "*.py")
    assert expand_inputs(str(root), ("*.py",)) == ("a.py", "pkg/b.py")
