'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const f = require('./fs');
const config = require('./config');
const taskdoc = require('./taskdoc');
const task = require('./task');
const init = require('./init');

const WORKTREES = '.code-flow/worktrees';
const TOOL_PREFIXES = ['.code-flow/templates/', '.code-flow/launcher/', '.claude/', '.codex/',
  '.costrict/', '.opencode/', '.agents/'];
const TOOL_FILES = ['AGENTS.md', 'CLAUDE.md', 'opencode.json'];

function git(root, args, raw = false) {
  const result = spawnSync('git', args, { cwd: root, encoding: 'utf8', maxBuffer: 4 * 1024 * 1024 });
  if (result.error || result.status !== 0) {
    throw new f.FlowError('git_error', (result.stderr || result.error?.message || 'git failed').trim(), 1);
  }
  return raw ? result.stdout : result.stdout.trim();
}

function statusEntries(root) {
  const raw = git(root, ['status', '--porcelain=v1', '-z', '--untracked-files=all'], true);
  const entries = [], parts = raw.split('\0');
  for (let index = 0; index < parts.length; index++) {
    const entry = parts[index];
    if (!entry) continue;
    const code = entry.slice(0, 2), relative = entry.slice(3);
    entries.push({ code, path: relative });
    if (code[0] === 'R' || code[0] === 'C') index++;
  }
  return entries;
}

function hashFile(file) {
  return fs.existsSync(file) && fs.statSync(file).isFile()
    ? crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex') : null;
}

function commitContent(worktree, relative) {
  const result = spawnSync('git', ['show', 'HEAD:' + relative], { cwd: worktree, maxBuffer: 8 * 1024 * 1024 });
  return result.status === 0 ? crypto.createHash('sha256').update(result.stdout).digest('hex') : null;
}

function isTool(relative) {
  return TOOL_FILES.includes(relative) || TOOL_PREFIXES.some(prefix => relative.startsWith(prefix));
}

function isRequirement(relative, requirementDir) {
  return relative === requirementDir || relative.startsWith(requirementDir + '/');
}

function baselinePaths(entries, requirementDir) {
  const allowed = [], tool = [], other = [];
  for (const entry of entries) {
    if (entry.path.startsWith('.code-flow/specs/') || entry.path === '.code-flow/config.json' ||
        isRequirement(entry.path, requirementDir)) allowed.push(entry.path);
    else if (isTool(entry.path)) tool.push(entry.path);
    else other.push(entry.path);
  }
  if (other.length) throw new f.FlowError('dirty_tree',
    'Uncommitted changes outside .code-flow docs: ' + other.slice(0, 8).join(', '), 1);
  return { allowed, tool };
}

function commitBaseline(root, requirementDir, runId) {
  const before = git(root, ['rev-parse', 'HEAD']);
  const entries = statusEntries(root);
  const { allowed } = baselinePaths(entries, requirementDir);
  if (!allowed.length) return before;
  git(root, ['add', '--', ...allowed]);
  git(root, ['commit', '-q', '-m', 'code-flow: baseline ' + runId]);
  return git(root, ['rev-parse', 'HEAD']);
}

function specsHash(root) {
  const base = path.join(root, '.code-flow/specs');
  const digest = crypto.createHash('sha256');
  const walk = directory => fs.readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))
    .flatMap(entry => entry.isDirectory() ? walk(path.join(directory, entry.name))
      : entry.isFile() ? [path.join(directory, entry.name)] : []);
  for (const file of walk(base)) {
    const relative = path.relative(base, file).split(path.sep).join('/');
    digest.update(relative + '\0'); digest.update(fs.readFileSync(file)); digest.update('\0');
  }
  return digest.digest('hex');
}

function ledgerPath(root, runId) { return path.join(root, WORKTREES, runId, 'run.json'); }

function readLedger(root, runId) {
  const raw = f.readText(ledgerPath(root, runId), 1024 * 1024);
  f.demand(raw !== null, 'run_not_found', 'Missing worktree run: ' + runId, 2);
  let ledger;
  try { ledger = JSON.parse(raw); } catch (error) {
    throw new f.FlowError('run_invalid', 'Invalid run ledger: ' + error.message, 2);
  }
  f.demand(ledger && ledger.run_id === runId && /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(ledger.run_id),
    'run_invalid', 'Run ledger identity does not match: ' + runId, 2);
  f.demand(Array.isArray(ledger.worktrees) && ledger.merge && Array.isArray(ledger.merge.order),
    'run_invalid', 'Run ledger has no worktree/merge list', 2);
  for (const worker of ledger.worktrees) {
    f.demand(worker && /^TASK-\d+$/.test(worker.task) &&
      worker.path === worktreePath(runId, worker.task) &&
      worker.branch === branchName(runId, worker.task), 'run_invalid',
      'Run ledger owns an invalid worker resource: ' + String(worker?.task), 2);
  }
  const tasks = ledger.worktrees.map(worker => worker.task).sort();
  f.demand(JSON.stringify(tasks) === JSON.stringify([...ledger.merge.order].sort()),
    'run_invalid', 'Run ledger merge order does not match worktrees', 2);
  return ledger;
}

function writeLedger(root, ledger) {
  const file = ledgerPath(root, ledger.run_id);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temporary = file + '.tmp';
  fs.writeFileSync(temporary, JSON.stringify(ledger, null, 2) + '\n');
  fs.renameSync(temporary, file);
}

function ensureRunId(value) {
  f.demand(typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(value),
    'invalid_run_id', 'Invalid run id', 2);
  return value;
}

function worktreePath(runId, taskId) { return WORKTREES + '/' + runId + '/' + taskId; }
function branchName(runId, taskId) { return 'cf-task/' + runId + '/' + taskId; }

function selectedTasks(document, taskIds) {
  f.demand(Array.isArray(taskIds) && taskIds.length > 0, 'tasks_required', 'Select at least one TASK', 2);
  f.demand(new Set(taskIds).size === taskIds.length, 'tasks_duplicate', 'TASK list contains duplicates', 2);
  const byId = new Map(document.tasks.map(item => [item.id, item]));
  const selected = taskIds.map(id => {
    f.demand(byId.has(id), 'unknown_task', 'Unknown TASK: ' + id, 2);
    return byId.get(id);
  });
  const first = taskdoc.batches(document.tasks)[0] || [];
  const notReady = selected.filter(item => !first.includes(item.id)).map(item => item.id);
  f.demand(!notReady.length, 'task_not_ready', 'Not in current dependency batch: ' + notReady.join(', '), 1);
  return selected;
}

async function initWorktree(worktree, platforms) {
  const changes = new Map();
  for (const platform of platforms) {
    await init.init(worktree, { platform });
    for (const entry of statusEntries(worktree)) {
      if (changes.has(entry.path)) continue;
      changes.set(entry.path, { path: entry.path, status: entry.code, tracked: false,
        before_sha256: commitContent(worktree, entry.path),
        after_sha256: hashFile(path.join(worktree, entry.path)) });
    }
  }
  for (const change of changes.values()) change.tracked = change.before_sha256 !== null;
  return [...changes.values()];
}

function integrationEnv(runId, order) {
  return { CF_WORKTREE_ID: runId + '/integration', CF_TASK_ID: '',
    CF_TASK_IDS: order.join(','), CF_RUN_ID: runId };
}

function integrationPlan(tasks, order) {
  const byId = new Map(tasks.map(item => [item.id, item]));
  const tests = [], sources = [], skipped = [];
  for (const id of order) {
    const item = byId.get(id);
    f.demand(item, 'task_missing', 'Missing TASK in document: ' + id, 1);
    if (!item.tests.length) {
      if (item.skipTests) skipped.push({ task: id, reason: item.skipReason });
      continue;
    }
    for (const test of item.tests) {
      const scoped = id + ':' + test.id;
      tests.push({ ...test, id: scoped });
      sources.push({ id: scoped, task: id, test: test.id });
    }
  }
  return { tests, sources, skipped, sourceById: new Map(sources.map(item => [item.id, item])) };
}

function assertInitState(worktree, worker) {
  for (const change of worker.init_changes) {
    f.demand(hashFile(path.join(worktree, change.path)) === change.after_sha256,
      'init_changed', worker.task + ' changed managed tool file: ' + change.path, 1);
  }
  const committed = git(worktree, ['diff', '--name-only', worker.base_head + '..HEAD'])
    .split('\n').filter(Boolean);
  const tool = committed.filter(relative => isTool(relative) ||
    worker.init_changes.some(item => item.path === relative));
  f.demand(!tool.length, 'init_committed',
    worker.task + ' committed managed tool files: ' + tool.slice(0, 8).join(', '), 1);
}

function taskAt(root, revision, taskFile) {
  return taskdoc.parse(git(root, ['show', revision + ':' + taskFile], true), path.join(root, taskFile));
}

function assertScope(root, ledger, worker, head) {
  f.demand(spawnSync('git', ['merge-base', '--is-ancestor', worker.base_head, head],
    { cwd: root }).status === 0, 'worktree_scope_violation',
    worker.task + ' branch is not based on baseline', 1);
  const requirementDir = path.posix.dirname(ledger.task_file);
  const paths = git(root, ['diff', '--name-only', worker.base_head + '..' + head])
    .split('\n').filter(Boolean);
  const illegal = paths.filter(relative => {
    if (relative === ledger.task_file) return false;
    if (isTool(relative)) return true;
    if (relative.startsWith('.code-flow/')) return true;
    if (relative === requirementDir || relative.startsWith(requirementDir + '/')) return true;
    return false;
  });
  f.demand(!illegal.length, 'worktree_scope_violation',
    worker.task + ' changed shared paths: ' + illegal.slice(0, 8).join(', '), 1);
  const base = taskAt(root, worker.base_head, ledger.task_file);
  const current = taskAt(root, head, ledger.task_file);
  f.demand(JSON.stringify(base.meta) === JSON.stringify(current.meta) &&
    base.preamble === current.preamble, 'worktree_scope_violation',
    worker.task + ' changed shared task-document structure', 1);
  f.demand(base.tasks.map(item => item.id).join(',') === current.tasks.map(item => item.id).join(','),
    'worktree_scope_violation', worker.task + ' changed TASK set or order', 1);
  const baseMap = new Map(base.tasks.map(item => [item.id, item.text]));
  for (const item of current.tasks) {
    if (item.id !== worker.task) f.demand(item.text === baseMap.get(item.id), 'worktree_scope_violation',
      worker.task + ' changed another TASK: ' + item.id, 1);
  }
  const own = current.tasks.find(item => item.id === worker.task);
  f.demand(own && own.status === 'done', 'task_not_done', worker.task + ' is not done', 1);
  f.demand(own.text !== baseMap.get(worker.task), 'no_task_change',
    worker.task + ' has no task-section change', 1);
  return own;
}

function verifyCollected(root, ledger, worker) {
  const worktree = path.join(root, worker.path);
  f.demand(fs.existsSync(worktree), 'worktree_missing', 'Missing worktree: ' + worker.path, 1);
  f.demand(fs.realpathSync(git(worktree, ['rev-parse', '--show-toplevel'])) === fs.realpathSync(worktree),
    'worktree_mismatch', 'Path is not the registered worktree: ' + worker.path, 1);
  f.demand(fs.realpathSync(path.resolve(worktree, git(worktree, ['rev-parse', '--git-common-dir']))) ===
    ledger.coordinator.git_common_dir, 'worktree_mismatch',
    worker.task + ' uses another repository', 1);
  f.demand(git(worktree, ['symbolic-ref', '-q', 'HEAD']) === 'refs/heads/' + worker.branch,
    'worktree_mismatch', worker.task + ' is on the wrong branch', 1);
  const branch = git(root, ['rev-parse', 'refs/heads/' + worker.branch]);
  f.demand(branch === worker.collected_head, 'worker_changed',
    worker.task + ' branch moved after collect', 1);
  f.demand(git(worktree, ['rev-parse', 'HEAD']) === worker.collected_head, 'worker_changed',
    worker.task + ' HEAD moved after collect', 1);
  assertInitState(worktree, worker);
  const managed = new Set(worker.init_changes.map(item => item.path));
  const dirty = statusEntries(worktree).filter(entry => !managed.has(entry.path));
  f.demand(!dirty.length, 'dirty_worktree',
    worker.task + ' has uncommitted changes: ' + dirty.slice(0, 8).map(item => item.path).join(', '), 1);
  const current = taskAt(root, worker.collected_head, ledger.task_file).tasks.find(item => item.id === worker.task);
  f.demand(current && crypto.createHash('sha256').update(current.text).digest('hex') ===
    worker.collected_task_sha256, 'worker_changed', worker.task + ' task section changed after collect', 1);
  return current;
}

async function prepare(root, options) {
  return require('./locks').withRepository(root, () => prepareLocked(root, options));
}

function ensureWorker(root, worker, baseHead) {
  const worktree = path.join(root, worker.path);
  const branchRef = 'refs/heads/' + worker.branch;
  const branch = spawnSync('git', ['rev-parse', '--verify', branchRef], { cwd: root, encoding: 'utf8' });
  if (fs.existsSync(worktree)) {
    f.demand(fs.realpathSync(git(worktree, ['rev-parse', '--show-toplevel'])) === fs.realpathSync(worktree),
      'worktree_mismatch', 'Path is not the registered worktree: ' + worker.path, 1);
    f.demand(git(worktree, ['symbolic-ref', '-q', 'HEAD']) === branchRef,
      'worktree_mismatch', 'Worktree is on the wrong branch: ' + worker.path, 1);
    f.demand(git(worktree, ['rev-parse', 'HEAD']) === baseHead,
      'worktree_changed', 'Worktree has commits beyond baseline: ' + worker.path, 1);
    return;
  }
  if (branch.status === 0) {
    f.demand(branch.stdout.trim() === baseHead, 'branch_changed',
      'Branch moved beyond baseline: ' + worker.branch, 1);
    git(root, ['worktree', 'add', worktree, worker.branch]);
    return;
  }
  git(root, ['worktree', 'add', '-b', worker.branch, worktree, baseHead]);
}

function preflightNewRun(root, runId, taskFile, selected, order) {
  const claimed = require('./runs').unfinished(root, run => run.ledger &&
    run.ledger.task_file === taskFile && Array.isArray(run.ledger.worktrees) &&
    run.ledger.worktrees.some(worker => order.includes(worker.task) && worker.status !== 'removed'));
  f.demand(!claimed.length, 'task_claimed',
    'Task already claimed by unfinished runs: ' + claimed.map(run => run.run_id).join(', '), 1);
  for (const item of selected) {
    f.demand(!fs.existsSync(path.join(root, worktreePath(runId, item.id))), 'worktree_exists',
      'Worktree path already exists: ' + worktreePath(runId, item.id), 1);
    f.demand(spawnSync('git', ['rev-parse', '--verify', 'refs/heads/' + branchName(runId, item.id)],
      { cwd: root }).status !== 0, 'branch_exists', 'Branch already exists: ' + branchName(runId, item.id), 1);
  }
  const repo = fs.realpathSync(git(root, ['rev-parse', '--show-toplevel']));
  f.demand(repo === fs.realpathSync(root), 'not_repository_root', 'Run at the repository root', 1);
  f.demand(git(root, ['rev-parse', '--is-bare-repository']) === 'false',
    'not_repository', 'Bare repositories are not supported', 1);
  f.demand(spawnSync('git', ['check-ignore', '-q', WORKTREES + '/' + runId + '/probe'],
    { cwd: root }).status === 0, 'worktrees_not_ignored', 'Add ' + WORKTREES + '/ to .gitignore', 1);
  const branch = git(root, ['symbolic-ref', '-q', 'HEAD']);
  f.demand(branch.startsWith('refs/heads/'), 'detached_head', 'Coordinator must be on a branch', 1);
  const commonReal = fs.realpathSync(path.resolve(root, git(root, ['rev-parse', '--git-common-dir'])));
  return { requirementDir: path.posix.dirname(taskFile), initialHead: git(root, ['rev-parse', 'HEAD']),
    coordinator: { root: repo, git_common_dir: commonReal, repository_key: f.hash(commonReal), branch } };
}

function buildLedger(runId, taskFile, selected, order, baseline, baseHash, platforms, workers, context) {
  return { version: 1, run_id: runId, task_file: taskFile, base_head: baseline,
    coordinator: { ...context.coordinator, initial_head: context.initialHead, base_head: baseline },
    baseline_specs_sha256: baseHash, platforms, workers,
    jobs: config.load(context.coordinator.root).tests.jobs,
    status: 'preparing', operation: null,
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    worktrees: selected.map(item => ({
      task: item.id, path: worktreePath(runId, item.id), branch: branchName(runId, item.id),
      base_head: baseline, status: 'planned', collected_head: null, collected_task_sha256: null,
      env: { CF_WORKTREE_ID: runId + '/' + item.id, CF_TASK_ID: item.id, CF_RUN_ID: runId },
      init_changes: [], error: null
    })),
    merge: { order, steps: [], conflicts: [] },
    integration: { status: 'not-run', tested_head: null, env: integrationEnv(runId, order),
      commands: [], skipped: [], deduped: 0, elapsed_ms: 0, error: null },
    cleanup: { steps: [], kept: [] } };
}

async function prepareWorkers(root, ledger, platforms) {
  for (const worker of ledger.worktrees) {
    if (worker.status === 'prepared') continue;
    try {
      ensureWorker(root, worker, ledger.base_head);
      worker.status = 'created';
      ledger.updated_at = new Date().toISOString();
      writeLedger(root, ledger);
      worker.init_changes = await initWorktree(path.join(root, worker.path), platforms);
      worker.status = 'prepared';
      worker.error = null;
      ledger.updated_at = new Date().toISOString();
      writeLedger(root, ledger);
    } catch (error) {
      worker.error = error.message;
      ledger.status = 'blocked';
      ledger.updated_at = new Date().toISOString();
      writeLedger(root, ledger);
      throw error;
    }
  }
  ledger.status = 'running';
  ledger.error = null;
  ledger.updated_at = new Date().toISOString();
  writeLedger(root, ledger);
}

async function prepareLocked(root, options) {
  const runId = ensureRunId(options.runId);
  const taskFile = options.taskFile.replace(/\\/g, '/');
  const document = task.loadDocument(root, taskFile);
  const selected = selectedTasks(document, options.tasks);
  const order = selected.map(item => item.id);
  if (fs.existsSync(ledgerPath(root, runId))) {
    return resumePrepare(root, runId, taskFile, order);
  }
  const context = preflightNewRun(root, runId, taskFile, selected, order);
  const cleanDocs = baselinePaths(statusEntries(root), context.requirementDir).allowed;
  if (options.noAutoBaseline) {
    f.demand(!cleanDocs.length, 'baseline_dirty',
      '--no-auto-baseline requires committed .code-flow docs', 1);
  }
  const baseline = options.noAutoBaseline ? context.initialHead :
    commitBaseline(root, context.requirementDir, runId);
  const platforms = options.noInit ? [] : init.installed(root);
  const workers = options.workers ?? 2;
  f.positive(workers, 'workers', true);
  const ledger = buildLedger(runId, taskFile, selected, order, baseline, specsHash(root),
    platforms, workers, context);
  writeLedger(root, ledger);
  await prepareWorkers(root, ledger, platforms);
  return { ok: true, action: 'prepare', run_id: runId, base_head: baseline,
    workers: ledger.workers, jobs: ledger.jobs, worktrees: ledger.worktrees };
}

function assertResumeIdentity(root, ledger, runId, taskFile, order) {
  f.demand(ledger.task_file === taskFile, 'run_mismatch', 'Run uses another task document: ' + runId, 1);
  f.demand(JSON.stringify(ledger.merge.order) === JSON.stringify(order), 'run_mismatch',
    'Run uses another TASK order: ' + runId, 1);
  f.demand(['preparing', 'running', 'blocked'].includes(ledger.status), 'run_exists',
    'Worktree run already exists: ' + runId, 1);
  f.demand(ledger.worktrees.every(item => ['planned', 'created', 'prepared'].includes(item.status)),
    'run_exists', 'Run has progressed beyond prepare: ' + runId, 1);
  f.demand(fs.realpathSync(git(root, ['rev-parse', '--show-toplevel'])) === ledger.coordinator.root,
    'coordinator_changed', 'Coordinator root changed', 1);
  f.demand(git(root, ['symbolic-ref', '-q', 'HEAD']) === ledger.coordinator.branch,
    'coordinator_changed', 'Coordinator branch changed', 1);
  f.demand(git(root, ['rev-parse', 'HEAD']) === ledger.base_head, 'baseline_changed',
    'Coordinator HEAD moved after baseline', 1);
  f.demand(specsHash(root) === ledger.baseline_specs_sha256, 'specs_changed',
    'Specs changed after baseline', 1);
}

function assertPreparedWorker(root, worker) {
  const worktree = path.join(root, worker.path);
  f.demand(fs.existsSync(worktree), 'worktree_missing', 'Missing worktree: ' + worker.path, 1);
  f.demand(git(worktree, ['rev-parse', 'HEAD']) === worker.base_head, 'worktree_changed',
    'Worker has commits before dispatch: ' + worker.path, 1);
  assertInitState(worktree, worker);
  const managed = new Set(worker.init_changes.map(item => item.path));
  const dirty = statusEntries(worktree).filter(entry => !managed.has(entry.path));
  f.demand(!dirty.length, 'dirty_worktree', 'Worker changed before dispatch: ' + worker.path, 1);
}

async function resumePrepare(root, runId, taskFile, order) {
  const ledger = readLedger(root, runId);
  assertResumeIdentity(root, ledger, runId, taskFile, order);
  for (const worker of ledger.worktrees) {
    if (worker.status === 'prepared') assertPreparedWorker(root, worker);
  }
  await prepareWorkers(root, ledger, ledger.platforms ?? []);
  return { ok: true, action: 'prepare', run_id: runId, resumed: true,
    base_head: ledger.base_head, workers: ledger.workers, jobs: ledger.jobs,
    worktrees: ledger.worktrees };
}

function collect(root, runId) {
  return require('./locks').withRepositorySync(root, () => collectLocked(root, runId));
}

function collectLocked(root, runId) {
  const ledger = readLedger(root, runId);
  for (const worker of ledger.worktrees) {
    if (worker.status === 'removed') continue;
    const worktree = path.join(root, worker.path);
    f.demand(fs.existsSync(worktree), 'worktree_missing', 'Missing worktree: ' + worker.path, 1);
    const head = git(worktree, ['rev-parse', 'HEAD']);
    f.demand(head !== worker.base_head, 'no_commit', worker.task + ' has no commit', 1);
    if (worker.status === 'merged' && worker.collected_head === head) continue;
    const current = assertScope(root, ledger, worker, head);
    assertInitState(worktree, worker);
    const managed = new Set(worker.init_changes.map(item => item.path));
    const dirty = statusEntries(worktree).filter(entry => !managed.has(entry.path));
    f.demand(!dirty.length, 'dirty_worktree',
      worker.task + ' has uncommitted changes: ' + dirty.slice(0, 8).map(item => item.path).join(', '), 1);
    worker.status = 'collected';
    worker.collected_head = head;
    worker.collected_task_sha256 = crypto.createHash('sha256').update(current.text).digest('hex');
  }
  ledger.status = 'merging';
  ledger.updated_at = new Date().toISOString();
  writeLedger(root, ledger);
  return { ok: true, action: 'collect', run_id: runId, worktrees: ledger.worktrees };
}

function taskMerge(baseText, mainText, workerText, taskId, file) {
  const base = taskdoc.parse(baseText, file), main = taskdoc.parse(mainText, file), worker = taskdoc.parse(workerText, file);
  const ids = main.tasks.map(item => item.id).join(',');
  f.demand(base.tasks.map(item => item.id).join(',') === ids && worker.tasks.map(item => item.id).join(',') === ids,
    'task_merge_conflict', 'TASK set/order changed in worker', 1);
  f.demand(JSON.stringify(worker.meta) === JSON.stringify(base.meta) && worker.preamble === base.preamble,
    'task_merge_conflict', 'Worker changed shared task-document structure', 1);
  const baseMap = new Map(base.tasks.map(item => [item.id, item.text]));
  const mainMap = new Map(main.tasks.map(item => [item.id, item.text]));
  const workerMap = new Map(worker.tasks.map(item => [item.id, item.text]));
  const sections = main.tasks.map(item => {
    const B = baseMap.get(item.id), M = mainMap.get(item.id), W = workerMap.get(item.id);
    if (item.id === taskId) {
      if (M === B) return W;
      if (W === B) return M;
      if (M === W) return M;
      throw new f.FlowError('task_merge_conflict', 'Both sides changed ' + taskId, 1);
    }
    if (W !== B) throw new f.FlowError('task_merge_conflict', 'Worker changed another TASK: ' + item.id, 1);
    return M;
  });
  return taskdoc.write({ ...main, body: main.preamble + sections.join('') }, main.preamble + sections.join(''));
}

async function merge(root, runId) {
  return require('./locks').withRepository(root, () => mergeLocked(root, runId));
}

function mergeCandidates(root, collectedHead) {
  const raw = git(root, ['rev-list', '--merges', '--parents', '--ancestry-path',
    collectedHead + '..HEAD']);
  return raw.split('\n').filter(Boolean).map(line => {
    const [commit, ...parents] = line.split(/\s+/);
    return { commit, parents };
  }).filter(item => item.parents.includes(collectedHead));
}

function recoverMerge(root, worker) {
  if (spawnSync('git', ['merge-base', '--is-ancestor', worker.collected_head, 'HEAD'],
    { cwd: root }).status !== 0) return null;
  const candidates = mergeCandidates(root, worker.collected_head);
  f.demand(candidates.length === 1, 'merge_recovery',
    'Cannot uniquely recover merge commit for ' + worker.task +
    ' (candidates=' + candidates.length + ')', 1);
  return candidates[0];
}

function applyMerge(root, ledger, worker, before, head) {
  const result = spawnSync('git', ['merge', '--no-ff', '--no-commit', head],
    { cwd: root, encoding: 'utf8' });
  if (result.status !== 0) {
    const conflicts = git(root, ['diff', '--name-only', '--diff-filter=U']).split('\n').filter(Boolean);
    if (!conflicts.length) {
      spawnSync('git', ['merge', '--abort'], { cwd: root });
      throw new f.FlowError('merge_failed',
        (result.stderr || result.error?.message || 'git merge failed').trim(), 1);
    }
    if (conflicts.some(item => item !== ledger.task_file)) {
      spawnSync('git', ['merge', '--abort'], { cwd: root });
      ledger.status = 'blocked'; ledger.merge.conflicts = conflicts;
      ledger.operation = null; ledger.error = 'Code conflict';
      writeLedger(root, ledger);
      throw new f.FlowError('code_conflict', 'Code conflict: ' + conflicts.join(', '), 1);
    }
  }
  const mergeBase = git(root, ['merge-base', before, head]);
  const baseText = git(root, ['show', mergeBase + ':' + ledger.task_file]);
  const mainText = git(root, ['show', before + ':' + ledger.task_file]);
  const workerText = git(root, ['show', head + ':' + ledger.task_file]);
  const body = taskMerge(baseText, mainText, workerText, worker.task, path.join(root, ledger.task_file));
  fs.writeFileSync(path.join(root, ledger.task_file), body);
  git(root, ['add', ledger.task_file]);
  git(root, ['commit', '-q', '-m', 'Merge cf-task ' + worker.task]);
  return git(root, ['rev-parse', 'HEAD']);
}

function mergeWorker(root, ledger, worker) {
  if (worker.status === 'merged') return;
  verifyCollected(root, ledger, worker);
  const head = worker.collected_head;
  const recovered = recoverMerge(root, worker);
  if (recovered) {
    worker.status = 'merged';
    ledger.merge.steps.push({ task: worker.task, collected_head: head,
      before_head: recovered.parents[0], after_head: recovered.commit, status: 'recovered' });
    ledger.operation = null;
    ledger.updated_at = new Date().toISOString();
    writeLedger(root, ledger);
    return;
  }
  const before = git(root, ['rev-parse', 'HEAD']);
  ledger.operation = { kind: 'merge', task: worker.task, expected_head: before,
    collected_head: head, target: null };
  ledger.updated_at = new Date().toISOString();
  writeLedger(root, ledger);
  try {
    const after = applyMerge(root, ledger, worker, before, head);
    worker.status = 'merged';
    ledger.merge.steps.push({ task: worker.task, collected_head: head, before_head: before,
      after_head: after, status: 'merged' });
    ledger.operation = null;
    ledger.updated_at = new Date().toISOString();
    writeLedger(root, ledger);
  } catch (error) {
    if (error.code !== 'code_conflict') {
      ledger.status = 'blocked';
      ledger.operation = null;
      ledger.error = error.message;
      ledger.updated_at = new Date().toISOString();
      writeLedger(root, ledger);
    }
    throw error;
  }
}

function integrationCommands(plan, verified) {
  return verified.results.map(result => {
    const source = plan.sourceById.get(result.id) ?? { task: null, test: null };
    return { ...result, task: source.task, test: source.test };
  });
}

async function integrate(root, ledger, runId) {
  ledger.operation = null;
  const merged = task.loadDocument(root, ledger.task_file);
  const plan = integrationPlan(merged.tasks, ledger.merge.order);
  const settings = config.load(root);
  const testedHead = git(root, ['rev-parse', 'HEAD']);
  const env = integrationEnv(runId, ledger.merge.order);
  if (!plan.tests.length) {
    ledger.status = 'cleaning';
    ledger.integration = { status: 'skipped', tested_head: testedHead, env,
      commands: [], skipped: plan.skipped, deduped: 0, elapsed_ms: 0, error: null };
    return;
  }
  ledger.status = 'verifying';
  ledger.integration = { status: 'running', tested_head: testedHead, env,
    commands: [], skipped: plan.skipped, deduped: 0, elapsed_ms: 0, error: null };
  ledger.updated_at = new Date().toISOString();
  writeLedger(root, ledger);
  const verified = await require('./verify').run(root, plan.tests, settings.tests, { env });
  const commands = integrationCommands(plan, verified);
  const dirty = statusEntries(root).filter(entry => !isTool(entry.path));
  const invalidated = git(root, ['rev-parse', 'HEAD']) !== testedHead || dirty.length > 0 ||
    specsHash(root) !== ledger.baseline_specs_sha256;
  const status = !verified.ok ? 'failed' : invalidated ? 'invalidated' : 'passed';
  ledger.integration = { status, tested_head: testedHead, env, commands, skipped: plan.skipped,
    deduped: verified.deduped, elapsed_ms: Math.round(verified.elapsed_ms),
    error: status === 'failed' ? 'integration tests failed' :
      status === 'invalidated' ? 'Working tree or HEAD changed during integration' : null };
  if (status !== 'passed') {
    ledger.status = 'blocked';
    ledger.updated_at = new Date().toISOString();
    writeLedger(root, ledger);
    throw new f.FlowError(status === 'invalidated' ? 'integration_invalidated' : 'integration_failed',
      ledger.integration.error, 1);
  }
  ledger.status = 'cleaning';
}

async function mergeLocked(root, runId) {
  const ledger = readLedger(root, runId);
  f.demand(ledger.worktrees.every(item => ['collected', 'merged'].includes(item.status)),
    'not_collected', 'Collect all workers first', 1);
  if (spawnSync('git', ['rev-parse', '-q', '--verify', 'MERGE_HEAD'], { cwd: root }).status === 0) {
    ledger.status = 'blocked'; ledger.error = 'Merge is already in progress';
    writeLedger(root, ledger);
    throw new f.FlowError('merge_in_progress', 'Resolve or abort the in-progress merge first', 1);
  }
  if (specsHash(root) !== ledger.baseline_specs_sha256) {
    throw new f.FlowError('specs_changed', 'Specs changed since baseline; restart the run', 1);
  }
  for (const worker of ledger.worktrees) mergeWorker(root, ledger, worker);
  await integrate(root, ledger, runId);
  ledger.updated_at = new Date().toISOString();
  writeLedger(root, ledger);
  return { ok: true, action: 'merge', run_id: runId, worktrees: ledger.worktrees, integration: ledger.integration };
}

function cleanup(root, runId, force = false) {
  return require('./locks').withRepositorySync(root, () => cleanupLocked(root, runId, force));
}

function assertCleanupReady(root, ledger) {
  f.demand(['cleaning', 'done'].includes(ledger.status), 'run_not_done',
    'Run is not ready for cleanup; use --force to abandon', 1);
  f.demand(['passed', 'skipped'].includes(ledger.integration.status), 'integration_not_passed',
    'Integration has not passed; use --force to abandon', 1);
  f.demand(git(root, ['rev-parse', 'HEAD']) === ledger.integration.tested_head, 'cleanup_changed',
    'Coordinator HEAD changed after integration; rerun merge', 1);
  f.demand(specsHash(root) === ledger.baseline_specs_sha256, 'cleanup_changed',
    'Specs changed after integration; rerun merge', 1);
  const dirty = statusEntries(root).filter(entry => !isTool(entry.path));
  f.demand(!dirty.length, 'cleanup_dirty', 'Coordinator has unverified changes: ' +
    dirty.slice(0, 8).map(item => item.path).join(', '), 1);
}

function assertCleanupWorker(worktree, worker) {
  f.demand(git(worktree, ['rev-parse', 'HEAD']) === worker.collected_head,
    'cleanup_changed', worker.task + ' worktree HEAD changed after collect', 1);
  assertInitState(worktree, worker);
  const managed = new Set(worker.init_changes.map(item => item.path));
  const dirty = statusEntries(worktree).filter(entry => !managed.has(entry.path));
  f.demand(!dirty.length, 'cleanup_dirty', worker.task + ' has user changes: ' +
    dirty.slice(0, 8).map(item => item.path).join(', '), 1);
}

function assertWorkerOwnership(root, ledger, worker) {
  f.demand(worker.path === worktreePath(ledger.run_id, worker.task) &&
    worker.branch === branchName(ledger.run_id, worker.task), 'cleanup_ownership',
    worker.task + ' ledger resource names are not owned by run ' + ledger.run_id, 1);
  const worktree = f.inside(root, worker.path);
  if (fs.existsSync(worktree)) {
    f.demand(fs.realpathSync(git(worktree, ['rev-parse', '--show-toplevel'])) === fs.realpathSync(worktree),
      'worktree_mismatch', 'Path is not the owned worktree: ' + worker.path, 1);
    f.demand(git(worktree, ['symbolic-ref', '-q', 'HEAD']) === 'refs/heads/' + worker.branch,
      'worktree_mismatch', worker.task + ' worktree branch changed: ' + worker.path, 1);
  }
  return worktree;
}

function cleanupWorker(root, ledger, worker, force, steps) {
  const abandoned = worker.status !== 'merged';
  const worktree = assertWorkerOwnership(root, ledger, worker);
  if (fs.existsSync(worktree)) {
    if (!force) assertCleanupWorker(worktree, worker);
    git(root, ['worktree', 'remove', '--force', worktree]);
  }
  const branch = spawnSync('git', ['rev-parse', '--verify', 'refs/heads/' + worker.branch],
    { cwd: root, encoding: 'utf8' });
  if (branch.status === 0) {
    if (!force) f.demand(branch.stdout.trim() === worker.collected_head, 'branch_changed',
      worker.task + ' branch moved after collect', 1);
    git(root, ['branch', '-D', worker.branch]);
  }
  worker.status = 'removed';
  steps.set(worker.task, { task: worker.task, path: worker.path, branch: worker.branch,
    collected_head: worker.collected_head, status: 'removed', abandoned: Boolean(force && abandoned) });
  ledger.cleanup.steps = [...steps.values()];
  ledger.updated_at = new Date().toISOString();
  writeLedger(root, ledger);
}

function cleanupLocked(root, runId, force = false) {
  const ledger = readLedger(root, runId);
  if (!force) assertCleanupReady(root, ledger);
  const steps = new Map(ledger.cleanup.steps.map(item => [item.task, item]));
  for (const worker of ledger.worktrees) {
    if (worker.status !== 'removed') cleanupWorker(root, ledger, worker, force, steps);
  }
  ledger.status = force ? 'aborted' : 'done';
  ledger.cleanup.steps = [...steps.values()];
  ledger.cleanup.kept = [];
  ledger.updated_at = new Date().toISOString();
  writeLedger(root, ledger);
  return { ok: true, action: 'cleanup', run_id: runId, steps: ledger.cleanup.steps };
}

function status(root, runId) {
  const ledger = readLedger(root, runId);
  return { ok: true, action: 'status', run_id: runId, status: ledger.status,
    workers: ledger.workers, jobs: ledger.jobs, operation: ledger.operation ?? null,
    worktrees: ledger.worktrees, merge: ledger.merge, integration: ledger.integration,
    cleanup: ledger.cleanup };
}

module.exports = { prepare, collect, merge, cleanup, status, readLedger };
