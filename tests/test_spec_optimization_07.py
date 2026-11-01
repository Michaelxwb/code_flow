"""Release acceptance through real CLI, project files and adapter checks."""
from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / 'src/core/code-flow/scripts'
sys.path.insert(0, str(SCRIPTS))

from test_spec_optimization_06 import ROOT, _apply_tty, _project, _run
from test_spec_optimization_04 import _project as _context_project


def test_s_08(tmp_path: Path) -> None:
    _project(tmp_path)
    guide = (ROOT / 'docs/spec-optimization.md').read_text(encoding='utf-8')
    commands = [
        ('stats', '--audit', '--json'),
        ('spec', 'budget', '--paths', 'src/app.py', '--json'),
        ('spec', 'impact', 'app-rules', '--json'),
        ('spec', 'optimize', '--dry-run', '--paths', 'app/rules.md', '--target', 'app/conventions.md', '--json'),
    ]
    for command in commands:
        assert 'code-flow ' + ' '.join(command) in guide
        result = _run(tmp_path, *command)
        assert result.returncode in ((0, 3) if command[1] == 'budget' else (0,)), result.stdout + result.stderr
        report = json.loads(result.stdout)
        if command[1] == 'impact':
            assert not report['truncated'] and not report['errors']
        if command[1] == 'optimize':
            assert report['operations'] and report['mapping_diff']
            plan = tmp_path / 'plan.json'
            plan.write_text(json.dumps(report), encoding='utf-8')
            applied = _apply_tty(tmp_path, plan)
            assert applied.returncode == 0, applied.stdout + applied.stderr
    assert 'spec doctor' in guide and 'spec refresh' in guide and 'spec optimize --apply' in guide
    other = tmp_path / 'context-project'
    other.mkdir()
    task = _context_project(other)
    for action in ('refresh', 'doctor'):
        result = _run(other, 'spec', action, '--task-dir', str(task), '--root', str(other), '--json')
        assert result.returncode == 0, result.stdout + result.stderr


def test_s_09(tmp_path: Path) -> None:
    _project(tmp_path)
    parity = subprocess.run([sys.executable, '-m', 'pytest', '-q', 'tests/test_adapter_parity.py'], cwd=ROOT,
                            text=True, capture_output=True, timeout=60)
    assert parity.returncode == 0, parity.stdout + parity.stderr
    result = _run(ROOT, 'sync', 'check', '--root', str(ROOT))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'all pairs in sync' in result.stdout
    guide = (ROOT / 'docs/spec-optimization.md').read_text(encoding='utf-8')
    assert all(name in guide for name in ('Claude', 'Codex', 'Costrict', 'OpenCode'))


def test_e_08(tmp_path: Path) -> None:
    _project(tmp_path)
    from codeflow.spec.cf_scan import build_report
    config_path = tmp_path / '.code-flow/config.yml'
    config = yaml.safe_load(config_path.read_text())
    config.pop('audit', None)
    config_path.write_text(yaml.safe_dump(config))
    spec = tmp_path / '.code-flow/specs/app/long.md'
    spec.write_text('---\ndescription: old style\n---\n# Long\n' + 'a' * 2200)
    report = build_report(str(tmp_path))
    entry = next(item for item in report['files'] if item['path'] == 'specs/app/long.md')
    assert any('冗长' in item for item in entry['issues'])
    stats = _run(tmp_path, 'stats', '--audit', '--json')
    assert stats.returncode == 0, stats.stdout + stats.stderr
    data = json.loads(stats.stdout)
    assert {'audit', 'l0', 'l1', 'total_tokens', 'total_budget', 'utilization', 'warnings'} <= data.keys()
    package = json.loads((ROOT / 'package.json').read_text())
    assert package['dependencies'] == {'@ccusage/codex': '^18.0.10'}
    for path in (ROOT / 'src/core/code-flow/validation.yml', ROOT / '.code-flow/validation.yml'):
        validators = yaml.safe_load(path.read_text())['validators']
        assert next(item for item in validators if item['name'] == 'Pytest')['timeout'] >= 600000


@pytest.mark.capacity
def test_b_04(tmp_path: Path) -> None:
    source, _ = _project(tmp_path)
    for index in range(99):
        (source.parent / f'extra-{index}.md').write_text(
            f'---\nid: extra-{index}\ndescription: fixture\nstages: [code]\nenforcement: advisory\n---\n# Extra\n')
    task_dir = tmp_path / '.code-flow/tasks/capacity'
    task_dir.mkdir(parents=True)
    for index in range(1000):
        (task_dir / f'task-{index}.md').write_text(
            f'# Tasks\n\n## TASK-{index:03d}: Example\n- **Status**: done\n- **Spec-Refs**: app-rules#RULE-app-001\n')
    measurements = {}
    for name, args in {'budget': ('spec', 'budget', '--paths', 'src/app.py', '--json'),
                       'impact': ('spec', 'impact', 'app-rules', '--json')}.items():
        samples = []
        for _ in range(3):
            start = time.perf_counter()
            result = _run(tmp_path, *args)
            samples.append(time.perf_counter() - start)
            assert result.returncode in ((0, 3) if name == 'budget' else (0,)), result.stdout + result.stderr
            data = json.loads(result.stdout)
            if name == 'impact':
                assert data['scanned_files'] == 1000 and not data['truncated'] and not data['errors']
        measurements[name] = samples
    print(json.dumps({'platform': platform.platform(), 'python': platform.python_version(),
                      'node': subprocess.check_output(['node', '--version'], text=True).strip(),
                      'specs': 100, 'tasks': 1000, 'seconds': measurements}))
    assert all(sample < 2 for samples in measurements.values() for sample in samples), measurements
