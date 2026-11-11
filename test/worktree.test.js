'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const h = require('./helpers');
const init = require('../lib/init');
const locks = require('../lib/locks');
const f = require('../lib/fs');
const task = require('../lib/task');
const worktree = require('../lib/worktree');
const cli = path.resolve(__dirname, '../bin/code-flow.js');

function git(root, args) {
  const result = spawnSync('git', args, { cwd: root, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  return result.stdout.trim();
}

function repo(t, items = [{ id: 'TASK-001' }, { id: 'TASK-002' }]) {
  const root = h.project(t);
  h.write(root, '.gitignore', '.code-flow/worktrees/\n');
  h.spec(root);
  const file = h.tasks(root, items);
  git(root, ['init', '-q']);
  git(root, ['config', 'core.autocrlf', 'false']);
  git(root, ['config', 'user.name', 'Fixture']);
  git(root, ['config', 'user.email', 'fixture@example.invalid']);
  git(root, ['add', '-A']);
  git(root, ['commit', '-qm', 'baseline']);
  return { root, file };
}

async function finishWorker(root, file, taskId, changes = {}) {
  await task.start(root, file, taskId);
  for (const [relative, text] of Object.entries(changes)) h.write(root, relative, text);
  const result = await task.finish(root, file, taskId);
  assert.equal(result.ok, true);
  git(root, ['add', '-A']);
  git(root, ['commit', '-qm', 'cf-task(' + taskId + ')']);
  return result;
}

const countParts = {
  id: 'parts', argv: [process.execPath, '-e',
    'const fs=require("fs");process.exit(fs.existsSync("parts")&&fs.readdirSync("parts").length===1?0:1)']
};

test('prepare creates baseline worktrees, collect/merge/cleanup completes the batch', async t => {
  const { root, file } = repo(t);
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001', 'TASK-002'],
    runId: 'run-1', noInit: true });
  assert.equal(prepared.ok, true);
  assert.equal(prepared.worktrees.length, 2);
  assert.deepEqual(prepared.worktrees.map(item => item.env.CF_TASK_ID), ['TASK-001', 'TASK-002']);
  assert.ok(fs.existsSync(path.join(root, '.code-flow/worktrees/run-1/TASK-001')));
  assert.ok(fs.existsSync(path.join(root, '.code-flow/worktrees/run-1/TASK-002')));
  const workerOne = path.join(root, prepared.worktrees[0].path);
  const workerTwo = path.join(root, prepared.worktrees[1].path);
  await finishWorker(workerOne, file, 'TASK-001');
  await finishWorker(workerTwo, file, 'TASK-002');
  assert.equal(locks.directory(workerOne), locks.directory(root));
  const held = f.acquireIn(locks.directory(root), 'repository');
  assert.throws(() => worktree.collect(root, 'run-1'), /Resource lock is held/);
  const cross = spawnSync(process.execPath, ['-e',
    'require(' + JSON.stringify(path.resolve(__dirname, '../lib/worktree')) + ').collect(' +
    JSON.stringify(root) + ', "run-1")'], { cwd: root, encoding: 'utf8' });
  assert.equal(cross.status, 1);
  assert.match(cross.stderr, /Resource lock is held/);
  f.releaseLock(held);
  const collected = worktree.collect(root, 'run-1');
  assert.equal(collected.ok, true);
  assert.ok(collected.worktrees.every(item => item.status === 'collected'));
  const merged = await worktree.merge(root, 'run-1');
  assert.equal(merged.ok, true);
  assert.equal(merged.integration.status, 'passed');
  assert.equal(merged.integration.deduped, 1);
  assert.equal(merged.integration.env.CF_TASK_IDS, 'TASK-001,TASK-002');
  assert.equal(merged.integration.env.CF_WORKTREE_ID, 'run-1/integration');
  assert.deepEqual(merged.integration.commands.map(item => item.task).sort(), ['TASK-001', 'TASK-002']);
  assert.equal(merged.integration.commands.filter(item => item.duplicate).length, 1);
  assert.deepEqual(task.loadDocument(root, file).tasks.map(item => item.status), ['done', 'done']);
  await assert.rejects(task.archive(root, path.posix.dirname(file)), /Unfinished worktree run/);
  await assert.rejects(task.learn(root, file, 'TASK-001', true), /Unfinished worktree run/);
  const cleaned = worktree.cleanup(root, 'run-1');
  assert.equal(cleaned.ok, true);
  assert.equal(fs.existsSync(path.join(root, '.code-flow/worktrees/run-1/TASK-001')), false);
});

test('prepare rejects dirty business code and collect rejects unfinished workers', async t => {
  const { root, file } = repo(t);
  await assert.rejects(worktree.prepare(root, { taskFile: file, tasks: ['TASK-001', 'TASK-001'],
    runId: 'run-duplicate', noInit: true }), /duplicates/);
  h.write(root, 'src/business.js', 'dirty\n');
  await assert.rejects(worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-dirty', noInit: true }), /Uncommitted changes/);
  fs.rmSync(path.join(root, 'src/business.js'));
  await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'], runId: 'run-2', noInit: true });
  assert.throws(() => worktree.collect(root, 'run-2'), /not done|no commit/);
});

test('prepare rejects a worker with an incomplete ignored Specs snapshot', async t => {
  const root = h.project(t, { always: ['private/rules'] });
  h.write(root, '.gitignore', '.code-flow/worktrees/\n.code-flow/specs/private/\n');
  h.spec(root, 'private/rules', 'Private rule.');
  const file = h.tasks(root, [{ id: 'TASK-001' }]);
  git(root, ['init', '-q']);
  git(root, ['config', 'core.autocrlf', 'false']);
  git(root, ['config', 'user.name', 'Fixture']);
  git(root, ['config', 'user.email', 'fixture@example.invalid']);
  git(root, ['add', '-A']);
  git(root, ['commit', '-qm', 'baseline']);
  await assert.rejects(worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-specs', noInit: true }), /Specs snapshot differs|specs_incomplete/);
  const ledger = worktree.readLedger(root, 'run-specs');
  assert.equal(ledger.status, 'blocked');
  assert.equal(ledger.worktrees[0].status, 'created');
});

test('prepare rejects user content added to a mixed managed file during retry', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  await init.init(root, { platform: 'codex' });
  h.write(root, '.agents/skills/cf-check/SKILL.md', 'unmanaged\n');
  git(root, ['add', '-A']);
  git(root, ['commit', '-qm', 'tools']);
  const options = { taskFile: file, tasks: ['TASK-001'], runId: 'run-mixed' };
  await assert.rejects(worktree.prepare(root, options), /unmanaged/);
  const ledger = worktree.readLedger(root, 'run-mixed');
  const worker = path.join(root, ledger.worktrees[0].path);
  fs.rmSync(path.join(worker, '.agents/skills/cf-check/SKILL.md'));
  h.write(worker, 'AGENTS.md',
    '<!-- code-flow:v1 start -->\nold managed block\n<!-- code-flow:v1 end -->\n\nUser note must stay.\n');
  await assert.rejects(worktree.prepare(root, options), /init_user_content|user content/);
  assert.ok(fs.readFileSync(path.join(worker, 'AGENTS.md'), 'utf8').includes('User note must stay.'));
});

test('prepare rejects user content in an untracked mixed managed file', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  h.write(root, '.gitignore', '.code-flow/worktrees/\nAGENTS.md\n');
  git(root, ['add', '.gitignore']);
  git(root, ['commit', '-qm', 'ignore agents']);
  await init.init(root, { platform: 'codex' });
  h.write(root, '.agents/skills/cf-check/SKILL.md', 'unmanaged\n');
  git(root, ['add', '-A']);
  git(root, ['commit', '-qm', 'unmanaged skill']);
  const options = { taskFile: file, tasks: ['TASK-001'], runId: 'run-untracked' };
  await assert.rejects(worktree.prepare(root, options), /unmanaged/);
  const ledger = worktree.readLedger(root, 'run-untracked');
  const worker = path.join(root, ledger.worktrees[0].path);
  fs.rmSync(path.join(worker, '.agents/skills/cf-check/SKILL.md'));
  h.write(worker, 'AGENTS.md', '<!-- code-flow:v1 start -->\nold\n<!-- code-flow:v1 end -->\n\nUntracked user note.\n');
  await assert.rejects(worktree.prepare(root, options), /init_user_content|user content/);
  assert.ok(fs.readFileSync(path.join(worker, 'AGENTS.md'), 'utf8').includes('Untracked user note.'));
  h.write(worker, 'AGENTS.md', '<!-- code-flow:v1 start -->\nold\n<!-- code-flow:v1 end -->\n');
  const resumed = await worktree.prepare(root, options);
  assert.equal(resumed.resumed, true);
});

test('prepare rejects user content in Codex hooks managed settings', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  h.write(root, '.codex/hooks.json', JSON.stringify({ hooks: {
    SessionStart: [{ hooks: [{ type: 'command', command: 'echo user-session' }] }]
  } }));
  git(root, ['add', '.codex/hooks.json']);
  git(root, ['commit', '-qm', 'user codex hook']);
  await init.init(root, { platform: 'codex' });
  h.write(root, '.agents/skills/cf-check/SKILL.md', 'unmanaged\n');
  git(root, ['add', '.agents/skills/cf-check/SKILL.md']);
  git(root, ['commit', '-qm', 'unmanaged skill']);
  const options = { taskFile: file, tasks: ['TASK-001'], runId: 'run-codex-hooks' };
  await assert.rejects(worktree.prepare(root, options), /unmanaged/);
  const ledger = worktree.readLedger(root, 'run-codex-hooks');
  const worker = path.join(root, ledger.worktrees[0].path);
  fs.rmSync(path.join(worker, '.agents/skills/cf-check/SKILL.md'));
  const hooksFile = path.join(worker, '.codex/hooks.json');
  const hooks = JSON.parse(fs.readFileSync(hooksFile, 'utf8'));
  hooks.hooks.UserPromptSubmit = hooks.hooks.UserPromptSubmit || [];
  hooks.hooks.Stop = [{ hooks: [{ type: 'command', command: 'echo keep-me' }] }];
  fs.writeFileSync(hooksFile, JSON.stringify(hooks, null, 2));
  await assert.rejects(worktree.prepare(root, options), /init_user_content|user content/);
  assert.match(fs.readFileSync(hooksFile, 'utf8'), /echo keep-me/);
});

test('prepare rejects user content in Codex config managed settings', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  h.write(root, '.codex/config.toml', 'model = "user-choice"\n');
  git(root, ['add', '.codex/config.toml']);
  git(root, ['commit', '-qm', 'user codex config']);
  await init.init(root, { platform: 'codex' });
  h.write(root, '.agents/skills/cf-check/SKILL.md', 'unmanaged\n');
  git(root, ['add', '.agents/skills/cf-check/SKILL.md']);
  git(root, ['commit', '-qm', 'unmanaged skill']);
  const options = { taskFile: file, tasks: ['TASK-001'], runId: 'run-codex-config' };
  await assert.rejects(worktree.prepare(root, options), /unmanaged/);
  const ledger = worktree.readLedger(root, 'run-codex-config');
  const worker = path.join(root, ledger.worktrees[0].path);
  fs.rmSync(path.join(worker, '.agents/skills/cf-check/SKILL.md'));
  fs.appendFileSync(path.join(worker, '.codex/config.toml'),
    '[mcp_servers."fixture]one".env]\nhooks = "user-value"\n');
  await assert.rejects(worktree.prepare(root, options), /init_user_content|user content/);
  const configFile = path.join(worker, '.codex/config.toml');
  assert.match(fs.readFileSync(configFile, 'utf8'), /user-value/);
  fs.writeFileSync(configFile, fs.readFileSync(configFile, 'utf8')
    .replace('[mcp_servers."fixture]one".env]\nhooks = "user-value"\n', ''));
  const resumed = await worktree.prepare(root, options);
  assert.equal(resumed.resumed, true);
});

test('prepare tolerates CRLF checkout with autocrlf enabled', async t => {
  const root = h.project(t);
  h.write(root, '.gitignore', '.code-flow/worktrees/\n');
  h.spec(root);
  const file = h.task(root);
  h.write(root, 'AGENTS.md', 'User note\r\n');
  git(root, ['init', '-q']);
  git(root, ['config', 'core.autocrlf', 'true']);
  git(root, ['config', 'user.name', 'Fixture']);
  git(root, ['config', 'user.email', 'fixture@example.invalid']);
  git(root, ['add', '-A']);
  git(root, ['commit', '-qm', 'baseline']);
  await init.init(root, { platform: 'codex' });
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-autocrlf' });
  assert.equal(prepared.ok, true);
  worktree.cleanup(root, 'run-autocrlf', true);
});

test('prepare commits a staged rename inside the current requirement', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  const directory = path.posix.dirname(file);
  h.write(root, directory + '/before.txt', 'before\n');
  git(root, ['add', '-A']);
  git(root, ['commit', '-qm', 'add requirement file']);
  git(root, ['mv', directory + '/before.txt', directory + '/after.txt']);
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-legal-rename', noInit: true });
  assert.equal(prepared.ok, true);
  assert.equal(fs.existsSync(path.join(root, directory, 'after.txt')), true);
});

test('prepare rejects staged renames whose source is outside baseline', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  h.write(root, 'README.md', 'readme\n');
  git(root, ['add', 'README.md']);
  git(root, ['commit', '-qm', 'add readme']);
  git(root, ['mv', 'README.md', '.code-flow/tasks/2026-11-10/demo/README.md']);
  await assert.rejects(worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-rename', noInit: true }), /Staged changes outside baseline/);
});

test('prepare rejects unrelated staged files instead of committing them', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  h.write(root, '.agents/user-notes.txt', 'keep\n');
  git(root, ['add', '.agents/user-notes.txt']);
  await assert.rejects(worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-staged', noInit: true }), /Staged changes outside baseline/);
  assert.equal(git(root, ['status', '--porcelain']), 'A  .agents/user-notes.txt');
  assert.equal(fs.readFileSync(path.join(root, '.agents/user-notes.txt'), 'utf8'), 'keep\n');
});

test('integration reruns the merged batch, blocks on failure and retries merged workers', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001', tests: [countParts] },
    { id: 'TASK-002', tests: [countParts] }]);
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001', 'TASK-002'],
    runId: 'run-integration', noInit: true });
  const workerOne = path.join(root, prepared.worktrees[0].path);
  const workerTwo = path.join(root, prepared.worktrees[1].path);
  await finishWorker(workerOne, file, 'TASK-001', { 'parts/one.txt': 'one\n' });
  await finishWorker(workerTwo, file, 'TASK-002', { 'parts/two.txt': 'two\n' });
  worktree.collect(root, 'run-integration');
  await assert.rejects(worktree.merge(root, 'run-integration'), /integration tests failed/);
  let ledger = worktree.readLedger(root, 'run-integration');
  assert.equal(ledger.status, 'blocked');
  assert.equal(ledger.integration.status, 'failed');
  assert.equal(ledger.integration.commands.length, 2);
  assert.ok(ledger.integration.commands.some(item => item.status === 'fail'));
  assert.ok(fs.existsSync(workerOne) && fs.existsSync(workerTwo));
  assert.throws(() => worktree.cleanup(root, 'run-integration'), /not ready|Integration/);
  fs.rmSync(path.join(root, 'parts/two.txt'));
  git(root, ['add', '-A']);
  git(root, ['commit', '-qm', 'integration fix']);
  const retried = await worktree.merge(root, 'run-integration');
  assert.equal(retried.integration.status, 'passed');
  ledger = worktree.readLedger(root, 'run-integration');
  assert.equal(ledger.merge.steps.length, 2);
  assert.equal(worktree.cleanup(root, 'run-integration').ok, true);
});

test('code conflicts stop the batch and keep every worktree and branch', async t => {
  const { root, file } = repo(t);
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001', 'TASK-002'],
    runId: 'run-conflict', noInit: true });
  const workerOne = path.join(root, prepared.worktrees[0].path);
  const workerTwo = path.join(root, prepared.worktrees[1].path);
  await finishWorker(workerOne, file, 'TASK-001', { 'shared.txt': 'one\n' });
  await finishWorker(workerTwo, file, 'TASK-002', { 'shared.txt': 'two\n' });
  worktree.collect(root, 'run-conflict');
  await assert.rejects(worktree.merge(root, 'run-conflict'), /Code conflict: .*shared\.txt/);
  const ledger = worktree.readLedger(root, 'run-conflict');
  assert.equal(ledger.status, 'blocked');
  assert.deepEqual(ledger.merge.conflicts, [file, 'shared.txt']);
  assert.ok(fs.existsSync(workerOne) && fs.existsSync(workerTwo));
  assert.equal(spawnSync('git', ['rev-parse', '-q', '--verify', 'MERGE_HEAD'],
    { cwd: root }).status, 0);
  assert.deepEqual(git(root, ['diff', '--name-only', '--diff-filter=U']).split('\n').sort(),
    [file, 'shared.txt'].sort());
  const cleaned = worktree.cleanup(root, 'run-conflict', true);
  spawnSync('git', ['merge', '--abort'], { cwd: root });
  assert.equal(cleaned.ok, true);
  assert.equal(cleaned.steps.some(item => item.abandoned), true);
  assert.equal(fs.existsSync(workerOne), false);
});

test('auto-init installs detected platforms and rejects committed tool files', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  await init.init(root, { platform: 'codex' });
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'], runId: 'run-init' });
  assert.deepEqual(prepared.worktrees[0].init_changes.length > 0, true);
  assert.ok(prepared.worktrees[0].init_changes.some(item => item.path.startsWith('.codex/')));
  const worker = path.join(root, prepared.worktrees[0].path);
  await task.start(worker, file, 'TASK-001');
  await task.finish(worker, file, 'TASK-001');
  git(worker, ['add', '--', file]);
  git(worker, ['commit', '-qm', 'task only']);
  assert.equal(worktree.collect(root, 'run-init').ok, true);
  assert.equal((await worktree.merge(root, 'run-init')).integration.status, 'passed');
  assert.equal(worktree.cleanup(root, 'run-init').ok, true);
});

test('collect rejects a worker that committed platform init output', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  await init.init(root, { platform: 'codex' });
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'], runId: 'run-init-commit' });
  const worker = path.join(root, prepared.worktrees[0].path);
  await finishWorker(worker, file, 'TASK-001');
  assert.throws(() => worktree.collect(root, 'run-init-commit'), /shared paths|committed managed tool files/);
});

test('prepare records init intent before partial writes and resumes after a write failure', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  await init.init(root, { platform: 'codex' });
  const options = { taskFile: file, tasks: ['TASK-001'], runId: 'run-partial-init' };
  const original = f.atomicWrite;
  let calls = 0;
  f.atomicWrite = (...args) => {
    if (++calls === 2) throw new Error('simulated write failure');
    return original(...args);
  };
  try { await assert.rejects(worktree.prepare(root, options), /simulated write failure/); }
  finally { f.atomicWrite = original; }
  let ledger = worktree.readLedger(root, 'run-partial-init');
  assert.equal(ledger.status, 'blocked');
  assert.ok(ledger.worktrees[0].init_changes.length > 0);
  const resumed = await worktree.prepare(root, options);
  assert.equal(resumed.resumed, true);
  assert.equal(resumed.worktrees[0].status, 'prepared');
  ledger = worktree.readLedger(root, 'run-partial-init');
  assert.equal(ledger.status, 'running');
});

test('prepare resumes a partially initialized run after init failure', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  await init.init(root, { platform: 'codex' });
  h.write(root, '.agents/skills/cf-check/SKILL.md', 'unmanaged\n');
  git(root, ['add', '-A']);
  git(root, ['commit', '-qm', 'tools']);
  const options = { taskFile: file, tasks: ['TASK-001'], runId: 'run-resume' };
  await assert.rejects(worktree.prepare(root, options), /unmanaged/);
  let ledger = worktree.readLedger(root, 'run-resume');
  assert.equal(ledger.status, 'blocked');
  assert.equal(ledger.worktrees[0].status, 'created');
  const worker = path.join(root, ledger.worktrees[0].path);
  assert.ok(fs.existsSync(worker));
  fs.rmSync(path.join(worker, '.agents/skills/cf-check/SKILL.md'));
  h.write(worker, 'src/user.js', 'preserve me\n');
  await assert.rejects(worktree.prepare(root, options), /dirty_worktree|changed before dispatch|uncommitted changes/);
  assert.ok(fs.existsSync(path.join(worker, 'src/user.js')));
  fs.rmSync(path.join(worker, 'src/user.js'));
  const resumed = await worktree.prepare(root, options);
  assert.equal(resumed.resumed, true);
  assert.equal(resumed.worktrees[0].status, 'prepared');
  ledger = worktree.readLedger(root, 'run-resume');
  assert.equal(ledger.status, 'running');
  assert.ok(ledger.worktrees[0].init_changes.some(item => item.path === '.agents/skills/cf-check/SKILL.md'));
  assert.ok(!ledger.worktrees[0].init_changes.some(item => item.path === 'src/user.js'));
});

test('merge recovers a commit whose ledger step was not recorded', async t => {
  const { root, file } = repo(t);
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001', 'TASK-002'],
    runId: 'run-recover', noInit: true });
  await finishWorker(path.join(root, prepared.worktrees[0].path), file, 'TASK-001');
  await finishWorker(path.join(root, prepared.worktrees[1].path), file, 'TASK-002');
  worktree.collect(root, 'run-recover');
  await worktree.merge(root, 'run-recover');
  let ledger = worktree.readLedger(root, 'run-recover');
  const steps = ledger.merge.steps.slice();
  assert.equal(steps.length, 2);
  ledger.status = 'merging';
  ledger.worktrees.forEach(worker => { worker.status = 'collected'; });
  ledger.merge.steps = [];
  ledger.operation = { kind: 'merge', task: 'TASK-001', expected_head: steps[0].before_head,
    collected_head: steps[0].collected_head, target: null };
  fs.writeFileSync(path.join(root, '.code-flow/worktrees/run-recover/run.json'),
    JSON.stringify(ledger, null, 2) + '\n');
  const recovered = await worktree.merge(root, 'run-recover');
  ledger = worktree.readLedger(root, 'run-recover');
  assert.deepEqual(ledger.merge.steps.map(item => item.status), ['recovered', 'recovered']);
  assert.deepEqual(ledger.merge.steps.map(item => item.after_head), steps.map(item => item.after_head));
  assert.equal(recovered.integration.status, 'passed');
  assert.equal(worktree.cleanup(root, 'run-recover').ok, true);
});

test('collect audits the full branch diff and rechecks HEAD before merge', async t => {
  const { root, file } = repo(t);
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-scope', noInit: true });
  const worker = path.join(root, prepared.worktrees[0].path);
  await finishWorker(worker, file, 'TASK-001');
  fs.appendFileSync(path.join(worker, '.code-flow/specs/cli/runtime.md'), '\n<!-- changed -->\n');
  git(worker, ['add', '-A']);
  git(worker, ['commit', '-qm', 'spec change']);
  assert.throws(() => worktree.collect(root, 'run-scope'), /shared paths: .*\.code-flow\/specs/);
  git(worker, ['reset', '--hard', '-q', 'HEAD~1']);
  await task.start(worker, file, 'TASK-002');
  git(worker, ['add', '-A']);
  git(worker, ['commit', '-qm', 'other task change']);
  assert.throws(() => worktree.collect(root, 'run-scope'), /changed another TASK: TASK-002/);
  git(worker, ['reset', '--hard', '-q', 'HEAD~1']);
  h.write(worker, 'src/feature.js', 'feature\n');
  git(worker, ['add', '-A']);
  git(worker, ['commit', '-qm', 'business']);
  assert.equal(worktree.collect(root, 'run-scope').ok, true);
  h.write(worker, 'src/late.js', 'late\n');
  git(worker, ['add', '-A']);
  git(worker, ['commit', '-qm', 'late']);
  await assert.rejects(worktree.merge(root, 'run-scope'), /moved after collect/);
  const before = worktree.readLedger(root, 'run-scope').worktrees[0].collected_head;
  const recollected = worktree.collect(root, 'run-scope');
  assert.notEqual(recollected.worktrees[0].collected_head, before);
  assert.equal((await worktree.merge(root, 'run-scope')).integration.status, 'passed');
  worktree.cleanup(root, 'run-scope');
});

test('cleanup resumes after a partially removed worktree', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-cleanup', noInit: true });
  const worker = path.join(root, prepared.worktrees[0].path);
  await finishWorker(worker, file, 'TASK-001');
  worktree.collect(root, 'run-cleanup');
  await worktree.merge(root, 'run-cleanup');
  git(root, ['worktree', 'remove', '--force', worker]);
  assert.equal(fs.existsSync(worker), false);
  const cleaned = worktree.cleanup(root, 'run-cleanup');
  assert.equal(cleaned.ok, true);
  assert.equal(spawnSync('git', ['rev-parse', '--verify', 'refs/heads/' + prepared.worktrees[0].branch],
    { cwd: root }).status !== 0, true);
  assert.equal(worktree.readLedger(root, 'run-cleanup').status, 'done');
});

test('cleanup protects user changes and force records the abandonment', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-cleanup-dirty', noInit: true });
  const worker = path.join(root, prepared.worktrees[0].path);
  await finishWorker(worker, file, 'TASK-001');
  worktree.collect(root, 'run-cleanup-dirty');
  await worktree.merge(root, 'run-cleanup-dirty');
  h.write(root, 'late.txt', 'unverified\n');
  assert.throws(() => worktree.cleanup(root, 'run-cleanup-dirty'), /unverified changes: late\.txt/);
  fs.rmSync(path.join(root, 'late.txt'));
  h.write(worker, 'user.txt', 'keep\n');
  assert.throws(() => worktree.cleanup(root, 'run-cleanup-dirty'), /user changes: user\.txt/);
  assert.ok(fs.existsSync(path.join(worker, 'user.txt')));
  const cleaned = worktree.cleanup(root, 'run-cleanup-dirty', true);
  assert.equal(cleaned.ok, true);
  assert.equal(cleaned.steps[0].abandoned, false);
  assert.equal(fs.existsSync(worker), false);
});

test('worktree run records Delta and archive applies it in the coordinator', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001', spec_delta: [
    { id: 'D1', op: 'add', target: 'cli/runtime', rule: 'Worktree rule.', evidence: 'worktree' }
  ] }]);
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-delta', noInit: true });
  const worker = path.join(root, prepared.worktrees[0].path);
  await finishWorker(worker, file, 'TASK-001');
  worktree.collect(root, 'run-delta');
  await worktree.merge(root, 'run-delta');
  worktree.cleanup(root, 'run-delta');
  const archived = await task.archive(root, path.posix.dirname(file));
  assert.equal(archived.ok, true);
  assert.match(fs.readFileSync(path.join(root, '.code-flow/specs/cli/runtime.md'), 'utf8'), /Worktree rule\./);
  assert.ok(archived.archived_to.includes(path.join('.code-flow', 'tasks', 'archived', '')));
  assert.ok(fs.existsSync(archived.archived_to));
});

test('internal task parallel CLI prepares, reports and force-cleans a run', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  const run = args => spawnSync(process.execPath, [cli, 'task', 'parallel', ...args, '--json'],
    { cwd: root, encoding: 'utf8' });
  const prepared = run(['prepare', '--task-file', file, '--tasks', 'TASK-001',
    '--run-id', 'cli-run', '--no-init']);
  assert.equal(prepared.status, 0, prepared.stderr);
  assert.equal(JSON.parse(prepared.stdout).run_id, 'cli-run');
  assert.equal(JSON.parse(prepared.stdout).workers, 2);
  const ledger = worktree.readLedger(root, 'cli-run');
  assert.equal(ledger.workers, 2);
  assert.equal(ledger.jobs, 2);
  assert.equal(ledger.operation, null);
  const status = run(['status', '--run-id', 'cli-run']);
  assert.equal(status.status, 0, status.stderr);
  assert.equal(JSON.parse(status.stdout).status, 'running');
  const cleaned = run(['cleanup', '--run-id', 'cli-run', '--force']);
  assert.equal(cleaned.status, 0, cleaned.stderr);
  assert.equal(JSON.parse(cleaned.stdout).steps[0].status, 'removed');
  assert.equal(fs.existsSync(path.join(root, '.code-flow/worktrees/cli-run/TASK-001')), false);
});

test('prepare refuses a TASK claimed by another unfinished run', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'], runId: 'run-claimed-a', noInit: true });
  await assert.rejects(worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-claimed-b', noInit: true }), /already claimed/);
  worktree.cleanup(root, 'run-claimed-a', true);
  const second = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-claimed-b', noInit: true });
  assert.equal(second.run_id, 'run-claimed-b');
});

test('worker finish injects the ledger environment into declared tests', async t => {
  const envTest = { id: 'env', argv: [process.execPath, '-e',
    'process.stdout.write(JSON.stringify([process.env.CF_WORKTREE_ID,process.env.CF_TASK_ID,process.env.CF_RUN_ID]))'] };
  const { root, file } = repo(t, [{ id: 'TASK-001', tests: [envTest] }]);
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-env', noInit: true });
  const worker = path.join(root, prepared.worktrees[0].path);
  const result = await finishWorker(worker, file, 'TASK-001');
  assert.deepEqual(JSON.parse(result.results[0].stdout), ['run-env/TASK-001', 'TASK-001', 'run-env']);
});

test('merge reports a three-way conflict when the coordinator changes the same TASK', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }, { id: 'TASK-002' }]);
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-reopen', noInit: true });
  const worker = path.join(root, prepared.worktrees[0].path);
  await finishWorker(worker, file, 'TASK-001');
  worktree.collect(root, 'run-reopen');
  await task.start(root, file, 'TASK-001');
  git(root, ['add', '--', file]);
  git(root, ['commit', '-qm', 'coordinator reopen']);
  await assert.rejects(worktree.merge(root, 'run-reopen'), /Both sides changed TASK-001/);
  const ledger = worktree.readLedger(root, 'run-reopen');
  assert.equal(ledger.status, 'blocked');
  assert.equal(spawnSync('git', ['rev-parse', '-q', '--verify', 'MERGE_HEAD'],
    { cwd: root }).status, 0);
  assert.ok(fs.existsSync(worker));
  spawnSync('git', ['merge', '--abort'], { cwd: root });
  assert.equal(worktree.cleanup(root, 'run-reopen', true).ok, true);
});

test('force cleanup still verifies ledger ownership and worker branch', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-own', noInit: true });
  const worker = path.join(root, prepared.worktrees[0].path);
  git(worker, ['checkout', '-q', '-b', 'intruder']);
  assert.throws(() => worktree.cleanup(root, 'run-own', true), /worktree branch changed/);
  git(worker, ['checkout', '-q', prepared.worktrees[0].branch]);
  const ledger = worktree.readLedger(root, 'run-own');
  ledger.worktrees[0].branch = 'refs/heads/main';
  fs.writeFileSync(path.join(root, '.code-flow/worktrees/run-own/run.json'),
    JSON.stringify(ledger, null, 2) + '\n');
  assert.throws(() => worktree.cleanup(root, 'run-own', true), /owned by run|run_invalid|invalid worker resource/);
});

test('worktree operations reject a changed coordinator branch', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-branch', noInit: true });
  const main = git(root, ['symbolic-ref', '--short', 'HEAD']);
  await finishWorker(path.join(root, prepared.worktrees[0].path), file, 'TASK-001');
  git(root, ['checkout', '-q', '-b', 'other']);
  assert.throws(() => worktree.collect(root, 'run-branch'), /Coordinator branch changed/);
  git(root, ['checkout', '-q', main]);
  assert.equal(worktree.collect(root, 'run-branch').ok, true);
  git(root, ['checkout', '-q', 'other']);
  await assert.rejects(worktree.merge(root, 'run-branch'), /Coordinator branch changed/);
  git(root, ['checkout', '-q', main]);
  assert.equal((await worktree.merge(root, 'run-branch')).integration.status, 'passed');
  git(root, ['checkout', '-q', 'other']);
  assert.throws(() => worktree.cleanup(root, 'run-branch', true), /Coordinator branch changed/);
  git(root, ['checkout', '-q', main]);
  assert.equal(worktree.cleanup(root, 'run-branch').ok, true);
});

test('collect rejects non-ASCII paths outside the owned requirement', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-cn-scope', noInit: true });
  const worker = path.join(root, prepared.worktrees[0].path);
  await finishWorker(worker, file, 'TASK-001');
  git(worker, ['config', 'core.quotePath', 'true']);
  h.write(worker, '.code-flow/tasks/2026-11-10/其他需求/其他需求.md', '# other requirement\n');
  git(worker, ['add', '-A']);
  git(worker, ['commit', '-qm', 'touch other requirement']);
  assert.throws(() => worktree.collect(root, 'run-cn-scope'), /shared paths: .*其他需求/);
});

test('worker finish rejects a damaged run ledger instead of dropping isolation env', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-ledger', noInit: true });
  const worker = path.join(root, prepared.worktrees[0].path);
  await task.start(worker, file, 'TASK-001');
  fs.writeFileSync(path.join(root, '.code-flow/worktrees/run-ledger/run.json'), '{broken');
  await assert.rejects(task.finish(worker, file, 'TASK-001'), /run_invalid|Invalid run ledger/);
  assert.equal(task.load(worker, file).meta.status, 'in-progress');
});

test('worker finish rejects ledger env that is complete enough to parse but invalid', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-env-invalid', noInit: true });
  const worker = path.join(root, prepared.worktrees[0].path);
  await task.start(worker, file, 'TASK-001');
  const ledger = worktree.readLedger(root, 'run-env-invalid');
  ledger.worktrees[0].env = { CF_WORKTREE_ID: 'wrong', CF_TASK_ID: '', CF_RUN_ID: '' };
  fs.writeFileSync(path.join(root, '.code-flow/worktrees/run-env-invalid/run.json'),
    JSON.stringify(ledger, null, 2) + '\n');
  await assert.rejects(task.finish(worker, file, 'TASK-001'), /run_invalid|Invalid worker environment/);
  assert.equal(task.load(worker, file).meta.status, 'in-progress');
});

test('worker and moved worker worktrees cannot archive or learn Specs', async t => {
  const { root, file } = repo(t, [{ id: 'TASK-001' }]);
  const requirementDir = path.posix.dirname(file);
  const prepared = await worktree.prepare(root, { taskFile: file, tasks: ['TASK-001'],
    runId: 'run-worker', noInit: true });
  const worker = path.join(root, prepared.worktrees[0].path);
  await assert.rejects(task.archive(worker, requirementDir), /coordinator worktree/);
  await assert.rejects(task.learn(worker, file, 'TASK-001', true), /coordinator worktree/);
  const moved = path.join(root, 'moved-worker');
  fs.renameSync(worker, moved);
  await assert.rejects(task.archive(moved, requirementDir), /coordinator worktree/);
  await assert.rejects(task.learn(moved, file, 'TASK-001'), /coordinator worktree/);
});
