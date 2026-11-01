"""Read-only, bounded impact analysis for Spec Contexts and task documents."""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Callable, Iterator

from codeflow.spec.cf_spec_context_model import ContextError, load_context
from codeflow.spec.cf_spec_resolver import resolve_candidates
from codeflow.task.cf_task_doc import TaskDocumentError, parse_task_document


def _identity(root: str, value: str) -> tuple[str, str]:
    query = value.replace('\\', '/').removeprefix('.code-flow/specs/')
    found: dict[str, str] = {}
    for stage in ('prd', 'design', 'plan', 'code', 'review'):
        for item in resolve_candidates(root, stage, ()):
            if query in (item.spec_id, item.path):
                found[item.spec_id] = item.path
    if len(found) != 1:
        raise ValueError('spec_not_found' if not found else 'spec_identity_ambiguous')
    return next(iter(found.items()))


def _files(root: Path, max_depth: int, onerror: Callable[[OSError], None]) -> Iterator[Path | None]:
    if not root.exists():
        return
    for current, dirs, names in os.walk(root, followlinks=False, onerror=onerror):
        directory = Path(current)
        depth = len(directory.relative_to(root).parts)
        blocked = [name for name in dirs if depth >= max_depth or (directory / name).is_symlink()]
        dirs[:] = sorted(name for name in dirs if name not in blocked)
        if blocked:
            yield None
        for name in sorted(names):
            if name == 'spec-context.yml' or (name.endswith('.md') and not name.endswith(('.prd.md', '.design.md', '.scenarios.md'))):
                yield directory / name


def _context_references(path: Path, root: Path, identities: dict[str, str]) -> list[dict[str, object]]:
    context = load_context(str(path))
    rows: list[dict[str, object]] = []
    for binding in context.bindings:
        if binding.spec_id not in identities:
            continue
        for rule in binding.rules:
            if rule.enforcement != 'required':
                continue
            stage = rule.stage_status.get('code') or rule.stage_status.get('design')
            rows.append({'context_path': path.relative_to(root).as_posix(), 'task_id': context.task,
                         'spec_id': binding.spec_id, 'rule_ref': f'{binding.spec_id}#{rule.ref}',
                         'rule_status': stage.status if stage else 'unknown',
                         'source': 'context', 'archived': 'archived' in path.parts})
    return rows


def _task_references(path: Path, root: Path, identities: dict[str, str]) -> list[dict[str, object]]:
    text = path.read_text(encoding='utf-8')
    candidates = {name: spec_path for name, spec_path in identities.items() if name in text or spec_path in text}
    if not candidates:
        return []
    try:
        document = parse_task_document(text, source=str(path))
    except TaskDocumentError as exc:
        if exc.code == 'task_document_empty':
            return []
        raise
    rows: list[dict[str, object]] = []
    for task in document.tasks:
        for spec_id, spec_path in candidates.items():
            pattern = re.compile(rf'{re.escape(spec_id)}#(RULE-[\w-]+)')
            refs = sorted(set(pattern.findall(task.body)))
            if not refs and spec_path not in task.body:
                continue
            for ref in refs or ['']:
                rows.append({'task_path': path.relative_to(root).as_posix(), 'task_id': task.id,
                             'spec_id': spec_id, 'status': task.status,
                             'rule_ref': f'{spec_id}#{ref}' if ref else '',
                             'source': 'task', 'archived': 'archived' in path.parts})
    return rows


def scan_impacts(root: str, identities: dict[str, str], max_files: int = 5000,
                 max_depth: int = 20) -> dict[str, object]:
    if max_files <= 0 or max_depth <= 0:
        raise ValueError('impact limits must be positive')
    project = Path(root).resolve()
    tasks = project / '.code-flow/tasks'
    rows: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    def walk_error(exc: OSError) -> None:
        errors.append({'path': str(exc.filename or tasks), 'message': str(exc)})
    scanned = 0
    truncated = False
    for path in _files(tasks, max_depth, walk_error):
        if path is None:
            truncated = True
            continue
        if scanned >= max_files:
            truncated = True
            break
        scanned += 1
        try:
            if path.is_symlink():
                raise ValueError('symlink task file is not scanned')
            references = (_context_references(path, project, identities) if path.name == 'spec-context.yml'
                          else _task_references(path, project, identities))
            rows.extend(references)
        except (OSError, UnicodeError, ValueError, ContextError) as exc:
            errors.append({'path': path.relative_to(project).as_posix(), 'message': str(exc)})
    return {'references': rows, 'scanned_files': scanned, 'truncated': truncated, 'errors': errors}


def inspect_impact(root: str, query: str, max_files: int = 5000, max_depth: int = 20) -> dict[str, object]:
    spec_id, spec_path = _identity(root, query)
    return {'spec_id': spec_id, 'spec_path': spec_path,
            **scan_impacts(root, {spec_id: spec_path}, max_files, max_depth),
            'next': '修改后运行 code-flow spec refresh'}
