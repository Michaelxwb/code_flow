#!/usr/bin/env python3
"""E-09/B-04 integration coverage for migration preflight and staging."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_migrate import preflight, stage_plan


SPEC = """---
id: app-rules
description: Application rules
stages: [design, plan, code]
enforcement: required
verifiers:
  - rule: RULE-app-001
    type: test
    config:
      argv: [python3, -m, pytest]
---
# App
## Rules
- [RULE-app-001] Keep application compatible.
"""


def _tree_hash(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def _project(tmp_path: Path, version: str = "0.5.2") -> Path:
    flow = tmp_path / ".code-flow"
    (flow / "specs/app").mkdir(parents=True)
    (flow / "specs/app/rules.md").write_text(SPEC, encoding="utf-8")
    (flow / ".version").write_text(version, encoding="utf-8")
    (flow / "config.yml").write_text(yaml.safe_dump({"path_mapping": {"app": {"patterns": ["src/*"], "specs": [{"path": "app/rules.md"}]}}}), encoding="utf-8")
    date = flow / "tasks/2026-07-18"
    date.mkdir(parents=True)
    for name in ("demo.prd.md", "demo.frontend.design.md", "demo.backend.design.md", "demo.md"):
        (date / name).write_text(f"# {name}\n", encoding="utf-8")
    archived = flow / "tasks/archived/2025-01-01/old.md"
    archived.parent.mkdir(parents=True)
    archived.write_bytes(b"archived bytes\x00")
    return tmp_path


def test_e_09_preflight_groups_longest_suffix_without_writes(tmp_path: Path) -> None:
    root = _project(tmp_path)
    before = _tree_hash(root)
    result = preflight(str(root))
    assert _tree_hash(root) == before
    assert result["source_package_version"] == "0.5.2"
    assert result["target_package_version"] == "0.6.0"
    transforms = result["layout_transforms"]
    assert {item["demand"] for item in transforms} == {"demo"}
    assert len(transforms[0]["files"]) == 4
    assert transforms[0]["target"].endswith("/2026-07-18/demo")
    assert result["ready"] is True


def test_b_04_archived_is_hash_only_and_future_version_blocks(tmp_path: Path) -> None:
    root = _project(tmp_path, "0.7.0")
    archived = root / ".code-flow/tasks/archived/2025-01-01/old.md"
    digest = hashlib.sha256(archived.read_bytes()).hexdigest()
    result = preflight(str(root))
    assert result["archived"] == [{"path": ".code-flow/tasks/archived/2025-01-01/old.md", "sha256": digest, "active": False}]
    assert "future_version" in {item["code"] for item in result["unresolved"]}
    assert all("archived" not in item["target"] for item in result["layout_transforms"])


def test_preflight_reports_missing_verifier_and_target_conflict(tmp_path: Path) -> None:
    root = _project(tmp_path)
    spec = root / ".code-flow/specs/app/rules.md"
    spec.write_text(SPEC.replace("verifiers:", "verifiers_disabled:", 1), encoding="utf-8")
    target = root / ".code-flow/tasks/2026-07-18/demo"
    target.mkdir()
    (target / "demo.md").write_text("different", encoding="utf-8")
    result = preflight(str(root))
    codes = {item["code"] for item in result["unresolved"]}
    assert {"invalid_spec", "target_conflict"} <= codes
    assert result["ready"] is False


def test_preflight_cli_stdout_is_one_json_and_zero_write(tmp_path: Path) -> None:
    root = _project(tmp_path, "0.4.2")
    before = _tree_hash(root)
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "cf_spec_migrate.py"), "preflight", "--root", str(root), "--json"],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["source_package_version"] == "0.4.2"
    assert result.stderr == ""
    assert _tree_hash(root) == before


def test_s_09_stage_transformer_writes_only_staging(tmp_path: Path) -> None:
    root = _project(tmp_path)
    plan = preflight(str(root))
    staging = tmp_path / "outside-staging"
    staging.mkdir()
    before = _tree_hash(root)

    manifest = stage_plan(plan, str(staging))

    after = _tree_hash(root)
    assert {path: after[path] for path in before} == before
    target = staging / ".code-flow/tasks/2026-07-18/demo"
    assert (target / "demo.prd.md").exists()
    context = yaml.safe_load((target / "spec-context.yml").read_text(encoding="utf-8"))
    assert context["version"] == 1
    assert context["task"] == "demo"
    config = yaml.safe_load((staging / ".code-flow/config.yml").read_text(encoding="utf-8"))
    assert config["spec_workflow"]["schema_version"] == 1
    assert manifest["targets"]
    assert ".code-flow/.inject-state" in manifest["deletions"]
    archived = staging / ".code-flow/tasks/archived/2025-01-01/old.md"
    assert archived.read_bytes() == b"archived bytes\x00"


def test_b_03_unresolved_plan_writes_nothing_to_staging(tmp_path: Path) -> None:
    root = _project(tmp_path, "0.7.0")
    plan = preflight(str(root))
    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(ValueError, match="unresolved"):
        stage_plan(plan, str(staging))
    assert list(staging.iterdir()) == []
