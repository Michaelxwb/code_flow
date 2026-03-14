#!/usr/bin/env python3
import fnmatch
import json
import os


def load_config(project_root: str) -> dict:
    config_path = os.path.join(project_root, ".code-flow", "config.yml")
    if not os.path.exists(config_path):
        return {}
    try:
        import yaml
    except Exception:
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
        return data or {}
    except Exception:
        return {}


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def normalize_path(path: str) -> str:
    return path.replace(os.sep, "/")


def is_code_file(rel_path: str, inject_config: dict) -> bool:
    rel_path = normalize_path(rel_path)
    for pattern in inject_config.get("skip_paths") or []:
        if fnmatch.fnmatch(rel_path, pattern):
            return False
    _, ext = os.path.splitext(rel_path)
    if ext in (inject_config.get("skip_extensions") or []):
        return False
    code_exts = inject_config.get("code_extensions") or []
    return ext in code_exts


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


def read_specs(project_root: str, domain: str, domain_cfg: dict) -> list:
    specs_root = os.path.join(project_root, ".code-flow", "specs")
    specs = []
    for rel in domain_cfg.get("specs") or []:
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
                }
            )
        except Exception:
            continue
    return specs


def select_specs(specs: list, budget: int, priorities: dict) -> list:
    if budget <= 0:
        return []

    def priority(spec: dict) -> int:
        value = priorities.get(spec.get("path"))
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except Exception:
            return 1000

    ordered = sorted(specs, key=lambda spec: (priority(spec), spec.get("path", "")))
    selected = []
    total = 0
    for spec in ordered:
        if total + spec.get("tokens", 0) <= budget:
            selected.append(spec)
            total += spec.get("tokens", 0)
    return selected


def assemble_context(specs: list, heading: str) -> str:
    parts = [heading]
    for spec in specs:
        parts.append(f"### {spec['path']}")
        parts.append(spec["content"])
    parts.append("---")
    parts.append("以上规范是本次开发的约束条件，生成代码必须遵循。")
    return "\n\n".join(parts)


def load_inject_state(project_root: str) -> dict:
    state_path = os.path.join(project_root, ".code-flow", ".inject-state")
    try:
        with open(state_path, "r", encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def save_inject_state(project_root: str, payload: dict) -> None:
    state_path = os.path.join(project_root, ".code-flow", ".inject-state")
    try:
        with open(state_path, "w", encoding="utf-8") as file:
            json.dump(payload, file)
    except Exception:
        return
