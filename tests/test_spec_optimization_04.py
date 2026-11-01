"""Read-only spec impact through the real CLI and Git project."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'src/core/code-flow/scripts'
sys.path.insert(0, str(SCRIPTS))


def _run(root: Path, *args: str, payload: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['node', str(ROOT / 'src/cli.js'), *args], cwd=root, text=True,
                          input=json.dumps(payload) if payload is not None else None,
                          capture_output=True, timeout=30)


def _project(root: Path) -> Path:
    init = _run(root, 'init', '--platform=codex')
    assert init.returncode == 0, init.stdout + init.stderr
    config_path = root / '.code-flow/config.yml'
    config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    config['path_mapping']['app'] = {'patterns': ['src/*.py'], 'specs': [{'path': 'app/rules.md'}]}
    config_path.write_text(yaml.safe_dump(config), encoding='utf-8')
    spec = root / '.code-flow/specs/app/rules.md'
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text('---\nid: app-rules\ndescription: app rules\nstages: [design, code]\nenforcement: required\n'
                    'verifiers:\n  - rule: RULE-app-001\n    type: regex\n'
                    '    config: {pattern: forbidden, files: "src/*.py"}\n---\n'
                    '# Rules\n## Rules\n- [RULE-app-001] Preserve correctness.\n', encoding='utf-8')
    task = root / '.code-flow/tasks/2026-01-01/demo'
    task.mkdir(parents=True)
    (task / 'demo.md').write_text('# Tasks\n\n## TASK-001: App\n- **Status**: in-progress\n'
                                 '- **Spec-Refs**: app-rules#RULE-app-001\n', encoding='utf-8')
    result = _run(root, 'spec', 'bind', '--task-dir', str(task), '--root', str(root), '--stage', 'design', '--json',
                  payload={'task': 'demo', 'paths': ['src/app.py'], 'selections': [
                      {'spec_id': 'app-rules', 'selected_by': 'path', 'reason': 'fixture'}], 'applications': []})
    assert result.returncode == 0, result.stdout + result.stderr
    for args in (('init', '-q'), ('config', 'user.name', 'Test'), ('config', 'user.email', 'test@example.invalid'),
                 ('add', '-A'), ('commit', '-qm', 'fixture')):
        subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)
    return task


def _snapshot(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (root / '.code-flow/tasks').rglob('*') if path.is_file()}


def test_s_06(tmp_path: Path) -> None:
    _project(tmp_path)
    before = _snapshot(tmp_path)
    result = _run(tmp_path, 'spec', 'impact', 'app-rules', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['truncated'] is False and report['errors'] == []
    assert any(row.get('rule_ref') == 'app-rules#RULE-app-001' and row.get('task_id') == 'TASK-001'
               and row.get('status') == 'in-progress' for row in report['references'])
    assert any(row.get('rule_ref') == 'app-rules#RULE-app-001' and row.get('context_path', '').endswith('spec-context.yml')
               and row.get('rule_status') == 'pending' for row in report['references'])
    assert _snapshot(tmp_path) == before
    path_result = _run(tmp_path, 'spec', 'impact', 'app/rules.md', '--json')
    assert path_result.returncode == 0 and json.loads(path_result.stdout)['references'] == report['references']


def test_b_03(tmp_path: Path) -> None:
    _project(tmp_path)
    result = _run(tmp_path, 'spec', 'impact', 'app-rules', '--max-files', '1', '--json')
    report = json.loads(result.stdout)
    assert report['truncated'] is True and report['scanned_files'] == 1
    assert result.returncode != 0


def test_impact_does_not_hide_unreadable_context_or_depth_limit(tmp_path: Path) -> None:
    task = _project(tmp_path)
    (task / 'spec-context.yml').write_text('broken: [', encoding='utf-8')
    result = _run(tmp_path, 'spec', 'impact', 'app-rules', '--json')
    report = json.loads(result.stdout)
    assert result.returncode != 0 and report['errors']
    limited = _run(tmp_path, 'spec', 'impact', 'app-rules', '--max-depth', '1', '--json')
    assert limited.returncode != 0 and json.loads(limited.stdout)['truncated'] is True


def test_impact_unknown_spec_has_explicit_error_and_human_report(tmp_path: Path) -> None:
    _project(tmp_path)
    missing = _run(tmp_path, 'spec', 'impact', 'not-a-real-spec', '--json')
    assert missing.returncode != 0 and json.loads(missing.stdout)['error']['code'] == 'spec_not_found'
    human = _run(tmp_path, 'spec', 'impact', 'app-rules')
    assert human.returncode == 0 and 'TASK-001' in human.stdout and 'spec refresh' in human.stdout
