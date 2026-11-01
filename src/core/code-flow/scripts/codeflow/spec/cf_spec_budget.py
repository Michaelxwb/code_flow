"""Shared path-projection inputs and budget accounting."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from codeflow.core.cf_core import assemble_context, compress_content, estimate_tokens, load_config, parse_spec_frontmatter, resolve_compress
from codeflow.spec.cf_spec_resolver import resolve_candidates


class SpecBudgetError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def path_specs(root: str, paths: Sequence[str], compress: bool = True,
               matched_only: bool = True) -> list[dict[str, object]]:
    try:
        candidates = resolve_candidates(root, 'code', tuple(paths), matched_only=matched_only)
    except ValueError as exc:
        raise SpecBudgetError('invalid_spec_metadata', str(exc)) from exc
    specs: list[dict[str, object]] = []
    for candidate in candidates:
        if matched_only and candidate.scope == 'unmatched':
            continue
        target = Path(root) / '.code-flow/specs' / candidate.path
        try:
            raw = target.read_text(encoding='utf-8')
        except OSError as exc:
            raise SpecBudgetError('spec_read_failed', f'{candidate.path}: {exc}') from exc
        _, content = parse_spec_frontmatter(raw)
        final = compress_content(content.strip()) if compress else content.strip()
        specs.append({'path': candidate.path, 'content': final, 'tier': 1})
    return specs


def measure_path_budget(root: str, paths: Sequence[str]) -> dict[str, object]:
    config = load_config(root)
    quality = config.get('quality_loop')
    compress = resolve_compress(quality if isinstance(quality, dict) else {})
    matched = path_specs(root, paths, compress) if paths else []
    aggregate = path_specs(root, (), compress, matched_only=False)
    text = assemble_context(matched, '## Active Specs (path-mapped)') if matched else ''
    budget = config.get('budget', {})
    if not isinstance(budget, dict):
        raise SpecBudgetError('invalid_budget', 'budget must be a mapping')
    limit = min(int(budget.get('total', 2500)), int(budget.get('l1_max', 1700)))
    if limit <= 0:
        raise SpecBudgetError('invalid_budget', 'budget limit must be positive')
    total = estimate_tokens(text)
    return {'matched_specs': [{'path': item['path'], 'tokens': estimate_tokens(item['content'])}
                              for item in matched], 'matched_total': total,
            'aggregate_total': sum(estimate_tokens(item['content']) for item in aggregate),
            'limit': limit, 'over_limit': total > limit}
