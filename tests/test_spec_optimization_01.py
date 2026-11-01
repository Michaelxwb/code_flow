"""TASK-001: audit real project files, configuration, and reports."""
from __future__ import annotations
from pathlib import Path
import json
import subprocess
import sys

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / 'src/core/code-flow/scripts'
sys.path.insert(0, str(SCRIPTS))
from codeflow.spec.cf_scan import build_report, find_redundant_lines


def _project(root: Path, config: dict | None = None) -> Path:
    directory = root / '.code-flow/specs/app'
    directory.mkdir(parents=True)
    (root / '.code-flow/config.yml').write_text(yaml.safe_dump(config or {}), encoding='utf-8')
    return directory


def _write(directory: Path, name: str, body: str) -> None:
    (directory / name).write_text('---\ndescription: audit test\n---\n# Test\n' + body, encoding='utf-8')


def _entry(report: dict, name: str) -> dict:
    return next(item for item in report['files'] if item['path'] == f'specs/app/{name}')


def test_s_01(tmp_path: Path) -> None:
    directory = _project(tmp_path)
    target = tmp_path / 'apps/a/src/pkg/application/x.py'
    target.parent.mkdir(parents=True)
    target.write_text('VALUE = 1\n', encoding='utf-8')
    _write(directory, 'rules.md', 'Use application/x.py\n')
    entry = _entry(build_report(str(tmp_path)), 'rules.md')
    assert not any('application/x.py' in issue for issue in entry['issues'])
    assert entry['resolved_paths']['application/x.py'] == 'apps/a/src/pkg'
    result = subprocess.run([sys.executable, str(SCRIPTS / 'cf_stats.py'), '--audit', '--json'],
                            cwd=tmp_path, text=True, capture_output=True, check=True)
    audit = json.loads(result.stdout)['audit']
    assert any(item['resolved_paths'].get('application/x.py') == 'apps/a/src/pkg'
               for item in audit['path_resolutions'])


def test_s_02(tmp_path: Path) -> None:
    directory = _project(tmp_path)
    _write(directory, 'rules.md', 'Use ghost/y.py\n')
    entry = _entry(build_report(str(tmp_path)), 'rules.md')
    assert any('ghost/y.py' in issue for issue in entry['issues'])


def test_e_01(tmp_path: Path) -> None:
    outside = tmp_path.parent / 'outside-audit-root'
    outside.mkdir(exist_ok=True)
    directory = _project(tmp_path, {'audit': {'path_roots': ['missing/root', str(outside)]}})
    _write(directory, 'rules.md', 'Use ghost/y.py\n')
    report = build_report(str(tmp_path))
    assert any('ghost/y.py' in item for item in _entry(report, 'rules.md')['issues'])
    assert len(report['audit_warnings']) == 2
    assert all(item['code'] == 'invalid_path_root' for item in report['audit_warnings'])
    result = subprocess.run([sys.executable, str(SCRIPTS / 'cf_stats.py'), '--audit', '--json'],
                            cwd=tmp_path, text=True, capture_output=True, check=True)
    assert len(json.loads(result.stdout)['audit']['warnings']) == 2


def test_path_resolution_order_and_ignored_globs(tmp_path: Path) -> None:
    directory = _project(tmp_path, {'audit': {'path_roots': ['custom']}})
    for root in ('custom', 'apps/a/src/pkg'):
        target = tmp_path / root / 'app/x.py'
        target.parent.mkdir(parents=True)
        target.write_text('pass\n', encoding='utf-8')
    _write(directory, 'rules.md', 'app/x.py https://example.org/a/b.py src/*/test.py src/{one,two}/test.py\n')
    entry = _entry(build_report(str(tmp_path)), 'rules.md')
    assert entry['resolved_paths']['app/x.py'] == 'custom'
    assert not any('过时' in issue for issue in entry['issues'])


def test_e_02(tmp_path: Path) -> None:
    directory = _project(tmp_path)
    body = '---\nstages:\n- design\nverifiers:\n  - type: command\n---\n# Rules\n- Keep this shared rule.\n'
    specs = []
    for index in range(3):
        path = directory / f'{index}.md'
        path.write_text(body, encoding='utf-8')
        specs.append({'path': str(path), 'content': path.read_text(encoding='utf-8')})
    duplicates = find_redundant_lines(specs)
    assert '- Keep this shared rule.' in duplicates
    assert 'stages:' not in duplicates and '- design' not in duplicates and 'verifiers:' not in duplicates
    assert '- type: command' not in duplicates


def test_s_03(tmp_path: Path) -> None:
    directory = _project(tmp_path, {'audit': {'long_spec_tokens': 2500}})
    _write(directory, 'small.md', 'a' * 9600)
    _write(directory, 'large.md', 'b' * 10400)
    report = build_report(str(tmp_path))
    assert not any('冗长' in item for item in _entry(report, 'small.md')['issues'])
    assert any('冗长' in item for item in _entry(report, 'large.md')['issues'])
    for invalid in (0, -1, 'bad', True):
        (tmp_path / '.code-flow/config.yml').write_text(yaml.safe_dump({'audit': {'long_spec_tokens': invalid}}), encoding='utf-8')
        with pytest.raises(ValueError, match='long_spec_tokens'):
            build_report(str(tmp_path))
