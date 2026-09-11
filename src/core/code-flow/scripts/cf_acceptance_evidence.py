"""Append execution history without erasing the user's acceptance contract."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence
from uuid import uuid4

STATES = frozenset(("planned", "pending", "tbd", "verified", "unverified", "failed", "incomplete", "not_configured", "e2e_deferred", "manual_pending"))


def scenario_line(line: str, scenario_id: str) -> bool:
    return bool(re.match(rf"^\s*(?:\|\s*|[-*]\s+){re.escape(scenario_id)}(?=\s*[:|])", line))


def line_status(line: str, scenario_id: str) -> str:
    if not scenario_line(line, scenario_id):
        return ""
    if line.lstrip().startswith("|"):
        cells = [cell.strip().lower() for cell in line.strip().strip("|").split("|")]
        return next((cell for cell in reversed(cells) if cell in STATES), "")
    match = re.match(r"^\s*[-*]\s+[^:]+:\s*([a-z0-9_]+)\b", line, re.I)
    return match.group(1).lower() if match and match.group(1).lower() in STATES else ""


def _status_line(line: str, scenario_id: str, status: str) -> str:
    if not scenario_line(line, scenario_id):
        return line
    if line.lstrip().startswith("|"):
        cells = line.split("|")
        for index in range(len(cells) - 1, 0, -1):
            if cells[index].strip().lower() in STATES:
                cells[index] = f" {status} "
                return "|".join(cells)
        return line.rstrip().rstrip("|") + f"| {status} |"
    prefix = r"(^\s*[-*]\s+[^:]+:\s*)"
    if line_status(line, scenario_id):
        return re.sub(prefix + r"(?:" + "|".join(sorted(STATES)) + r")\b", rf"\g<1>{status}", line, count=1, flags=re.I)
    return re.sub(prefix, rf"\g<1>{status} — ", line, count=1)


def _patch_section(section: str, scenario_id: str, status: str, record: str) -> str:
    contract = re.search(r"(?ms)^### Acceptance Contract[^\n]*\n(.*?)(?=^### |^## |\Z)", section)
    if contract:
        body = "\n".join(_status_line(line, scenario_id, status) for line in contract.group(1).splitlines()) + "\n"
        section = section[:contract.start(1)] + body + section[contract.end(1):]
    evidence = re.search(r"(?ms)^### Acceptance Evidence[^\n]*\n(.*?)(?=^### |^## |\Z)", section)
    if evidence:
        body = evidence.group(1)
        if record not in body.splitlines():
            body = body.rstrip() + "\n" + record + "\n\n"
        section = section[:evidence.start(1)] + body + section[evidence.end(1):]
    else:
        section = section.rstrip() + "\n\n### Acceptance Evidence\n" + record + "\n"
    return section


def sync_task_evidence(task: Path, scenario_id: str, confirmed_by: str, evidence: str, owner: str = "", status: str = "verified") -> None:
    text = task.read_text(encoding="utf-8")
    task_pattern = re.escape(owner) if owner else r"TASK-\d+"
    match = re.search(rf"(?ms)^##\s+{task_pattern}:.*?(?=^## |\Z)", text)
    if match is None:
        raise ValueError(f"acceptance owner missing: {owner}")
    record = f"- {scenario_id}: {status} — {evidence} (confirmed_by: {confirmed_by})"
    section = _patch_section(match.group(0), scenario_id, status, record)
    text = text[:match.start()] + section + text[match.end():]
    coverage = re.search(r"(?ms)^## Acceptance Coverage[^\n]*\n(.*?)(?=^## |\Z)", text)
    if coverage:
        body = "\n".join(_status_line(line, scenario_id, status) for line in coverage.group(1).splitlines()) + "\n"
        text = text[:coverage.start(1)] + body + text[coverage.end(1):]
    from cf_spec_context import _atomic_text
    _atomic_text(task, text)


def persist_results(path: Path, data: dict[str, object], results: Sequence[Mapping[str, object]]) -> None:
    rows = {row["id"]: row for row in data["scenarios"]}
    run_id, executed_at = uuid4().hex, datetime.now(timezone.utc).isoformat()
    updates = []
    for result in results:
        state = str(result["status"])
        if state in ("not_included", "manual_pending"):
            continue
        row = rows[result["id"]]
        row["revision"] = int(row.get("revision", 0)) + 1
        status = "verified" if state == "passed" else state
        row["status"] = status
        record = {**result, "revision": row["revision"], "run_id": run_id, "executed_at": executed_at}
        row["evidence"] = record
        row.setdefault("runs", []).append(record)
        updates.append((row, record, status))
    from cf_spec_context import _atomic_text
    _atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    task_name = data.get("task_file")
    if isinstance(task_name, str) and task_name:
        task = Path(task_name) if Path(task_name).is_absolute() else path.parent / task_name
        for row, record, status in updates:
            detail = f"automated command {record['status']}; run_id={run_id}"
            sync_task_evidence(task, str(row["id"]), "runner", detail, str(row.get("owner", "")), status)
