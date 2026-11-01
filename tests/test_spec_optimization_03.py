"""Doctor layout and bounded catalog acceptance through the real CLI."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'src/core/code-flow/scripts'
sys.path.insert(0, str(SCRIPTS))
from codeflow.core.cf_core import build_effective_mapping, build_spec_catalog, load_config, normalize_spec_entry


def _cli(root: Path, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['node', str(ROOT / 'src/cli.js'), *args], cwd=root, input=input_text,
                          text=True, capture_output=True, timeout=30)


def _project(root: Path) -> Path:
    init = _cli(root, 'init', '--platform=codex')
    assert init.returncode == 0, init.stdout + init.stderr
    task = root / '.code-flow/tasks/demo'
    task.mkdir(parents=True)
    result = _cli(root, 'spec', 'bind', '--task-dir', str(task), '--root', str(root), '--stage', 'prd', '--json',
                  input_text=json.dumps({'task': 'demo', 'paths': [], 'selections': [], 'applications': []}))
    assert result.returncode == 0, result.stdout + result.stderr
    for args in (('init', '-q'), ('config', 'user.name', 'Test'), ('config', 'user.email', 'test@example.invalid'),
                 ('add', '-A'), ('commit', '-qm', 'fixture')):
        subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)
    return task


def _config(root: Path) -> dict:
    return yaml.safe_load((root / '.code-flow/config.yml').read_text(encoding='utf-8'))


def _save(root: Path, config: dict) -> None:
    (root / '.code-flow/config.yml').write_text(yaml.safe_dump(config), encoding='utf-8')


def _doctor(root: Path, task: Path) -> subprocess.CompletedProcess[str]:
    return _cli(root, 'spec', 'doctor', '--task-dir', str(task), '--root', str(root), '--json')


def test_e_04(tmp_path: Path) -> None:
    task = _project(tmp_path)
    config = _config(tmp_path)
    config['path_mapping']['missing_domain'] = {'patterns': ['missing/*'], 'specs': []}
    _save(tmp_path, config)
    normal = _doctor(tmp_path, task)
    assert normal.returncode == 0, normal.stdout + normal.stderr
    finding = next(x for x in json.loads(normal.stdout)['findings'] if x['code'] == 'domain_directory_missing')
    assert finding['severity'] == 'warn' and finding['fix']
    config['spec_workflow']['strict_domain_layout'] = True
    _save(tmp_path, config)
    strict = _doctor(tmp_path, task)
    assert strict.returncode != 0
    assert any(x['code'] == 'domain_directory_missing' and x['severity'] == 'block'
               for x in json.loads(strict.stdout)['findings'])


def test_e_05(tmp_path: Path) -> None:
    task = _project(tmp_path)
    config = _config(tmp_path)
    (tmp_path / '.code-flow/specs/e2e').mkdir()
    config['path_mapping']['e2e'] = {'patterns': ['e2e/*'], 'specs': [{'path': 'backend/logging.md'}]}
    _save(tmp_path, config)
    before = (tmp_path / '.code-flow/config.yml').read_bytes()
    result = _doctor(tmp_path, task)
    assert any(x['code'] == 'domain_cross_reference' for x in json.loads(result.stdout)['findings'])
    assert (tmp_path / '.code-flow/config.yml').read_bytes() == before


def test_doctor_explains_automatic_discovery_without_claiming_spec_is_missing(tmp_path: Path) -> None:
    task = _project(tmp_path)
    config = _config(tmp_path)
    directory = tmp_path / '.code-flow/specs/extra'
    directory.mkdir()
    (directory / 'rules.md').write_text('# auto discovered\n', encoding='utf-8')
    config['path_mapping']['extra'] = {'patterns': ['extra/*'], 'specs': []}
    _save(tmp_path, config)
    result = _doctor(tmp_path, task)
    finding = next(item for item in json.loads(result.stdout)['findings']
                   if item['code'] == 'domain_auto_discovered' and 'extra/rules.md' in item['message'])
    assert finding['severity'] == 'warn' and '已由自动发现纳入' in finding['message']


def test_s_05(tmp_path: Path) -> None:
    _project(tmp_path)
    config = _config(tmp_path)
    config['budget']['catalog_max'] = 200
    for index in range(22):
        domain = f'domain{index:02}'
        directory = tmp_path / '.code-flow/specs' / domain
        directory.mkdir()
        (directory / 'rules.md').write_text(f'---\nid: {domain}\ndescription: long domain {index}\nstages: [code]\nenforcement: advisory\n---\n# Rules\n', encoding='utf-8')
        config['path_mapping'][domain] = {'patterns': [domain + '/*'], 'specs': [{'path': domain + '/rules.md'}]}
    _save(tmp_path, config)
    result = _cli(tmp_path, 'spec', 'catalog', '--root', str(tmp_path), '--stage', 'code', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    mapping = build_effective_mapping(str(tmp_path), load_config(str(tmp_path))['path_mapping'])
    text = build_spec_catalog(str(tmp_path), mapping, 200)
    displayed = [line.split('`')[1] for line in text.splitlines() if line.startswith('- `')]
    entries = [normalize_spec_entry(item)['path'] for value in mapping.values() for item in value['specs']
               if normalize_spec_entry(item)['tags'] and (tmp_path / '.code-flow/specs' / normalize_spec_entry(item)['path']).is_file()]
    from collections import Counter
    omitted = list((Counter(entries) - Counter(displayed)).elements())
    assert omitted and report['dropped_count'] == len(omitted)
    assert report['dropped_domains'] == sorted({path.split('/')[0] for path in omitted})
    human = _cli(tmp_path, 'spec', 'catalog', '--root', str(tmp_path), '--stage', 'code')
    assert human.returncode == 0 and '因预算未列出' in human.stdout


def test_b_02(tmp_path: Path) -> None:
    _project(tmp_path)
    config = _config(tmp_path)
    config['budget']['catalog_max'] = 1
    _save(tmp_path, config)
    result = _cli(tmp_path, 'spec', 'catalog', '--root', str(tmp_path), '--stage', 'code', '--json')
    assert result.returncode != 0
    error = json.loads(result.stdout)['error']
    assert error['code'] == 'catalog_budget_too_small' and error['minimum'] > 1
