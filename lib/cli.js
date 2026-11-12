'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const f = require('./fs');
const config = require('./config');
const task = require('./task');
const spec = require('./spec');
const render = require('./render');
const hook = require('./hook');
const VERSION = require('../package.json').version;
const COMMANDS = {
  init: { count: 0, flags: { platform: 'string', 'dry-run': 'boolean' } },
  node: { count: 0, flags: { 'dry-run': 'boolean' } },
  doctor: { count: 0, flags: {} },
  'hook prompt': { count: 0, flags: { format: 'string' } },
  'hook capabilities': { count: 0, flags: {} },
  'task start': { count: 1, flags: { task: 'string', session: 'string' } },
  'task block': { count: 1, flags: { task: 'string', reason: 'string' } },
  'task reopen': { count: 1, flags: { task: 'string', reason: 'string' } },
  'task unbind': { count: 0, flags: { session: 'string' } },
  'task finish': { count: 1, flags: { task: 'string', jobs: 'number' } },
  'task archive': { count: 1, flags: { 'dry-run': 'boolean', 'no-learn': 'boolean' } },
  'task status': { count: -1, flags: {} },
  'process collect': { count: 0, flags: { out: 'string', transcript: 'string' } },
  'task parallel prepare': { count: 0, flags: { 'task-file': 'string', tasks: 'string', 'run-id': 'string', workers: 'number', 'no-auto-baseline': 'boolean', init: 'boolean' } },
  'task parallel status': { count: 0, flags: { 'run-id': 'string' } },
  'task parallel collect': { count: 0, flags: { 'run-id': 'string' } },
  'task parallel merge': { count: 0, flags: { 'run-id': 'string' } },
  'task parallel cleanup': { count: 0, flags: { 'run-id': 'string', force: 'boolean', purge: 'boolean' } },
  'spec list': { count: 0, flags: {} },
  'spec inject': { count: 0, flags: { 'task-file': 'string', task: 'string', path: 'multiple', full: 'boolean' } },
  'spec learn': { count: 0, flags: { 'from-task': 'string', task: 'string', 'dry-run': 'boolean' } }
};
function usage(command = null) {
  const names = command ? Object.keys(COMMANDS).filter(name => name === command || name.startsWith(command + ' ')) : Object.keys(COMMANDS);
  f.demand(names.length > 0, 'usage', 'Unknown command: ' + command);
  return 'code-flow v' + require('../package.json').version + '\nGlobal Node-only runtime\n\n' + names.map(name => {
    const definition = COMMANDS[name];
    const target = definition.count === 1 ? (name === 'task archive' ? ' <requirement-dir>' : ' <task-file>') :
      definition.count === -1 ? ' [requirement-dir]' : '';
    return '  code-flow ' + name + target + Object.entries(definition.flags).map(([key, type]) =>
      ' [--' + key + (type === 'boolean' ? '' : ' <value>') + ']').join('') + (name === 'hook prompt' ? '' : ' [--json]');
  }).join('\n') + '\n';
}
function commandFor(argv) {
  if (['init', 'node', 'doctor'].includes(argv[0])) return argv[0];
  const three = argv.slice(0, 3).join(' ');
  return Object.hasOwn(COMMANDS, three) ? three : argv.slice(0, 2).join(' ');
}
function parse(argv) {
  const command = commandFor(argv);
  f.demand(Object.hasOwn(COMMANDS, command), 'usage', 'Unknown command: ' + command);
  const definition = COMMANDS[command], flags = { ...definition.flags, ...(command === 'hook prompt' ? {} : { json: 'boolean' }) };
  const options = {}, positional = [], offset = command.split(' ').length;
  for (let i = offset; i < argv.length; i++) {
    const arg = argv[i];
    if (!arg.startsWith('--')) { positional.push(arg); continue; }
    const equal = arg.indexOf('='), key = arg.slice(2, equal < 0 ? undefined : equal);
    f.demand(Object.hasOwn(flags, key), 'usage', 'Unknown option: --' + key);
    const type = flags[key];
    f.demand(type === 'multiple' || !Object.hasOwn(options, key), 'usage', 'Duplicate option: --' + key);
    if (type === 'boolean') { f.demand(equal < 0, 'usage', '--' + key + ' takes no value'); options[key] = true; continue; }
    const value = equal < 0 ? argv[++i] : arg.slice(equal + 1);
    f.demand(typeof value === 'string' && value.length > 0 && !value.startsWith('--'), 'usage', 'Missing value: --' + key);
    if (type === 'number') options[key] = f.positive(Number(value), key, true);
    else if (type === 'multiple') (options[key] ??= []).push(value);
    else options[key] = value;
  }
  f.demand(definition.count === -1 ? positional.length <= 1 : positional.length === definition.count,
    'usage', 'Wrong arguments; use code-flow ' + command + ' --help');
  return { command, positional, options };
}
function input(stream) {
  return new Promise((resolve, reject) => {
    const chunks = []; let size = 0;
    const finish = (error, raw) => {
      clearTimeout(timer); stream.removeListener('data', data); stream.removeListener('end', end);
      stream.removeListener('error', fail);
      if (error) { stream.destroy(); reject(error); } else resolve(raw);
    };
    const data = chunk => {
      size += Buffer.byteLength(chunk);
      if (size > 1048576) finish(new f.FlowError('hook_input_large', 'Hook input exceeds 1 MiB'));
      else chunks.push(Buffer.from(chunk));
    };
    const end = () => finish(null, Buffer.concat(chunks).toString('utf8'));
    const fail = error => finish(error);
    const timer = setTimeout(() => finish(new f.FlowError('hook_timeout', 'Hook input timed out')), 2000);
    stream.on('data', data); stream.once('end', end); stream.once('error', fail);
  });
}
function diagnostics(items, stderr) {
  for (const item of items ?? []) stderr.write('code-flow [' + item.code + '] ' + item.message.replace(/[\r\n]+/g, ' ') + '\n');
}
function eventPath(cwd) {
  if (process.env.CF_EVENT_LOG) return process.env.CF_EVENT_LOG;
  try {
    const root = config.findRoot(cwd, false);
    if (!root) return null;
    const settings = config.load(root);
    if (!settings.capture.enabled) return null;
    return f.inside(root, settings.capture.path + '/events.jsonl');
  } catch (_) { return null; }
}

function counters(streams, file) {
  if (!file) return streams;
  const state = { stdout: 0, stderr: 0 };
  const wrap = (stream, key) => ({ write(text) {
    state[key] += Buffer.byteLength(String(text)); return stream.write(text);
  } });
  return { stdin: streams.stdin, stdout: wrap(streams.stdout, 'stdout'),
    stderr: wrap(streams.stderr, 'stderr'), state };
}

function shortHash(value) {
  return typeof value === 'string' && value
    ? crypto.createHash('sha256').update(value).digest('hex').slice(0, 16) : null;
}
function refs(value) {
  return (Array.isArray(value) ? value : []).slice(0, 50)
    .map(item => typeof item === 'string' ? item : item?.ref)
    .filter(item => typeof item === 'string');
}
function bounded(value, max = 1000) {
  if (typeof value !== 'string') return null;
  const text = value.replace(/[\r\n]+/g, ' ').trim();
  return text.length > max ? text.slice(0, max) + '...' : text;
}
function redactArgs(argv) {
  const result = [];
  for (let index = 0; index < argv.length; index++) {
    if (argv[index] === '--session') {
      result.push(argv[index]);
      if (index + 1 < argv.length) { result.push('<redacted>'); index++; }
    } else if (argv[index].startsWith('--session=')) result.push('--session=<redacted>');
    else result.push(argv[index]);
  }
  return result;
}
function summaryBase(result) {
  return { task: result?.task ?? null, session: shortHash(result?.session),
    emitted_refs: refs(result?.emitted), omitted_refs: refs(result?.omitted) };
}
function summarize(command, result) {
  if (!result || typeof result !== 'object') return null;
  const base = summaryBase(result);
  if (command === 'task finish') return { ...base, ok: result.ok, executed: result.executed,
    deduped: result.deduped, tests_changed: Boolean(result.tests_changed),
    head: result.head ?? null, dirty: result.dirty ?? null,
    results: (result.results || []).slice(0, 50).map(item => ({
      id: item.id, status: item.status, exit_code: item.exit_code, duration_ms: item.duration_ms })) };
  if (command === 'task start' || command === 'spec inject') return { ...base,
    emitted: (result.emitted || []).length, omitted: (result.omitted || []).length,
    paths: Array.isArray(result.paths) ? result.paths.slice(0, 20) : [],
    diagnostics: (result.diagnostics || []).map(item => item.code) };
  if (command === 'task block' || command === 'task reopen') return { ...base, ok: result.ok,
    action: result.action, reason: bounded(result.reason, 500) };
  if (command.startsWith('task parallel')) return { ok: result.ok ?? null, action: result.action ?? null,
    run_id: result.run_id ?? null, status: result.status ?? null,
    workers: Array.isArray(result.workers) ? result.workers.length :
      (typeof result.workers === 'number' ? result.workers : null),
    worktrees: Array.isArray(result.worktrees) ? result.worktrees.length : null,
    steps: Array.isArray(result.steps) ? result.steps.length : null };
  if (command === 'task archive') return { ok: result.ok, archived_to: result.archived_to ?? null,
    learning_skipped: Boolean(result.learning_skipped), results: (result.results || []).length };
  if (command === 'spec learn') return { results: (result.results || []).slice(0, 50).map(item => ({
    source: item.source, target: item.target, rule: item.rule, status: item.status })) };
  if (command === 'spec list') return { specs: (result.items || []).length };
  if (command === 'task status') {
    const items = result.items || [];
    return { tasks: items.length, done: items.filter(item => item.status === 'done').length,
      in_progress: items.filter(item => item.status === 'in-progress').length,
      draft: items.filter(item => item.status === 'draft').length,
      blocked: items.filter(item => item.status === 'blocked').length };
  }
  if (command === 'doctor') return { ok: result.ok, summary: result.summary };
  return { ok: result.ok ?? null };
}
function summarizeSafe(command, result) {
  try { return summarize(command, result); } catch (error) {
    return { capture_error: error.code || 'capture_summary_failed' };
  }
}

function writeEvent(argv, command, started, io, code, summary, cwd, file) {
  if (!file) return;
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.appendFileSync(file, JSON.stringify({ version: 2, at: new Date().toISOString(),
      cli_version: VERSION, node: process.version, platform: process.platform, command,
      args: redactArgs(argv), cwd, exit: code, ms: Date.now() - started,
      stdout_bytes: io.state?.stdout ?? 0, stderr_bytes: io.state?.stderr ?? 0,
      summary: summary ?? null }) + '\n');
  } catch (_) { /* capture is best-effort; never affect the command */ }
}

async function runHook(options, streams) {
  const format = options.format ?? 'claude';
  let result, prompt = null;
  try {
    f.demand(['claude', 'codex', 'costrict', 'opencode'].includes(format),
      'hook_format', 'Expected --format=claude|codex|costrict|opencode');
    const raw = await input(streams.stdin);
    if (!raw.trim()) return { code: 0, summary: { format, blank: true } };
    const data = JSON.parse(raw);
    prompt = typeof data.prompt === 'string' ? data.prompt : null;
    result = hook.build(data, format);
  } catch (error) { result = { payload: hook.payload(format, ''), diagnostics: [{ code: error.code || 'hook_input', message: error.message }] }; }
  const promptBytes = prompt === null ? null : Buffer.byteLength(prompt);
  const promptHash = shortHash(prompt);
  diagnostics(result.diagnostics, streams.stderr);
  if (result.payload) streams.stdout.write(JSON.stringify(result.payload) + '\n');
  return { code: 0, summary: { format, task: result.task ?? null,
    session: shortHash(result.session), prompt_bytes: promptBytes, prompt_hash: promptHash,
    paths: Array.isArray(result.paths) ? result.paths.slice(0, 20) : [],
    emitted: (result.emitted || []).length, omitted: (result.omitted || []).length,
    emitted_refs: refs(result.emitted), omitted_refs: refs(result.omitted),
    diagnostics: (result.diagnostics || []).map(item => item.code) } };
}
async function dispatch(parsed, cwd) {
  const { command, positional: args, options } = parsed;
  if (command === 'init') return require('./init').init(f.realpath(cwd),
    { platform: options.platform, dryRun: options['dry-run'] });
  if (command === 'node') return require('./init').node(f.realpath(cwd),
    { dryRun: options['dry-run'] });
  if (command === 'doctor') {
    const root = config.findRoot(cwd, false) || f.realpath(cwd);
    return require('./doctor').run(root);
  }
  if (command === 'hook capabilities') {
    return { package: require('../package.json').name, version: require('../package.json').version,
      hook_protocol: 1, node: process.execPath, entry: path.resolve(__dirname, '../bin/code-flow.js') };
  }
  const root = config.findRoot(cwd); config.load(root);
  switch (command) {
    case 'task start': return task.start(root, args[0], f.string(options.task, '--task'), options.session);
    case 'task block': return task.transition(root, args[0], f.string(options.task, '--task'), 'block', options.reason);
    case 'task reopen': return task.transition(root, args[0], f.string(options.task, '--task'), 'reopen', options.reason);
    case 'task unbind': return require('./session').unbind(root, options.session);
    case 'task finish': return task.finish(root, args[0], f.string(options.task, '--task'), options);
    case 'task archive': return task.archive(root, args[0], { dryRun: options['dry-run'], noLearn: options['no-learn'] });
    case 'task status': return task.list(root, args[0]);
    case 'process collect': return require('./process').collect(root,
      { out: options.out, transcript: options.transcript });
    case 'task parallel prepare': {
      const runId = options['run-id'] || new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
      return require('./worktree').prepare(root, { taskFile: f.string(options['task-file'], '--task-file'),
        tasks: f.string(options.tasks, '--tasks').split(',').map(item => item.trim()).filter(Boolean),
        runId, noAutoBaseline: Boolean(options['no-auto-baseline']), noInit: !options.init,
        workers: options.workers });
    }
    case 'task parallel status': return require('./worktree').status(root, f.string(options['run-id'], '--run-id'));
    case 'task parallel collect': return require('./worktree').collect(root, f.string(options['run-id'], '--run-id'));
    case 'task parallel merge': return require('./worktree').merge(root, f.string(options['run-id'], '--run-id'));
    case 'task parallel cleanup': return require('./worktree').cleanup(root,
      f.string(options['run-id'], '--run-id'), Boolean(options.force), Boolean(options.purge));
    case 'spec list': {
      const result = spec.list(root); return { ok: result.diagnostics.length === 0, ...result };
    }
    case 'spec inject': {
      const taskFile = options['task-file'];
      f.demand(!taskFile || options.task, 'usage', '--task is required with --task-file');
      return { ok: true, ...render.inject(root, { taskFile, taskId: options.task,
        paths: options.path ?? [], full: options.full, strictTask: Boolean(taskFile) }),
        paths: options.path ?? [] };
    }
    case 'spec learn': return task.learn(root, f.string(options['from-task'], '--from-task'),
      f.string(options.task, '--task'), options['dry-run']);
    default: throw new f.FlowError('usage', 'Unsupported command');
  }
}
function display(result, json, stdout) {
  if (json) {
    const value = result.schema_version === 1 && Object.hasOwn(result, 'text')
      ? Object.fromEntries(Object.entries(result).filter(([key]) => key !== 'text')) : result;
    stdout.write(JSON.stringify(value, null, 2) + '\n');
  }
  else if (result.text) stdout.write(result.text + (result.text.endsWith('\n') ? '' : '\n'));
  else if (result.items) {
    stdout.write(result.items.map(item => item.task ? item.task + '  ' + item.status + '  tests=' + item.tests :
      item.id + '  rules=' + item.rules + '  ' + item.description).join('\n') + '\n');
  } else stdout.write(JSON.stringify(result, null, 2) + '\n');
}
async function main(argv, streams = { stdin: process.stdin, stdout: process.stdout, stderr: process.stderr }, cwd = process.cwd()) {
  const isHook = argv[0] === 'hook';
  const started = Date.now();
  const eventFile = eventPath(cwd);
  const io = counters(streams, eventFile);
  try {
    if (!isHook && argv.length === 1 && ['--version', '-v'].includes(argv[0])) {
      io.stdout.write(require('../package.json').version + '\n'); return 0;
    }
    if (!isHook && argv.includes('--help')) {
      io.stdout.write(usage(argv.filter(arg => arg !== '--help').slice(0, 2).join(' ') || null)); return 0;
    }
    const parsed = parse(argv);
    if (parsed.command === 'hook prompt') {
      const hookResult = await runHook(parsed.options, io);
      writeEvent(argv, 'hook prompt', started, io, hookResult.code, hookResult.summary, cwd, eventFile);
      return hookResult.code;
    }
    const result = await dispatch(parsed, cwd);
    diagnostics(result.diagnostics, io.stderr);
    display(result, parsed.options.json, io.stdout);
    const code = result.interrupted ? (result.interrupted === 'SIGINT' ? 130 : 143) : result.ok === false ? 1 : 0;
    writeEvent(argv, parsed.command, started, io, code, summarizeSafe(parsed.command, result), cwd, eventFile);
    return code;
  } catch (error) {
    io.stderr.write('code-flow [' + (error.code || 'operation_failed') + '] ' + error.message + '\n');
    if (isHook) {
      const value = argv.find(arg => arg.startsWith('--format='));
      const format = value ? value.slice(9) : argv[argv.indexOf('--format') + 1];
      io.stdout.write(JSON.stringify(hook.payload(format, '')) + '\n');
      writeEvent(argv, 'hook prompt', started, io, 0, { error: error.code || 'hook_error', error_message: bounded(error.message) }, cwd, eventFile);
      return 0;
    }
    if (argv.includes('--json')) io.stdout.write(JSON.stringify({ ok: false, code: error.code || 'operation_failed', message: error.message }) + '\n');
    const code = error.exitCode ?? (error instanceof SyntaxError ? 2 : 1);
    writeEvent(argv, argv.slice(0, 2).join(' '), started, io, code, { error: error.code || 'operation_failed', error_message: bounded(error.message) }, cwd, eventFile);
    return code;
  }
}
module.exports = { main, parse, usage, dispatch, runHook };
