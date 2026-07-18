#!/usr/bin/env python3
"""S-10/E-07 workflow metrics coverage."""

from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "src/core/code-flow/scripts"
sys.path.insert(0, str(SCRIPTS))

import cf_log
from cf_stats import spec_workflow_summary


def test_s_10_aggregates_stage_coverage_first_compliance_and_late_rate(tmp_path: Path) -> None:
    events = (
        ("spec_candidate", {"task": "demo", "stage": "design", "spec": "app", "rule": "R1"}),
        ("spec_bound", {"task": "demo", "stage": "design", "spec": "app", "rule": "R1"}),
        ("spec_applied", {"task": "demo", "stage": "design", "spec": "app", "rule": "R1"}),
        ("spec_read", {"task": "demo", "stage": "design", "spec": "app", "source": "align"}),
        ("spec_gate", {"task": "demo", "stage": "design", "rule": "R1", "decision": "pass", "first_pass": True}),
        ("spec_drift", {"task": "demo", "stage": "code", "spec": "app", "status": "stale"}),
        ("late_violation", {"task": "demo", "stage": "code", "rule": "R1", "expected_stage": "design"}),
    )
    for event, data in events:
        assert cf_log.append_event(str(tmp_path), event, data, "s1")

    summary = spec_workflow_summary(str(tmp_path))
    assert summary["coverage"] == "100%"
    assert summary["first_compliance_rate"] == "100%"
    assert summary["late_violation_rate"] == "100%"
    assert summary["statuses"]["stale"] == 1
    assert summary["read_note"] == "read 仅表示读取，不代表理解"


def test_e_07_metrics_degraded_marks_incomplete_data(tmp_path: Path) -> None:
    assert cf_log.append_event(str(tmp_path), "metrics_degraded", {"component": "spec_workflow", "reason": "readonly"}, "s1")
    summary = spec_workflow_summary(str(tmp_path))
    assert summary["data_complete"] is False
    assert summary["degraded_events"] == 1
