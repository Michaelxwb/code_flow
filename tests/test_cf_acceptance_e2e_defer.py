#!/usr/bin/env python3
"""Test E2E scenario deferral in acceptance workflow."""

import json
import sys
from pathlib import Path
import tempfile

sys.path.insert(0, str(Path(__file__).parent.parent / ".code-flow" / "scripts"))

from cf_acceptance_manifest import extract_manifest, _kind
from cf_acceptance_runner import run_manifest


def test_e2e_kind_mapping():
    """E2E level maps to e2e kind, not functional."""
    assert _kind("E2E") == "e2e"
    assert _kind("e2e") == "e2e"
    assert _kind("unit") == "functional"
    assert _kind("integration") == "functional"
    assert _kind("manual") == "manual"


def test_e2e_deferred_by_default():
    """E2E scenarios return e2e_deferred status when include_e2e=False."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Create manifest with mixed scenarios
        manifest = {
            "schema": 1,
            "task_sha256": "abc123",
            "scenarios": [
                {"id": "S-01", "kind": "functional", "command": ["echo", "unit"]},
                {"id": "E-01", "kind": "e2e", "command": ["echo", "e2e"]},
                {"id": "B-01", "kind": "manual"},
            ]
        }

        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        # Run without E2E
        result = run_manifest(str(manifest_path), str(root), write_evidence=False, include_e2e=False)

        assert result["decision"] == "pass"
        statuses = {r["id"]: r["status"] for r in result["results"]}
        assert statuses["S-01"] == "passed"
        assert statuses["E-01"] == "e2e_deferred"
        assert statuses["B-01"] == "manual_pending"


def test_e2e_executed_when_enabled():
    """E2E scenarios execute when include_e2e=True."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        manifest = {
            "schema": 1,
            "task_sha256": "abc123",
            "scenarios": [
                {"id": "E-01", "kind": "e2e", "command": ["echo", "e2e"]},
            ]
        }

        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        # Run with E2E enabled
        result = run_manifest(str(manifest_path), str(root), write_evidence=False, include_e2e=True)

        assert result["decision"] == "pass"
        assert result["results"][0]["status"] == "passed"


def test_e2e_failure_blocks_when_enabled():
    """Failed E2E scenarios block the gate when include_e2e=True."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        manifest = {
            "schema": 1,
            "task_sha256": "abc123",
            "scenarios": [
                {"id": "E-01", "kind": "e2e", "command": ["false"]},
            ]
        }

        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        result = run_manifest(str(manifest_path), str(root), write_evidence=False, include_e2e=True)

        assert result["decision"] == "block"
        assert result["results"][0]["status"] == "failed"


if __name__ == "__main__":
    test_e2e_kind_mapping()
    test_e2e_deferred_by_default()
    test_e2e_executed_when_enabled()
    test_e2e_failure_blocks_when_enabled()
    print("All E2E deferral tests passed")
