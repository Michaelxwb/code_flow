"""Read-only optimization proposal over a real project and CLI."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'src/core/code-flow/scripts'
sys.path.insert(0, str(SCRIPTS))


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['node', str(ROOT / 'src/cli.js'), *args], cwd=root, text=True,
                          capture_output=True, timeout=30,
                          env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})


def _project(root: Path) -> Path:
    init = _run(root, 'init', '--platform=codex')
    assert init.returncode == 0, init.stdout + init.stderr
    config_path = root / '.code-flow/config.yml'
    config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    config['path_mapping']['app'] = {'patterns': ['src/*.py'], 'specs': [{'path': 'app/rules.md'}]}
    config_path.write_text(yaml.safe_dump(config), encoding='utf-8')
    path = root / '.code-flow/specs/app/rules.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('---\nid: app-rules\ndescription: app rules\nstages: [code]\nenforcement: required\n'
                    'verifiers:\n  - rule: RULE-app-001\n    type: regex\n'
                    '    config: {pattern: forbidden, files: "src/*.py"}\n---\n'
                    '# Rules\n## Rules\n- [RULE-app-001] Preserve correctness.\n'
                    '## Conventions\n' + ('Reusable convention.\n' * 1200), encoding='utf-8')
    for args in (('init', '-q'), ('config', 'user.name', 'Test'), ('config', 'user.email', 'test@example.invalid'),
                 ('add', '-A'), ('commit', '-qm', 'fixture')):
        subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)
    return path


def _snapshot(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file() and '.git' not in path.parts}


def test_s_10(tmp_path: Path) -> None:
    path = _project(tmp_path)
    before = _snapshot(tmp_path)
    result = _run(tmp_path, 'spec', 'optimize', '--dry-run', '--paths', 'app/rules.md', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['schema'] == 1 and report['proposal_id']
    entry = next(item for item in report['specs'] if item['path'] == 'app/rules.md')
    assert entry['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert entry['tokens'] > 5000 and entry['rule_ids'] == ['RULE-app-001']
    assert entry['convention_percent'] > 0 and entry['rule_percent'] > 0
    assert report['config_sha256'] and 'before' in report['budget'] and 'after' in report['budget']
    assert 'mapping_diff' in report and 'affected_contexts' in report and report['suggestions']
    assert _snapshot(tmp_path) == before


def test_preview_detects_shared_patterns_without_changing_files(tmp_path: Path) -> None:
    first = _project(tmp_path)
    second = tmp_path / '.code-flow/specs/app/other.md'
    second.write_text(first.read_text(encoding='utf-8').replace('id: app-rules', 'id: app-other'), encoding='utf-8')
    before = _snapshot(tmp_path)
    result = _run(tmp_path, 'spec', 'optimize', '--dry-run', '--paths', 'app/rules.md', 'app/other.md', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['path_overlaps'] == [{'paths': ['app/other.md', 'app/rules.md'], 'patterns': ['src/*.py']}]
    assert any(item['kind'] == 'review_overlap' for item in report['suggestions'])
    assert report['operations'] == [] and _snapshot(tmp_path) == before
