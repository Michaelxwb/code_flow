#!/usr/bin/env python3
"""Tests for cf_core.py — covers tag extraction, spec matching, tiered selection."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))

from cf_core import (
    compress_content,
    extract_context_tags,
    extract_prompt_tags,
    match_specs_by_tags,
    normalize_spec_entry,
    select_specs_tiered,
    is_code_file,
    match_domains,
    estimate_tokens,
    load_config,
    load_inject_state,
    save_inject_state,
    resolve_session_id,
    debug_log,
)


# --- extract_context_tags ---


def test_extract_tags_model_file():
    tags = extract_context_tags("models/user.py")
    assert "model" in tags
    assert "models" in tags
    assert "user" in tags
    # semantic: models dir → database tags
    assert "database" in tags


def test_extract_tags_api_file():
    tags = extract_context_tags("api/auth/login.py")
    assert "api" in tags
    assert "auth" in tags
    assert "login" in tags


def test_extract_tags_component():
    tags = extract_context_tags("src/components/Button.tsx")
    assert "component" in tags
    assert "components" in tags
    assert "button" in tags


def test_extract_tags_no_bad_deplural():
    """Fix #2: 'process', 'address', 'status' should NOT be broken."""
    tags = extract_context_tags("process/handler.py")
    assert "process" in tags
    assert "proces" not in tags  # no broken deplural

    tags = extract_context_tags("address/validator.py")
    assert "address" in tags
    assert "addres" not in tags


def test_extract_tags_safe_deplural():
    """Known plurals should depluralize correctly."""
    tags = extract_context_tags("services/payment.py")
    assert "services" in tags
    assert "service" in tags

    tags = extract_context_tags("middlewares/auth.py")
    assert "middleware" in tags


def test_extract_tags_semantic_mapping():
    """Semantic directory mapping adds concept tags."""
    tags = extract_context_tags("handlers/error_handler.py")
    assert "api" in tags  # handlers → api
    assert "error" in tags  # handlers → error, also from filename

    tags = extract_context_tags("migrations/001_init.py")
    assert "database" in tags  # migrations → database
    assert "migration" in tags


def test_extract_tags_filename_semantic():
    """Filename words also trigger semantic mapping."""
    tags = extract_context_tags("src/logger.py")
    assert "log" in tags  # logger → log, logging
    assert "logging" in tags


# --- extract_prompt_tags ---


def test_extract_prompt_tags_chinese_only():
    hits = extract_prompt_tags("写一个用户登录服务，注意性能和异常处理")
    assert "performance" in hits
    assert "exception" in hits


def test_extract_prompt_tags_english_only():
    hits = extract_prompt_tags("add retry and cache to query layer")
    assert "retry" in hits
    assert "cache" in hits
    assert "query" in hits


def test_extract_prompt_tags_mixed():
    hits = extract_prompt_tags("给 API 加 timeout 和日志")
    assert "api" in hits
    assert "timeout" in hits
    assert "log" in hits


def test_extract_prompt_tags_case_insensitive_ascii():
    hits = extract_prompt_tags("PERFORMANCE matters")
    assert "performance" in hits


def test_extract_prompt_tags_empty_or_blank():
    assert extract_prompt_tags("") == set()
    assert extract_prompt_tags("   \n\t") == set()
    assert extract_prompt_tags(None) == set()


def test_extract_prompt_tags_no_hits():
    assert extract_prompt_tags("hello world, nothing relevant here") == set()


def test_extract_prompt_tags_word_boundary_short_ascii():
    """'ui' inside 'guide' must NOT match; 'use db layer' must match 'database'."""
    assert "ui" not in extract_prompt_tags("please write a complete guide")
    assert "database" in extract_prompt_tags("use db layer for persistence")


def test_extract_prompt_tags_word_boundary_api():
    """'api' inside 'rapid' must NOT match; 'the api route' must match."""
    assert "api" not in extract_prompt_tags("rapid prototyping")
    assert "api" in extract_prompt_tags("expose the api route")


# --- normalize_spec_entry ---


def test_normalize_old_format():
    result = normalize_spec_entry("backend/database.md")
    assert result["path"] == "backend/database.md"
    assert result["tags"] == ["*"]
    assert result["tier"] == 1


def test_normalize_new_format():
    result = normalize_spec_entry({"path": "backend/database.md", "tags": ["db"], "tier": 1})
    assert result["path"] == "backend/database.md"
    assert result["tags"] == ["db"]


# --- match_specs_by_tags ---


SAMPLE_SPECS = [
    {"path": "backend/_map.md", "tags": ["*"], "tier": 0},
    {"path": "backend/database.md", "tags": ["database", "db", "sql", "orm", "model"], "tier": 1},
    {"path": "backend/logging.md", "tags": ["log", "logging", "debug"], "tier": 1},
    {"path": "backend/platform-rules.md", "tags": ["api", "deploy", "config"], "tier": 1},
]


def test_match_model_file():
    tags = extract_context_tags("models/user.py")
    matched, has_t1 = match_specs_by_tags(SAMPLE_SPECS, tags)
    paths = [m["path"] for m in matched]
    assert "backend/_map.md" in paths  # wildcard
    assert "backend/database.md" in paths  # model tag
    assert "backend/logging.md" not in paths
    assert has_t1 is True


def test_match_api_file():
    tags = extract_context_tags("api/auth.py")
    matched, has_t1 = match_specs_by_tags(SAMPLE_SPECS, tags)
    paths = [m["path"] for m in matched]
    assert "backend/_map.md" in paths
    assert "backend/platform-rules.md" in paths  # api tag
    assert has_t1 is True


def test_match_no_tier1_returns_false():
    """When no tier 1 matches, has_tier1_match is False → triggers fallback."""
    tags = extract_context_tags("services/payment.py")
    # payment, service, services — no overlap with any tier 1 tags
    # But semantic mapping: services → no semantic mapping for "services" directory
    # Actually let me check... _DIR_SEMANTIC_TAGS doesn't have "services"
    # So tags are: {payment, service, services}
    # These don't match any tier 1 spec tags
    matched, has_t1 = match_specs_by_tags(SAMPLE_SPECS, tags)
    paths = [m["path"] for m in matched]
    assert "backend/_map.md" in paths  # wildcard always matches
    assert has_t1 is False  # no tier 1 match


def test_match_with_semantic_fallthrough():
    """handlers/ gets semantic tags 'api' + 'error', should match platform-rules."""
    tags = extract_context_tags("handlers/payment.py")
    matched, has_t1 = match_specs_by_tags(SAMPLE_SPECS, tags)
    paths = [m["path"] for m in matched]
    assert "backend/platform-rules.md" in paths  # api tag from semantic
    assert has_t1 is True


# --- select_specs_tiered ---


def test_tiered_tier0_always_included():
    specs = [
        {"path": "map.md", "tokens": 300, "tier": 0},
        {"path": "rules.md", "tokens": 200, "tier": 1},
    ]
    selected = select_specs_tiered(specs, budget=50, map_max=400)
    paths = [s["path"] for s in selected]
    assert "map.md" in paths  # tier 0 within map_max
    assert "rules.md" not in paths  # tier 1 exceeds budget


def test_tiered_tier0_exceeds_map_max():
    specs = [
        {"path": "map.md", "tokens": 500, "tier": 0},
        {"path": "rules.md", "tokens": 200, "tier": 1},
    ]
    selected = select_specs_tiered(specs, budget=1700, map_max=400)
    paths = [s["path"] for s in selected]
    assert "map.md" not in paths  # exceeds map_max
    assert "rules.md" in paths


def test_scripts_map_within_budget_guardrail():
    map_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        ".code-flow",
        "specs",
        "scripts",
        "_map.md",
    )
    with open(map_path, "r", encoding="utf-8") as f:
        tokens = estimate_tokens(f.read())

    assert tokens <= 400


def test_tiered_budget_controls_tier1():
    specs = [
        {"path": "a.md", "tokens": 100, "tier": 1},
        {"path": "b.md", "tokens": 100, "tier": 1},
        {"path": "c.md", "tokens": 100, "tier": 1},
    ]
    selected = select_specs_tiered(specs, budget=200, map_max=400)
    paths = [s["path"] for s in selected]
    assert len(paths) == 2  # only first 2 fit


# --- is_code_file ---


def test_is_code_file_python():
    cfg = {"code_extensions": [".py"], "skip_extensions": [".md"], "skip_paths": ["docs/**"]}
    assert is_code_file("src/main.py", cfg) is True
    assert is_code_file("README.md", cfg) is False
    assert is_code_file("docs/api.py", cfg) is False


# --- match_domains ---


def test_match_domains_backend():
    mapping = {
        "backend": {"patterns": ["**/*.py", "services/**"]},
        "frontend": {"patterns": ["**/*.tsx"]},
    }
    assert match_domains("services/auth.py", mapping) == ["backend"]
    assert match_domains("src/App.tsx", mapping) == ["frontend"]


# --- load/save inject state ---


def test_inject_state_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".code-flow"))
        payload = {"session_id": "123", "injected_specs": ["a.md", "b.md"]}
        save_inject_state(tmpdir, payload)
        loaded = load_inject_state(tmpdir)
        assert loaded["session_id"] == "123"
        assert loaded["injected_specs"] == ["a.md", "b.md"]


def test_inject_state_missing_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        loaded = load_inject_state(tmpdir)
        assert loaded == {}


# --- estimate_tokens ---


def test_estimate_tokens():
    assert estimate_tokens("a" * 400) == 100


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print(f"  PASS {test.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL {test.__name__}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

# --- match_specs_by_tags with prompt_tags (TASK-002) ---
def test_match_with_prompt_tags_only():
    """path_tags empty + prompt_tags={"performance"} should match performance spec."""
    # performance tag is in _TAG_ALIASES but not in SAMPLE_SPECS tags
    # Let's add a performance-related spec to test properly
    perf_specs = SAMPLE_SPECS + [{"path": "backend/performance.md", "tags": ["performance", "perf"], "tier": 1}]
    matched, has_t1 = match_specs_by_tags(perf_specs, set(), prompt_tags={"performance"})
    paths = [m["path"] for m in matched]
    assert "backend/_map.md" in paths
    assert "backend/performance.md" in paths
    assert has_t1 is True

def test_match_with_path_and_prompt_tags():
    """path_tags={"api"} + prompt_tags={"log"} should match multiple specs."""
    matched, has_t1 = match_specs_by_tags(SAMPLE_SPECS, {"api"}, prompt_tags={"log"})
    paths = [m["path"] for m in matched]
    assert "backend/_map.md" in paths
    assert "backend/platform-rules.md" in paths  # api tag from path
    assert "backend/logging.md" in paths          # log tag from prompt
    assert has_t1 is True

def test_match_backward_compatibility():
    """Default prompt_tags=None should behave exactly like before."""
    tags = extract_context_tags("api/auth.py")
    # Call without prompt_tags
    matched_old, has_t1_old = match_specs_by_tags(SAMPLE_SPECS, tags)
    # Call with explicit None
    matched_new, has_t1_new = match_specs_by_tags(SAMPLE_SPECS, tags, prompt_tags=None)
    # Results should be identical
    assert [m["path"] for m in matched_old] == [m["path"] for m in matched_new]
    assert has_t1_old == has_t1_new

# --- resolve_session_id ---
def test_resolve_session_id_from_hook_data():
    """When hook_data contains session_id, should return it."""
    hook_data = {"session_id": "abc123", "other": "data"}
    assert resolve_session_id(hook_data) == "abc123"

def test_resolve_session_id_fallback_to_pid():
    """When hook_data missing session_id, should fall back to PID."""
    hook_data = {"prompt": "test"}
    result = resolve_session_id(hook_data)
    assert result == str(os.getpid())

def test_resolve_session_id_empty_dict():
    """Empty dict should fall back to PID."""
    result = resolve_session_id({})
    assert result == str(os.getpid())

# --- debug_log ---
def test_debug_log_silent_without_env():
    """When CF_DEBUG not set, should not write anything."""
    original = os.environ.get("CF_DEBUG")
    if "CF_DEBUG" in os.environ:
        del os.environ["CF_DEBUG"]
    try:
        # Should not raise, should not create file
        debug_log("test message")
        assert not os.path.exists(".code-flow/.debug.log")
    finally:
        if original is not None:
            os.environ["CF_DEBUG"] = original

def test_debug_log_writes_when_enabled():
    """When CF_DEBUG=1, should append to .debug.log."""
    original = os.environ.get("CF_DEBUG")
    os.environ["CF_DEBUG"] = "1"
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            debug_log("test hook test_event detail=foo", project_root=tmpdir)
            log_path = os.path.join(tmpdir, ".code-flow", ".debug.log")
            assert os.path.exists(log_path)
            with open(log_path, "r") as f:
                content = f.read()
            assert "test hook test_event detail=foo" in content
            # Should be ISO timestamp format
            assert "T" in content
    finally:
        if original is None:
            del os.environ["CF_DEBUG"]
        else:
            os.environ["CF_DEBUG"] = original


# --- compress_content ---


def test_compress_content_happy():
    text = (
        "## Rules   \n"
        "- use type hints\n"
        "- handle errors\n"
        "\n\n\n"
        "## Patterns\n"
        "- single responsibility\n"
    )
    result = compress_content(text)
    assert "\n\n\n" not in result
    assert "## Rules" in result
    assert "## Patterns" in result
    assert result.count("- ") == 3
    assert not any(line.endswith(" ") for line in result.split("\n"))
    assert estimate_tokens(result) <= estimate_tokens(text)


def test_compress_content_empty():
    assert compress_content("") == ""
    assert compress_content("   \n\n  \n") == ""


def test_compress_content_no_blank_lines():
    text = "## Rules\n- a\n- b\n- c"
    assert compress_content(text) == text


def test_compress_content_html_comments():
    text = "## Title\n<!-- TODO: drop this -->\nkeep me\n<!--\nmulti\nline\n-->\nalso kept"
    result = compress_content(text)
    assert "TODO" not in result
    assert "multi" not in result
    assert "keep me" in result
    assert "also kept" in result
    assert "## Title" in result


def test_compress_content_multi_blank_lines():
    text = "a\n\n\n\n\nb"
    result = compress_content(text)
    assert result == "a\n\nb"


def test_compress_content_duplicate_bullets():
    text = "- foo\n- foo\n- bar\n- bar\n- bar"
    result = compress_content(text)
    assert result == "- foo\n- bar"


def test_compress_content_preserves_structure():
    text = (
        "# H1\n"
        "## H2\n"
        "### H3\n"
        "| col1 | col2 |\n"
        "|------|------|\n"
        "| a | b |\n"
        "\n"
        "```python\n"
        "def f():\n"
        "    pass\n"
        "```\n"
        "\n"
        "[link](https://example.com)\n"
        "- item1\n"
        "- item2\n"
        "* star item\n"
    )
    result = compress_content(text)
    assert "# H1" in result
    assert "## H2" in result
    assert "### H3" in result
    assert result.count("|") == text.count("|")
    assert "```python" in result
    assert "```" in result
    assert "[link](https://example.com)" in result
    assert "- item1" in result
    assert "- item2" in result
    assert "* star item" in result


def test_compress_content_idempotent():
    text = (
        "## Rules   \n\n\n\n"
        "- a  \n"
        "- a\n"
        "<!-- drop -->\n"
        "- b\n"
    )
    once = compress_content(text)
    twice = compress_content(once)
    assert once == twice


def test_compress_content_non_string_returns_input():
    assert compress_content(None) is None
    assert compress_content(123) == 123
