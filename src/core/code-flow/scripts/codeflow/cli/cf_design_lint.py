"""Deterministic design ID closure and template checks."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import IO, Mapping, Optional, Sequence

_ID = re.compile(r"\b(?:FEAT|API|NFR(?:-[A-Z]+)?|S|E|B)-\d+\b")
_REQUIRED = {"lite": ("需求概述", "功能方案", "范围与边界", "验收条件"),
             "full": ("需求概述", "痛点与价值", "功能方案", "范围与边界", "验收条件"),
             "frontend": ("需求概述", "功能方案", "范围与边界", "验收条件", "页面与路由", "组件设计", "UI 状态")}


def _issue(code: str, path: str, reference: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "reference": reference, "message": message}


def _expand_range(match: re.Match[str]) -> str:
    prefix, first, last = match.groups()
    start, end = int(first), int(last)
    if end < start or end - start > 100:
        raise ValueError("design_id_range_invalid")
    return " ".join(f"{prefix}-{value:0{len(first)}d}" for value in range(start, end + 1))


def _content(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"```[^\n]*\n[\s\S]*?```|~~~[^\n]*\n[\s\S]*?~~~", "", text)
    return re.sub(r"\b(FEAT|API|NFR(?:-[A-Z]+)?)-(\d+)\s*\.\.\s*(\d+)\b", _expand_range, text)


def _document(path: Path) -> dict[str, object]:
    text = _content(path)
    definitions: dict[str, str] = {}
    edges: dict[str, set[str]] = {}
    excluded: set[str] = set()
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            for value in _ID.findall(line):
                if value.startswith(("FEAT-", "API-", "NFR-")):
                    definitions.setdefault(value, "")
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if not line.strip().startswith("|") or not cells:
            continue
        first = cells[0]
        if _ID.fullmatch(first):
            definitions[first] = cells[1] if len(cells) > 1 else ""
            if re.search(r"延期|不做|out.of.scope|deferred", line, re.I):
                excluded.add(first)
        ids = set(_ID.findall(line))
        scenario_ids = {value for value in ids if value.startswith(("S-", "E-", "B-"))}
        feature_ids = {value for value in ids if value.startswith("FEAT-")}
        for scenario in scenario_ids:
            edges.setdefault(scenario, set()).update(feature_ids)
    return {"path": str(path), "text": text, "definitions": definitions, "edges": edges,
            "references": set(_ID.findall(text)), "excluded": excluded}


def _template_issues(document: Mapping[str, object], template: str) -> list[dict[str, str]]:
    text = str(document["text"])
    selected = template
    if selected == "auto":
        match = re.search(r"(?mi)^design_template:\s*(lite|full|frontend)\s*$", text)
        selected = match.group(1) if match else ""
    headings = "\n".join(line for line in text.splitlines() if re.match(r"^#{1,6}\s", line))
    normalized = re.sub(r"\s+", "", headings).lower()
    return [_issue("template_section_missing", str(document["path"]), section, f"缺少 {selected} 必填章节: {section}")
            for section in _REQUIRED.get(selected, ()) if re.sub(r"\s+", "", section).lower() not in normalized]


def _reference_issues(documents: Sequence[Mapping[str, object]], defined: set[str]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    nfr_definitions: dict[str, tuple[str, str]] = {}
    for document in documents:
        for reference in sorted(document["references"] - defined):
            code = "nfr_id_mismatch" if reference.startswith("NFR-") else "traceability_undefined_id"
            issues.append(_issue(code, str(document["path"]), reference, f"引用的 ID 未定义: {reference}"))
        for reference, label in document["definitions"].items():
            if not reference.startswith("NFR-") or not label:
                continue
            previous = nfr_definitions.get(reference)
            if previous and previous[0] != label:
                issues.append(_issue("nfr_id_mismatch", str(document["path"]), reference,
                                     f"同一 NFR ID 的定义与 {previous[1]} 不一致"))
            nfr_definitions[reference] = (label, str(document["path"]))
    return issues


def _feature_issues(documents: Sequence[Mapping[str, object]],
                     scenarios: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    edges: dict[str, set[str]] = {}
    features: set[str] = set()
    for document in documents:
        features.update(value for value in document["definitions"]
                        if value.startswith("FEAT-") and value not in document["excluded"])
        for scenario, references in document["edges"].items():
            edges.setdefault(scenario, set()).update(references)
    for scenario in scenarios:
        references = set(scenario.get("features", []))
        scenario_id = str(scenario["id"])
        if references and edges.get(scenario_id) and references != edges[scenario_id]:
            issues.append(_issue("scenario_feature_mismatch", "", scenario_id, "场景源与设计中的功能引用不一致"))
        edges.setdefault(scenario_id, set()).update(references)
    covered = {value for references in edges.values() for value in references}
    issues.extend(_issue("feature_without_scenario", "", feature, "范围内功能没有验收场景")
                  for feature in sorted(features - covered))
    return issues


def lint_designs(files: Sequence[str], scenarios_file: str = "", template: str = "auto", *,
                 scenarios: Optional[Sequence[Mapping[str, object]]] = None) -> dict[str, object]:
    documents = [_document(Path(name)) for name in files]
    if scenarios is None:
        scenarios = []
        if scenarios_file:
            from codeflow.cli.cf_scenarios import parse_scenarios
            scenarios = parse_scenarios(scenarios_file)["scenarios"]
    scenarios = list(scenarios)
    defined = {reference for document in documents for reference in document["definitions"]}
    defined.update(str(row["id"]) for row in scenarios)
    issues = _reference_issues(documents, defined)
    for scenario in scenarios:
        references = {reference for value in (*scenario.get("features", []), *scenario.get("design_refs", []))
                      for reference in _ID.findall(str(value))}
        for reference in sorted(references):
            if reference not in defined:
                code = "nfr_id_mismatch" if reference.startswith("NFR-") else "traceability_undefined_id"
                issues.append(_issue(code, scenarios_file, reference, "场景引用了未定义的设计 ID"))
    issues.extend(_feature_issues(documents, scenarios))
    for document in documents:
        issues.extend(_template_issues(document, template))
    return {"decision": "block" if issues else "pass", "findings": issues,
            "files": list(files), "definitions": sorted(defined)}


def lint_requirement(task_file: str, scenarios_file: str = "", *,
                     task_text: Optional[str] = None,
                     scenarios: Optional[Sequence[Mapping[str, object]]] = None) -> dict[str, object]:
    directory = Path(task_file).parent
    files = {str(path.resolve()) for path in directory.glob("*.design.md")}
    text = (Path(task_file).read_text(encoding="utf-8") if task_text is None else task_text)
    text = text.split("## TASK-", 1)[0]
    roots = [directory, *[parent.parent for parent in directory.parents if parent.name == ".code-flow"]]
    for name in re.findall(r"[\w./-]+\.design\.md", text):
        resolved = next(((root / name).resolve() for root in roots if (root / name).is_file()), None)
        if resolved is None:
            return {"decision": "block", "findings": [_issue("design_source_missing", name, "", "引用的设计文件不存在")],
                    "files": sorted(files)}
        files.add(str(resolved))
    return lint_designs(sorted(files), scenarios_file, scenarios=scenarios) if files else {
        "decision": "pass", "findings": [], "files": []}


def main(argv: Sequence[str] | None = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND") or None, allow_abbrev=False)
    parser.add_argument("--file", action="append", required=True)
    parser.add_argument("--scenarios-file", default="")
    parser.add_argument("--template", choices=("auto", "lite", "full", "frontend"), default="auto")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = lint_designs(args.file, args.scenarios_file, args.template)
        stdout.write(json.dumps(result, ensure_ascii=False))
        return 0 if result["decision"] == "pass" else 3
    except (OSError, ValueError) as exc:
        stdout.write(json.dumps({"decision": "block", "error": str(exc)}, ensure_ascii=False))
        return 2
