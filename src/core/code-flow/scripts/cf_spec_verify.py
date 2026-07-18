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
from typing import Mapping, Optional, Sequence

from cf_checks import run_regex_verifier
from cf_spec_metadata import SpecMetadata, SpecRule, SpecVerifier


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


def _command(config: Mapping[str, object], scope: VerificationScope) -> _Outcome:
    argv = _argv(config)
    if argv is None:
        return _Outcome(False, "invalid_verifier_config", None, {"required": ["argv"]})
    cwd = _config_string(config, "cwd") or "."
    timeout_value = config.get("timeout", 30)
    timeout = float(timeout_value) if isinstance(timeout_value, (int, float)) else 30.0
    allowed_value = config.get("allowed_exit_codes", [0])
    allowed = tuple(item for item in allowed_value if isinstance(item, int)) if isinstance(allowed_value, list) else (0,)
    try:
        completed = subprocess.run(
            argv,
            cwd=str(Path(scope.root) / cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _Outcome(False, "verifier_timeout", None, {"timeout": timeout, "argv": argv})
    except OSError as exc:
        return _Outcome(False, "command_unavailable", None, {"argv": argv, "error": str(exc)})
    details = {
        "argv": argv,
        "exit_code": completed.returncode,
        "stdout_sha256": _hash_bytes(completed.stdout.encode()),
        "stderr_sha256": _hash_bytes(completed.stderr.encode()),
    }
    passed = completed.returncode in allowed
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
) -> _Outcome:
    if verifier.type == "document":
        return _document(verifier.config, scope)
    if verifier.type == "regex":
        return _regex(verifier.config, metadata, scope)
    if verifier.type == "ast":
        return _ast(verifier.config, scope)
    if verifier.type in ("command", "test"):
        return _command(verifier.config, scope)
    if verifier.type == "manual":
        return _manual(verifier.config, confirmation)
    return _Outcome(False, "verifier_type_unimplemented", None, {"type": verifier.type})


def _evidence(
    metadata: SpecMetadata,
    rule: SpecRule,
    verifier: SpecVerifier,
    scope: VerificationScope,
    confirmation: Optional[Mapping[str, object]],
) -> VerificationEvidence:
    outcome = _run(verifier, metadata, scope, confirmation)
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


def run_all_verifiers(
    metadata: SpecMetadata,
    scope: VerificationScope,
    confirmations: Optional[Mapping[str, Mapping[str, object]]] = None,
) -> VerificationResult:
    verifier_by_rule = {item.rule: item for item in metadata.verifiers}
    confirmation_by_rule = confirmations or {}
    evidence: list[VerificationEvidence] = []
    for rule in metadata.rules:
        if rule.enforcement != "required":
            continue
        verifier = verifier_by_rule.get(rule.ref)
        if verifier is None:
            details = {"rule": rule.ref}
            evidence.append(
                VerificationEvidence(
                    f"{metadata.id}#{rule.ref}",
                    datetime.now(timezone.utc).isoformat(),
                    "unverified",
                    rule.text_sha256,
                    None,
                    scope.diff_sha256,
                    _result_hash("unverified", "verifier_missing", details),
                    "verifier_missing",
                    details,
                )
            )
            continue
        evidence.append(_evidence(metadata, rule, verifier, scope, confirmation_by_rule.get(rule.ref)))
    result = tuple(evidence)
    return VerificationResult(result, bool(result) and all(item.status == "verified" for item in result))


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
