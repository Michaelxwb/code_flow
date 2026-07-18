#!/usr/bin/env python3
"""S-13/E-11 integration coverage for Rule verifier execution."""

import hashlib
from pathlib import Path
import sys

import yaml


SCRIPTS = Path(__file__).resolve().parents[1] / "src" / "core" / "code-flow" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_metadata import load_spec_metadata
from cf_spec_verify import VerificationScope, evidence_is_fresh, run_all_verifiers


def _metadata(tmp_path: Path, verifiers: list[dict[str, object]], rules: list[tuple[str, str]]):
    frontmatter = {
        "id": "verify-rules",
        "description": "Verifier integration rules",
        "stages": ["code", "review"],
        "enforcement": "required",
        "verifiers": verifiers,
    }
    body = "\n".join(f"- [{rule_id}] {text}" for rule_id, text in rules)
    path = tmp_path / ".code-flow" / "specs" / "verify" / "rules.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"---\n{yaml.safe_dump(frontmatter, sort_keys=False)}---\n\n# Verify\n\n## Rules\n{body}\n",
        encoding="utf-8",
    )
    return load_spec_metadata(str(path))


def test_s_13_document_regex_ast_and_test_produce_fresh_evidence(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir(parents=True)
    source.write_text("def run():\n    return 1\n", encoding="utf-8")
    artifact = tmp_path / "design.md"
    artifact.write_text("## 3.5\nRULE-verify-001 is applied.\n", encoding="utf-8")
    artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    verifiers = [
        {
            "rule": "RULE-verify-001",
            "type": "document",
            "config": {
                "artifact": "design.md",
                "section_id": "3.5",
                "item_id": "RULE-verify-001",
                "artifact_sha256": artifact_hash,
            },
        },
        {
            "rule": "RULE-verify-002",
            "type": "regex",
            "config": {"pattern": "print\\(", "files": "src/*.py"},
        },
        {
            "rule": "RULE-verify-003",
            "type": "ast",
            "config": {"language": "python", "assertion": "forbid_call", "call": "eval"},
        },
        {
            "rule": "RULE-verify-004",
            "type": "test",
            "config": {
                "argv": [sys.executable, "-c", "import sys; sys.exit(0)"],
                "cwd": ".",
                "timeout": 1,
                "allowed_exit_codes": [0],
            },
        },
    ]
    rules = [(f"RULE-verify-{index:03d}", f"Rule {index}") for index in range(1, 5)]
    metadata = _metadata(tmp_path, verifiers, rules)
    scope = VerificationScope(str(tmp_path), ("src/app.py",), "d" * 64)

    result = run_all_verifiers(metadata, scope)

    assert result.passed is True
    assert [item.status for item in result.evidence] == ["verified"] * 4
    assert all(item.rule_text_sha256 for item in result.evidence)
    assert all(item.result_sha256 for item in result.evidence)
    assert result.evidence[0].artifact_sha256 == artifact_hash
    assert result.evidence[1].diff_sha256 == "d" * 64
    assert all(
        evidence_is_fresh(
            item,
            item.rule_text_sha256,
            item.artifact_sha256,
            item.diff_sha256,
        )
        for item in result.evidence
    )


def test_e_11_failures_are_unverified_and_stale_hash_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir(parents=True)
    source.write_text("print('debug')\n", encoding="utf-8")
    verifiers = [
        {
            "rule": "RULE-verify-001",
            "type": "regex",
            "config": {"pattern": "print\\(", "files": "src/*.py"},
        },
        {
            "rule": "RULE-verify-002",
            "type": "ast",
            "config": {"language": "javascript", "assertion": "parse"},
        },
        {
            "rule": "RULE-verify-003",
            "type": "command",
            "config": {
                "argv": [sys.executable, "-c", "import time; time.sleep(0.2)"],
                "cwd": ".",
                "timeout": 0.01,
                "allowed_exit_codes": [0],
            },
        },
    ]
    rules = [(f"RULE-verify-{index:03d}", f"Rule {index}") for index in range(1, 4)]
    metadata = _metadata(tmp_path, verifiers, rules)

    result = run_all_verifiers(metadata, VerificationScope(str(tmp_path), ("src/app.py",), "d" * 64))

    assert result.passed is False
    assert [item.status for item in result.evidence] == ["unverified"] * 3
    assert [item.error_code for item in result.evidence] == [
        "regex_violation",
        "unsupported_ast_language",
        "verifier_timeout",
    ]
    first = result.evidence[0]
    assert evidence_is_fresh(first, "changed-rule-hash", first.artifact_sha256, first.diff_sha256) is False


def test_regex_ignores_deleted_and_unmatched_scope_files(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    metadata = _metadata(
        tmp_path,
        [{"rule": "RULE-verify-001", "type": "regex", "config": {"pattern": "print\\(", "files": "src/*.py"}}],
        [("RULE-verify-001", "No print calls")],
    )
    scope = VerificationScope(
        str(tmp_path),
        ("src/app.py", "src/deleted.py", "docs/deleted.md"),
        "d" * 64,
    )

    result = run_all_verifiers(metadata, scope)

    assert result.passed is True
    assert result.evidence[0].details["checked_files"] == 1
