#!/usr/bin/env python3
"""Session activity log: JSONL event stream for the quality-loop feature.

Design contract (spec-quality-loop.design.md §3.3):
- One event per line: {"v", "ts", "sid", "event", "data"}.
- append is O(1) single-write; failures are swallowed (stderr only) so the
  hook protocol is never broken by logging (RULE-01 / E-03).
- Reads are line-tolerant: corrupt lines are skipped, never raised (RULE-05).
- Rotation: when the live file reaches MAX_BYTES it is archived to
  sessions/YYYY-MM/session-log-<ts>.jsonl and a fresh file starts (B-02).
"""
import json
import os
import sys
from datetime import datetime, timedelta

LOG_NAME = ".session-log.jsonl"
SESSIONS_DIR = "sessions"
MAX_BYTES = 5 * 1024 * 1024
SCHEMA_VERSION = 1

KNOWN_EVENTS = (
    "inject",
    "edit",
    "violation",
    "correction",
    "false_positive",
    "degrade",
    "stop_check",
    "spec_candidate",
    "spec_bound",
    "spec_applied",
    "spec_read",
    "spec_drift",
    "spec_gate",
    "late_violation",
    "metrics_degraded",
)


def _log(msg: str) -> None:
    sys.stderr.write(f"[cf-log] {msg}\n")


def log_path(project_root: str) -> str:
    return os.path.join(project_root, ".code-flow", LOG_NAME)


def _archive_dir(project_root: str, month: str) -> str:
    return os.path.join(project_root, ".code-flow", SESSIONS_DIR, month)


def _rotate_if_needed(project_root: str, path: str) -> None:
    try:
        if os.path.getsize(path) < MAX_BYTES:
            return
    except OSError:
        return
    now = datetime.now()
    month_dir = _archive_dir(project_root, now.strftime("%Y-%m"))
    os.makedirs(month_dir, exist_ok=True)
    target = os.path.join(
        month_dir, f"session-log-{now.strftime('%Y%m%dT%H%M%S')}.jsonl"
    )
    os.replace(path, target)


def append_event(project_root: str, event: str, data: dict, sid: str) -> bool:
    """Append one event line. Never raises; returns False on failure (E-03)."""
    try:
        path = log_path(project_root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _rotate_if_needed(project_root, path)
        line = json.dumps(
            {
                "v": SCHEMA_VERSION,
                "ts": datetime.now().isoformat(timespec="seconds"),
                "sid": sid,
                "event": event,
                "data": data or {},
            },
            ensure_ascii=False,
        )
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return True
    except Exception as exc:
        _log(f"append_event failed: {exc}")
        return False


def degrade(project_root: str, component: str, error: object, sid: str = "") -> None:
    """Record a degrade event (FEAT-02). Never raises — degrading the
    degrade-logger itself must stay invisible (RULE-01)."""
    append_event(
        project_root,
        "degrade",
        {"component": component, "error": str(error)[:200]},
        sid,
    )


def _candidate_files(project_root: str, days: int) -> list:
    """Live log + archived months overlapping the [now-days, now] window."""
    paths = []
    base = os.path.join(project_root, ".code-flow", SESSIONS_DIR)
    if os.path.isdir(base):
        cutoff = datetime.now() - timedelta(days=days)
        for month in sorted(os.listdir(base)):
            try:
                month_start = datetime.strptime(month, "%Y-%m")
            except ValueError:
                continue
            # keep a month if any part of it can fall inside the window
            if month_start >= cutoff.replace(day=1):
                month_dir = os.path.join(base, month)
                paths.extend(
                    os.path.join(month_dir, name)
                    for name in sorted(os.listdir(month_dir))
                    if name.endswith(".jsonl")
                )
    live = log_path(project_root)
    if os.path.exists(live):
        paths.append(live)
    return paths


def read_events(project_root: str, days: int = 30, events: tuple = ()) -> list:
    """Read events within the window, oldest first. Corrupt lines skipped."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    wanted = set(events) if events else None
    out = []
    for path in _candidate_files(project_root, days):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        item = json.loads(raw)
                    except Exception:
                        continue
                    if not isinstance(item, dict) or "event" not in item:
                        continue
                    if wanted is not None and item["event"] not in wanted:
                        continue
                    if str(item.get("ts", "")) < cutoff:
                        continue
                    out.append(item)
        except Exception as exc:
            _log(f"read_events skipped {path}: {exc}")
            continue
    return out
