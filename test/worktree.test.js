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
  assert.equal(git(root, ['status', '--porcelain']), '');
  const cleaned = worktree.cleanup(root, 'run-conflict', true);
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
  const resumed = await worktree.prepare(root, options);
  assert.equal(resumed.resumed, true);
  assert.equal(resumed.worktrees[0].status, 'prepared');
  ledger = worktree.readLedger(root, 'run-resume');
  assert.equal(ledger.status, 'running');
  assert.ok(ledger.worktrees[0].init_changes.some(item => item.path === '.agents/skills/cf-check/SKILL.md'));
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
