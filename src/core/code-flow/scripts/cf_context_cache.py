"""Rebuildable Context parse cache bound to source bytes and parser version."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Protocol

from cf_core import _log
import cf_spec_context
from cf_spec_context import (ContextError, SpecContext, context_from_data,
                             context_sha256, context_to_data)


class ContextLoader(Protocol):
    def __call__(self, path: str, *, source: bytes | None = None) -> SpecContext: ...


def _digest(value: dict[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read(path: Path, key: str) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        checksum = payload.pop("checksum", None)
        if payload.get("version") == 1 and payload.get("key") == key and checksum == _digest(payload):
            return payload
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _log(f"Context parse cache unavailable; reloading source: {exc}")
    return {}


def _write(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        payload = dict(payload, checksum=_digest(payload))
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    except (OSError, UnicodeError, TypeError) as exc:
        _log(f"Context parse cache cannot be saved: {exc}")
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError as exc:
            _log(f"Context parse cache cleanup failed: {exc}")


def load_snapshot(root: str, path: str, loader: ContextLoader) -> tuple[SpecContext, str]:
    source = Path(path).read_bytes()
    parser = Path(cf_spec_context.__file__).read_bytes()
    key = hashlib.sha256(str(Path(path).resolve()).encode("utf-8") + b"\0"
                         + hashlib.sha256(source).digest() + hashlib.sha256(parser).digest()).hexdigest()
    cache = Path(root) / ".code-flow/.context-state.json"
    payload = _read(cache, key)
    if payload:
        try:
            context = context_from_data(payload.get("context"), path)
            identity = payload.get("identity")
            if isinstance(identity, str) and len(identity) == 64:
                return context, identity
        except ContextError as exc:
            _log(f"Context parse cache invalid; reloading source: {exc}")
    context = loader(path, source=source)
    identity = context_sha256(context)
    _write(cache, {"version": 1, "key": key, "context": context_to_data(context), "identity": identity})
    return context, identity
