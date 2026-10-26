#!/usr/bin/env python3
"""Import CI JUnit / Playwright reports as central acceptance evidence.

CI owns full E2E execution; the local workflow imports the report instead of
re-running it. Imports are fail-closed:

- ``--commit`` must resolve to the current ``HEAD``; a different commit means
  the report does not describe this worktree and is rejected.
- The worktree must be clean (ignoring ``.code-flow/``): CI proves committed
  content, not uncommitted local edits.
- ``run_url``, ``input_hash``, ``exit_code`` and ``source=ci`` are mandatory
  provenance; ``input_hash`` binds evidence to the exact worktree content.
- Every test case must map to a manifest check/scenario. Unmapped cases are
  rejected instead of being silently attributed or dropped.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import IO, Mapping, Optional, Sequence
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

from cf_acceptance_evidence import persist_results
from cf_acceptance_schema import load_manifest, scenario_check_ids
from cf_check_inputs import check_input_hashes
from cf_evidence_store import EvidenceStoreError, discover_project_root
from cf_exec_base import worktree_fingerprint

MANIFEST_NAME = ".acceptance-manifest.json"
FORMATS = ("junit", "playwright")
_PASSED, _FAILED, _SKIPPED = "passed", "failed", "skipped"
_FAILED_RESULTS = ("failed", "timedOut", "interrupted")


class EvidenceImportError(ValueError):
    """Stable rejection for an import that cannot prove its claims."""

    def __init__(self, code: str, field: str, message: str, path: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.message = message
        self.path = path


@dataclass(frozen=True)
class ReportCase:
    """One executable test case from a CI report."""

    name: str
    classname: str
    file: str
    line: Optional[int]
    status: str
    message: str = ""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _line(value: object) -> Optional[int]:
    text = _text(value)
    return int(text) if text.isdigit() else None


def _junit_case(node: ET.Element) -> ReportCase:
    tags = {_local(child.tag) for child in node}
    if tags & {"failure", "error"}:
        status = _FAILED
    elif "skipped" in tags:
        status = _SKIPPED
    else:
        status = _PASSED
    detail = next((child for child in node if _local(child.tag) in {"failure", "error"}), None)
    message = _text(detail.get("message")) if detail is not None else ""
    return ReportCase(
        name=_text(node.get("name")),
        classname=_text(node.get("classname")),
        file=_text(node.get("file")),
        line=_line(node.get("line")),
        status=status,
        message=message,
    )


def _parse_junit(path: Path) -> list[ReportCase]:
    try:
        root = ET.parse(str(path)).getroot()
    except (OSError, UnicodeError, ET.ParseError) as exc:
        raise EvidenceImportError("invalid_report", "file", f"invalid JUnit XML: {exc}", str(path)) from exc
    cases = [_junit_case(node) for node in root.iter() if _local(node.tag) == "testcase"]
    if not cases:
        raise EvidenceImportError("empty_report", "file", "JUnit report has no testcase", str(path))
    return cases


def _playwright_status(test: Mapping[str, object]) -> str:
    results = test.get("results")
    last = ""
    if isinstance(results, list) and results and isinstance(results[-1], Mapping):
        last = _text(results[-1].get("status"))
    status = _text(test.get("status"))
    if last in _FAILED_RESULTS or status == "unexpected":
        return _FAILED
    if status == "skipped" or last == "skipped":
        return _SKIPPED
    return _PASSED if last == "passed" else _SKIPPED


def _playwright_spec_status(tests: Sequence[object]) -> str:
    statuses = [_playwright_status(test) for test in tests if isinstance(test, Mapping)]
    if _FAILED in statuses:
        return _FAILED
    if statuses and all(status == _PASSED for status in statuses):
        return _PASSED
    return _SKIPPED


def _walk_playwright_suite(suite: Mapping[str, object], parent_file: str, cases: list[ReportCase]) -> None:
    file = _text(suite.get("file")) or parent_file
    specs = suite.get("specs")
    for spec in specs if isinstance(specs, list) else []:
        if not isinstance(spec, Mapping):
            continue
        tests = spec.get("tests")
        cases.append(
            ReportCase(
                name=_text(spec.get("title")),
                classname=_text(suite.get("title")),
                file=_text(spec.get("file")) or file,
                line=_line(spec.get("line")),
                status=_playwright_spec_status(tests if isinstance(tests, list) else []),
            )
        )
    children = suite.get("suites")
    for child in children if isinstance(children, list) else []:
        if isinstance(child, Mapping):
            _walk_playwright_suite(child, file, cases)


def _parse_playwright(path: Path) -> list[ReportCase]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise EvidenceImportError("invalid_report", "file", f"invalid Playwright JSON: {exc}", str(path)) from exc
    suites = loaded.get("suites") if isinstance(loaded, Mapping) else None
    if not isinstance(suites, list):
        raise EvidenceImportError("invalid_report", "file", "Playwright report needs a suites list", str(path))
    cases: list[ReportCase] = []
    for suite in suites:
        if isinstance(suite, Mapping):
            _walk_playwright_suite(suite, "", cases)
    if not cases:
        raise EvidenceImportError("empty_report", "file", "Playwright report has no spec", str(path))
    return cases


def load_report(path: object, fmt: str) -> list[ReportCase]:
    report = Path(path)
    if fmt == "junit":
        return _parse_junit(report)
    if fmt == "playwright":
        return _parse_playwright(report)
    raise EvidenceImportError("unsupported_format", "format", f"unsupported report format: {fmt}")


def _resolve_manifest(root: Path, manifest: str, task_dir: str) -> Path:
    if manifest:
        path = Path(manifest).expanduser()
        return path if path.is_absolute() else root / path
    if task_dir:
        path = Path(task_dir).expanduser()
        base = path if path.is_absolute() else root / path
        return base / MANIFEST_NAME
    marker = root / ".code-flow" / ".active-task.json"
    try:
        loaded = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise EvidenceImportError(
            "manifest_unresolved", "manifest", "pass --manifest/--task-dir or start a task first", str(marker)
        ) from exc
    task = loaded.get("task_dir") if isinstance(loaded, Mapping) else None
    if not isinstance(task, str) or not task.strip():
        raise EvidenceImportError("manifest_unresolved", "manifest", "active task has no task_dir", str(marker))
    base = Path(task)
    base = base if base.is_absolute() else root / base
    return base / MANIFEST_NAME


def _load_plan(path: Path) -> tuple[dict[str, object], dict[str, object], dict[str, str], list[tuple[str, str]]]:
    try:
        data = load_manifest(path)
    except (OSError, ValueError) as exc:
        raise EvidenceImportError("manifest_invalid", "manifest", str(exc), str(path)) from exc
    checks = {
        str(item["id"]): item
        for item in data.get("checks", [])
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    scenarios = {
        str(item["id"]): item
        for item in data.get("scenarios", [])
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    linked: dict[str, str] = {}
    for scenario_id, item in scenarios.items():
        ids = scenario_check_ids(item)
        if len(ids) == 1 and ids[0] in checks:
            linked[scenario_id] = ids[0]
    if not checks or not any(scenario_check_ids(row) for row in scenarios.values()):
        raise EvidenceImportError(
            "manifest_schema_unsupported", "manifest", "CI import needs manifest v3 checks linked to scenarios", str(path)
        )
    assertions: list[tuple[str, str]] = []
    for scenario_id, item in scenarios.items():
        raw = item.get("assertions")
        for value in raw if isinstance(raw, list) else []:
            if isinstance(value, str) and value.strip():
                assertions.append((scenario_id, value.strip()))
    return data, checks, linked, assertions


def _has_token(text: str, token: str) -> bool:
    return re.search(rf"(?<![0-9A-Za-z_-]){re.escape(token)}(?![0-9A-Za-z_-])", text) is not None


def _normalize_path(value: str) -> str:
    text = value.replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/")


def _assertion_matches(assertion: str, case: ReportCase) -> bool:
    if not case.file:
        return False
    target, line = assertion, None
    if "::" in target:
        target = target.split("::", 1)[0]
    head, separator, tail = target.rpartition(":")
    if separator and tail.isdigit():
        target, line = head, int(tail)
    expected, actual = _normalize_path(target), _normalize_path(case.file)
    if not expected or not actual:
        return False
    if not (expected == actual or actual.endswith("/" + expected) or expected.endswith("/" + actual)):
        return False
    return line is None or case.line is None or line == case.line


def _match_case(
    case: ReportCase, override: str, checks: Mapping[str, object], linked: Mapping[str, str],
    assertions: Sequence[tuple[str, str]],
) -> str:
    if override:
        return override
    text = " ".join(part for part in (case.classname, case.name, case.file) if part)
    candidates = [candidate for candidate in checks if _has_token(text, candidate)]
    if len(candidates) > 1:
        raise EvidenceImportError("ambiguous_test_case", "file",
                                  f"test case must identify one check: {_case_label(case)}")
    if candidates:
        return candidates[0]
    scenario_id = next((candidate for candidate in linked if _has_token(text, candidate)), "")
    if scenario_id:
        return linked[scenario_id]
    for candidate, assertion in assertions:
        if candidate in linked and _assertion_matches(assertion, case):
            return linked[candidate]
    return ""


def _case_label(case: ReportCase) -> str:
    name = case.name or "<unnamed>"
    return f"{case.classname}::{name}" if case.classname else name


def _map_cases(
    cases: Sequence[ReportCase], override: str, checks: Mapping[str, object],
    linked: Mapping[str, str], assertions: Sequence[tuple[str, str]],
) -> dict[str, list[str]]:
    mapped: dict[str, list[str]] = {}
    unmapped: list[str] = []
    for case in cases:
        check_id = _match_case(case, override, checks, linked, assertions)
        if not check_id:
            unmapped.append(_case_label(case))
            continue
        mapped.setdefault(check_id, []).append(case.status)
    if unmapped:
        raise EvidenceImportError(
            "unmapped_test_cases", "file", "unmapped test cases: " + ", ".join(unmapped[:10])
        )
    if not mapped:
        raise EvidenceImportError("no_matching_tests", "file", "report does not cover any manifest check")
    return mapped


def _check_outcomes(mapped: Mapping[str, Sequence[str]]) -> dict[str, tuple[str, int]]:
    outcomes: dict[str, tuple[str, int]] = {}
    for check_id, statuses in mapped.items():
        if _FAILED in statuses:
            outcomes[check_id] = ("failed", 1)
        elif not statuses or any(status != _PASSED for status in statuses):
            outcomes[check_id] = ("incomplete", 1)
        else:
            outcomes[check_id] = ("passed", 0)
    return outcomes


def _git(root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ("git", *arguments), cwd=str(root), text=True, encoding="utf-8", capture_output=True, check=False
        )
    except (OSError, UnicodeError):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _resolve_commit(root: Path, value: str) -> str:
    text = _text(value)
    if not text:
        raise EvidenceImportError("missing_commit", "commit", "CI evidence requires --commit")
    resolved = _git(root, "rev-parse", "--verify", "--quiet", f"{text}^{{commit}}")
    if not resolved:
        raise EvidenceImportError("commit_invalid", "commit", f"unknown commit: {text}")
    head = _git(root, "rev-parse", "HEAD")
    if not head:
        raise EvidenceImportError("git_unavailable", "commit", "cannot read HEAD; CI import needs a git worktree")
    if resolved != head:
        raise EvidenceImportError("commit_mismatch", "commit", f"CI commit {resolved} != HEAD {head}")
    return head


def _changed_paths(root: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ("git", "status", "--porcelain", "--untracked-files=all"),
            cwd=str(root), text=True, encoding="utf-8", capture_output=True, check=False,
        )
    except (OSError, UnicodeError) as exc:
        raise EvidenceImportError("git_unavailable", "worktree", str(exc)) from exc
    if completed.returncode != 0:
        raise EvidenceImportError("git_unavailable", "worktree", completed.stderr.strip())
    paths: list[str] = []
    for line in completed.stdout.splitlines():
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if not path or path.startswith(".code-flow/"):
            continue
        paths.append(path)
    return paths


def _require_clean(root: Path) -> None:
    paths = _changed_paths(root)
    if paths:
        raise EvidenceImportError(
            "worktree_dirty", "worktree", "CI evidence requires a clean worktree: " + ", ".join(paths[:5])
        )


def _require_run_url(value: str) -> str:
    text = _text(value)
    if not text:
        raise EvidenceImportError("missing_run_url", "run_url", "CI evidence requires --run-url")
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise EvidenceImportError("invalid_run_url", "run_url", f"not an http(s) run URL: {text}")
    return text


def _report_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, UnicodeError) as exc:
        raise EvidenceImportError("invalid_report", "file", str(exc), str(path)) from exc


def _scenario_results(
    data: Mapping[str, object], outcomes: Mapping[str, tuple[str, int]], *,
    commit: str, run_url: str, fmt: str, report_sha256: str,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for row in data.get("scenarios", []):
        if not isinstance(row, Mapping) or str(row.get("kind", "functional")) == "manual":
            continue
        check_ids = scenario_check_ids(row)
        if not check_ids or any(check_id not in outcomes for check_id in check_ids):
            continue
        statuses = [outcomes[check_id][0] for check_id in check_ids]
        if any(status == "failed" for status in statuses):
            status = "failed"
        elif any(status != "passed" for status in statuses):
            status = "incomplete"
        else:
            status = "passed"
        exit_code = max(outcomes[check_id][1] for check_id in check_ids)
        results.append({
            "id": str(row["id"]),
            "kind": str(row.get("kind", "functional")),
            "status": status,
            "exit_code": exit_code,
            "check_ids": check_ids,
            "check_results": {check_id: {"status": outcomes[check_id][0],
                                         "exit_code": outcomes[check_id][1]}
                              for check_id in check_ids},
            "source": "ci",
            "commit": commit,
            "run_url": run_url,
            "ci_format": fmt,
            "ci_report_sha256": report_sha256,
        })
    return results


def _already_imported(data: Mapping[str, object], results: Sequence[Mapping[str, object]], run_id: str) -> bool:
    rows = {
        str(row["id"]): row
        for row in data.get("scenarios", [])
        if isinstance(row, Mapping) and isinstance(row.get("id"), str)
    }
    for result in results:
        evidence = rows.get(str(result["id"]), {}).get("evidence")
        if not isinstance(evidence, Mapping):
            return False
        if evidence.get("run_id") != run_id or evidence.get("source") != "ci":
            return False
    return True


def _checks_payload(mapped: Mapping[str, Sequence[str]], outcomes: Mapping[str, tuple[str, int]]) -> list[dict[str, object]]:
    return [
        {"check_id": check_id, "status": outcomes[check_id][0],
         "exit_code": outcomes[check_id][1], "cases": len(mapped[check_id])}
        for check_id in sorted(outcomes)
    ]


def _payload(
    status: str, decision: str, results: Sequence[Mapping[str, object]], mapped: Mapping[str, Sequence[str]],
    outcomes: Mapping[str, tuple[str, int]], *, fmt: str, head: str, run_url: str,
    fingerprint: str, run_id: str, report_sha256: str,
) -> dict[str, object]:
    return {
        "status": status,
        "decision": decision,
        "source": "ci",
        "format": fmt,
        "commit": head,
        "run_url": run_url,
        "input_hash": fingerprint,
        "run_id": run_id,
        "imported": len(results),
        "checks": _checks_payload(mapped, outcomes),
        "scenarios": sorted(str(result["id"]) for result in results),
        "report_sha256": report_sha256,
    }


def _attach_check_hashes(
    data: Mapping[str, object], results: Sequence[dict[str, object]],
    per_check: Mapping[str, Mapping[str, object]], fallback: str,
) -> None:
    rows = {
        str(item.get("id")): item for item in data.get("scenarios", [])
        if isinstance(item, Mapping) and item.get("id")
    }
    for result in results:
        row = rows.get(str(result.get("id")))
        if not row:
            continue
        raw = result.get("check_ids")
        check_ids = [str(value) for value in raw] if isinstance(raw, list) else []
        if not check_ids:
            raw = row.get("checks")
            check_ids = [str(value) for value in raw] if isinstance(raw, list) else []
        if not check_ids and isinstance(row.get("check"), str):
            check_ids = [str(row.get("check"))]
        if not check_ids:
            result["input_hash"] = fallback
            continue
        hashes = {
            check_id: str(per_check.get(check_id, {}).get("input_hash") or fallback)
            for check_id in check_ids
        }
        result["check_ids"] = check_ids
        result["check_hashes"] = hashes
        if len(hashes) == 1:
            result["input_hash"] = next(iter(hashes.values()))
        else:
            payload = "|".join(f"{key}={hashes[key]}" for key in sorted(hashes))
            result["input_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()


def import_report(
    root: object, *, report: object, fmt: str, commit: str, run_url: str,
    manifest: str = "", task_dir: str = "", check: str = "", exit_code: Optional[int] = None,
) -> dict[str, object]:
    """Import one CI report; returns the imported evidence summary."""
    project = discover_project_root(root)
    report_path = Path(report)
    plan_path = _resolve_manifest(project, manifest, task_dir)
    if not plan_path.is_file():
        raise EvidenceImportError("manifest_missing", "manifest", "acceptance manifest not found", str(plan_path))
    data, checks, linked, assertions = _load_plan(plan_path)
    url = _require_run_url(run_url)
    if check and check not in checks:
        raise EvidenceImportError("unknown_check", "check", f"check not in manifest: {check}")
    if check and not any(check in scenario_check_ids(row) for row in data["scenarios"]):
        raise EvidenceImportError("check_without_scenarios", "check", f"check has no scenario: {check}")
    cases = load_report(report_path, fmt)
    mapped = _map_cases(cases, check, checks, linked, assertions)
    head = _resolve_commit(project, commit)
    outcomes = _check_outcomes(mapped)
    derived_exit = 0 if all(status == "passed" for status, _ in outcomes.values()) else 1
    if exit_code is not None and exit_code != derived_exit:
        raise EvidenceImportError(
            "exit_code_mismatch", "exit_code", f"CI exit code {exit_code} != report exit code {derived_exit}"
        )
    _require_clean(project)
    fingerprint = worktree_fingerprint(str(project))
    if not fingerprint:
        raise EvidenceImportError("input_hash_unavailable", "input_hash", "cannot fingerprint the worktree")
    check_hashes = check_input_hashes(str(project), checks, fingerprint)
    digest = _report_digest(report_path)
    run_id = hashlib.sha256(
        json.dumps([head, fmt, digest, url], ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:32]
    results = _scenario_results(
        data, outcomes, commit=head, run_url=url, fmt=fmt, report_sha256=digest
    )
    _attach_check_hashes(data, results, check_hashes, fingerprint)
    if not results:
        raise EvidenceImportError("check_without_scenarios", "check", "report checks have no scenario")
    decision = "pass" if derived_exit == 0 else "block"
    if _already_imported(data, results, run_id):
        return _payload("unchanged", decision, results, mapped, outcomes, fmt=fmt, head=head,
                        run_url=url, fingerprint=fingerprint, run_id=run_id, report_sha256=digest)
    persist_results(plan_path, data, results, fingerprint=fingerprint, run_id=run_id)
    return _payload("imported", decision, results, mapped, outcomes, fmt=fmt, head=head,
                    run_url=url, fingerprint=fingerprint, run_id=run_id, report_sha256=digest)


def _rejection(code: str, field: str, message: str, path: str = "") -> dict[str, object]:
    return {"status": "rejected", "decision": "block", "error_code": code,
            "field": field, "error": message, "message": message, "path": path}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND") or "code-flow evidence")
    actions = parser.add_subparsers(dest="action", required=True)
    importer = actions.add_parser("import", help="Import a CI JUnit/Playwright report as evidence")
    importer.add_argument("--format", required=True, choices=FORMATS)
    importer.add_argument("--file", required=True)
    importer.add_argument("--commit", required=True)
    importer.add_argument("--run-url", required=True)
    importer.add_argument("--root", default=".")
    importer.add_argument("--manifest", default="")
    importer.add_argument("--task-dir", default="")
    importer.add_argument("--check", default="", help="Report belongs to one manifest check")
    importer.add_argument("--exit-code", type=int, default=None, help="Cross-check the CI job exit code")
    importer.add_argument("--json", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    args = _parser().parse_args(argv)
    try:
        result = import_report(
            args.root, report=args.file, fmt=args.format, commit=args.commit, run_url=args.run_url,
            manifest=args.manifest, task_dir=args.task_dir, check=args.check, exit_code=args.exit_code,
        )
    except EvidenceImportError as exc:
        stdout.write(json.dumps(_rejection(exc.code, exc.field, exc.message, exc.path), ensure_ascii=False))
        return 2
    except EvidenceStoreError as exc:
        stdout.write(json.dumps(_rejection(exc.code, exc.field, exc.message, exc.path), ensure_ascii=False))
        return 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        stdout.write(json.dumps(_rejection("import_failed", "file", str(exc)), ensure_ascii=False))
        return 2
    stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
