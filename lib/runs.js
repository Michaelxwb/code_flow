'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const f = require('./fs');
const repo = require('./repo');

const UNFINISHED = new Set(['preparing', 'running', 'merging', 'verifying', 'cleaning', 'blocked']);
const STATUSES = new Set([...UNFINISHED, 'done', 'aborted']);
const WORKTREES = '.code-flow/worktrees';

function list(root) {
  const base = path.join(root, WORKTREES);
  if (!fs.existsSync(base)) return [];
  const runs = [];
  for (const entry of fs.readdirSync(base, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const file = path.join(base, entry.name, 'run.json');
    if (!fs.existsSync(file)) continue;
    try {
      const ledger = JSON.parse(fs.readFileSync(file, 'utf8'));
      const valid = ledger && typeof ledger === 'object' && ledger.run_id === entry.name &&
        STATUSES.has(ledger.status) && Array.isArray(ledger.worktrees) &&
        ledger.merge && Array.isArray(ledger.merge.order) &&
        ledger.worktrees.every(worker => worker && /^TASK-\d+$/.test(worker.task) &&
          worker.path === WORKTREES + '/' + entry.name + '/' + worker.task &&
          worker.branch === 'cf-task/' + entry.name + '/' + worker.task) &&
        JSON.stringify(ledger.worktrees.map(worker => worker.task).sort()) ===
          JSON.stringify([...ledger.merge.order].sort());
      runs.push(valid
        ? { run_id: ledger.run_id || entry.name, status: ledger.status,
          task_file: ledger.task_file || null, file: path.join(WORKTREES, entry.name, 'run.json'), ledger }
        : { run_id: entry.name, status: 'invalid', task_file: null,
          file: path.join(WORKTREES, entry.name, 'run.json'), error: 'Invalid ledger schema' });
    } catch (error) {
      runs.push({ run_id: entry.name, status: 'invalid', task_file: null,
        file: path.join(WORKTREES, entry.name, 'run.json'), error: error.message });
    }
  }
  return runs;
}

function unfinished(root, filter = () => true) {
  return list(root).filter(run => (UNFINISHED.has(run.status) || run.status === 'invalid') && filter(run));
}

function assertArchiveAllowed(root, requirementDir) {
  const normalized = requirementDir.replace(/\\/g, '/').replace(/\/$/, '');
  const blocked = unfinished(root, run => !run.task_file ||
    run.task_file === normalized || run.task_file.startsWith(normalized + '/'));
  f.demand(!blocked.length, 'run_incomplete',
    'Unfinished worktree run for requirement: ' + blocked.map(run => run.run_id).join(', '), 1);
}

function assertLearnAllowed(root) {
  const blocked = unfinished(root);
  f.demand(!blocked.length, 'run_incomplete',
    'Unfinished worktree run before Spec learning: ' + blocked.map(run => run.run_id).join(', '), 1);
}

function workerEnv(root) {
  const current = fs.realpathSync(root);
  const identity = repo.identity(current);
  if (!identity.git || !identity.linked) return {};
  const result = spawnSync('git', ['worktree', 'list', '--porcelain'],
    { cwd: current, encoding: 'utf8', maxBuffer: 1024 * 1024 });
  f.demand(result.status === 0, 'git_identity',
    'Cannot read Git worktree registration: ' + (result.stderr || '').trim(), 2);
  const main = result.stdout.split('\n').find(line => line.startsWith('worktree '));
  f.demand(main, 'git_identity', 'Cannot locate coordinator worktree', 2);
  const coordinator = fs.realpathSync(main.slice(9));
  const base = path.join(coordinator, WORKTREES);
  if (!fs.existsSync(base)) return {};
  let found = null;
  for (const entry of fs.readdirSync(base, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const file = path.join(base, entry.name, 'run.json');
    if (!fs.existsSync(file)) continue;
    let ledger;
    try { ledger = JSON.parse(fs.readFileSync(file, 'utf8')); } catch (_) { continue; }
    if (!ledger || !Array.isArray(ledger.worktrees)) continue;
    for (const worker of ledger.worktrees) {
      if (!worker.env || typeof worker.path !== 'string') continue;
      if (worker.path !== WORKTREES + '/' + entry.name + '/' + worker.task) continue;
      let workerRoot;
      try { workerRoot = fs.realpathSync(path.join(coordinator, worker.path)); } catch (_) { continue; }
      if (workerRoot !== current) continue;
      f.demand(!found, 'env_conflict', 'Worktree is claimed by multiple run ledgers', 1);
      found = { ...worker.env };
    }
  }
  return found ?? {};
}

module.exports = { list, unfinished, assertArchiveAllowed, assertLearnAllowed, workerEnv, UNFINISHED };
