'use strict';
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const { performance } = require('node:perf_hooks');
const f = require('./fs');

function canonicalEnv(...layers) {
  return Object.fromEntries(Object.entries(Object.assign({}, ...layers))
    .sort(([left], [right]) => left.localeCompare(right)));
}

function prepare(root, tests, settings, runnerEnv = {}) {
  require('./task').validateTests(tests); f.object(runnerEnv, 'runner env');
  for (const key of ['CF_WORKTREE_ID', 'CF_TASK_ID', 'CF_TASK_IDS', 'CF_RUN_ID', 'CF_PORT_OFFSET', 'CF_DB_SUFFIX']) {
    f.demand(!Object.hasOwn(runnerEnv, key) || process.env[key] === undefined ||
      process.env[key] === runnerEnv[key], 'env_conflict',
      'Existing ' + key + ' does not match the selected run', 1);
  }
  const unique = new Map(), entries = [];
  const environment = f.hash(JSON.stringify(Object.keys(process.env).sort().map(key => [key, process.env[key]])));
  for (const input of tests) {
    const cwd = f.inside(root, input.cwd ?? '.');
    f.demand(require('node:fs').statSync(cwd).isDirectory(), 'test_cwd', 'Test cwd is not a directory');
    const env = canonicalEnv(runnerEnv, input.env ?? {});
    const item = { ...input, root, cwd, env, timeout: input.timeout ?? settings.timeoutSeconds,
      parallel: input.parallel ?? false, group: input.group ?? null };
    const key = JSON.stringify([item.argv ?? null, item.run ?? null, cwd, item.timeout, item.parallel, item.group, environment, env]);
    if (!unique.has(key)) unique.set(key, { ...item, key, queued: performance.now() });
    entries.push({ id: input.id, key });
  }
  return { commands: [...unique.values()], entries };
}
function tail(buffer) {
  let text = buffer.toString('utf8').split(/\r?\n/).slice(-50).join('\n');
  while (Buffer.byteLength(text) > 65536) text = text.slice(1);
  return text;
}
function capture() {
  let buffer = Buffer.alloc(0);
  return {
    push(chunk) { buffer = Buffer.concat([buffer, chunk]).subarray(-65536); },
    text() { return tail(buffer); }
  };
}
function signalGroup(pid, signal) {
  try { process.kill(-pid, signal); } catch (error) { if (error.code !== 'ESRCH') throw error; }
}
async function stopTree(child) {
  if (!child.pid) return;
  if (process.platform === 'win32') {
    const result = spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { timeout: 2000, windowsHide: true });
    if (result.error) throw result.error;
    if (child.exitCode === null) child.kill('SIGKILL');
    return;
  }
  signalGroup(child.pid, 'SIGTERM');
  await new Promise(resolve => setTimeout(resolve, 100));
  signalGroup(child.pid, 'SIGKILL');
}
function spawnCommand(command) {
  const options = { cwd: command.cwd, env: { ...process.env, ...(command.env ?? {}) },
    detached: process.platform !== 'win32', windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] };
  return command.argv ? spawn(command.argv[0], command.argv.slice(1), options) :
    spawn(command.run, { ...options, shell: true });
}
function spawnExecute(command, signal) {
  return new Promise(resolve => {
    const began = performance.now(), stdout = capture(), stderr = capture();
    let child, status = null, stop = null, errorText = null, settled = false;
    const end = async (code, childSignal) => {
      if (settled) return; settled = true;
      clearTimeout(timer); signal.removeEventListener('abort', cancel);
      if (stop) { try { await stop; } catch (error) { status = 'cleanup-error'; errorText = error.message; } }
      resolve({ id: command.id, status: status ?? (code === 0 ? 'pass' : childSignal ? 'signal' : 'fail'),
        exit_code: code, signal: childSignal, stdout: stdout.text(), stderr: stderr.text(),
        error: errorText, duration_ms: performance.now() - began, wait_ms: began - command.queued });
    };
    const halt = reason => {
      if (status) return;
      status = reason; stop = stopTree(child);
      const reap = () => {
        if (settled) return;
        child.stdout.destroy(); child.stderr.destroy();
        void end(child.exitCode, child.signalCode);
      };
      stop.then(reap, error => { errorText = error.message; reap(); });
    };
    const cancel = () => halt('cancelled');
    const timer = setTimeout(() => halt('timeout'), command.timeout * 1000);
    try {
      child = spawnCommand(command);
      child.stdout.on('data', chunk => stdout.push(chunk));
      child.stderr.on('data', chunk => stderr.push(chunk));
      child.once('error', error => { status = 'spawn-error'; errorText = error.message; });
      child.once('close', (code, childSignal) => { void end(code, childSignal); });
      signal.addEventListener('abort', cancel, { once: true });
      if (signal.aborted) cancel();
    } catch (error) { status = 'spawn-error'; errorText = error.message; void end(null, null); }
  });
}

async function execute(command, signal) {
  let lock = null;
  if (command.group) {
    const began = performance.now();
    try {
      lock = await require('./locks').acquireGroup(command.root, command.group, command.timeout, signal);
    } catch (error) {
      const status = error.code === 'cancelled' ? 'cancelled' :
        error.code === 'lock_timeout' ? 'lock-timeout' : 'spawn-error';
      return { id: command.id, status, exit_code: null, signal: null, stdout: '', stderr: '',
        error: error.message, duration_ms: performance.now() - began, wait_ms: began - command.queued };
    }
  }
  try { return await spawnExecute(command, signal); } finally {
    if (lock) require('./locks').release(lock);
  }
}
async function batch(commands, jobs, controller, results) {
  const pending = [...commands], running = new Set(), groups = new Set();
  while (pending.length || running.size) {
    while (!controller.signal.aborted && running.size < jobs) {
      const index = pending.findIndex(item => !item.group || !groups.has(item.group));
      if (index < 0) break;
      const item = pending.splice(index, 1)[0];
      if (item.group) groups.add(item.group);
      const job = execute(item, controller.signal).then(result => {
        results.set(item.key, result);
        if (result.status !== 'pass') controller.abort();
      }).finally(() => { groups.delete(item.group); running.delete(job); });
      running.add(job);
    }
    if (!running.size) break;
    await Promise.race(running);
  }
}
function report(plan, results, started, interrupted) {
  const seen = new Set();
  const rows = plan.entries.map(item => {
    const duplicate = seen.has(item.key); seen.add(item.key);
    return { ...(results.get(item.key) ?? { status: 'not-run' }), id: item.id, duplicate };
  });
  return { ok: rows.every(item => item.status === 'pass') && !interrupted, results: rows,
    executed: results.size, deduped: plan.entries.length - plan.commands.length,
    elapsed_ms: performance.now() - started, interrupted };
}
async function run(root, tests, settings, options = {}) {
  const started = performance.now(), plan = prepare(root, tests, settings, options.env ?? {}), results = new Map();
  const jobs = options.jobs ?? settings.jobs; f.positive(jobs, 'jobs', true);
  const controller = new AbortController();
  let interrupted = null;
  const interrupt = signal => { interrupted = signal; controller.abort(); };
  const onInt = () => interrupt('SIGINT'), onTerm = () => interrupt('SIGTERM');
  process.once('SIGINT', onInt); process.once('SIGTERM', onTerm);
  try {
    for (let index = 0; index < plan.commands.length && !controller.signal.aborted;) {
      const group = [plan.commands[index++]];
      if (group[0].parallel) {
        while (index < plan.commands.length && plan.commands[index].parallel) group.push(plan.commands[index++]);
      }
      await batch(group, group[0].parallel ? jobs : 1, controller, results);
    }
    return report(plan, results, started, interrupted);
  } finally {
    process.removeListener('SIGINT', onInt); process.removeListener('SIGTERM', onTerm);
  }
}
module.exports = { prepare, run, execute, capture, stopTree };
