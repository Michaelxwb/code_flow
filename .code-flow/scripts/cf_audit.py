#!/usr/bin/env python3
"""Read-only invariant audit for design acceptance data, manifest and evidence.

The report is derived, never hand-maintained:

- scenario / rule / risk counts come from the design §2.5.1, §2.5.2 and §5 tables;
- owners come from the manifest ``owner`` field, never from prose;
- verified evidence is resolved from the central evidence sidecar first, with
  the manifest run record as a compatibility fallback for pre-sidecar runs;
- findings always carry ``scenario_id`` and ``rule_ref`` so they can be fixed
  without guessing which row or invariant failed.

The audit only reads files. It never rewrites the manifest, task document,
design document or evidence sidecar.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import IO, Mapping, Optional, Sequence

from cf_acceptance_schema import load_manifest, verified_evidence
from cf_evidence_store import EvidenceStore
from cf_traceability import build_traceability

_SCENARIO_RE = re.compile(r"\b[SEB]-\d+\b")
_RULE_RE = re.compile(r"^RULE-\d+$")
_TASK_RE = re.compile(r"^TASK-\d+$")
_SEPARATOR_RE = re.compile(r"^:?-{2,}:?$")

_TRACE_FINDINGS = {
    "missing_in_manifest": (
        "design_scenario_missing_in_manifest",
        "RULE-10",
        "design_manifest_consistency",
        "design 已声明但 manifest 未登记",
    ),
    "extra_in_manifest": (
        "manifest_scenario_missing_in_design",
        "RULE-10",
        "design_manifest_consistency",
        "manifest 已登记但 design 未声明",
    ),
    "unbound_scenario": (
        "scenario_unbound",
        "RULE-02",
        "scenario_binding",
        "场景没有可执行 check，且未显式标为 aspirational",
    ),
}


def _section_body(text: str, heading: str) -> str:
    match = re.search(rf"(?m)^(#{{2,4}})\s+{heading}(?:\s+[^\n]*)?$", text)
    if match is None:
        return ""
    level = len(match.group(1))
    tail = text[match.end():]
    end = re.search(rf"(?m)^#{{1,{level}}}\s+", tail)
    return tail[:end.start()] if end else tail


def _first_table(text: str) -> tuple[list[str], list[list[str]]]:
    header: Optional[list[str]] = None
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if header is not None:
                break
            continue
        cells = [item.strip() for item in stripped.strip("|").split("|")]
        if all(_SEPARATOR_RE.match(cell.replace(" ", "")) for cell in cells):
            continue
        if header is None:
            header = cells
        else:
            rows.append(cells)
    return header or [], rows


def _column(header: Sequence[str], *names: str) -> int:
    for name in names:
        for index, cell in enumerate(header):
            if name.lower() in cell.lower():
                return index
    return -1


def _cell(row: Sequence[str], index: int) -> str:
    return row[index].strip() if 0 <= index < len(row) else ""


def parse_design_rules(design_file: str) -> list[dict[str, object]]:
    """Read RULE-* rows from design §2.5.1 (IDs and verified scenarios)."""
    text = Path(design_file).read_text(encoding="utf-8")
    header, rows = _first_table(_section_body(text, r"2\.5\.1"))
    id_index = _column(header, "id")
    description_index = _column(header, "描述", "description")
    scenario_index = _column(header, "验证场景", "场景")
    rules: list[dict[str, object]] = []
    for row in rows:
        rule_id = _cell(row, id_index) if id_index >= 0 else _cell(row, 0)
        if not _RULE_RE.match(rule_id):
            continue
        rules.append({
            "id": rule_id,
            "description": _cell(row, description_index),
            "scenarios": _SCENARIO_RE.findall(_cell(row, scenario_index)),
        })
    return rules


def parse_design_risks(design_file: str) -> list[dict[str, object]]:
    """Read §5 risk rows; risk IDs are synthesized from their derived order."""
    text = Path(design_file).read_text(encoding="utf-8")
    header, rows = _first_table(_section_body(text, r"5\."))
    level_index = _column(header, "等级", "level")
    risks: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        title = _cell(row, 0)
        if not title or title in {"风险", "-"}:
            continue
        risks.append({
            "id": f"RISK-{index + 1:02d}",
            "title": title,
            "level": _cell(row, level_index) if level_index >= 0 else _cell(row, 1),
        })
    return risks


def _finding(code: str, scenario_id: str, rule_ref: str, invariant: str,
             message: str, **extra: object) -> dict[str, object]:
    item: dict[str, object] = {
        "code": code,
        "scenario_id": scenario_id,
        "rule_ref": rule_ref,
        "invariant": invariant,
        "message": message,
    }
    item.update(extra)
    return item


def _trace_findings(trace: Mapping[str, object]) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for violation in trace.get("violations") or ():
        if not isinstance(violation, Mapping):
            continue
        known = _TRACE_FINDINGS.get(str(violation.get("code")))
        if known is None:
            continue
        code, rule_ref, invariant, message = known
        findings.append(_finding(
            code,
            str(violation.get("scenario") or ""),
            rule_ref,
            invariant,
            f"{message}: {violation.get('message', '')}",
        ))
    return findings


def _owner_findings(scenarios: Mapping[str, Mapping[str, object]]) -> list[dict[str, object]]:
    """Each scenario must declare exactly one owner in its manifest field."""
    findings: list[dict[str, object]] = []
    for scenario_id in sorted(scenarios):
        scenario = scenarios[scenario_id]
        owner = scenario.get("owner")
        if not isinstance(owner, str) or not owner.strip():
            findings.append(_finding(
                "owner_missing", scenario_id, "RULE-10", "owner_unique",
                f"{scenario_id} 的 owner 字段为空；请登记唯一负责任务。",
                fields=["owner"],
            ))
            continue
        tokens = re.findall(r"TASK-\d+", owner)
        if len(tokens) != 1 or _TASK_RE.match(owner.strip()) is None:
            findings.append(_finding(
                "owner_not_unique", scenario_id, "RULE-10", "owner_unique",
                f"{scenario_id} 的 owner 字段必须是单个 TASK ID，当前为 {owner!r}。",
                fields=["owner"],
            ))
    return findings


def _scenario_evidence(scenario: Mapping[str, object],
                       store: EvidenceStore) -> tuple[Mapping[str, object], str]:
    check_id = scenario.get("check")
    if isinstance(check_id, str) and check_id.strip():
        sidecar = store.read_latest(check_id)
        if sidecar is not None:
            return sidecar, "sidecar"
    value = scenario.get("evidence")
    if isinstance(value, Mapping):
        return value, "manifest"
    return {}, "missing"


def _verified_findings(scenarios: Mapping[str, Mapping[str, object]],
                       store: EvidenceStore) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for scenario_id in sorted(scenarios):
        scenario = scenarios[scenario_id]
        if scenario.get("status") != "verified":
            continue
        if scenario.get("kind") == "manual":
            if not verified_evidence(scenario):
                findings.append(_finding(
                    "manual_verified_evidence_missing", scenario_id, "RULE-01",
                    "verified_evidence", f"{scenario_id} 手写 verified 但缺少用户确认记录。",
                    fields=["confirmed_by", "evidence"],
                ))
            continue
        evidence, source = _scenario_evidence(scenario, store)
        input_hash = evidence.get("input_hash") or evidence.get("fingerprint")
        missing: list[str] = []
        if not isinstance(evidence.get("run_id"), str) or not str(evidence.get("run_id")).strip():
            missing.append("run_id")
        if evidence.get("exit_code") != 0:
            missing.append("exit_code")
        if not isinstance(input_hash, str) or not input_hash.strip():
            missing.append("input_hash")
        if missing:
            check_id = scenario.get("check")
            findings.append(_finding(
                "verified_evidence_incomplete", scenario_id, "RULE-01",
                "verified_evidence",
                f"{scenario_id} 已 verified，但证据缺少 {', '.join(missing)}。",
                check_id=check_id if isinstance(check_id, str) else "",
                source=source,
                fields=missing,
            ))
    return findings


def _scenario_rows(trace: Mapping[str, object],
                   scenarios: Mapping[str, Mapping[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in trace.get("scenarios") or ():
        if not isinstance(item, Mapping):
            continue
        scenario_id = str(item.get("id") or "")
        scenario = scenarios.get(scenario_id)
        owner = str(scenario.get("owner") or "") if scenario is not None else str(item.get("owner") or "")
        rows.append({
            "id": scenario_id,
            "owner": owner,
            "status": str(scenario.get("status") or item.get("status") or "") if scenario is not None else "",
            "check": str(scenario.get("check") or "-") if scenario is not None else "-",
            "binding": str(item.get("binding") or ""),
        })
    return rows


def _dedupe(findings: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    unique: dict[tuple[str, str, str], dict[str, object]] = {}
    for item in findings:
        key = (str(item.get("scenario_id", "")), str(item.get("code", "")), str(item.get("message", "")))
        unique[key] = dict(item)
    return sorted(unique.values(), key=lambda item: (
        str(item.get("scenario_id", "")), str(item.get("code", "")), str(item.get("message", ""))
    ))


def build_audit(design_file: str, manifest_file: str, root: str,
                requirement: str = "") -> dict[str, object]:
    """Build the read-only invariant report; raises ValueError on unreadable input."""
    design_path = Path(design_file)
    manifest_path = Path(manifest_file)
    if not design_path.is_file():
        raise ValueError(f"design_file_missing: {design_path}")
    if not manifest_path.is_file():
        raise ValueError(f"manifest_file_missing: {manifest_path}")
    rules = parse_design_rules(str(design_path))
    risks = parse_design_risks(str(design_path))
    manifest = load_manifest(manifest_path)
    trace = build_traceability(str(design_path), str(manifest_path))
    scenarios = {
        str(item["id"]): item
        for item in manifest.get("scenarios") or ()
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    checks = {
        str(item["id"]): item
        for item in manifest.get("checks") or ()
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    from cf_evidence_store import requirement_key
    store = EvidenceStore(str(root), requirement or requirement_key(manifest_path.parent))
    findings = [
        *_trace_findings(trace),
        *_owner_findings(scenarios),
        *_verified_findings(scenarios, store),
    ]
    findings = _dedupe(findings)
    rows = _scenario_rows(trace, scenarios)
    owners: dict[str, int] = {}
    for row in rows:
        owner = str(row.get("owner") or "")
        if owner:
            owners[owner] = owners.get(owner, 0) + 1
    risk_levels: dict[str, int] = {}
    for risk in risks:
        level = str(risk.get("level") or "unknown")
        risk_levels[level] = risk_levels.get(level, 0) + 1
    summary = dict(trace.get("summary") or {})
    summary.update({
        "checks": len(checks),
        "verified": sum(1 for item in scenarios.values() if item.get("status") == "verified"),
        "owners": owners,
        "unique_owners": len(owners),
        "rules": len(rules),
        "risks": len(risks),
        "risk_levels": risk_levels,
        "findings": len(findings),
    })
    return {
        "decision": "block" if findings else "pass",
        "read_only": True,
        "generated": True,
        "design_file": str(design_path),
        "manifest_file": str(manifest_path),
        "evidence_dir": str(store.directory),
        "summary": summary,
        "rules": rules,
        "risks": risks,
        "scenarios": rows,
        "findings": findings,
    }


def _md(value: object) -> str:
    text = "" if value is None else str(value)
    if not text:
        return "-"
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(report: Mapping[str, object]) -> str:
    """Render a human report from build_audit output; no file is written."""
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# code-flow audit",
        "",
        f"> Read-only audit of `{_md(report.get('manifest_file'))}` against "
        f"`{_md(report.get('design_file'))}`.",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| decision | {_md(report.get('decision'))} |",
        f"| design scenarios | {_md(summary.get('design_scenarios'))} |",
        f"| manifest scenarios | {_md(summary.get('manifest_scenarios'))} |",
        f"| checks | {_md(summary.get('checks'))} |",
        f"| bound / aspirational / unbound / missing | "
        f"{_md(summary.get('bound'))} / {_md(summary.get('aspirational'))} / "
        f"{_md(summary.get('unbound'))} / {_md(summary.get('missing'))} |",
        f"| verified | {_md(summary.get('verified'))} |",
        f"| rules | {_md(summary.get('rules'))} |",
        f"| risks | {_md(summary.get('risks'))} |",
        f"| findings | {_md(summary.get('findings'))} |",
    ]
    findings = report.get("findings") or ()
    if findings:
        lines.extend([
            "",
            "## Findings",
            "",
            "| Rule | Invariant | Scenario | Code | Message |",
            "|------|-----------|----------|------|---------|",
        ])
        for item in findings:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                f"| {_md(item.get('rule_ref'))} | {_md(item.get('invariant'))} | "
                f"{_md(item.get('scenario_id'))} | {_md(item.get('code'))} | {_md(item.get('message'))} |"
            )
    else:
        lines.extend(["", "No invariant findings."])
    return "\n".join(lines) + "\n"


def _resolve_paths(root: str, task_dir: str, design: str, manifest: str) -> tuple[Path, Path, Path]:
    root_path = Path(root).expanduser().resolve()
    directory = Path(task_dir).expanduser()
    directory = directory.resolve() if directory.is_absolute() else (root_path / directory).resolve()
    design_path = Path(design).expanduser().resolve() if design else None
    if design_path is None:
        candidates = sorted(directory.glob("*.design.md"))
        if not candidates:
            raise ValueError(f"design_file_missing: {directory}")
        if len(candidates) > 1:
            raise ValueError(f"design_file_ambiguous: {', '.join(str(item) for item in candidates)}")
        design_path = candidates[0]
    manifest_path = Path(manifest).expanduser().resolve() if manifest else directory / ".acceptance-manifest.json"
    return root_path, design_path, manifest_path


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND") or None)
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--root", default=os.getcwd())
    parser.add_argument("--design", default="")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        root, design, manifest = _resolve_paths(args.root, args.task_dir, args.design, args.manifest)
        report = build_audit(str(design), str(manifest), root=str(root))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        stdout.write(json.dumps({"decision": "block", "error": str(exc)}, ensure_ascii=False))
        return 2
    if args.json:
        stdout.write(json.dumps(report, ensure_ascii=False))
    else:
        stdout.write(render_markdown(report))
    return 0 if report["decision"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
