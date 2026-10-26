"""Session-isolated injection deduplication, committed after successful output."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Iterator, TYPE_CHECKING

from codeflow.core import cf_log

if TYPE_CHECKING:
    from codeflow.spec.cf_spec_router import RouteResult

_PENDING: ContextVar[list[Callable[[], None]] | None] = ContextVar("injection_output", default=None)
_INTERVAL = 25


def defer_commit(action: Callable[[], None]) -> None:
    pending = _PENDING.get()
    if pending is None:
        action()
    else:
        pending.append(action)


@contextmanager
def injection_output() -> Iterator[None]:
    """Discard pending dedup state if building or writing the output fails."""
    if _PENDING.get() is not None:
        yield
        return
    actions: list[Callable[[], None]] = []
    token = _PENDING.set(actions)
    try:
        yield
    except BaseException:
        raise
    else:
        for action in actions:
            action()
    finally:
        _PENDING.reset(token)


def _state_path(root: str, sid: str) -> Path:
    name = hashlib.sha256(sid.encode("utf-8")).hexdigest()
    return Path(root) / ".code-flow/sessions/injection" / f"{name}.json"


def _load_state(path: Path) -> dict[str, object]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        return state if isinstance(state, dict) and state.get("version") == 1 else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def _number(state: dict[str, object], key: str) -> int:
    value = state.get(key, 0)
    return value if type(value) is int and value >= 0 else 0


def _save_state(path: Path, state: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    except (OSError, UnicodeError, TypeError) as exc:
        cf_log.warn(f"cf_injection: dedup state unavailable: {exc}")
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError as exc:
            cf_log.warn(f"cf_injection: cannot remove temporary dedup state: {exc}")


def _commit(root: str, sid: str, result: RouteResult, count: int, fingerprint: str, emitted: bool) -> None:
    path = _state_path(root, sid)
    state = _load_state(path)
    state.update(version=1, prompt_count=count)
    if emitted:
        state[f"{result.mode}_fingerprint"] = fingerprint
        state[f"{result.mode}_last_prompt"] = count
        cf_log.append_event(root, "inject", {"specs": list(result.specs), "mode": result.mode,
                            "source": result.mode}, sid)
    _save_state(path, state)


def injection_text(root: str, sid: str, result: RouteResult, *, prompt: bool = False) -> str:
    if result.mode not in {"task", "path"} or not result.text:
        return result.text
    state = _load_state(_state_path(root, sid))
    count = _number(state, "prompt_count") + int(prompt)
    fingerprint = hashlib.sha256(
        (result.mode + "\n" + result.text).encode("utf-8")
    ).hexdigest()
    emitted = (state.get(f"{result.mode}_fingerprint") != fingerprint
               or count - _number(state, f"{result.mode}_last_prompt") >= _INTERVAL)
    defer_commit(lambda: _commit(root, sid, result, count, fingerprint, emitted))
    return result.text if emitted else ""


def pre_tool_payload(text: str, blocked: bool) -> dict[str, object]:
    output: dict[str, object] = {"hookEventName": "PreToolUse", "additionalContext": text}
    if blocked:
        output.update(permissionDecision="deny", permissionDecisionReason=text)
    return {"hookSpecificOutput": output}
