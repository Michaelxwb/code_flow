"""Read-only, input-bound Spec optimization proposals."""
from __future__ import annotations

import hashlib
import difflib
import json
from pathlib import Path
import re
from typing import Sequence

from codeflow.core.cf_core import estimate_tokens, load_config
from codeflow.spec.cf_spec_budget import measure_path_budget
from codeflow.spec.cf_spec_impact import scan_impacts
from codeflow.spec.cf_spec_metadata import parse_spec_metadata
from codeflow.spec.cf_spec_resolver import resolve_candidates


def _selected(root: str, paths: Sequence[str]) -> list:
    all_candidates = list(resolve_candidates(root, 'code', ()))
    if not paths:
        return all_candidates
    normalized = [item.replace('\\', '/').removeprefix('.code-flow/specs/') for item in paths]
    direct = {item.path for item in all_candidates if item.path in normalized}
    code_paths = [path for path in normalized if path not in direct]
    matched = {item.path for item in resolve_candidates(root, 'code', tuple(code_paths), matched_only=True)} if code_paths else set()
    selected = [item for item in all_candidates if item.path in direct | matched]
    if not selected:
        raise ValueError('no matching specs for requested paths')
    return selected


def _section_tokens(text: str, heading: str) -> int:
    match = re.search(rf'(?im)^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s|\Z)', text)
    return estimate_tokens(match.group(1)) if match else 0


def _spec_data(root: Path, candidate: object, config: dict) -> dict[str, object]:
    relative = str(candidate.path)
    base = (root / '.code-flow/specs').resolve()
    path = (base / relative).resolve()
    if base not in path.parents or not path.is_file():
        raise ValueError(f'invalid spec path: {relative}')
    raw = path.read_bytes()
    text = raw.decode('utf-8')
    domain = relative.split('/', 1)[0]
    mapping = config.get('path_mapping') or {}
    entry = mapping.get(domain, {}) if isinstance(mapping, dict) else {}
    patterns = entry.get('patterns', []) if isinstance(entry, dict) else []
    rules = [rule for rule in candidate.metadata.rules if rule.ref.startswith('RULE-')]
    tokens = estimate_tokens(text)
    rule_tokens = _section_tokens(text, 'Rules')
    convention_tokens = _section_tokens(text, 'Conventions')
    return {'id': candidate.spec_id, 'path': relative, 'sha256': hashlib.sha256(raw).hexdigest(),
            'tokens': tokens, 'rule_tokens': rule_tokens, 'convention_tokens': convention_tokens,
            'rule_percent': round(100 * rule_tokens / tokens, 2) if tokens else 0,
            'convention_percent': round(100 * convention_tokens / tokens, 2) if tokens else 0,
            'rule_ids': sorted(rule.ref for rule in rules), 'patterns': patterns,
            'verifiers': [{'rule': item.rule, 'type': item.type, 'stage': item.stage, 'config': item.config}
                          for item in candidate.metadata.verifiers]}


def _suggestions(specs: list[dict[str, object]], limit: int) -> list[dict[str, object]]:
    return [{'path': item['path'], 'kind': 'review_conventions_split',
             'reason': '规范超过单次注入上限；需人工选择目标，规则保持原位'}
            for item in specs if int(item['tokens']) > limit and int(item['convention_tokens']) > 0]


def _overlaps(specs: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    for index, first in enumerate(specs):
        for second in specs[index + 1:]:
            shared = sorted(set(first['patterns']) & set(second['patterns']))
            if shared:
                groups.append({'paths': [first['path'], second['path']], 'patterns': shared})
    return groups


def _target_path(root: Path, target: str) -> Path:
    relative = Path(target)
    if relative.is_absolute() or '..' in relative.parts or len(relative.parts) < 2 or relative.suffix != '.md':
        raise ValueError('target must be a relative spec path inside an existing domain')
    if relative.parts[0] in ('shared', '_session') or relative.parts[0].startswith('.'):
        raise ValueError('target domain must be an injectable spec domain')
    base = (root / '.code-flow/specs').resolve()
    path = base / relative
    if any((base.joinpath(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts) + 1)):
        raise ValueError('target path must not contain symlinks')
    if base not in path.resolve().parents or not path.parent.is_dir():
        raise ValueError('target domain directory must exist within specs')
    if path.exists() or path.is_symlink():
        raise ValueError('target already exists')
    return path


def _movement(root: Path, specs: list[dict[str, object]], target: str, config: dict) -> tuple[list[dict], list[dict]]:
    if len(specs) != 1:
        raise ValueError('target requires exactly one source spec')
    destination = _target_path(root, target)
    source = specs[0]
    base = root / '.code-flow/specs'
    relative_source = Path(str(source['path']))
    if any(base.joinpath(*relative_source.parts[:i]).is_symlink() for i in range(1, len(relative_source.parts) + 1)):
        raise ValueError('source path must not contain symlinks')
    text = (base / relative_source).read_text(encoding='utf-8')
    match = re.search(r'(?im)^##\s+Conventions\s*$([\s\S]*?)(?=^##\s|\Z)', text)
    if not match or 'RULE-' in match.group(0):
        raise ValueError('source conventions missing or contain rule references')
    new_id = str(source['id']) + '-conventions'
    for stage in ('prd', 'design', 'plan', 'code', 'review'):
        if any(item.spec_id == new_id for item in resolve_candidates(str(root), stage, ())):
            raise ValueError('target spec id already exists')
    relative = destination.relative_to(root / '.code-flow/specs').as_posix()
    operation = {'kind': 'move_conventions', 'source': source['path'], 'target': relative, 'target_id': new_id}
    source_after, target_after = render_movement(root, operation)
    operation.update({'source_after_sha256': hashlib.sha256(source_after).hexdigest(),
                      'target_after_sha256': hashlib.sha256(target_after).hexdigest(),
                      'source_after_tokens': estimate_tokens(source_after.decode('utf-8')),
                      'target_after_tokens': estimate_tokens(target_after.decode('utf-8')),
                      'source_diff': ''.join(difflib.unified_diff(text.splitlines(keepends=True),
                          source_after.decode('utf-8').splitlines(keepends=True), fromfile=str(source['path']),
                          tofile=str(source['path']))),
                      'target_diff': ''.join(difflib.unified_diff([], target_after.decode('utf-8').splitlines(keepends=True),
                          fromfile='/dev/null', tofile=relative))})
    domain = relative.split('/')[0]
    mapping = config.get('path_mapping') or {}
    entry = mapping.get(domain, {}) if isinstance(mapping, dict) else {}
    patterns = entry.get('patterns', []) if isinstance(entry, dict) else []
    return [operation], [{'kind': 'auto_discovery_add', 'domain': domain, 'path': relative,
                          'source_patterns': source['patterns'], 'target_patterns': patterns}]


def render_movement(root: Path, operation: dict) -> tuple[bytes, bytes]:
    source = root / '.code-flow/specs' / str(operation['source'])
    text = source.read_text(encoding='utf-8')
    match = re.search(r'(?im)^##\s+Conventions\s*$([\s\S]*?)(?=^##\s|\Z)', text)
    if not match or 'RULE-' in match.group(0):
        raise ValueError('rule guard: invalid conventions section')
    updated = text[:match.start()] + text[match.end():]
    before = parse_spec_metadata(text, path=str(source))
    target = ('---\nid: ' + str(operation['target_id']) + '\ndescription: Migrated conventions\n'
              'stages: ' + json.dumps(list(before.stages)) + '\nenforcement: advisory\n---\n\n'
              '# Conventions\n\n' + match.group(0) + '\n')
    after = parse_spec_metadata(updated, path=str(source))
    target_meta = parse_spec_metadata(target, path=str(root / '.code-flow/specs' / str(operation['target'])))
    signature = lambda meta: [(rule.ref, rule.text_sha256, rule.section, rule.enforcement) for rule in meta.rules]
    if signature(before) != signature(after) or before.verifiers != after.verifiers or target_meta.verifiers:
        raise ValueError('rule guard: rule or verifier changed')
    if any(item.ref.startswith('RULE-') for item in target_meta.rules):
        raise ValueError('rule guard: target contains rules')
    return updated.encode('utf-8'), target.encode('utf-8')


def build_proposal(root: str, paths: Sequence[str], target: str = '') -> dict[str, object]:
    project = Path(root).resolve()
    config = load_config(root)
    candidates = _selected(root, paths)
    specs = [_spec_data(project, candidate, config) for candidate in candidates]
    operations, mapping_diff = _movement(project, specs, target, config) if target else ([], [])
    identities = {str(item['id']): str(item['path']) for item in specs}
    for operation in operations:
        identities[str(operation['target_id'])] = str(operation['target'])
    impact = scan_impacts(root, identities)
    if impact['truncated'] or impact['errors']:
        raise ValueError('impact scan incomplete; proposal cannot assert complete scope')
    budget = config.get('budget') or {}
    if not isinstance(budget, dict):
        raise ValueError('budget must be a mapping')
    limit = min(int(budget.get('total', 2500)), int(budget.get('l1_max', 1700)))
    if limit <= 0:
        raise ValueError('budget limit must be positive')
    config_hash = hashlib.sha256((project / '.code-flow/config.yml').read_bytes()).hexdigest()
    code_paths = [path for path in paths if not any(path in (item['path'], '.code-flow/specs/' + str(item['path'])) for item in specs)]
    measured = measure_path_budget(root, code_paths) if code_paths else None
    raw_before = sum(int(item['tokens']) for item in specs)
    raw_after = (raw_before - int(specs[0]['tokens']) + int(operations[0]['source_after_tokens'])
                 + int(operations[0]['target_after_tokens'])) if operations else raw_before
    affected_files = {str(row.get('context_path') or row.get('task_path')) for row in impact['references']}
    affected_hashes = {path: hashlib.sha256((project / path).read_bytes()).hexdigest() for path in sorted(affected_files)}
    overlap = _overlaps(specs)
    suggestions = _suggestions(specs, limit)
    suggestions.extend({'paths': group['paths'], 'kind': 'review_overlap',
                        'reason': '相同路径模式命中多份规范；人工评估是否合并 Conventions'} for group in overlap)
    proposal = {'schema': 1, 'config_sha256': config_hash, 'specs': specs,
                'budget': {'before': {'raw_spec_tokens': raw_before, 'path_measurement': measured},
                           'after': {'raw_spec_tokens': raw_after, 'path_measurement': None if operations else measured},
                           'limit': limit, 'note': '变更后单次注入需在应用后重新测量'},
                'mapping_diff': mapping_diff, 'affected_contexts': impact['references'],
                'affected_file_hashes': affected_hashes,
                'scanned_files': impact['scanned_files'], 'path_overlaps': overlap, 'suggestions': suggestions,
                'operations': operations, 'note': ('请审核提案并交互确认应用。' if target
                                                     else '未指定迁移目标，提案没有可应用的文件变更。')}
    proposal['proposal_id'] = hashlib.sha256(json.dumps(proposal, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return proposal
