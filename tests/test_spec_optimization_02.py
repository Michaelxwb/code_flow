"""Budget simulations exercise the real CLI and path router."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'src/core/code-flow/scripts'
sys.path.insert(0, str(SCRIPTS))
from codeflow.core.cf_core import estimate_tokens
from codeflow.spec.cf_spec_router import _read_candidates


def _project(root: Path, limit: int = 5000) -> None:
    subprocess.run(['node', str(ROOT / 'src/cli.js'), 'init', '--platform=codex'], cwd=root,
                   text=True, capture_output=True, check=True, timeout=30)
    config = yaml.safe_load((root / '.code-flow/config.yml').read_text(encoding='utf-8'))
    config['budget']['total'] = limit
    config['budget']['l1_max'] = limit
    config['path_mapping']['app'] = {'patterns': ['src/*.py'], 'specs': [{'path': 'app/rules.md'}]}
    (root / '.code-flow/config.yml').write_text(yaml.safe_dump(config), encoding='utf-8')
    spec = root / '.code-flow/specs/app/rules.md'
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text('---\nid: app-rules\ndescription: app rules\nstages: [code]\nenforcement: required\n'
                    'verifiers:\n  - rule: RULE-app-001\n    type: regex\n'
                    '    config: {pattern: forbidden, files: "src/*.py"}\n---\n'
                    '# Rules\n## Rules\n- [RULE-app-001] Preserve correctness.\n', encoding='utf-8')
    (root / 'src').mkdir(exist_ok=True)
    (root / 'src/a.py').write_text('A = 1\n', encoding='utf-8')
    (root / 'src/b.py').write_text('B = 1\n', encoding='utf-8')
    for args in (('init', '-q'), ('config', 'user.name', 'Test'),
                 ('config', 'user.email', 'test@example.invalid'), ('add', '-A'),
                 ('commit', '-qm', 'fixture')):
        subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)


def _budget(root: Path, *paths: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['node', str(ROOT / 'src/cli.js'), 'spec', 'budget', '--paths', *paths, '--json'],
                          cwd=root, text=True, capture_output=True, timeout=30)


def test_s_04(tmp_path: Path) -> None:
    _project(tmp_path)
    result = _budget(tmp_path, 'src/a.py')
    assert result.returncode == 0, result.stderr + result.stdout
    data = json.loads(result.stdout)
    route = _read_candidates(str(tmp_path), ('src/a.py',))
    assert data['matched_total'] == estimate_tokens(route.text)
    assert {row['path'] for row in data['matched_specs']} == set(route.specs)
    assert data['limit'] == 5000 and data['aggregate_total'] >= 0
    assert data['over_limit'] is False


def test_e_03(tmp_path: Path) -> None:
    _project(tmp_path, limit=5)
    result = _budget(tmp_path, 'src/a.py')
    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert data['over_limit'] is True and data['matched_total'] > data['limit'] == 5
    assert data['matched_specs']


def test_b_01(tmp_path: Path) -> None:
    _project(tmp_path)
    result = _budget(tmp_path, 'src/a.py', 'src/b.py')
    assert result.returncode == 0, result.stderr + result.stdout
    data = json.loads(result.stdout)
    route = _read_candidates(str(tmp_path), ('src/a.py', 'src/b.py'))
    paths = [item['path'] for item in data['matched_specs']]
    assert paths.count('app/rules.md') == 1 and len(paths) == len(set(paths))
    assert data['matched_total'] == estimate_tokens(route.text)


def test_changed_paths_include_untracked_and_empty_tree_is_not_injected(tmp_path: Path) -> None:
    _project(tmp_path)
    command = ['node', str(ROOT / 'src/cli.js'), 'spec', 'budget', '--changed', '--json']
    empty = subprocess.run(command, cwd=tmp_path, text=True, capture_output=True, check=True)
    assert json.loads(empty.stdout)['matched_total'] == 0
    (tmp_path / 'src/new.py').write_text('NEW = 1\n', encoding='utf-8')
    changed = subprocess.run(command, cwd=tmp_path, text=True, capture_output=True, check=True)
    report = json.loads(changed.stdout)
    assert report['matched_total'] == estimate_tokens(_read_candidates(str(tmp_path), ('src/new.py',)).text)


def test_stats_distinguishes_aggregate_from_per_edit_budget(tmp_path: Path) -> None:
    _project(tmp_path, limit=5)
    result = subprocess.run(['node', str(ROOT / 'src/cli.js'), 'stats', '--json'], cwd=tmp_path,
                            text=True, capture_output=True, check=True)
    warnings = json.loads(result.stdout)['warnings']
    assert any('L1 全量聚合' in item and '不代表单次编辑超限' in item for item in warnings)
    assert 'L1 超出预算' not in warnings
    assert json.loads(result.stdout)['budget_summary']['single_edit_limit'] == 5


def test_budget_human_output_and_missing_paths_error(tmp_path: Path) -> None:
    _project(tmp_path)
    prefix = ['node', str(ROOT / 'src/cli.js'), 'spec', 'budget']
    human = subprocess.run([*prefix, '--paths', 'src/a.py'], cwd=tmp_path, text=True, capture_output=True)
    assert human.returncode == 0 and '单次注入:' in human.stdout and '规范全量聚合:' in human.stdout
    missing = subprocess.run([*prefix, '--json'], cwd=tmp_path, text=True, capture_output=True)
    assert missing.returncode != 0 and json.loads(missing.stdout)['error']['code'] == 'paths_required'
