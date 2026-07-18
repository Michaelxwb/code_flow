#!/usr/bin/env python3
"""Spec frontmatter checks: parse, cache and execute (quality loop FEAT-01).

Contract (spec-quality-loop.design.md §2.3.2 / §3.4 / §3.5):
- Checks live in spec frontmatter `checks:` so rule text and machine check
  stay in the same file (ADR: frontmatter over checks.yml).
- Invalid entries are skipped and surfaced as parse errors (E-01) — they must
  never break parsing of sibling checks or spec injection.
- Execution guards: per-check timeout (E-02), oversized content skipped
  (B-01), disabled checks filtered (RULE-04 state), matched lines per check
  capped so feedback stays small (RISK-05).
- yaml import is lazy: specs without `checks:` never pay for it on the
  PostToolUse hot path (NFR-PERF-01).
"""
import fnmatch
import os
import re
import sys
from typing import Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from cf_core import _FRONTMATTER_RE, normalize_path

CHECK_TIMEOUT_SECONDS = 2.0
MAX_CONTENT_BYTES = 256 * 1024
MESSAGE_MAX_LEN = 200
MAX_LINES_PER_CHECK = 3

_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
IMPLEMENTED_TYPES = ("regex",)
RESERVED_TYPES = ("ast", "cmd")  # interface reserved, implementation deferred
_SEVERITIES = ("warn", "info")  # no "error": feedback only, never blocking

_checks_cache: dict = {}

STATE_NAME = ".check-state.json"
FP_DISABLE_COUNT = 3
FP_DISABLE_RATE = 0.10


def _log(msg: str) -> None:
    sys.stderr.write(f"[cf-checks] {msg}\n")


def state_path(project_root: str) -> str:
    return os.path.join(project_root, ".code-flow", STATE_NAME)


def load_check_state(project_root: str) -> dict:
    """Read check-state; corrupt/missing files rebuild as empty (tolerant)."""
    import json
    try:
        with open(state_path(project_root), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_check_state(project_root: str, state: dict) -> bool:
    import json
    try:
        path = state_path(project_root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        return True
    except Exception as exc:
        _log(f"save_check_state failed: {exc}")
        return False


def record_hits(project_root: str, check_ids: list) -> dict:
    """Increment hit_count for triggered checks (误报率分母). Returns state."""
    state = load_check_state(project_root)
    for cid in check_ids:
        entry = state.setdefault(cid, {})
        entry["hit_count"] = int(entry.get("hit_count", 0)) + 1
    save_check_state(project_root, state)
    return state


def record_false_positive(project_root: str, check_id: str) -> dict:
    """Mark one false positive; auto-disable past RULE-04 thresholds.

    Returns {"check_id", "fp_count", "hit_count", "disabled"}.
    """
    state = load_check_state(project_root)
    entry = state.setdefault(check_id, {})
    entry["fp_count"] = int(entry.get("fp_count", 0)) + 1
    fp = entry["fp_count"]
    hits = int(entry.get("hit_count", 0))
    if not entry.get("disabled") and (
        fp >= FP_DISABLE_COUNT or (hits > 0 and fp / hits > FP_DISABLE_RATE)
    ):
        entry["disabled"] = True
        entry["disabled_reason"] = (
            f"auto: fp_count={fp}" if fp >= FP_DISABLE_COUNT
            else f"auto: fp_rate={fp}/{hits}"
        )
    save_check_state(project_root, state)
    return {
        "check_id": check_id,
        "fp_count": fp,
        "hit_count": hits,
        "disabled": bool(entry.get("disabled")),
    }


def _validate_entry(entry: object, index: int, seen_ids: set) -> tuple:
    """Validate one raw checks entry → (check_dict | None, error | None)."""
    if not isinstance(entry, dict):
        return None, f"checks[{index}]: 不是对象，已跳过"
    cid = entry.get("id")
    if not isinstance(cid, str) or not _ID_RE.match(cid):
        return None, f"checks[{index}]: id 缺失或非 kebab-case，已跳过"
    if cid in seen_ids:
        return None, f"checks[{index}]: id '{cid}' 重复，已跳过"
    ctype = entry.get("type")
    if ctype in RESERVED_TYPES:
        return None, f"{cid}: type '{ctype}' 暂未实现（接口预留），已跳过"
    if ctype not in IMPLEMENTED_TYPES:
        return None, f"{cid}: 未知 type '{ctype}'，已跳过"
    pattern = entry.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        return None, f"{cid}: pattern 缺失，已跳过"
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return None, f"{cid}: pattern 非法正则（{exc}），已跳过"

    message = entry.get("message")
    if not isinstance(message, str) or not message.strip():
        return None, f"{cid}: message 缺失，已跳过"
    error = None
    if len(message) > MESSAGE_MAX_LEN:
        error = f"{cid}: message 超过 {MESSAGE_MAX_LEN} 字符，运行时截断"
        message = message[:MESSAGE_MAX_LEN]

    severity = entry.get("severity", "warn")
    if severity not in _SEVERITIES:
        error = error or f"{cid}: severity '{severity}' 非法，按 warn 处理"
        severity = "warn"

    # default "*": fnmatch's "*" crosses "/" so it matches any depth;
    # "**/*" under fnmatch would demand at least one directory level and
    # silently skip repo-root files (same pitfall fixed in config patterns)
    files = entry.get("files")
    if not isinstance(files, str) or not files:
        files = "*"

    return {
        "id": cid,
        "type": ctype,
        "pattern": pattern,
        "regex": compiled,
        "files": files,
        "message": message,
        "severity": severity,
    }, error


def parse_spec_checks(content: str) -> tuple:
    """Parse frontmatter checks → (checks, errors). Both lists, never raises."""
    if not isinstance(content, str):
        return [], []
    match = _FRONTMATTER_RE.match(content)
    if not match or "checks:" not in match.group(1):
        return [], []
    try:
        import yaml
        meta = yaml.safe_load(match.group(1)) or {}
    except Exception as exc:
        return [], [f"frontmatter YAML 解析失败: {exc}"]
    raw = meta.get("checks")
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], ["checks 必须是列表"]
    checks: list = []
    errors: list = []
    seen_ids: set = set()
    for index, entry in enumerate(raw):
        check, error = _validate_entry(entry, index, seen_ids)
        if error:
            errors.append(error)
        if check:
            checks.append(check)
            seen_ids.add(check["id"])
    return checks, errors


def load_spec_checks(spec_abs_path: str) -> tuple:
    """Parse a spec file's checks with mtime cache → (checks, errors)."""
    try:
        mtime = os.path.getmtime(spec_abs_path)
    except OSError:
        return [], []
    cached = _checks_cache.get(spec_abs_path)
    if cached and cached["mtime"] == mtime:
        return cached["checks"], cached["errors"]
    try:
        with open(spec_abs_path, "r", encoding="utf-8") as f:
            checks, errors = parse_spec_checks(f.read())
    except Exception as exc:
        _log(f"load_spec_checks failed {spec_abs_path}: {exc}")
        return [], []
    _checks_cache[spec_abs_path] = {
        "mtime": mtime, "checks": checks, "errors": errors,
    }
    return checks, errors


# 纠正句式（FEAT-04 信号①）：保守收录、宁漏勿误（E-06）。
# 否定排除：不要紧/不要紧张、对不对、不对外/不对称。
_CORRECTION_PATTERNS = [
    r"不要(?!紧)",
    r"(?<!对)不对(?![外称])",
    r"不是这样",
    r"我说过",
    r"改回[去来]",
    r"别再?用",
    r"写错了",
    r"\bdon'?t\s+use\b",
    r"\bthat'?s\s+wrong\b",
    r"\bI\s+said\b",
    r"\brevert\s+(that|this|it)\b",
    r"\bstop\s+using\b",
]
_CORRECTION_RE = re.compile("|".join(_CORRECTION_PATTERNS), re.IGNORECASE)


def detect_correction(prompt: str) -> dict:
    """Detect a correction phrase in a user prompt → {"phrase", "span"} | None.

    Single combined regex, first hit wins; the wordlist is deliberately
    conservative — a missed correction only delays learning, a false hit
    pollutes the candidate stream.
    """
    if not isinstance(prompt, str) or not prompt:
        return None
    match = _CORRECTION_RE.search(prompt)
    if not match:
        return None
    return {"phrase": match.group(0), "span": [match.start(), match.end()]}


def _match_lines(regex, content: str) -> list:
    hits = []
    for line_no, line in enumerate(content.splitlines(), 1):
        if regex.search(line):
            hits.append((line_no, line.strip()))
            if len(hits) >= MAX_LINES_PER_CHECK:
                break
    return hits


def run_checks(
    checks: list,
    rel_path: str,
    content: str,
    state: dict = None,
    timeout: float = CHECK_TIMEOUT_SECONDS,
) -> tuple:
    """Execute checks against one file's content → (violations, skipped).

    violations: [{check_id, file, line_no, line, message, severity}]
    skipped:    [{check_id, reason}] — timeout / oversize, caller records
                degrade events (E-02 / B-01).
    Disabled checks (state[check_id]["disabled"]) are silently filtered.
    """
    violations: list = []
    skipped: list = []
    if not checks or not isinstance(content, str):
        return violations, skipped
    if len(content.encode("utf-8", errors="ignore")) > MAX_CONTENT_BYTES:
        return violations, [{"check_id": "*", "reason": "content_too_large"}]

    rel_path = normalize_path(rel_path)
    state = state or {}
    with ThreadPoolExecutor(max_workers=1) as pool:
        for check in checks:
            if state.get(check["id"], {}).get("disabled"):
                continue
            if not fnmatch.fnmatch(rel_path, check["files"]):
                continue
            future = pool.submit(_match_lines, check["regex"], content)
            try:
                hits = future.result(timeout=timeout)
            except FutureTimeout:
                skipped.append({"check_id": check["id"], "reason": "timeout"})
                future.cancel()
                continue
            except Exception as exc:
                skipped.append({"check_id": check["id"], "reason": f"error:{exc}"})
                continue
            for line_no, line in hits:
                violations.append({
                    "check_id": check["id"],
                    "file": rel_path,
                    "line_no": line_no,
                    "line": line[:160],
                    "message": check["message"],
                    "severity": check["severity"],
                })
    return violations, skipped


def run_regex_verifier(
    pattern: str,
    files: str,
    contents: Mapping[str, str],
    timeout: float = CHECK_TIMEOUT_SECONDS,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Execute one verifier regex over explicit file contents."""
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return [], [{"check_id": "verifier", "reason": f"invalid_regex:{exc}"}]
    check = {
        "id": "verifier",
        "type": "regex",
        "pattern": pattern,
        "regex": compiled,
        "files": files,
        "message": "Rule verifier matched forbidden content",
        "severity": "warn",
    }
    violations: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    for relative, content in contents.items():
        file_violations, file_skipped = run_checks([check], relative, content, timeout=timeout)
        violations.extend(file_violations)
        skipped.extend(file_skipped)
    return violations, skipped
