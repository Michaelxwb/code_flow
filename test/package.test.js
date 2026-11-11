'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const h = require('./helpers');
const ROOT = path.resolve(__dirname, '..');
function npm(args, cwd, options = {}) {
  const entry = process.env.npm_execpath || path.resolve(path.dirname(process.execPath),
    process.platform === 'win32' ? 'node_modules/npm/bin/npm-cli.js' : '../lib/node_modules/npm/bin/npm-cli.js');
  const result = spawnSync(process.execPath, [entry, ...args], { cwd, encoding: 'utf8', timeout: 60000,
    env: { ...process.env, npm_config_offline: 'true', npm_config_update_notifier: 'false' }, ...options });
  assert.equal(result.status, 0, result.stderr || result.error?.message);
  return result.stdout;
}
test('tarball contains only v1 and installs globally into an isolated prefix', t => {
  const temporary = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'cf-package-')));
  t.after(() => fs.rmSync(temporary, { recursive: true, force: true }));
  const packed = JSON.parse(npm(['pack', '--ignore-scripts', '--json', '--pack-destination', temporary], ROOT))[0];
  const files = packed.files.map(item => item.path);
  assert.ok(files.includes('bin/code-flow.js') && files.includes('lib/learn.js'));
  assert.ok(files.includes('templates/adapters/opencode.mjs'));
  assert.ok(files.includes('templates/launcher/bridge.cjs'));
  assert.ok(files.includes('templates/workflow/scenarios.md'));
  assert.ok(!files.some(file => file.endsWith('.py') || file.startsWith('src/') ||
    file.includes('migrat') || file.includes('legacy') || file.startsWith('.code-flow/')));
  assert.deepEqual(require('../package.json').dependencies, {});
  const prefix = path.join(temporary, 'global');
  npm(['install', '--global', '--prefix', prefix, '--ignore-scripts', '--no-audit', '--no-fund',
    path.join(temporary, packed.filename)], ROOT);
  const globalRoot = npm(['root', '--global', '--prefix', prefix], ROOT).trim();
  const entry = path.join(globalRoot, '@michaelxwb/code-flow/bin/code-flow.js');
  assert.ok(fs.existsSync(entry));
  const project = h.project(t); h.spec(project); const task = h.task(project);
  const version = spawnSync(process.execPath, [entry, '--version'], { encoding: 'utf8' });
  assert.equal(version.stdout.trim(), '1.0.0');
  const initialized = spawnSync(process.execPath, [entry, 'init', '--platform=codex', '--json'],
    { cwd: project, encoding: 'utf8' });
  assert.equal(initialized.status, 0, initialized.stderr);
  const hooks = JSON.parse(fs.readFileSync(path.join(project, '.codex/hooks.json'), 'utf8')).hooks;
  assert.deepEqual(Object.keys(hooks), ['UserPromptSubmit']);
  const command = hooks.UserPromptSubmit[0].hooks[0].command;
  assert.ok(command.includes(process.platform === 'win32' ? 'hook.ps1' : '.code-flow/launcher/hook.sh'),
    'Hook must use the project launcher');
  assert.ok(fs.existsSync(path.join(project, '.code-flow/launcher/bridge.cjs')));
  if (process.platform !== 'win32') {
    const output = spawnSync('/bin/sh', ['-c', command], { cwd: project, encoding: 'utf8',
      input: JSON.stringify({ cwd: project, session_id: 'installed', prompt: 'task: ' + task + '#TASK-001' }) });
    assert.equal(output.status, 0, output.stderr);
    assert.ok(JSON.parse(output.stdout).hookSpecificOutput.additionalContext.includes('Current rule.'));
  }
  assert.equal(fs.existsSync(path.join(project, '.code-flow/scripts')), false);
});
test('real git worktree runs without project dependencies or installation metadata', t => {
  const root = h.project(t); h.spec(root); const task = h.task(root);
  const git = args => {
    const result = spawnSync('git', args, { cwd: root, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr); return result;
  };
  git(['init', '-q']); git(['add', '.']);
  git(['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture']);
  const worktree = path.join(root, 'linked-worktree');
  git(['worktree', 'add', '--detach', worktree, 'HEAD']);
  t.after(() => {
    const result = spawnSync('git', ['worktree', 'remove', '--force', worktree], { cwd: root, encoding: 'utf8' });
    if (result.status !== 0 && fs.existsSync(worktree)) throw new Error(result.stderr);
  });
  const entry = path.join(ROOT, 'bin/code-flow.js');
  const input = JSON.stringify({ cwd: worktree, session_id: 'tree', prompt: 'task: ' + task + '#TASK-001' });
  const result = spawnSync(process.execPath, [entry, 'hook', 'prompt', '--format=codex'],
    { cwd: worktree, input, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  assert.ok(JSON.parse(result.stdout).hookSpecificOutput.additionalContext.includes('Current rule.'));
  assert.equal(fs.existsSync(path.join(worktree, 'node_modules')), false);
  assert.equal(fs.existsSync(path.join(worktree, '.code-flow/.runtime-install.json')), false);
});
