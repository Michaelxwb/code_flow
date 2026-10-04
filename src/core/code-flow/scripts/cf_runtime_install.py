"""Integrity check for the installed runtime contract and managed artifacts."""
import hashlib
import json
from pathlib import Path


def verify_install(root: str) -> None:
    directory = Path(root)
    if (directory / ".code-flow/.runtime-migration.lock").exists():
        raise ValueError("runtime migration is in progress or needs recovery")
    manifest = json.loads((directory / ".code-flow/.runtime-install.json").read_text(encoding="utf-8"))
    version = (directory / ".code-flow/.version").read_text(encoding="utf-8").strip()
    if manifest.get("schema_version") != 1 or manifest.get("version") != version:
        raise ValueError("runtime installation version is inconsistent")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("runtime installation manifest has no artifacts")
    for relative, expected in files.items():
        path = directory / relative
        if not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError(f"installation artifact escapes project: {relative}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"managed runtime artifact has drifted: {relative}")
    for relative, expected in manifest.get("hook_contracts", {}).items():
        actual = json.loads((directory / relative).read_text(encoding="utf-8")).get("hooks", {})
        for event, groups in expected.items():
            for group in groups:
                candidates = [item for item in actual.get(event, [])
                              if item.get("matcher", "") == group.get("matcher", "")]
                for hook in group["hooks"]:
                    if not any(hook in item.get("hooks", []) for item in candidates):
                        raise ValueError(f"managed hook has drifted: {relative}:{event}")
