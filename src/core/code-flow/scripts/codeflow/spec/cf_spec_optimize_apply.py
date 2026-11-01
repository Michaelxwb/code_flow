"""Guarded, recoverable application of a reviewed conventions proposal."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Mapping

from codeflow.spec.cf_spec_optimize import build_proposal, render_movement
from codeflow.task.cf_task_doc import TaskDocumentError, parse_task_document


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _proposal_hash(proposal: Mapping[str, object]) -> str:
    unsigned = {key: value for key, value in proposal.items() if key != 'proposal_id'}
    return _digest(json.dumps(unsigned, ensure_ascii=False, sort_keys=True).encode())


def _check_context_tasks(root: Path, directory: str) -> None:
    task_directory = root / directory
    statuses: list[str] = []
    for path in sorted(task_directory.glob('*.md')):
        if path.name.endswith(('.prd.md', '.design.md', '.scenarios.md')):
            continue
        try:
            document = parse_task_document(path.read_text(encoding='utf-8'), source=str(path))
        except TaskDocumentError as exc:
            if exc.code == 'task_document_empty':
                continue
            raise
        statuses.extend(task.status for task in document.tasks)
    if not statuses or any(status not in ('done', 'verified') for status in statuses):
        raise ValueError('inflight_context: affected Context has incomplete or unproven tasks')


def _check_inflight(root: str, proposal: Mapping[str, object]) -> None:
    refs = proposal.get('affected_contexts')
    if not isinstance(refs, list):
        raise ValueError('proposal impact evidence missing')
    tasks = [row for row in refs if isinstance(row, dict) and row.get('source') == 'task' and not row.get('archived')]
    contexts = [row for row in refs if isinstance(row, dict) and row.get('source') == 'context' and not row.get('archived')]
    if any(row.get('status') not in ('done', 'verified') for row in tasks):
        raise ValueError('inflight_context: affected task is not complete')
    directories = {str(Path(str(row.get('context_path', ''))).parent) for row in contexts}
    for directory in sorted(directories):
        _check_context_tasks(Path(root), directory)


def _validate(root: str, proposal: Mapping[str, object]) -> dict[str, object]:
    if proposal.get('schema') != 1 or proposal.get('proposal_id') != _proposal_hash(proposal):
        raise ValueError('proposal guard: invalid proposal identity')
    operations = proposal.get('operations')
    if not isinstance(operations, list) or len(operations) != 1 or not isinstance(operations[0], dict):
        raise ValueError('proposal guard: exactly one explicit operation is required')
    operation = operations[0]
    if operation.get('kind') != 'move_conventions' or not isinstance(operation.get('source'), str) or not isinstance(operation.get('target'), str):
        raise ValueError('proposal guard: invalid operation')
    try:
        current = build_proposal(root, (operation['source'],), str(operation['target']))
    except (OSError, ValueError) as exc:
        raise ValueError(f'proposal_stale: {exc}') from exc
    if current != proposal:
        raise ValueError('proposal_stale: input, impact, or operation changed')
    _check_inflight(root, proposal)
    return operation


def _write(path: Path, data: bytes, mode: int = 0o600) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, 'wb') as handle:
        os.fchmod(handle.fileno(), mode)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _journal(directory: Path, data: dict[str, object]) -> None:
    temporary = directory / 'journal.tmp'
    if temporary.exists():
        raise ValueError('transaction journal temporary file already exists')
    _write(temporary, (json.dumps(data, ensure_ascii=False, sort_keys=True) + '\n').encode())
    os.replace(temporary, directory / 'journal.json')
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def commit_replace(staged: Path, destination: Path) -> None:
    """Replace the source; create a new target exclusively without overwriting."""
    if staged.name == 'target.staged':
        os.link(staged, destination)
    else:
        os.replace(staged, destination)


def _rollback(source: Path, target: Path, backup: Path, original_hash: str,
              source_after_hash: str, target_after_hash: str, target_created: bool) -> None:
    if target_created:
        if not target.is_file() or _digest(target.read_bytes()) != target_after_hash:
            raise ValueError('recovery_required: target changed during rollback')
        target.unlink()
    current = _digest(source.read_bytes()) if source.is_file() else ''
    if current == original_hash:
        return
    if current != source_after_hash or _digest(backup.read_bytes()) != original_hash:
        raise ValueError('recovery_required: source changed during rollback')
    os.replace(backup, source)


def _remove_transaction(directory: Path, parent_existed: bool) -> None:
    parent = directory.parent
    shutil.rmtree(directory)
    if not parent_existed:
        parent.rmdir()


def _transaction(root: Path, proposal: Mapping[str, object], operation: Mapping[str, object]) -> dict[str, object]:
    base = root / '.code-flow/specs'
    source = base / str(operation['source'])
    target = base / str(operation['target'])
    original = source.read_bytes()
    after_source, after_target = render_movement(root, dict(operation))
    specs = proposal.get('specs')
    if (not isinstance(specs, list) or len(specs) != 1 or not isinstance(specs[0], dict)
            or _digest(original) != specs[0].get('sha256')
            or _digest(after_source) != operation.get('source_after_sha256')
            or _digest(after_target) != operation.get('target_after_sha256')):
        raise ValueError('proposal_stale: source or proposed result changed')
    parent = base / '.optimize-transactions'
    if parent.is_symlink() or (parent.exists() and (not parent.is_dir() or any(parent.iterdir()))):
        raise ValueError('recovery_required: unfinished optimization transaction')
    parent_existed = parent.exists()
    parent.mkdir(exist_ok=True)
    directory = parent / str(proposal['proposal_id'])
    directory.mkdir()
    backup, source_stage, target_stage = directory / 'source.backup', directory / 'source.staged', directory / 'target.staged'
    target_created = False
    state = {'schema': 1, 'proposal_id': proposal['proposal_id'], 'source': operation['source'],
             'target': operation['target'], 'original_sha256': _digest(original),
             'source_after_sha256': _digest(after_source), 'target_after_sha256': _digest(after_target), 'state': 'prepared'}
    try:
        _write(backup, original, source.stat().st_mode & 0o777)
        _write(source_stage, after_source, source.stat().st_mode & 0o777)
        _write(target_stage, after_target, 0o644)
        _journal(directory, state)
        state['state'] = 'committing'
        _journal(directory, state)
        if _digest(source.read_bytes()) != state['original_sha256']:
            raise ValueError('proposal_stale: source changed before commit')
        commit_replace(source_stage, source)
        commit_replace(target_stage, target)
        target_created = True
        if _digest(source.read_bytes()) != state['source_after_sha256'] or _digest(target.read_bytes()) != state['target_after_sha256']:
            raise ValueError('post-write guard: content differs from approved proposal')
        state['state'] = 'committed'
        _journal(directory, state)
    except (OSError, ValueError):
        _rollback(source, target, backup, _digest(original), _digest(after_source), _digest(after_target), target_created)
        _remove_transaction(directory, parent_existed)
        raise
    _remove_transaction(directory, parent_existed)
    return {'decision': 'pass', 'proposal_id': proposal['proposal_id'],
            'changed': [str(operation['source']), str(operation['target'])]}


def apply_proposal(root: str, proposal: Mapping[str, object], *, confirmed: bool) -> dict[str, object]:
    if not confirmed:
        raise ValueError('explicit confirmation required')
    project = Path(root).resolve()
    lock = project / '.code-flow/specs/.optimize.lock'
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError('recovery_required: optimization lock exists') from exc
    os.close(descriptor)
    try:
        operation = _validate(root, proposal)
        return _transaction(project, proposal, operation)
    finally:
        lock.unlink()
