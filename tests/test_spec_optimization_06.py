"""Protected optimization uses a real CLI, filesystem and transaction journal."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'src/core/code-flow/scripts'
sys.path.insert(0, str(SCRIPTS))
from codeflow.spec.cf_spec_metadata import load_spec_metadata


def _run(root: Path, *args: str, payload: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['node', str(ROOT / 'src/cli.js'), *args], cwd=root, text=True,
                          input=json.dumps(payload) if payload is not None else '',
                          capture_output=True, timeout=30,
                          env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})


def _project(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    init = _run(root, 'init', '--platform=codex')
    assert init.returncode == 0, init.stdout + init.stderr
    config_path = root / '.code-flow/config.yml'
    config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    config['path_mapping']['app'] = {'patterns': ['src/*.py'], 'specs': [{'path': 'app/rules.md'}]}
    config_path.write_text(yaml.safe_dump(config), encoding='utf-8')
    source = root / '.code-flow/specs/app/rules.md'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('---\nid: app-rules\ndescription: app rules\nstages: [design, code]\nenforcement: required\n'
                      'verifiers:\n  - rule: RULE-app-001\n    type: regex\n'
                      '    config: {pattern: forbidden, files: "src/*.py"}\n---\n'
                      '# App\n## Rules\n- [RULE-app-001] Preserve correctness.\n'
                      '## Conventions\n- Prefer explicit names.\n## Guidance\nKeep guidance.\n', encoding='utf-8')
    for args in (('init', '-q'), ('config', 'user.name', 'Test'), ('config', 'user.email', 'test@example.invalid'),
                 ('add', '-A'), ('commit', '-qm', 'fixture')):
        subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)
    return source, root / '.code-flow/specs/app/conventions.md'


def _proposal(root: Path) -> tuple[dict, Path]:
    result = _run(root, 'spec', 'optimize', '--dry-run', '--paths', 'app/rules.md',
                  '--target', 'app/conventions.md', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    path = root / 'proposal.json'
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return data, path


def _apply_tty(root: Path, proposal: Path) -> subprocess.CompletedProcess[str]:
    master, slave = os.openpty()
    try:
        process = subprocess.Popen(['node', str(ROOT / 'src/cli.js'), 'spec', 'optimize', '--apply',
                                    '--plan', str(proposal), '--json'], cwd=root, stdin=slave,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        os.close(slave)
        slave = -1
        os.write(master, b'y\n')
        stdout, stderr = process.communicate(timeout=30)
        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)
    finally:
        os.close(master)
        if slave != -1:
            os.close(slave)


def _rule_signature(path: Path) -> tuple:
    metadata = load_spec_metadata(str(path))
    return ([(r.ref, r.text_sha256) for r in metadata.rules if r.ref.startswith('RULE-')],
            [(v.rule, v.type, v.stage, v.config) for v in metadata.verifiers])


def test_s_07(tmp_path: Path) -> None:
    source, target = _project(tmp_path)
    before = _rule_signature(source)
    proposal, plan = _proposal(tmp_path)
    assert proposal['operations'] and proposal['mapping_diff']
    assert proposal['mapping_diff'][0]['source_patterns'] == proposal['specs'][0]['patterns']
    assert 'target_patterns' in proposal['mapping_diff'][0]
    assert '-## Conventions' in proposal['operations'][0]['source_diff']
    assert '+- Prefer explicit names.' in proposal['operations'][0]['target_diff']
    config = (tmp_path / '.code-flow/config.yml').read_bytes()
    result = _apply_tty(tmp_path, plan)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['decision'] == 'pass'
    assert _rule_signature(source) == before
    assert 'Prefer explicit names.' not in source.read_text() and 'Prefer explicit names.' in target.read_text()
    assert load_spec_metadata(str(target)).stages == load_spec_metadata(str(source)).stages
    assert (tmp_path / '.code-flow/config.yml').read_bytes() == config


def test_e_06(tmp_path: Path) -> None:
    source, target = _project(tmp_path)
    proposal, _ = _proposal(tmp_path)
    proposal['specs'][0]['rule_ids'] = ['RULE-app-999']
    unsigned = {key: value for key, value in proposal.items() if key != 'proposal_id'}
    proposal['proposal_id'] = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    before = source.read_bytes()
    from codeflow.spec.cf_spec_optimize_apply import apply_proposal
    with pytest.raises(ValueError, match='proposal|rule|guard'):
        apply_proposal(str(tmp_path), proposal, confirmed=True)
    assert source.read_bytes() == before and not target.exists()


def test_e_07(tmp_path: Path) -> None:
    source, target = _project(tmp_path)
    before = source.read_bytes()
    result = _run(tmp_path, 'spec', 'optimize', '--dry-run', '--paths', 'app/rules.md',
                  '--target', 'missing/conventions.md', '--json')
    assert result.returncode != 0 and 'target' in result.stdout.lower()
    assert source.read_bytes() == before and not target.exists()


def test_e_09(tmp_path: Path) -> None:
    source, target = _project(tmp_path)
    _, plan = _proposal(tmp_path)
    source.write_text(source.read_text() + '\nchanged after preview\n', encoding='utf-8')
    after = source.read_bytes()
    result = _apply_tty(tmp_path, plan)
    assert result.returncode != 0 and source.read_bytes() == after and not target.exists()
    assert 'stale' in result.stdout.lower() or 'drift' in result.stdout.lower()


def test_e_10(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, target = _project(tmp_path)
    proposal, _ = _proposal(tmp_path)
    before = source.read_bytes()
    from codeflow.spec import cf_spec_optimize_apply
    original = cf_spec_optimize_apply.commit_replace
    calls = 0
    def fail_second(src: Path, dest: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('injected failure')
        original(src, dest)
    monkeypatch.setattr(cf_spec_optimize_apply, 'commit_replace', fail_second)
    with pytest.raises(OSError, match='injected failure'):
        cf_spec_optimize_apply.apply_proposal(str(tmp_path), proposal, confirmed=True)
    assert source.read_bytes() == before and not target.exists()


def test_apply_rejects_inflight_context_and_preserves_all_files(tmp_path: Path) -> None:
    source, target = _project(tmp_path)
    task = tmp_path / '.code-flow/tasks/2026-01-01/demo'
    task.mkdir(parents=True)
    doc = task / 'demo.md'
    doc.write_text('# Tasks\n\n## TASK-001: Work\n- **Status**: in-progress\n'
                   '- **Spec-Refs**: app-rules#RULE-app-001\n', encoding='utf-8')
    result = _run(tmp_path, 'spec', 'bind', '--task-dir', str(task), '--root', str(tmp_path), '--stage', 'code', '--json',
                  payload={'task': 'demo', 'paths': ['src/app.py'], 'selections': [
                      {'spec_id': 'app-rules', 'selected_by': 'path', 'reason': 'fixture'}], 'applications': []})
    assert result.returncode == 0, result.stdout + result.stderr
    proposal, plan = _proposal(tmp_path)
    assert proposal['affected_contexts'] and proposal['affected_file_hashes']
    before = (source.read_bytes(), doc.read_bytes(), (task / 'spec-context.yml').read_bytes())
    applied = _apply_tty(tmp_path, plan)
    assert applied.returncode != 0 and 'inflight_context' in applied.stdout
    assert before == (source.read_bytes(), doc.read_bytes(), (task / 'spec-context.yml').read_bytes())
    assert not target.exists()


def test_apply_requires_terminal_and_rejects_symlink_target(tmp_path: Path) -> None:
    source, target = _project(tmp_path)
    before = source.read_bytes()
    _, plan = _proposal(tmp_path)
    result = _run(tmp_path, 'spec', 'optimize', '--apply', '--plan', str(plan), '--json')
    assert result.returncode != 0 and 'terminal' in result.stdout
    assert source.read_bytes() == before and not target.exists()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (source.parent / 'link').symlink_to(outside, target_is_directory=True)
    rejected = _run(tmp_path, 'spec', 'optimize', '--dry-run', '--paths', 'app/rules.md',
                    '--target', 'app/link/conventions.md', '--json')
    assert rejected.returncode != 0 and 'symlinks' in rejected.stdout
    assert not (outside / 'conventions.md').exists()


def test_apply_preserves_target_created_concurrently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, target = _project(tmp_path)
    proposal, _ = _proposal(tmp_path)
    before = source.read_bytes()
    from codeflow.spec import cf_spec_optimize_apply
    original = cf_spec_optimize_apply.commit_replace
    calls = 0
    def competing_writer(staged: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            destination.write_text('user data', encoding='utf-8')
        original(staged, destination)
    monkeypatch.setattr(cf_spec_optimize_apply, 'commit_replace', competing_writer)
    with pytest.raises(FileExistsError):
        cf_spec_optimize_apply.apply_proposal(str(tmp_path), proposal, confirmed=True)
    assert source.read_bytes() == before and target.read_text(encoding='utf-8') == 'user data'


def test_apply_rejects_unfinished_transaction_without_deleting_it(tmp_path: Path) -> None:
    source, target = _project(tmp_path)
    proposal, _ = _proposal(tmp_path)
    original = source.read_bytes()
    pending = tmp_path / '.code-flow/specs/.optimize-transactions/unfinished'
    pending.mkdir(parents=True)
    journal = pending / 'journal.json'
    journal.write_text('{"state":"committing"}', encoding='utf-8')
    from codeflow.spec.cf_spec_optimize_apply import apply_proposal
    with pytest.raises(ValueError, match='recovery_required'):
        apply_proposal(str(tmp_path), proposal, confirmed=True)
    assert journal.is_file() and source.read_bytes() == original and not target.exists()


def test_apply_preserves_source_changed_during_transaction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, target = _project(tmp_path)
    proposal, _ = _proposal(tmp_path)
    from codeflow.spec import cf_spec_optimize_apply
    original = cf_spec_optimize_apply._journal
    calls = 0
    def competing_writer(directory: Path, state: dict) -> None:
        nonlocal calls
        original(directory, state)
        calls += 1
        if calls == 2:
            source.write_text('external change', encoding='utf-8')
    monkeypatch.setattr(cf_spec_optimize_apply, '_journal', competing_writer)
    with pytest.raises(ValueError, match='recovery_required'):
        cf_spec_optimize_apply.apply_proposal(str(tmp_path), proposal, confirmed=True)
    assert source.read_text(encoding='utf-8') == 'external change' and not target.exists()
    assert list((tmp_path / '.code-flow/specs/.optimize-transactions').glob('*/journal.json'))


def test_interrupted_application_keeps_recoverable_backup_and_refuses_retry(tmp_path: Path) -> None:
    source, target = _project(tmp_path)
    proposal, plan = _proposal(tmp_path)
    before = source.read_bytes()
    script = (
        "import json, os, sys\n"
        "from codeflow.spec import cf_spec_optimize_apply as module\n"
        "original = module.commit_replace\n"
        "calls = [0]\n"
        "def interrupted(src, dst):\n"
        "    calls[0] += 1\n"
        "    if calls[0] == 2: os._exit(73)\n"
        "    original(src, dst)\n"
        "module.commit_replace = interrupted\n"
        "module.apply_proposal(sys.argv[1], json.load(open(sys.argv[2])), confirmed=True)\n"
    )
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path), str(plan)], cwd=tmp_path,
                            env={**os.environ, 'PYTHONPATH': str(SCRIPTS)}, timeout=30)
    assert result.returncode == 73 and not target.exists()
    transaction = tmp_path / '.code-flow/specs/.optimize-transactions' / proposal['proposal_id']
    assert (transaction / 'source.backup').read_bytes() == before
    assert json.loads((transaction / 'journal.json').read_text(encoding='utf-8'))['state'] == 'committing'
    from codeflow.spec.cf_spec_optimize_apply import apply_proposal
    with pytest.raises(ValueError, match='recovery_required'):
        apply_proposal(str(tmp_path), proposal, confirmed=True)
