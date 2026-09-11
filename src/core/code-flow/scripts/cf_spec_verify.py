#!/usr/bin/env python3
"""Rule verifier registry and hash-bound Verification Evidence."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
from pathlib import Path
import subprocess
from threading import Lock
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Mapping, Optional, Sequence

from cf_checks import run_regex_verifier
from cf_spec_metadata import SpecMetadata, SpecRule, SpecVerifier
from cf_exec_base import execution_session, run_command


_RESULT_CACHE: dict[str, dict[str, object]] = {}
_RESULT_CACHE_ROOT: Optional[str] = None
_RESULT_CACHE_DIRTY = False
_RESULT_CACHE_LOCK = Lock()
_MAX_RESULT_CACHE_ENTRIES = 2048
_PURE_VERIFIER_TYPES = frozenset(("document", "regex", "ast"))


@dataclass(frozen=True)
class VerificationScope:
    root: str
    files: tuple[str, ...]
    diff_sha256: Optional[str]


@dataclass(frozen=True)
class VerificationEvidence:
    verifier_ref: str
    executed_at: str
    status: str
    rule_text_sha256: str
    artifact_sha256: Optional[str]
    diff_sha256: Optional[str]
    result_sha256: str
    error_code: Optional[str]
    details: Mapping[str, object]


@dataclass(frozen=True)
class VerificationResult:
    evidence: tuple[VerificationEvidence, ...]
    passed: bool


def _cache_file(root: str) -> Path:
    return Path(root) / ".code-flow" / ".verifier-cache.json"


def _cache_key(metadata: SpecMetadata, rule: SpecRule, verifier: SpecVerifier, scope: VerificationScope, confirmation: Optional[Mapping[str, object]]) -> str:
    payload = {
        "spec": metadata.hashes.file_sha256,
        "rule": rule.text_sha256,
        "verifier": {"type": verifier.type, "config": verifier.config},
        "files": scope.files,
        "diff": scope.diff_sha256,
        "confirmation": confirmation or {},
        "artifact_content": _artifact_fingerprint(verifier, scope),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _artifact_fingerprint(verifier: SpecVerifier, scope: VerificationScope) -> Optional[str]:
    if verifier.type != "document":
        return None
    relative = verifier.config.get("artifact")
    if not isinstance(relative, str):
        return "invalid"
    try:
        return hashlib.sha256((Path(scope.root) / relative).read_bytes()).hexdigest()
    except OSError as exc:
        return f"unreadable:{exc}"


def _load_result_cache(root: str) -> None:
    global _RESULT_CACHE_ROOT, _RESULT_CACHE, _RESULT_CACHE_DIRTY
    if _RESULT_CACHE_ROOT == root:
        return
    _RESULT_CACHE_ROOT = root
    _RESULT_CACHE = {}
    _RESULT_CACHE_DIRTY = False
    path = _cache_file(root)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            _RESULT_CACHE.update({str(key): value for key, value in loaded.items() if isinstance(value, dict)})
    except (OSError, ValueError):
        pass


def _cached_evidence(key: str) -> Optional[VerificationEvidence]:
    item = _RESULT_CACHE.get(key)
    if not isinstance(item, dict) or item.get("status") != "verified":
        return None
    try:
        return VerificationEvidence(**item)
    except (TypeError, ValueError):
        return None


def _save_result_cache(key: str, evidence: VerificationEvidence) -> None:
    global _RESULT_CACHE_DIRTY
    with _RESULT_CACHE_LOCK:
        _RESULT_CACHE[key] = evidence.__dict__
        _RESULT_CACHE_DIRTY = True
        while len(_RESULT_CACHE) > _MAX_RESULT_CACHE_ENTRIES:
            _RESULT_CACHE.pop(next(iter(_RESULT_CACHE)))


def _flush_result_cache(root: str) -> None:
    global _RESULT_CACHE_DIRTY
    with _RESULT_CACHE_LOCK:
        if not _RESULT_CACHE_DIRTY:
            return
        path = _cache_file(root)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(_RESULT_CACHE, ensure_ascii=False, sort_keys=True, default=str), encoding="utf-8"
            )
            temporary.replace(path)
            _RESULT_CACHE_DIRTY = False
        except OSError:
            pass


def _cached_or_run(
    metadata: SpecMetadata,
    rule: SpecRule,
    verifier: SpecVerifier,
    scope: VerificationScope,
    confirmation: Optional[Mapping[str, object]],
) -> VerificationEvidence:
    cacheable = verifier.type in _PURE_VERIFIER_TYPES
    key = _cache_key(metadata, rule, verifier, scope, confirmation) if cacheable else ""
    if cacheable:
        cached = _cached_evidence(key)
        if cached is not None:
            return cached
    current = _evidence(metadata, rule, verifier, scope, confirmation)
    if cacheable and current.status == "verified":
        _save_result_cache(key, current)
    return current


@dataclass(frozen=True)
class _Outcome:
    passed: bool
    error_code: Optional[str]
    artifact_sha256: Optional[str]
    details: Mapping[str, object]


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _result_hash(status: str, error: Optional[str], details: Mapping[str, object]) -> str:
    payload = {"status": status, "error_code": error, "details": details}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return _hash_bytes(encoded)


def _config_string(config: Mapping[str, object], key: str) -> Optional[str]:
    value = config.get(key)
    return value if isinstance(value, str) and value else None


def _read_scope_files(scope: VerificationScope) -> tuple[dict[str, str], Optional[_Outcome]]:
    contents: dict[str, str] = {}
    for relative in scope.files:
        path = Path(scope.root) / relative
        try:
            contents[relative] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            outcome = _Outcome(False, "file_read_error", None, {"file": relative, "error": str(exc)})
            return {}, outcome
    return contents, None


def _document(config: Mapping[str, object], scope: VerificationScope) -> _Outcome:
    relative = _config_string(config, "artifact")
    section = _config_string(config, "section_id")
    item = _config_string(config, "item_id")
    if not relative or not section or not item:
        return _Outcome(False, "invalid_verifier_config", None, {"required": ["artifact", "section_id", "item_id"]})
    path = Path(scope.root) / relative
    try:
        content = path.read_text(encoding="utf-8")
        artifact_hash = _hash_bytes(path.read_bytes())
    except (OSError, UnicodeError) as exc:
        return _Outcome(False, "artifact_read_error", None, {"artifact": relative, "error": str(exc)})
    expected = _config_string(config, "artifact_sha256")
    present = section in content and item in content
    hash_matches = expected is None or expected == artifact_hash
    details = {"artifact": relative, "section_present": section in content, "item_present": item in content, "hash_matches": hash_matches}
    return _Outcome(present and hash_matches, None if present and hash_matches else "document_mismatch", artifact_hash, details)


def _regex(config: Mapping[str, object], metadata: SpecMetadata, scope: VerificationScope) -> _Outcome:
    pattern = _config_string(config, "pattern")
    files = _config_string(config, "files") or "*"
    check_id = _config_string(config, "check_id")
    if check_id:
        check = next((item for item in metadata.checks if item.get("id") == check_id), None)
        if check is None:
            return _Outcome(False, "check_not_found", None, {"check_id": check_id})
        pattern = check.get("pattern") if isinstance(check.get("pattern"), str) else None
        files = check.get("files") if isinstance(check.get("files"), str) else "*"
    if pattern is None:
        return _Outcome(False, "invalid_verifier_config", None, {"required": ["pattern"]})
    selected = tuple(
        relative
        for relative in scope.files
        if fnmatch.fnmatch(relative, files) and (Path(scope.root) / relative).is_file()
    )
    contents, error = _read_scope_files(VerificationScope(scope.root, selected, scope.diff_sha256))
    if error is not None:
        return error
    violations, skipped = run_regex_verifier(pattern, files, contents)
    if skipped:
        return _Outcome(False, "regex_unavailable", None, {"skipped": skipped})
    details = {"checked_files": len(contents), "violations": violations}
    return _Outcome(not violations, None if not violations else "regex_violation", None, details)


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _ast(config: Mapping[str, object], scope: VerificationScope) -> _Outcome:
    if _config_string(config, "language") != "python":
        return _Outcome(False, "unsupported_ast_language", None, {"language": config.get("language")})
    assertion = _config_string(config, "assertion") or "parse"
    contents, error = _read_scope_files(scope)
    if error is not None:
        return error
    parsed: list[ast.AST] = []
    try:
        parsed = [ast.parse(content, filename=relative) for relative, content in contents.items()]
    except SyntaxError as exc:
        return _Outcome(False, "ast_parse_error", None, {"error": str(exc)})
    if assertion == "parse":
        return _Outcome(True, None, None, {"parsed_files": len(parsed)})
    if assertion == "forbid_call":
        call = _config_string(config, "call")
        hits = sum(_call_name(node) == call for tree in parsed for node in ast.walk(tree) if isinstance(node, ast.Call))
        return _Outcome(hits == 0, None if hits == 0 else "ast_assertion_failed", None, {"call": call, "hits": hits})
    return _Outcome(False, "unsupported_ast_assertion", None, {"assertion": assertion})


def _argv(config: Mapping[str, object]) -> Optional[list[str]]:
    value = config.get("argv")
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        return None
    return list(value)


def _command(config: Mapping[str, object], scope: VerificationScope, timeout_cap: Optional[float] = None) -> _Outcome:
    argv = _argv(config)
    if argv is None:
        return _Outcome(False, "invalid_verifier_config", None, {"required": ["argv"]})
    cwd = _config_string(config, "cwd") or "."
    timeout_value = config.get("timeout", 30)
    timeout = float(timeout_value) if isinstance(timeout_value, (int, float)) else 30.0
    allowed_value = config.get("allowed_exit_codes", [0])
    allowed = tuple(item for item in allowed_value if isinstance(item, int)) if isinstance(allowed_value, list) else (0,)
    deadline = None if timeout_cap is None else time.monotonic() + timeout_cap
    completed = run_command(argv, str(Path(scope.root) / cwd), timeout, deadline)
    if completed["status"] in ("timeout", "deadline_exceeded"):
        return _Outcome(False, "verifier_timeout", None, {"timeout": timeout, "argv": argv})
    if completed["status"] == "spawn_error":
        return _Outcome(False, "command_unavailable", None, {"argv": argv, "error": completed["stderr"]})
    details = {
        "argv": argv,
        "exit_code": completed["returncode"],
        "stdout_sha256": _hash_bytes(str(completed["stdout"]).encode()),
        "stderr_sha256": _hash_bytes(str(completed["stderr"]).encode()),
        "output": (str(completed["stdout"]) + str(completed["stderr"]))[-4000:],
    }
    passed = completed["returncode"] in allowed
    return _Outcome(passed, None if passed else "command_failed", None, details)


def _manual(config: Mapping[str, object], confirmation: Optional[Mapping[str, object]]) -> _Outcome:
    if confirmation is None:
        return _Outcome(False, "manual_confirmation_missing", None, {"checklist": config.get("checklist")})
    required = ("reason", "confirmed_by", "confirmed_at", "source")
    if not all(isinstance(confirmation.get(key), str) and confirmation.get(key) for key in required):
        return _Outcome(False, "manual_confirmation_invalid", None, {"required": list(required)})
    identity = str(confirmation["confirmed_by"]).lower().split(":", 1)[0]
    if identity in ("agent", "assistant", "codex", "claude", "opencode", "costrict"):
        return _Outcome(False, "manual_agent_forbidden", None, {"confirmed_by": confirmation["confirmed_by"]})
    return _Outcome(True, None, None, {"source": confirmation["source"], "owner": config.get("owner")})


def _run(
    verifier: SpecVerifier,
    metadata: SpecMetadata,
    scope: VerificationScope,
    confirmation: Optional[Mapping[str, object]],
    timeout_cap: Optional[float] = None,
) -> _Outcome:
    if verifier.type == "document":
        return _document(verifier.config, scope)
    if verifier.type == "regex":
        return _regex(verifier.config, metadata, scope)
    if verifier.type == "ast":
        return _ast(verifier.config, scope)
    if verifier.type in ("command", "test"):
        return _command(verifier.config, scope, timeout_cap)
    if verifier.type == "manual":
        return _manual(verifier.config, confirmation)
    return _Outcome(False, "verifier_type_unimplemented", None, {"type": verifier.type})


def _evidence(
    metadata: SpecMetadata,
    rule: SpecRule,
    verifier: SpecVerifier,
    scope: VerificationScope,
    confirmation: Optional[Mapping[str, object]],
    timeout_cap: Optional[float] = None,
) -> VerificationEvidence:
    outcome = _run(verifier, metadata, scope, confirmation, timeout_cap)
    status = "verified" if outcome.passed else "unverified"
    diff_hash = None if verifier.type == "document" else scope.diff_sha256
    return VerificationEvidence(
        f"{metadata.id}#{rule.ref}",
        datetime.now(timezone.utc).isoformat(),
        status,
        rule.text_sha256,
        outcome.artifact_sha256,
        diff_hash,
        _result_hash(status, outcome.error_code, outcome.details),
        outcome.error_code,
        outcome.details,
    )


def _skipped_evidence(metadata: SpecMetadata, rule: SpecRule, scope: VerificationScope) -> VerificationEvidence:
    details = {"skipped": True}
    return VerificationEvidence(
        f"{metadata.id}#{rule.ref}",
        datetime.now(timezone.utc).isoformat(),
        "unverified",
        rule.text_sha256,
        None,
        scope.diff_sha256,
        _result_hash("unverified", "skipped_in_cheap_gate", details),
        "skipped_in_cheap_gate",
        details,
    )


def _budget_evidence(metadata: SpecMetadata, rule: SpecRule, scope: VerificationScope, budget: float) -> VerificationEvidence:
    details = {"budget": budget}
    return VerificationEvidence(
        f"{metadata.id}#{rule.ref}",
        datetime.now(timezone.utc).isoformat(),
        "unverified",
        rule.text_sha256,
        None,
        scope.diff_sha256,
        _result_hash("unverified", "verifier_budget_exhausted", details),
        "verifier_budget_exhausted",
        details,
    )


def _missing_evidence(metadata: SpecMetadata, rule: SpecRule, scope: VerificationScope) -> VerificationEvidence:
    details = {"rule": rule.ref}
    return VerificationEvidence(
        f"{metadata.id}#{rule.ref}", datetime.now(timezone.utc).isoformat(),
        "unverified", rule.text_sha256, None, scope.diff_sha256,
        _result_hash("unverified", "verifier_missing", details), "verifier_missing", details,
    )


def _run_all_verifiers(
    metadata: SpecMetadata,
    scope: VerificationScope,
    confirmations: Optional[Mapping[str, Mapping[str, object]]] = None,
    skip_command: bool = False,
    timeout_budget: Optional[float] = None,
) -> VerificationResult:
    verifier_by_rule = {item.rule: item for item in metadata.verifiers}
    confirmation_by_rule = confirmations or {}
    _load_result_cache(scope.root)
    evidence_by_ref: dict[str, VerificationEvidence] = {}
    parallel: list[tuple[SpecRule, SpecVerifier, Optional[Mapping[str, object]]]] = []
    started = time.monotonic()
    for rule in metadata.rules:
        if rule.enforcement != "required":
            continue
        if timeout_budget is not None:
            remaining = timeout_budget - (time.monotonic() - started)
            if remaining <= 0:
                evidence_by_ref[rule.ref] = _budget_evidence(metadata, rule, scope, timeout_budget)
                continue
        verifier = verifier_by_rule.get(rule.ref)
        if verifier is None:
            evidence_by_ref[rule.ref] = _missing_evidence(metadata, rule, scope)
            continue
        if skip_command and verifier.type in ("command", "test"):
            evidence_by_ref[rule.ref] = _skipped_evidence(metadata, rule, scope)
            continue
        confirmation = confirmation_by_rule.get(rule.ref)
        if timeout_budget is None and verifier.type in ("document", "regex", "ast"):
            parallel.append((rule, verifier, confirmation))
            continue
        cap = None if timeout_budget is None else max(0.1, timeout_budget - (time.monotonic() - started))
        evidence_by_ref[rule.ref] = _cached_or_run(metadata, rule, verifier, scope, confirmation) if cap is None else _evidence(metadata, rule, verifier, scope, confirmation, cap)
    if parallel:
        with ThreadPoolExecutor(max_workers=min(8, len(parallel))) as pool:
            futures = {
                rule.ref: pool.submit(_cached_or_run, metadata, rule, verifier, scope, confirmation)
                for rule, verifier, confirmation in parallel
            }
            evidence_by_ref.update({ref: future.result() for ref, future in futures.items()})
    result = tuple(evidence_by_ref[rule.ref] for rule in metadata.rules if rule.ref in evidence_by_ref)
    _flush_result_cache(scope.root)
    return VerificationResult(result, bool(result) and all(item.status == "verified" for item in result))


def run_all_verifiers(metadata: SpecMetadata, scope: VerificationScope,
                      confirmations: Optional[Mapping[str, Mapping[str, object]]] = None,
                      skip_command: bool = False, timeout_budget: Optional[float] = None) -> VerificationResult:
    with execution_session():
        return _run_all_verifiers(metadata, scope, confirmations, skip_command, timeout_budget)


def evidence_is_fresh(
    evidence: VerificationEvidence,
    rule_text_sha256: str,
    artifact_sha256: Optional[str],
    diff_sha256: Optional[str],
) -> bool:
    return (
        evidence.status == "verified"
        and evidence.rule_text_sha256 == rule_text_sha256
        and evidence.artifact_sha256 == artifact_sha256
        and evidence.diff_sha256 == diff_sha256
    )
