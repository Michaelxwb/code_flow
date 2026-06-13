#!/usr/bin/env python3
"""Tests for cf_log.py — JSONL session log (TASK-001).

Requirement scenarios:
- happy path: append then read back, payload intact (incl. Chinese)
- event-type filter and time window
- corrupt / blank lines skipped (RULE-05)
- 5MB rotation archives to sessions/YYYY-MM/ and read still sees both (B-02)
- unwritable target → append returns False, never raises (E-03)
- empty project (no log) → read returns []
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))
import cf_log


def test_append_then_read_roundtrip():
    with tempfile.TemporaryDirectory() as root:
        ok = cf_log.append_event(root, "violation", {"check_id": "no-print", "中文": "值"}, "s1")
        assert ok is True
        events = cf_log.read_events(root)
        assert len(events) == 1
        item = events[0]
        assert item["v"] == cf_log.SCHEMA_VERSION
        assert item["sid"] == "s1"
        assert item["event"] == "violation"
        assert item["data"]["中文"] == "值"


def test_event_type_filter():
    with tempfile.TemporaryDirectory() as root:
        cf_log.append_event(root, "edit", {"file": "a.py"}, "s1")
        cf_log.append_event(root, "violation", {"check_id": "x"}, "s1")
        cf_log.append_event(root, "edit", {"file": "b.py"}, "s1")
        edits = cf_log.read_events(root, events=("edit",))
        assert [e["data"]["file"] for e in edits] == ["a.py", "b.py"]


def test_corrupt_and_blank_lines_skipped():
    with tempfile.TemporaryDirectory() as root:
        cf_log.append_event(root, "edit", {"file": "a.py"}, "s1")
        with open(cf_log.log_path(root), "a", encoding="utf-8") as f:
            f.write("{broken json\n\n[1,2,3]\n")
        cf_log.append_event(root, "edit", {"file": "b.py"}, "s1")
        events = cf_log.read_events(root)
        assert [e["data"]["file"] for e in events] == ["a.py", "b.py"]


def test_rotation_archives_and_read_spans_archive():
    with tempfile.TemporaryDirectory() as root:
        cf_log.append_event(root, "edit", {"file": "old.py"}, "s1")
        # inflate live file past the limit, then append triggers rotation
        with open(cf_log.log_path(root), "a", encoding="utf-8") as f:
            f.write("x" * cf_log.MAX_BYTES + "\n")
        ok = cf_log.append_event(root, "edit", {"file": "new.py"}, "s1")
        assert ok is True
        sessions = os.path.join(root, ".code-flow", cf_log.SESSIONS_DIR)
        archived = [
            os.path.join(dp, n)
            for dp, _, names in os.walk(sessions)
            for n in names
        ]
        assert len(archived) == 1
        # live file only contains the post-rotation event
        with open(cf_log.log_path(root), encoding="utf-8") as f:
            live_lines = [l for l in f if l.strip()]
        assert len(live_lines) == 1
        # read spans archive + live (corrupt filler line skipped)
        files = [e["data"]["file"] for e in cf_log.read_events(root, events=("edit",))]
        assert files == ["old.py", "new.py"]


def test_append_unwritable_returns_false():
    with tempfile.TemporaryDirectory() as root:
        # occupy the .code-flow path with a *file* so makedirs/open must fail
        with open(os.path.join(root, ".code-flow"), "w") as f:
            f.write("not a dir")
        ok = cf_log.append_event(root, "edit", {"file": "a.py"}, "s1")
        assert ok is False


def test_read_empty_project_returns_empty():
    with tempfile.TemporaryDirectory() as root:
        assert cf_log.read_events(root) == []


def test_window_filters_old_events():
    with tempfile.TemporaryDirectory() as root:
        cf_log.append_event(root, "edit", {"file": "a.py"}, "s1")
        # forge an old event beyond any reasonable window
        old = {"v": 1, "ts": "2020-01-01T00:00:00", "sid": "s0", "event": "edit", "data": {"file": "old.py"}}
        with open(cf_log.log_path(root), "a", encoding="utf-8") as f:
            f.write(json.dumps(old) + "\n")
        files = [e["data"]["file"] for e in cf_log.read_events(root, days=30)]
        assert files == ["a.py"]
