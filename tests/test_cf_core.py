#!/usr/bin/env python3
"""Tests for cf_core.py — covers tag extraction, spec matching, tiered selection."""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))

from cf_core import (
    extract_context_tags,
    match_specs_by_tags,
    normalize_spec_entry,
    select_specs_tiered,
    is_code_file,
    match_domains,
    estimate_tokens,
    load_config,
    load_inject_state,
    save_inject_state,
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


def _init_git_repo(path: str) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True, capture_output=True, text=True)
    with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as f:
        f.write("demo\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True, text=True)


def test_inject_state_new_common_dir_path_in_git_repo() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _init_git_repo(tmpdir)
        payload = {"injected_specs": ["a.md"], "last_file": "x.py"}
        save_inject_state(tmpdir, payload, session_id="sid-1")
        loaded = load_inject_state(tmpdir, session_id="sid-1")
        assert loaded["session_id"] == "sid-1"
        assert loaded["injected_specs"] == ["a.md"]
        legacy = os.path.join(tmpdir, ".code-flow", ".inject-state")
        assert not os.path.exists(legacy)


def test_inject_state_load_fallback_legacy_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".code-flow"), exist_ok=True)
        legacy = os.path.join(tmpdir, ".code-flow", ".inject-state")
        with open(legacy, "w", encoding="utf-8") as f:
            json.dump({"session_id": "legacy", "injected_specs": ["legacy.md"]}, f)
        loaded = load_inject_state(tmpdir, session_id="sid-legacy")
        assert loaded["session_id"] == "legacy"
        assert loaded["injected_specs"] == ["legacy.md"]


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
