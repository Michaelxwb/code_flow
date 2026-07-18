#!/usr/bin/env python3
import fnmatch
import os
import re
import sys

# --- Config cache (fix #3: avoid re-parsing YAML on every hook call) ---

_config_cache: dict = {}
_spec_domains_cache: dict = {}
_effective_mapping_cache: dict = {}
_ext_set_cache: dict = {}


def load_config(project_root: str) -> dict:
    config_path = os.path.join(project_root, ".code-flow", "config.yml")
    if not os.path.exists(config_path):
        return {}
    try:
        mtime = os.path.getmtime(config_path)
    except OSError:
        return {}
    cached = _config_cache.get(config_path)
    if cached and cached["mtime"] == mtime:
        return cached["data"]
    try:
        import yaml
    except Exception:
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
        result = data or {}
        _config_cache[config_path] = {"mtime": mtime, "data": result}
        return result
    except Exception:
        return {}


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def normalize_path(path: str) -> str:
    # Unconditional backslash replacement, not `os.sep`, so paths pasted from
    # a Windows machine into a prompt on macOS/Linux still normalize correctly.
    # On Windows `os.sep == '\\'`, so behavior there is unchanged.
    return path.replace("\\", "/")


def _spec_path_from_entry(entry) -> str:
    cfg = normalize_spec_entry(entry)
    return normalize_path(cfg.get("path", ""))


def discover_spec_domains(project_root: str) -> dict:
    cached = _spec_domains_cache.get(project_root)
    if cached is not None:
        return cached
    specs_root = os.path.join(project_root, ".code-flow", "specs")
    discovered = {}
    if not os.path.isdir(specs_root):
        _spec_domains_cache[project_root] = discovered
        return discovered

    for root, _, files in os.walk(specs_root):
        for filename in files:
            if not filename.endswith(".md"):
                continue
            full_path = os.path.join(root, filename)
            rel = normalize_path(os.path.relpath(full_path, specs_root))
            parts = rel.split("/", 1)
            if len(parts) < 2:
                continue
            domain = parts[0]
            discovered.setdefault(domain, []).append(rel)

    for domain in discovered:
        discovered[domain] = sorted(set(discovered[domain]))
    _spec_domains_cache[project_root] = discovered
    return discovered


def _default_spec_entry(rel: str) -> dict:
    tier = 0 if rel.endswith("/_map.md") else 1
    # shared/ 下非 _map.md 的文件是供 cf-task:align / cf-task:prd 命令
    # 显式 Read 的模板，不是约束规范，禁止通配符自动注入。
    if rel.startswith("shared/") and not rel.endswith("/_map.md"):
        return {"path": rel, "tags": [], "tier": tier}
    return {"path": rel, "tags": ["*"], "tier": tier}


def build_effective_mapping(project_root: str, mapping: dict) -> dict:
    cache_key = (project_root, id(mapping))
    cached = _effective_mapping_cache.get(cache_key)
    if cached is not None:
        return cached
    discovered = discover_spec_domains(project_root)
    effective = {}

    for domain, rel_paths in discovered.items():
        source_cfg = mapping.get(domain) or {}
        normalized_specs = []
        seen = set()

        for entry in source_cfg.get("specs") or []:
            rel = _spec_path_from_entry(entry)
            if not rel or rel in seen:
                continue
            normalized_specs.append(normalize_spec_entry(entry))
            seen.add(rel)

        for rel in rel_paths:
            if rel in seen:
                continue
            normalized_specs.append(_default_spec_entry(rel))
            seen.add(rel)

        effective[domain] = {
            "patterns": source_cfg.get("patterns") or [],
            "specs": normalized_specs,
        }

    for domain, source_cfg in (mapping or {}).items():
        if domain in effective:
            continue
        normalized_specs = []
        seen = set()
        for entry in source_cfg.get("specs") or []:
            rel = _spec_path_from_entry(entry)
            if not rel or rel in seen:
                continue
            normalized_specs.append(normalize_spec_entry(entry))
            seen.add(rel)
        effective[domain] = {
            "patterns": source_cfg.get("patterns") or [],
            "specs": normalized_specs,
        }

    _effective_mapping_cache[cache_key] = effective
    return effective


def is_code_file(rel_path: str, runtime_config: dict) -> bool:
    rel_path = normalize_path(rel_path)
    for pattern in runtime_config.get("skip_paths") or []:
        if fnmatch.fnmatch(rel_path, pattern):
            return False
    _, ext = os.path.splitext(rel_path)
    if ext in (runtime_config.get("skip_extensions") or []):
        return False
    code_exts = runtime_config.get("code_extensions") or []
    ext_set = _ext_set_cache.get(id(code_exts))
    if ext_set is None:
        ext_set = frozenset(code_exts)
        _ext_set_cache[id(code_exts)] = ext_set
    return ext in ext_set


def match_domains(rel_path: str, mapping: dict) -> list:
    rel_path = normalize_path(rel_path)
    domains = []
    for domain, cfg in (mapping or {}).items():
        patterns = cfg.get("patterns") or []
        for pattern in patterns:
            if fnmatch.fnmatch(rel_path, pattern):
                domains.append(domain)
                break
    return domains


# --- Fix #2: safe depluralization with allowlist ---

_SAFE_DEPLURALS = {
    "models": "model",
    "services": "service",
    "components": "component",
    "handlers": "handler",
    "controllers": "controller",
    "middlewares": "middleware",
    "validators": "validator",
    "schemas": "schema",
    "repositories": "repository",
    "migrations": "migration",
    "fixtures": "fixture",
    "plugins": "plugin",
    "routes": "route",
    "routers": "router",
    "hooks": "hook",
    "pages": "page",
    "stores": "store",
    "styles": "style",
    "types": "type",
    "configs": "config",
    "scripts": "script",
    "tasks": "task",
    "specs": "spec",
    "tests": "test",
    "utils": "util",
    "helpers": "helper",
    "views": "view",
    "templates": "template",
    "errors": "error",
    "exceptions": "exception",
    "docs": "doc",
}

# --- Fix #1: semantic directory → concept tag mapping ---

_DIR_SEMANTIC_TAGS = {
    "handlers": ["api", "error"],
    "controllers": ["api"],
    "middleware": ["api", "config"],
    "middlewares": ["api", "config"],
    "routers": ["api", "route"],
    "routes": ["api", "route"],
    "views": ["ui", "render"],
    "templates": ["ui", "render"],
    "models": ["model", "database", "orm", "schema"],
    "model": ["model", "database", "orm", "schema"],
    "schemas": ["model", "schema", "database"],
    "migrations": ["database", "migration"],
    "repositories": ["database", "query"],
    "dao": ["database", "query"],
    "validators": ["quality", "error"],
    "exceptions": ["error", "exception"],
    "errors": ["error", "exception"],
    "auth": ["api", "config"],
    "config": ["config", "deploy"],
    "configs": ["config", "deploy"],
    "settings": ["config"],
    "tests": ["test", "quality"],
    "test": ["test", "quality"],
    "utils": ["quality"],
    "helpers": ["quality"],
    "lib": ["quality"],
    "common": ["quality"],
    "shared": ["quality"],
    "core": ["quality"],
    "logging": ["log", "logging"],
    "logger": ["log", "logging"],
    "logs": ["log", "logging"],
    "cache": ["cache", "performance"],
    "queue": ["performance"],
    "jobs": ["performance"],
    "workers": ["performance"],
}


def extract_context_tags(rel_path: str) -> set:
    """Extract context tags from a file path for spec matching.

    Uses three strategies:
    1. Directory names as tags (with safe depluralization)
    2. Semantic mapping: common directory names → concept tags
    3. Filename stem word splitting
    """
    rel_path = normalize_path(rel_path)
    tags = set()
    parts = rel_path.split("/")

    for part in parts[:-1]:
        lower = part.lower()
        tags.add(lower)
        deplural = _SAFE_DEPLURALS.get(lower)
        if deplural:
            tags.add(deplural)
        semantic = _DIR_SEMANTIC_TAGS.get(lower)
        if semantic:
            tags.update(semantic)

    filename = parts[-1] if parts else ""
    stem = os.path.splitext(filename)[0].lower()
    if stem:
        words = _FILENAME_WORDS_RE.findall(stem.replace("_", " ").replace("-", " "))
        tags.update(words)
        for word in words:
            semantic = _DIR_SEMANTIC_TAGS.get(word)
            if semantic:
                tags.update(semantic)

    return tags


def normalize_spec_entry(entry) -> dict:
    """Normalize spec config entry. Supports both old (string) and new (dict) format."""
    if isinstance(entry, str):
        return {"path": entry, "tags": ["*"], "tier": 1}
    if isinstance(entry, dict):
        return {
            "path": entry.get("path", ""),
            "tags": entry.get("tags", ["*"]),
            "tier": entry.get("tier", 1),
        }
    return {}


_FILENAME_WORDS_RE = re.compile(r"[a-z]+")
_BULLET_PREFIXES = ("- ", "* ", "+ ")
_COMPRESS_HTML_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_COMPRESS_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)
_COMPRESS_BLANK_LINES_RE = re.compile(r"\n{3,}")


def compress_content(text: str) -> str:
    """Lossless compression for spec content injected at Hook time.

    Five conservative, semantics-preserving transforms:
    1. Strip multi-line HTML comments ``<!-- ... -->``.
    2. Strip trailing whitespace on every line.
    3. Collapse runs of 2+ blank lines into a single blank line.
    4. Drop a bullet line ( ``-`` / ``*`` / ``+`` ) equal to the previous line.
    5. Strip leading/trailing blank lines of the whole text.

    Idempotent: ``compress_content(compress_content(x)) == compress_content(x)``.
    On any exception, log to stderr and return the original text so Hook
    injection is never broken by a compression bug.
    """
    if not isinstance(text, str) or not text:
        return text
    try:
        result = _COMPRESS_HTML_RE.sub("", text)
        result = _COMPRESS_TRAILING_WS_RE.sub("", result)
        result = _COMPRESS_BLANK_LINES_RE.sub("\n\n", result)
        lines = result.split("\n")
        out_lines: list = []
        prev_line: str = ""
        in_fence = False
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith("```"):
                in_fence = not in_fence
            # never dedup inside fenced code blocks — ✅/❌ example snippets
            # may legitimately repeat identical bullet-looking lines (FEAT-07)
            is_bullet = (not in_fence) and stripped.startswith(_BULLET_PREFIXES)
            if is_bullet and out_lines and line == prev_line:
                continue
            out_lines.append(line)
            prev_line = line
        result = "\n".join(out_lines)
        return result.strip()
    except Exception as exc:
        _log(f"compress_content error: {exc}")
        return text


def read_matched_specs(
    project_root: str,
    domain: str,
    matched: list,
    compress: bool = True,
) -> list:
    """Read matched spec files; optionally apply lossless compression.

    When ``compress`` is True (default), each spec's content is passed through
    :func:`compress_content` before token estimation so callers can make
    explicit budget decisions from the returned token counts.

    Returned items carry:
        - ``content``: final content (compressed when ``compress=True``)
        - ``tokens``: token count of final content (drives budget decisions)
        - ``tokens_raw``: token count of uncompressed content (for cf-stats)

    ``CF_DEBUG=1`` emits a per-file ``compress path=... raw=... compressed=...
    saved=...%`` record via :func:`debug_log`.
    """
    specs_root = os.path.join(project_root, ".code-flow", "specs")
    specs: list = []
    for cfg in matched:
        rel = cfg["path"]
        spec_path = os.path.join(specs_root, rel)
        try:
            with open(spec_path, "r", encoding="utf-8") as f:
                raw_content = f.read().strip()
            # Frontmatter feeds the spec catalog only — never spend injection
            # budget on it. Specs without frontmatter pass through unchanged.
            _, raw_content = parse_spec_frontmatter(raw_content)
            raw_content = raw_content.strip()
            if not raw_content:
                continue
            raw_tokens = estimate_tokens(raw_content)
            if compress:
                try:
                    content = compress_content(raw_content)
                except Exception as exc:
                    _log(f"read_matched_specs compress failed path={rel}: {exc}")
                    content = raw_content
            else:
                content = raw_content
            tokens = estimate_tokens(content)
            if compress and raw_tokens != tokens:
                saved_pct = (
                    round((raw_tokens - tokens) * 100 / raw_tokens, 1)
                    if raw_tokens
                    else 0.0
                )
                debug_log(
                    f"compress path={rel} raw={raw_tokens} "
                    f"compressed={tokens} saved={saved_pct}%",
                    project_root,
                )
            specs.append(
                {
                    "path": rel,
                    "content": content,
                    "tokens": tokens,
                    "tokens_raw": raw_tokens,
                    "domain": domain,
                    "tier": cfg.get("tier", 1),
                }
            )
        except Exception:
            continue
    return specs


# --- Kept for backward compatibility with old config format ---


def read_specs(project_root: str, domain: str, domain_cfg: dict) -> list:
    specs_root = os.path.join(project_root, ".code-flow", "specs")
    specs = []
    for entry in domain_cfg.get("specs") or []:
        cfg = normalize_spec_entry(entry)
        rel = cfg.get("path", "")
        if not rel:
            continue
        spec_path = os.path.join(specs_root, rel)
        try:
            with open(spec_path, "r", encoding="utf-8") as file:
                content = file.read().strip()
            if not content:
                continue
            specs.append(
                {
                    "path": rel,
                    "content": content,
                    "tokens": estimate_tokens(content),
                    "domain": domain,
                    "tier": cfg.get("tier", 1),
                }
            )
        except Exception:
            continue
    return specs


def non_injectable_specs(effective_mapping: dict) -> set:
    """tags: [] 的命令专用模板（如 shared 的 PRD/设计模板）——永不自动注入，
    预算统计（cf-stats/cf-scan）必须排除，避免利用率虚高。"""
    excluded = set()
    for domain_cfg in (effective_mapping or {}).values():
        for entry in (domain_cfg or {}).get("specs") or []:
            cfg = normalize_spec_entry(entry)
            if cfg.get("path") and not cfg.get("tags"):
                excluded.add(cfg["path"])
    return excluded


def resolve_quality_loop(config: dict) -> dict:
    """Resolve quality_loop feature switches with safe defaults (RULE-06).

    Master `enabled`: only literal True enables — missing/other keeps the
    pre-0.6 behavior for upgraded users; new inits opt in via the config
    template. Sub-switches follow the master and only literal False disables
    them (resolve_compress philosophy).
    """
    if not isinstance(config, dict):
        return {"enabled": False, "post_check": False,
                "stop_check": False, "correction_capture": False}
    cfg = config.get("quality_loop")
    cfg = cfg if isinstance(cfg, dict) else {}
    enabled = cfg.get("enabled") is True

    def _sub(key: str) -> bool:
        return enabled and cfg.get(key) is not False

    return {
        "enabled": enabled,
        "post_check": _sub("post_check"),
        "stop_check": _sub("stop_check"),
        "correction_capture": _sub("correction_capture"),
    }


_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*\n?", re.DOTALL)


def parse_spec_frontmatter(content: str) -> tuple:
    """Split optional YAML frontmatter from spec content → (meta, body).

    Parses only flat `key: value` string pairs — enough for `description:` —
    so the hook hot path never needs pyyaml for this. Content without
    frontmatter returns ({}, content) unchanged.
    """
    if not isinstance(content, str):
        return {}, content
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content
    meta: dict = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        if key:
            meta[key] = value.strip().strip('"').strip("'")
    return meta, content[match.end():]


def spec_description(content: str) -> str:
    """One-line applicability summary for the spec catalog.

    Priority: frontmatter `description:` → first blockquote line → H1 text.
    Returns "" when none is found (cf-scan flags those specs).
    """
    meta, body = parse_spec_frontmatter(content)
    desc = (meta.get("description") or "").strip()
    if desc:
        return desc
    h1 = ""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            return stripped.lstrip("> ").strip()
        if not h1 and stripped.startswith("# "):
            h1 = stripped[2:].strip()
    return h1


_catalog_cache: dict = {}

CATALOG_HEADER = (
    "## Spec Catalog (code-flow)\n\n"
    "以下规范文件位于 `.code-flow/specs/`。开始编码或修改文件前，"
    "必须先 Read 与当前任务场景匹配的 spec 全文；与场景无关的不要读取。"
)


def _catalog_entries(project_root: str, effective_mapping: dict) -> list:
    """Collect injectable specs as (tier, rel_path, abs_path) sorted tier1-first."""
    specs_root = os.path.join(project_root, ".code-flow", "specs")
    entries = []
    for domain in sorted(effective_mapping.keys()):
        for entry in (effective_mapping[domain] or {}).get("specs") or []:
            cfg = normalize_spec_entry(entry)
            rel = cfg.get("path", "")
            # tags: [] marks command-only templates — never advertised either
            if not rel or not cfg.get("tags"):
                continue
            entries.append((cfg.get("tier", 1), rel, os.path.join(specs_root, rel)))
    # Tier 1 constraints first so budget truncation drops navigation maps first
    entries.sort(key=lambda item: (item[0] != 1, item[1]))
    return entries


def build_spec_catalog(
    project_root: str, effective_mapping: dict, catalog_max: int = 200
) -> str:
    """Build the compact Catalog used only when no task or path is active.

    The model performs the semantic matching itself by reading the catalog and
    pulling relevant specs — replacing keyword-table guessing on prompts with
    no explicit path evidence. Cached per project_root keyed by the mtimes of
    config.yml and every listed spec file.
    """
    entries = _catalog_entries(project_root, effective_mapping)
    if not entries:
        return ""
    config_path = os.path.join(project_root, ".code-flow", "config.yml")
    signature = []
    for path in [config_path] + [abs_path for _, _, abs_path in entries]:
        try:
            signature.append((path, os.path.getmtime(path)))
        except OSError:
            signature.append((path, 0.0))
    signature = tuple(signature)
    cached = _catalog_cache.get(project_root)
    if cached and cached["signature"] == signature and cached["catalog_max"] == catalog_max:
        return cached["catalog"]

    lines = []
    for tier, rel, abs_path in entries:
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                desc = spec_description(f.read())
        except Exception:
            continue
        suffix = "（导航地图）" if tier == 0 else ""
        lines.append(f"- `{rel}` — {desc or '(no description)'}{suffix}")
    if not lines:
        return ""

    catalog = CATALOG_HEADER
    included = 0
    for line in lines:
        candidate = catalog + "\n" + line
        if estimate_tokens(candidate) > catalog_max:
            break
        catalog = candidate
        included += 1
    if included < len(lines):
        _log(
            f"WARNING: spec catalog truncated to {included}/{len(lines)} "
            f"entries (catalog_max={catalog_max} tokens)"
        )
    if included == 0:
        return ""
    _catalog_cache[project_root] = {
        "signature": signature,
        "catalog_max": catalog_max,
        "catalog": catalog,
    }
    return catalog


def assemble_context(specs: list, heading: str) -> str:
    parts = [heading]
    parts.append("以上规范是本次开发的约束条件，生成代码必须遵循。")
    parts.append("---")
    tier0 = [s for s in specs if s.get("tier", 1) == 0]
    tier1 = [s for s in specs if s.get("tier", 1) != 0]

    if tier0:
        parts.append("### Navigation (Retrieval Map)")
        for spec in tier0:
            parts.append(f"#### {spec['path']}")
            parts.append(spec["content"])

    if tier1:
        parts.append("### Constraints (matched by file context)")
        for spec in tier1:
            parts.append(f"#### {spec['path']}")
            parts.append(spec["content"])

    return "\n\n".join(parts)


def _log(msg: str) -> None:
    """Log to stderr (fix #9: don't pollute stdout which is hook output)."""
    print(msg, file=sys.stderr)


def ensure_utf8_io() -> None:
    """Force stdin/stdout/stderr to UTF-8 so Windows hooks don't mojibake.

    Claude Code/Codex pass UTF-8 JSON over stdin and expect UTF-8 over stdout,
    but Python on Windows defaults streams to the system codepage (cp936 on
    zh-CN locales). That corrupts CJK content end-to-end — both the parsed
    prompt and anything written back, including the CF_DEBUG=1 .debug.log.
    ``reconfigure`` is a TextIOWrapper-only method, so test doubles built on
    ``io.StringIO`` are silently skipped.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                pass


def resolve_compress(quality_config: dict) -> bool:
    """Return whether Hook-time spec compression is enabled.

    Only a literal ``False`` turns it off; missing, ``None``, or any
    non-bool value falls back to ``True`` so upgrades pick up compression
    without requiring a config edit.
    """
    if not isinstance(quality_config, dict):
        return True
    value = quality_config.get("compress")
    if value is False:
        return False
    return True


def resolve_session_id(hook_data: dict) -> str:
    """Derive a session id consistent across PreToolUse / UserPromptSubmit hooks.

    Prefer the platform-provided id so prompt, edit, feedback, and stop events
    share one trace. Fall back to the PID for older runtimes and unit tests.
    """
    if isinstance(hook_data, dict):
        sid = hook_data.get("session_id")
        if sid:
            return str(sid)
    return str(os.getpid())


def debug_log(msg: str, project_root: str = None) -> None:
    """Append a debug line to .code-flow/.debug.log when CF_DEBUG=1.
    Silent no-op unless CF_DEBUG=1 so default runs don't pay any IO cost.
    Writes to a dotfile so cf_scan.py skips it and processDir upgrades don't overwrite it.
    Failures (missing dir, unwritable fs) are swallowed on purpose
    — we must never break the hook JSON protocol over logging.
    """
    if os.environ.get("CF_DEBUG") != "1":
        return
    root = project_root or os.getcwd()
    debug_dir = os.path.join(root, ".code-flow")
    log_path = os.path.join(debug_dir, ".debug.log")
    try:
        os.makedirs(debug_dir, exist_ok=True)
        from datetime import datetime
        ts = datetime.now().isoformat(timespec="seconds")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{ts} {msg}\n")
    except Exception:
        return
