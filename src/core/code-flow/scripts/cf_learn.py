#!/usr/bin/env python3
import argparse
import datetime
import json
import os
import sys


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


def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read()
    except Exception:
        return ""


def write_text(path: str, content: str) -> bool:
    try:
        with open(path, "w", encoding="utf-8") as file:
            file.write(content)
        return True
    except Exception:
        return False


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def find_target_spec(domain: str, config: dict, file_arg: str) -> tuple:
    mapping = config.get("path_mapping") or {}
    domain_cfg = mapping.get(domain) or {}
    specs = domain_cfg.get("specs") or []
    if not specs:
        return "", specs
    if file_arg:
        if file_arg in specs:
            return file_arg, specs
        return "", specs
    if len(specs) == 1:
        return specs[0], specs
    return "", specs


def insert_learning(content: str, entry: str) -> str:
    text = content.rstrip()
    if not text:
        return f"## Learnings\n{entry}\n"

    lines = text.splitlines()
    learn_index = None
    for index, line in enumerate(lines):
        if line.strip() == "## Learnings":
            learn_index = index
            break

    if learn_index is None:
        return f"{text}\n\n## Learnings\n{entry}\n"

    insert_at = len(lines)
    for idx in range(learn_index + 1, len(lines)):
        if lines[idx].startswith("## "):
            insert_at = idx
            break

    lines.insert(insert_at, entry)
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", required=True, choices=["global", "frontend", "backend"])
    parser.add_argument("--content", required=True)
    parser.add_argument("--file", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    project_root = os.getcwd()
    config = load_config(project_root)

    date_str = datetime.date.today().isoformat()
    entry = f"- [{date_str}] {args.content.strip()}"

    if args.scope == "global":
        target_path = os.path.join(project_root, "CLAUDE.md")
        content = read_text(target_path)
        updated = insert_learning(content, entry)
        if args.dry_run:
            tokens = estimate_tokens(updated)
            print(
                json.dumps(
                    {
                        "status": "dry_run",
                        "target": "CLAUDE.md",
                        "entry": entry,
                        "tokens": tokens,
                        "warning": "L0 超出预算" if tokens > 800 else "",
                    },
                    ensure_ascii=False,
                )
            )
            return
        if not write_text(target_path, updated):
            print(json.dumps({"error": "write_failed", "target": "CLAUDE.md"}, ensure_ascii=False))
            return
        tokens = estimate_tokens(updated)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "target": "CLAUDE.md",
                    "entry": entry,
                    "tokens": tokens,
                    "warning": "L0 超出预算" if tokens > 800 else "",
                },
                ensure_ascii=False,
            )
        )
        return

    if not config:
        print(json.dumps({"error": "config_missing"}, ensure_ascii=False))
        return

    spec_rel, specs = find_target_spec(args.scope, config, args.file)
    if not spec_rel:
        print(
            json.dumps(
                {
                    "error": "spec_not_selected",
                    "available_specs": specs,
                },
                ensure_ascii=False,
            )
        )
        return

    target_path = os.path.join(project_root, ".code-flow", "specs", spec_rel)
    content = read_text(target_path)
    if not content:
        print(
            json.dumps(
                {"error": "spec_missing_or_empty", "target": spec_rel},
                ensure_ascii=False,
            )
        )
        return

    updated = insert_learning(content, entry)
    tokens = estimate_tokens(updated)
    warning = ""
    if tokens > 500:
        warning = "单文件超过 500 tokens，建议精简"
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "dry_run",
                    "target": spec_rel,
                    "entry": entry,
                    "tokens": tokens,
                    "warning": warning,
                },
                ensure_ascii=False,
            )
        )
        return
    if not write_text(target_path, updated):
        print(json.dumps({"error": "write_failed", "target": spec_rel}, ensure_ascii=False))
        return
    print(
        json.dumps(
            {
                "status": "ok",
                "target": spec_rel,
                "entry": entry,
                "tokens": tokens,
                "warning": warning,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
