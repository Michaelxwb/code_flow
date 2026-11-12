'use strict';
const path = require('node:path');
const fs = require('node:fs');
const f = require('./fs');
const config = require('./config');
const session = require('./session');
const taskdoc = require('./taskdoc');
const repo = require('./repo');

const STATES = taskdoc.STATES;

function loadDocument(root, relative, writable = false) {
  f.string(relative, 'task path');
  const normalized = relative.replace(/\\/g, '/').replace(/^\.\//, '');
  f.demand(/^\.code-flow\/tasks\/(?:archived\/)?\d{4}-\d{2}-\d{2}\/[^/]+\/[^/]+\.md$/.test(normalized),
    'task_path', 'Expected complete task document path: ' + relative, 2);
  f.demand(!normalized.includes('/./'), 'task_path', 'Task path must be canonical', 2);
  f.demand(!/\.(prd|design|scenarios)\.md$/.test(normalized), 'task_path', 'Expected task document, not PRD/design/scenarios', 2);
  f.demand(!writable || !normalized.startsWith('.code-flow/tasks/archived/'),
    'task_archived', 'Cannot mutate an archived task document', 2);
  const file = f.inside(root, normalized);
  const raw = f.readText(file, 1024 * 1024);
  f.demand(raw !== null, 'task_missing', 'Missing task document: ' + relative, 2);
  const document = taskdoc.parse(raw, file);
  return { ...document, file, relative: normalized, raw };
}

function resolveTask(document, taskId) {
  if (taskId) return taskdoc.find(document, taskId);
  f.demand(document.tasks.length === 1, 'task_id_required',
    'Task document has multiple TASK sections; pass --task TASK-NNN', 2);
  return document.tasks[0];
}

function loadTask(root, relative, taskId = '', writable = false) {
  const document = loadDocument(root, relative, writable);
  const task = resolveTask(document, taskId);
  return taskdoc.taskFrom(document, task);
}

function load(root, relative, taskId = '') {
  return loadTask(root, relative, taskId);
}

function writeDocument(document) {
  f.atomicWrite(document.file, taskdoc.write(document), document.raw);
}

async function withDocumentLock(root, relative, operation) {
  for (let attempt = 0; attempt < 200; attempt++) {
    try { return await f.withLock(root, 'doc:' + relative, operation); } catch (error) {
      if (error.code !== 'locked') throw error;
      await new Promise(resolve => setTimeout(resolve, 10));
    }
  }
  throw new f.FlowError('locked', 'Document write lock timed out: ' + relative, 1);
}

function withTaskLock(root, relative, taskId, operation) {
  return f.withLock(root, 'task:' + relative + '#' + taskId, () =>
    withDocumentLock(root, relative, operation));
}

async function start(root, relative, taskId, value) {
  config.load(root);
  if (value) session.location(root, value);
  const initial = loadTask(root, relative, taskId, true);
  return withTaskLock(root, initial.relative, initial.id, async () => {
    const task = loadTask(root, initial.relative, initial.id, true);
    f.demand(task.status !== 'done', 'task_state', 'Use task reopen for a done task', 1);
    let document = task.document;
    if (task.status !== 'in-progress') {
      document = taskdoc.updateTask(document, task.id,
        { status: 'in-progress', log: 'started tests=' + taskdoc.testsDigest(task) });
      writeDocument({ ...document, raw: document.raw });
    }
    const updated = loadTask(root, initial.relative, initial.id);
    const result = require('./render').inject(root, { taskFile: updated.relative, taskId: updated.id, session: value });
    const diagnostics = result.diagnostics;
    if (value) {
      try { await session.bind(root, value, updated.relative, updated.id); } catch (error) {
        diagnostics.push({ code: 'binding_failed', message: 'Task started; binding failed: ' + error.message });
      }
    }
    return { ok: true, action: 'start', task: updated.relative + '#' + updated.id, ...result, diagnostics };
  });
}

async function transition(root, relative, taskId, action, reason) {
  config.load(root); f.string(reason, 'reason');
  const initial = loadTask(root, relative, taskId, true);
  return withTaskLock(root, initial.relative, initial.id, async () => {
    const task = loadTask(root, initial.relative, initial.id, true);
    const from = action === 'block' ? 'in-progress' : 'done';
    f.demand(task.status === from, 'task_state', action + ' requires status ' + from, 1);
    const document = taskdoc.updateTask(task.document, task.id, {
      status: action === 'block' ? 'blocked' : 'in-progress', log: action + ': ' + reason
    });
    writeDocument(document);
    return { ok: true, action, task: task.relative + '#' + task.id };
  });
}

function isTaskDocument(relative) {
  const match = /^\.code-flow\/tasks\/(?:archived\/)?\d{4}-\d{2}-\d{2}\/([^/]+)\/([^/]+)\.md$/.exec(relative);
  return Boolean(match) && match[1] === match[2];
}

function list(root, directory = '.code-flow/tasks') {
  const base = f.inside(root, directory);
  f.demand(fs.existsSync(base), 'task_missing', 'Task directory missing: ' + directory, 1);
  const relative = path.relative(root, base).split(path.sep).join('/');
  f.demand(relative === '.code-flow/tasks' || relative.startsWith('.code-flow/tasks/'),
    'task_path', 'Expected task directory', 2);
  const names = require('./spec').walk(base).filter(name => name.endsWith('.md'));
  const items = [], diagnostics = [];
  let ignored = 0;
  for (const name of names.filter(name => !name.startsWith('archived/'))) {
    const taskPath = relative + '/' + name;
    if (!isTaskDocument(taskPath)) {
      if (!/\.(prd|design|scenarios)\.md$/.test(name)) ignored++;
      continue;
    }
    try {
      const document = loadDocument(root, taskPath);
      for (const task of document.tasks) {
        const verification = task.text.match(/^- \d{4}-[^\r\n]*(?:PASS|FAIL|SKIPPED)[^\r\n]*/gm) || [];
        const summary = verification.at(-1) ?? null;
        const head = summary ? /\bhead=([a-f0-9]{7,40}|none)\b/.exec(summary)?.[1] ?? null : null;
        items.push({ task: taskPath + '#' + task.id, task_file: taskPath, task_id: task.id,
          status: task.status, depends: task.depends, tests: task.tests.length,
          spec_refs: task.specRefs, scenarios: task.scenarios, verification: summary,
          verified_head: head === 'none' ? null : head,
          tests_changed: Boolean(summary && /\btests-changed\b/.test(summary)) });
      }
    } catch (error) { diagnostics.push({ source: taskPath, code: error.code, message: error.message }); }
  }
  return { ok: diagnostics.length === 0, items, diagnostics, ignored };
}

async function verify(root, relative, taskId, options = {}) {
  const settings = config.load(root), task = loadTask(root, relative, taskId);
  const tests = task.tests;
  if (tests.length === 0) {
    f.demand(task.skipTests, 'tests_missing', 'Declare tests or skip_tests with skip_reason', 1);
    return { ok: true, action: 'verify', skipped: task.skipReason, results: [], executed: 0, deduped: 0 };
  }
  const env = options.env ?? require('./runs').workerEnv(root);
  return { action: 'verify', ...await require('./verify').run(root, tests, settings.tests, { ...options, env }) };
}

function verificationLines(result, meta = {}) {
  const label = result.skipped ? 'SKIPPED' : result.ok ? 'PASS' : 'FAIL';
  const summary = '- ' + new Date().toISOString() + ' ' + label + ' commands=' +
    result.results.filter(item => item.status === 'pass').length + '/' + result.results.length +
    ' executed=' + result.executed + ' deduped=' + result.deduped +
    (result.elapsed_ms === undefined ? '' : ' elapsed=' + Math.round(result.elapsed_ms) + 'ms') +
    ' tests=' + (meta.tests ?? 'unknown') +
    ' head=' + (meta.head ? String(meta.head).slice(0, 12) : 'none') +
    ' dirty=' + (meta.dirty === null || meta.dirty === undefined ? 'unknown' : meta.dirty ? '1' : '0') +
    (meta.testsChanged ? ' tests-changed' : '') +
    (result.skipped ? ' reason=' + result.skipped : '');
  return [summary, ...result.results.map(item => '  - ' + item.id + ' ' + item.status.toUpperCase() +
    (item.exit_code === undefined ? '' : ' exit=' + item.exit_code))];
}

async function finish(root, relative, taskId, options = {}) {
  const initial = loadTask(root, relative, taskId, true);
  return f.withLock(root, 'task:' + initial.relative + '#' + initial.id, async () => {
    const task = loadTask(root, initial.relative, initial.id, true);
    f.demand(task.status === 'in-progress', 'task_state', 'finish requires in-progress', 1);
    const declared = taskdoc.testsDigest(task), started = taskdoc.startedTests(task.text);
    const gitState = repo.state(root);
    const result = await verify(root, task.relative, task.id, options), diagnostics = [];
    try { require('./learn').deltas(task); } catch (error) {
      diagnostics.push({ code: error.code, message: error.message });
    }
    return withDocumentLock(root, task.relative, async () => {
      const current = loadTask(root, task.relative, task.id, true);
      f.demand(current.text === task.text, 'concurrent_change',
        'Concurrent change: Task section changed during finish', 1);
      const document = taskdoc.updateTask(current.document, task.id, {
        status: result.ok ? 'done' : 'in-progress',
        verification: verificationLines(result, { tests: declared,
          testsChanged: started !== null && started !== declared,
          head: gitState.head, dirty: gitState.dirty })
      });
      writeDocument(document);
      return { ...result, action: 'finish', task: task.relative + '#' + task.id, diagnostics };
    });
  });
}

function requirement(root, relative) {
  const normalized = relative.replace(/\\/g, '/').replace(/^\.\//, '').replace(/\/$/, '');
  f.demand(/^\.code-flow\/tasks\/\d{4}-\d{2}-\d{2}\/[^/]+$/.test(normalized),
    'requirement_path', 'Expected unarchived requirement directory', 2);
  const directory = f.inside(root, normalized);
  const name = path.basename(normalized) + '.md';
  const taskPath = normalized + '/' + name;
  f.demand(fs.existsSync(path.join(root, taskPath)), 'tasks_missing', 'Requirement task document missing: ' + taskPath, 1);
  const document = loadDocument(root, taskPath, true);
  f.demand(document.tasks.length > 0, 'tasks_missing', 'Requirement has no TASK sections', 1);
  const tasks = document.tasks.map(task => taskdoc.taskFrom(document, task));
  f.demand(tasks.every(task => task.status === 'done'), 'tasks_unfinished', 'All tasks must be done', 1);
  const target = f.inside(root, '.code-flow/tasks/archived/' + normalized.slice('.code-flow/tasks/'.length));
  f.demand(!fs.existsSync(target), 'archive_conflict', 'Archive target exists: ' + target, 1);
  return { directory, target, document, tasks, normalized, name };
}

function removeEmptyDirectory(directory) {
  try { fs.rmdirSync(directory); } catch (error) {
    if (error.code !== 'ENOTEMPTY' && error.code !== 'ENOENT') throw error;
  }
}

async function archive(root, relative, options = {}) {
  config.load(root);
  require('./repo').requireCoordinator(root, 'task archive');
  require('./runs').assertArchiveAllowed(root, relative);
  const initial = requirement(root, relative), learn = require('./learn');
  if (options.dryRun) return {
    ...(options.noLearn ? { ok: true, dry_run: true, results: [] } : learn.preview(learn.plan(root, initial.tasks))),
    action: 'archive', archived_to: initial.target };
  return require('./locks').withRepository(root, () => f.withLock(root, 'write', async () => {
    require('./repo').requireCoordinator(root, 'task archive');
    require('./runs').assertArchiveAllowed(root, relative);
    const current = requirement(root, relative);
    let learned = { results: [], learning_skipped: Boolean(options.noLearn) };
    if (!options.noLearn) learned = learn.commit(learn.plan(root, current.tasks));
    f.demand(f.readText(current.document.file) === current.document.raw,
      'concurrent_change', 'Task document changed during archive', 1);
    f.demand(!fs.existsSync(current.target), 'archive_conflict', 'Archive target appeared', 1);
    fs.mkdirSync(path.dirname(current.target), { recursive: true });
    fs.renameSync(current.directory, current.target);
    removeEmptyDirectory(path.dirname(current.directory));
    return { ...learned, ok: true, action: 'archive', archived_to: current.target };
  }));
}

async function learn(root, relative, taskId, dryRun = false) {
  config.load(root);
  require('./repo').requireCoordinator(root, 'spec learn');
  require('./runs').assertLearnAllowed(root);
  const task = loadTask(root, relative, taskId, true);
  if (dryRun) return require('./learn').apply(root, [task], true);
  return require('./locks').withRepository(root, () => {
    require('./repo').requireCoordinator(root, 'spec learn');
    require('./runs').assertLearnAllowed(root);
    return f.withLock(root, 'task:' + task.relative + '#' + task.id,
      () => require('./learn').apply(root, [loadTask(root, task.relative, task.id, true)]));
  });
}

module.exports = {
  STATES, archive, finish, learn, list, load, loadDocument, loadTask,
  requirement, start, transition, validateTests: taskdoc.validateTests, verify
};
