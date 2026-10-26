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

from cf_acceptance_schema import (check_outcome, load_manifest, recorded_check_hash,
                                  scenario_check_ids, verified_evidence)
from cf_acceptance_risk import risk_counts
from cf_evidence_store import EvidenceStore
from cf_markdown import column_index, is_separator_row, table_cells
from cf_traceability import build_traceability, build_traceability_many, build_traceability_from_scenarios

_SCENARIO_RE = re.compile(r"\b[SEB]-\d+\b")
_RULE_RE = re.compile(r"^RULE-\d+$")
_TASK_RE = re.compile(r"^TASK-\d+$")

_TRACE_FINDINGS = {
    "unknown_scenario": ("unknown_scenario", "scenario-source", "coverage_ids", "Coverage 引用了场景源中不存在的场景"),
    "scenario_not_in_coverage": ("scenario_not_in_coverage", "scenario-source", "coverage_ids", "场景源场景未进入 Acceptance Coverage"),
    "duplicate_scenario_owner": ("duplicate_scenario_owner", "scenario-source", "unique_owner", "同一场景存在多个 owner"),
    "missing_check": ("missing_check", "scenario-source", "checks_exist", "场景引用了不存在的 check"),
    "design_scenario_duplicate": ("design_scenario_duplicate", "scenario-source", "design_references_only", "design 仍重复定义验收场景"),
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
        cells = table_cells(line)
        if not cells:
            if header is not None:
                break
            continue
        if is_separator_row(cells):
            continue
        if header is None:
            header = list(cells)
        else:
            rows.append(list(cells))
    return header or [], rows


def _cell(row: Sequence[str], index: int) -> str:
    return row[index].strip() if 0 <= index < len(row) else ""


def parse_design_rules(design_file: str) -> list[dict[str, object]]:
    """Read RULE-* rows from design §2.5.1 (IDs and verified scenarios)."""
    text = Path(design_file).read_text(encoding="utf-8")
    header, rows = _first_table(_section_body(text, r"2\.5\.1"))
    id_index = column_index(header, "id")
    description_index = column_index(header, "描述", "description")
    scenario_index = column_index(header, "验证场景", "场景")
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
    level_index = column_index(header, "等级", "level")
    risks: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        title = _cell(row, 0)
        if not title or title in {"风险", "-"}:
            continue
        risks.append({
            "id": f"RISK-{index + 1:02d}",
            "title": title,
            "level": _cell(row, level_index) if level_index >= 0 else _cell(row, 1),
            "details": {name: _cell(row, column) for column, name in enumerate(header)},
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


def _scenario_evidence(scenario: Mapping[str, object], store: EvidenceStore
                       ) -> list[tuple[str, Mapping[str, object], str]]:
    """Resolve every required check; partial sidecars cannot borrow a pass."""
    ids = scenario_check_ids(scenario)
    sidecars = {check_id: store.read_latest(check_id) for check_id in ids}
    if any(item is not None for item in sidecars.values()):
        return [(check_id, item or {}, "sidecar" if item is not None else "missing")
                for check_id, item in sidecars.items()]
    value = scenario.get("evidence")
    evidence = value if isinstance(value, Mapping) else {}
    if not ids:
        return [("", evidence, "manifest" if evidence else "missing")]
    return [(check_id, {**check_outcome(evidence, check_id),
                        "input_hash": recorded_check_hash(scenario, check_id)},
             "manifest" if evidence else "missing") for check_id in ids]


def _evidence_fields(evidence: Mapping[str, object], expected_hash: str) -> list[str]:
    """Check the recorded proof, not the current workspace of a historical audit."""
    missing: list[str] = []
    if not isinstance(evidence.get("run_id"), str) or not str(evidence["run_id"]).strip():
        missing.append("run_id")
    if type(evidence.get("exit_code")) is not int or evidence["exit_code"] != 0:
        missing.append("exit_code")
    # An explicit empty per-check hash must not fall back to the scenario hash.
    input_hash = evidence.get("input_hash", evidence.get("fingerprint"))
    if not isinstance(input_hash, str) or not input_hash.strip():
        missing.append("input_hash")
    elif expected_hash and input_hash != expected_hash:
        missing.append("input_hash_mismatch")
    if evidence.get("status") not in ("passed", "verified"):
        missing.append("status")
    return missing


def _verified_findings(scenarios: Mapping[str, Mapping[str, object]],
                       store: EvidenceStore) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for scenario_id in sorted(scenarios):
        scenario = scenarios[scenario_id]
        if scenario.get("status") != "verified":
            continue
        if scenario.get("kind") == "manual" or scenario.get("exec") == "manual":
            if not verified_evidence(scenario):
                findings.append(_finding(
                    "manual_verified_evidence_missing", scenario_id, "RULE-01",
                    "verified_evidence", f"{scenario_id} 手写 verified 但缺少用户确认记录。",
                    fields=["confirmed_by", "evidence"],
                ))
            continue
        for check_id, evidence, source in _scenario_evidence(scenario, store):
            missing = _evidence_fields(evidence, recorded_check_hash(scenario, check_id))
            if not missing:
                continue
            findings.append(_finding(
                "verified_evidence_incomplete", scenario_id, "RULE-01",
                "verified_evidence",
                f"{scenario_id}/{check_id or 'scenario'} 已 verified，但证据无效: {', '.join(missing)}。",
                check_id=check_id,
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
            "check": next(iter(scenario_check_ids(scenario)), "-") if scenario is not None else "-",
            "checks": scenario_check_ids(scenario) if scenario is not None else [],
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


def _scenario_source_findings(scenarios_file: str, manifest_path: Path,
                              design_paths: Sequence[Path], manifest: Mapping[str, object]) -> list[dict[str, str]]:
    from cf_scenarios import audit_scenario_source, parse_scenarios
    from cf_traceability import parse_design_scenarios
    source = parse_scenarios(scenarios_file)
    coverage: list[dict[str, object]] = []
    task_name = manifest.get("task_file")
    if isinstance(task_name, str) and task_name:
        task = manifest_path.parent / task_name
        try:
            from cf_acceptance_manifest import extract_manifest
            coverage = list(extract_manifest(str(task))["scenarios"])
        except (OSError, ValueError):
            coverage = []
    manifest_ids = [str(item.get("id")) for item in manifest.get("scenarios", []) if isinstance(item, Mapping)]
    report = audit_scenario_source(source.get("scenarios", []), coverage, manifest_ids)
    violations: list[dict[str, str]] = []
    for code, key in (("unknown_scenario", "unknown"), ("scenario_not_in_coverage", "missing"),
                      ("duplicate_scenario_owner", "duplicate_owner"),
                      ("missing_in_manifest", "manifest_missing"),
                      ("extra_in_manifest", "manifest_unknown")):
        for scenario_id in report.get(key, []):
            violations.append({"code": code, "scenario": str(scenario_id), "message": f"{scenario_id}: {key}"})
    paths = [design_paths] if isinstance(design_paths, Path) else list(design_paths)
    design_ids: set[str] = set()
    for path in paths:
        try:
            design_ids.update(item.id for item in parse_design_scenarios(str(path)))
        except (OSError, ValueError):
            continue
    for scenario_id in sorted(design_ids):
        violations.append({"code": "design_scenario_duplicate", "scenario": scenario_id,
                           "message": f"{scenario_id} 仍在 design 中定义；场景源已接管"})
    return violations


def _merge_design_rules(design_paths: Sequence[Path]) -> list[dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    for path in design_paths:
        for rule in parse_design_rules(str(path)):
            rule_id = str(rule.get("id"))
            if rule_id in merged and merged[rule_id] != rule:
                raise ValueError(f"duplicate design rule id with conflicting definition: {rule_id}")
            merged[rule_id] = rule
    return sorted(merged.values(), key=lambda item: str(item.get("id")))


def _merge_design_risks(design_paths: Sequence[Path]) -> list[dict[str, object]]:
    merged: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for path in design_paths:
        for risk in parse_design_risks(str(path)):
            key = (str(path.resolve()), str(risk["id"]))
            if key in seen:
                continue
            seen.add(key)
            item = dict(risk)
            item["source"] = path.name
            item["source_ref"] = f"{path.resolve().as_posix()}#{risk['id']}"
            merged.append(item)
    return merged


def _audit_summary(trace: Mapping[str, object], manifest: Mapping[str, object],
                   rows: Sequence[Mapping[str, object]], rules: Sequence[Mapping[str, object]],
                   risks: Sequence[Mapping[str, object]], findings: Sequence[Mapping[str, object]]) -> dict[str, object]:
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
        "checks": len(manifest.get("checks", [])),
        "verified": sum(1 for item in manifest.get("scenarios", []) if item.get("status") == "verified"),
        "owners": owners,
        "unique_owners": len(owners),
        "rules": len(rules),
        "risks": len(risks),
        **risk_counts(manifest),
        "risk_levels": risk_levels,
        "findings": len(findings),
    })
    return summary


def _audit_trace(design_paths: Sequence[Path], manifest_path: Path,
                 manifest: Mapping[str, object], scenarios_file: str) -> dict[str, object]:
    if scenarios_file:
        trace = build_traceability_from_scenarios(scenarios_file, str(manifest_path))
        extra_findings = _scenario_source_findings(scenarios_file, manifest_path, design_paths, manifest)
        trace.setdefault("violations", []).extend(extra_findings)
        return trace
    if len(design_paths) > 1:
        return build_traceability_many([str(path) for path in design_paths], str(manifest_path))
    return build_traceability(str(design_paths[0]), str(manifest_path))


def build_audit(design_file: str, manifest_file: str, root: str,
                requirement: str = "", scenarios_file: str = "",
                design_files: Sequence[str] = ()) -> dict[str, object]:
    """Build the read-only invariant report; multiple designs merge by global ID."""
    design_paths = [Path(item) for item in design_files] or [Path(design_file)]
    manifest_path = Path(manifest_file)
    if any(not path.is_file() for path in design_paths):
        raise ValueError(f"design_file_missing: {', '.join(str(path) for path in design_paths)}")
    if not manifest_path.is_file():
        raise ValueError(f"manifest_file_missing: {manifest_path}")
    rules = _merge_design_rules(design_paths)
    risks = _merge_design_risks(design_paths)
    manifest = load_manifest(manifest_path)
    trace = _audit_trace(design_paths, manifest_path, manifest, scenarios_file)
    scenarios = {
        str(item["id"]): item
        for item in manifest.get("scenarios") or ()
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
    summary = _audit_summary(trace, manifest, rows, rules, risks, findings)
    return {
        "decision": "block" if findings else "pass",
        "read_only": True,
        "generated": True,
        "design_file": str(design_paths[0]),
        "design_files": [str(path) for path in design_paths],
        "source": trace.get("source", ""),
        "deprecated": not bool(scenarios_file),
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
        f"| accepted risks | {_md(summary.get('accepted_risks'))} |",
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


def _resolve_paths(root: str, task_dir: str, design: str,
                   manifest: str) -> tuple[Path, Path, Path, list[Path]]:
    root_path = Path(root).expanduser().resolve()
    directory = Path(task_dir).expanduser()
    directory = directory.resolve() if directory.is_absolute() else (root_path / directory).resolve()
    if design:
        design_paths = [
            Path(item).expanduser().resolve()
            for item in design.split(",") if item.strip()
        ]
    else:
        design_paths = sorted(directory.glob("*.design.md"))
    if not design_paths:
        raise ValueError(f"design_file_missing: {directory}")
    manifest_path = Path(manifest).expanduser().resolve() if manifest else directory / ".acceptance-manifest.json"
    return root_path, design_paths[0], manifest_path, design_paths


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND") or None)
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--root", default=os.getcwd())
    parser.add_argument("--design", default="")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        root, design, manifest, design_paths = _resolve_paths(
            args.root, args.task_dir, args.design, args.manifest
        )
        resolved_dir = manifest.parent
        sources = sorted(resolved_dir.glob("*.scenarios.md")) if resolved_dir.is_dir() else []
        scenarios_file = str(sources[0]) if len(sources) == 1 else ""
        if len(sources) > 1:
            raise ValueError("scenario_source_ambiguous")
        report = build_audit(
            str(design), str(manifest), root=str(root), scenarios_file=scenarios_file,
            design_files=[str(path) for path in design_paths],
        )
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
