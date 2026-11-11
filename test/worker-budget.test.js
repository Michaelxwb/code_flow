'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const h = require('./helpers');
const worktree = require('../lib/worktree');

function git(root, args) {
  const result = spawnSync('git', args, { cwd: root, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  return result.stdout.trim();
}

function repo(t) {
  const root = h.project(t);
  h.write(root, '.gitignore', '.code-flow/worktrees/\n');
  h.spec(root);
  git(root, ['init', '-q']);
  git(root, ['config', 'core.autocrlf', 'false']);
  git(root, ['config', 'user.name', 'Fixture']);
  git(root, ['config', 'user.email', 'fixture@example.invalid']);
  return root;
}

function workerScript() {
  return [
    "const fs=require('fs');",
    "const {execFileSync}=require('child_process');",
    "const task=require(" + JSON.stringify(path.resolve(__dirname, '../lib/task')) + ");",
    "const [root,file,id,log]=process.argv.slice(1);",
    "const mark=phase=>fs.appendFileSync(log,JSON.stringify({task:id,phase,time:Date.now()})+'\\n');",
    "mark('worker-start');",
    "(async()=>{await task.start(root,file,id);const result=await task.finish(root,file,id);",
    "if(!result.ok)throw new Error('finish failed');execFileSync('git',['add','-A'],{cwd:root});",
    "execFileSync('git',['commit','-qm','worker '+id],{cwd:root});mark('worker-end');})().catch(error=>{",
    "console.error(error.stack||error.message);process.exit(1);});"
  ].join('');
}

function launch(root, file, id, log) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, ['-e', workerScript(), root, file, id, log],
      { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
    let stderr = '';
    child.stderr.on('data', chunk => { stderr += chunk; });
    child.once('error', reject);
    child.once('close', code => code === 0 ? resolve() : reject(new Error(stderr || 'worker failed')));
  });
}

async function dispatch(workers, limit) {
  const queue = [...workers], active = new Set();
  let peak = 0;
  while (queue.length || active.size) {
    while (queue.length && active.size < limit) {
      const worker = queue.shift();
      const job = worker.run().finally(() => active.delete(job));
      active.add(job); peak = Math.max(peak, active.size);
    }
    if (active.size) await Promise.race(active);
  }
  return peak;
}

function peakLog(log) {
  const events = fs.readFileSync(log, 'utf8').trim().split('\n').filter(Boolean)
    .map(line => JSON.parse(line)).sort((left, right) => left.time - right.time || left.phase.localeCompare(right.phase));
  let active = 0, peak = 0;
  for (const event of events) {
    if (event.phase === 'worker-start') peak = Math.max(peak, ++active);
    else if (event.phase === 'worker-end') active--;
  }
  return { peak, events };
}

test('CI worker budget simulation dispatches at most ledger.workers', async t => {
  const root = repo(t);
  const log = path.join(os.tmpdir(), 'cf-worker-budget-' + process.pid + '-' + Date.now() + '.log');
  t.after(() => fs.rmSync(log, { force: true }));
  const testCase = { id: 'env', argv: [process.execPath, '-e',
    'if(process.env.CF_TASK_ID)require("fs").appendFileSync(process.env.CF_BUDGET_LOG,' +
    'JSON.stringify({task:process.env.CF_TASK_ID,run:process.env.CF_RUN_ID,phase:"test"})+"\\n")'],
  env: { CF_BUDGET_LOG: log } };
  const file = h.tasks(root, [{ id: 'TASK-001', tests: [testCase] },
    { id: 'TASK-002', tests: [testCase] }, { id: 'TASK-003', tests: [testCase] }]);
  git(root, ['add', '-A']);
  git(root, ['commit', '-qm', 'baseline']);
  const prepared = await worktree.prepare(root, { taskFile: file,
    tasks: ['TASK-001', 'TASK-002', 'TASK-003'], runId: 'run-budget',
    workers: 2, noInit: true });
  assert.equal(prepared.workers, 2);
  assert.equal(prepared.jobs, 2);
  const ledger = worktree.readLedger(root, 'run-budget');
  const workers = ledger.worktrees.map(worker => ({ task: worker.task,
    run: () => launch(path.join(root, worker.path), file, worker.task, log) }));
  const peak = await dispatch(workers, ledger.workers);
  assert.equal(peak, 2);
  const observed = peakLog(log);
  assert.equal(observed.peak, 2);
  for (const id of ['TASK-001', 'TASK-002', 'TASK-003']) {
    const event = observed.events.find(item => item.task === id && item.phase === 'test');
    assert.ok(event, id);
    assert.equal(event.run, 'run-budget');
    assert.ok(observed.events.some(item => item.task === id && item.phase === 'worker-end'), id);
  }
  worktree.collect(root, 'run-budget');
  const merged = await worktree.merge(root, 'run-budget');
  assert.equal(merged.integration.status, 'passed');
  assert.equal(worktree.cleanup(root, 'run-budget').ok, true);
});
