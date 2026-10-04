#!/usr/bin/env python3
"""cf-sync: one-command canonical → deploy sync for dual-copy artifacts.

Pairs (canonical source → deployed live copy), each with an explicit include
prefix list. Project-owned trees (specs/, tasks/) and merge-managed files
(CLAUDE.md, AGENTS.md, settings.local.json, hooks.json, config.toml,
opencode.json, config.yml, validation.yml) are upgraded by `code-flow init`
with additive merges, not by byte-sync:

  src/core/code-flow         → .code-flow        (scripts/, runtime-commands.json, .version, .gitignore)
  src/adapters/claude        → .claude           (commands/)
  src/adapters/codex/skills  → .agents/skills    (everything)
  src/adapters/costrict      → .costrict         (commands/)
  src/adapters/opencode      → .opencode         (commands/, plugins/)

`check` (default) reports drift; `sync` copies canonical → deploy. Deploy-only
files are never deleted (use --prune to remove files whose source side no
longer contains them within the include prefixes).
"""

import argparse
import json
import os
from pathlib import Path
import sys
from typing import IO, Optional, Sequence


PAIRS = (
    ("src/core/code-flow", ".code-flow", ("scripts/", "runtime-commands.json", ".version", ".gitignore")),
    ("src/adapters/claude", ".claude", ("commands/",)),
    ("src/adapters/codex/skills", ".agents/skills", ("*",)),
    ("src/adapters/costrict", ".costrict", ("commands/",)),
    ("src/adapters/opencode", ".opencode", ("commands/", "plugins/")),
)

_IGNORED_DIRS = {"__pycache__", ".git", "node_modules", "dist", "build"}


def _included(relative: str, prefixes: Sequence[str]) -> bool:
    return any(prefix == "*" or relative.startswith(prefix) for prefix in prefixes)


def _walk(source: Path) -> list[str]:
    files = []
    for current, dirs, names in os.walk(source):
        dirs[:] = sorted(item for item in dirs if item not in _IGNORED_DIRS)
        base = Path(current)
        for name in names:
            files.append(str((base / name).relative_to(source)))
    return sorted(files)


def _relative(relative: str) -> str:
    return relative.replace("\\", "/")


def _canonical_bytes(root: Path, source: Path) -> bytes:
    if source == root / "src/adapters/opencode/plugins/code-flow/package.json":
        data = json.loads(source.read_text(encoding="utf-8"))
        data["version"] = json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]
        return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return source.read_bytes()


def _pair_diffs(root: Path, source_rel: str, deploy_rel: str, prefixes: Sequence[str]) -> tuple[list[str], list[str], list[str]]:
    """Return (differ, missing_in_deploy, deploy_only_within_prefixes)."""
    source = root / source_rel
    deploy = root / deploy_rel
    differ: list[str] = []
    missing: list[str] = []
    for relative in _walk(source):
        if not _included(_relative(relative), prefixes):
            continue
        source_file = source / relative
        deploy_file = deploy / relative
        if not deploy_file.exists():
            missing.append(relative)
        elif _canonical_bytes(root, source_file) != deploy_file.read_bytes():
            differ.append(relative)
    deploy_only: list[str] = []
    if deploy.is_dir():
        deploy_relative = set(_walk(deploy))
        source_relative = {_relative(item) for item in _walk(source) if _included(_relative(item), prefixes)}
        deploy_only = sorted(item for item in deploy_relative if item not in source_relative and _included(item, prefixes))
    return differ, missing, deploy_only


def _report(stdout: IO[str], root: Path, verbose: bool) -> int:
    drift = 0
    for source_rel, deploy_rel, prefixes in PAIRS:
        differ, missing, deploy_only = _pair_diffs(root, source_rel, deploy_rel, prefixes)
        status = "OK " if not (differ or missing) else "DRIFT"
        stdout.write(f"{status} {source_rel} -> {deploy_rel}\n")
        for relative in differ:
            stdout.write(f"  diff  {deploy_rel}/{relative}\n")
            drift += 1
        for relative in missing:
            stdout.write(f"  miss  {deploy_rel}/{relative}\n")
            drift += 1
        if verbose and deploy_only:
            stdout.write(f"  only-in-deploy ({len(deploy_only)}):\n")
            for relative in deploy_only[:10]:
                stdout.write(f"    {deploy_rel}/{relative}\n")
    return drift


def _sync(root: Path, stdout: IO[str]) -> int:
    copied = 0
    for source_rel, deploy_rel, prefixes in PAIRS:
        source = root / source_rel
        deploy = root / deploy_rel
        for relative in _walk(source):
            if not _included(_relative(relative), prefixes):
                continue
            source_file = source / relative
            deploy_file = deploy / relative
            content = _canonical_bytes(root, source_file)
            if deploy_file.exists() and content == deploy_file.read_bytes():
                continue
            deploy_file.parent.mkdir(parents=True, exist_ok=True)
            deploy_file.write_bytes(content)
            stdout.write(f"sync  {deploy_rel}/{relative}\n")
            copied += 1
    return copied


def main(argv: Optional[Sequence[str]] = None, stdout: IO[str] = sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND", "cf_sync.py"))
    parser.add_argument("action", choices=("check", "sync"), nargs="?", default="check")
    parser.add_argument("--root", default=".")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.action == "check":
        drift = _report(stdout, root, args.verbose)
        if drift:
            stdout.write(f"{drift} file(s) drifted; run `code-flow sync apply` to deploy.\n")
            return 1
        stdout.write("all pairs in sync.\n")
        return 0
    copied = _sync(root, stdout)
    stdout.write(f"{copied} file(s) deployed.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
