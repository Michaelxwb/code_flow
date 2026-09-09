#!/usr/bin/env python3
"""[S-10] 路由收敛与统计线性化回归测试。"""
import sys
import time
from pathlib import Path

import yaml


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

from cf_spec_resolver import resolve_candidates  # noqa: E402
from cf_spec_router import _read_candidates  # noqa: E402
from cf_stats import _violation_fixed, violation_fixed_batch  # noqa: E402


def _spec(spec_id: str) -> str:
    return (
        "---\nid: %s\ndescription: d\nstages: [code]\nenforcement: advisory\n"
        "verifiers:\n  - rule: RULE-x-001\n    type: manual\n"
        "    config:\n      checklist: review\n      owner: anyone\n"
        "---\n\n# R %s BODY\n## Rules\n- [RULE-x-001] Be good.\n" % (spec_id, spec_id)
    )


def _project(tmp_path: Path) -> Path:
    (tmp_path / ".code-flow/specs/cli").mkdir(parents=True)
    (tmp_path / ".code-flow/specs/cli/cli.md").write_text(_spec("cli-a"), encoding="utf-8")
    (tmp_path / ".code-flow/specs/db").mkdir(parents=True)
    (tmp_path / ".code-flow/specs/db/db.md").write_text(_spec("db-a"), encoding="utf-8")
    (tmp_path / ".code-flow/specs/shared").mkdir(parents=True)
    (tmp_path / ".code-flow/specs/shared/base.md").write_text(_spec("shared-a"), encoding="utf-8")
    config = {
        "spec_workflow": {"schema_version": 1, "enforcement": "required"},
        "path_mapping": {
            "cli": {"patterns": ["src/cli/*"], "specs": [{"path": "cli/cli.md"}]},
            "db": {"patterns": ["src/db/*"], "specs": [{"path": "db/db.md"}]},
            "shared": {"specs": [{"path": "shared/base.md"}]},
        },
    }
    (tmp_path / ".code-flow/config.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    return tmp_path


def test_unmatched_path_specs_are_not_global(tmp_path: Path) -> None:
    """路径未命中且域有 patterns 时标 unmatched，而非 global。"""
    root = _project(tmp_path)
    by_id = {c.spec_id: c for c in resolve_candidates(str(root), "code", ["src/cli/app.py"])}
    assert by_id["cli-a"].scope == "path"
    assert by_id["db-a"].scope == "unmatched"
    assert by_id["shared-a"].scope == "global"


def test_router_injects_only_global_and_path(tmp_path: Path) -> None:
    """注入只含真 global + path 命中（字符量收敛）。"""
    root = _project(tmp_path)
    result = _read_candidates(str(root), ["src/cli/app.py"])
    assert "db-a BODY" not in result.text
    assert "cli-a BODY" in result.text
    assert "shared-a BODY" in result.text
    assert "db-a" not in result.specs


def test_batch_matches_single_and_runs_linear(tmp_path: Path) -> None:
    """批量判定与逐个一致；3000 事件 <1s。"""
    events = []
    for i in range(300):
        sid = f"s-{i % 7}"
        events.append({"event": "violation", "sid": sid, "data": {"file": "a.py", "check_id": "c1"}})
        events.append({"event": "edit", "sid": sid, "data": {"file": "a.py"}})
        if i % 3 == 0:
            events.append({"event": "violation", "sid": sid, "data": {"file": "a.py", "check_id": "c1"}})
    expected = [_violation_fixed(i, events) for i, e in enumerate(events) if e["event"] == "violation"]
    assert violation_fixed_batch(events) == expected
    big = events * 4  # ~3000+
    started = time.monotonic()
    violation_fixed_batch(big)
    assert time.monotonic() - started < 1.0
