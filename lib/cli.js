'use strict';
const fs = require('node:fs');
const path = require('node:path');
const f = require('./fs');
const config = require('./config');
const task = require('./task');
const spec = require('./spec');
const render = require('./render');
const hook = require('./hook');
const COMMANDS = {
  init: { count: 0, flags: { platform: 'string', 'dry-run': 'boolean' } },
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
  'task parallel prepare': { count: 0, flags: { 'task-file': 'string', tasks: 'string', 'run-id': 'string', workers: 'number', 'no-auto-baseline': 'boolean', 'no-init': 'boolean' } },
  'task parallel status': { count: 0, flags: { 'run-id': 'string' } },
  'task parallel collect': { count: 0, flags: { 'run-id': 'string' } },
  'task parallel merge': { count: 0, flags: { 'run-id': 'string' } },
  'task parallel cleanup': { count: 0, flags: { 'run-id': 'string', force: 'boolean' } },
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
  if (['init', 'doctor'].includes(argv[0])) return argv[0];
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
async function runHook(options, streams) {
  const format = options.format ?? 'claude';
  let result;
  try {
    f.demand(['claude', 'codex', 'costrict', 'opencode'].includes(format),
      'hook_format', 'Expected --format=claude|codex|costrict|opencode');
    const raw = await input(streams.stdin);
    if (!raw.trim()) return 0;
    result = hook.build(JSON.parse(raw), format);
  } catch (error) { result = { payload: hook.payload(format, ''), diagnostics: [{ code: error.code || 'hook_input', message: error.message }] }; }
  diagnostics(result.diagnostics, streams.stderr);
  if (result.payload) streams.stdout.write(JSON.stringify(result.payload) + '\n');
  return 0;
}
async function dispatch(parsed, cwd) {
  const { command, positional: args, options } = parsed;
  if (command === 'init') return require('./init').init(f.realpath(cwd),
    { platform: options.platform, dryRun: options['dry-run'] });
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
    case 'task parallel prepare': {
      const runId = options['run-id'] || new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
      return require('./worktree').prepare(root, { taskFile: f.string(options['task-file'], '--task-file'),
        tasks: f.string(options.tasks, '--tasks').split(',').map(item => item.trim()).filter(Boolean),
        runId, noAutoBaseline: Boolean(options['no-auto-baseline']), noInit: Boolean(options['no-init']),
        workers: options.workers });
    }
    case 'task parallel status': return require('./worktree').status(root, f.string(options['run-id'], '--run-id'));
    case 'task parallel collect': return require('./worktree').collect(root, f.string(options['run-id'], '--run-id'));
    case 'task parallel merge': return require('./worktree').merge(root, f.string(options['run-id'], '--run-id'));
    case 'task parallel cleanup': return require('./worktree').cleanup(root,
      f.string(options['run-id'], '--run-id'), Boolean(options.force));
    case 'spec list': {
      const result = spec.list(root); return { ok: result.diagnostics.length === 0, ...result };
    }
    case 'spec inject': {
      const taskFile = options['task-file'];
      f.demand(!taskFile || options.task, 'usage', '--task is required with --task-file');
      return { ok: true, ...render.inject(root, { taskFile, taskId: options.task,
        paths: options.path ?? [], full: options.full, strictTask: Boolean(taskFile) }) };
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
  try {
    if (!isHook && argv.length === 1 && ['--version', '-v'].includes(argv[0])) {
      streams.stdout.write(require('../package.json').version + '\n'); return 0;
    }
    if (!isHook && argv.includes('--help')) {
      streams.stdout.write(usage(argv.filter(arg => arg !== '--help').slice(0, 2).join(' ') || null)); return 0;
    }
    const parsed = parse(argv);
    if (parsed.command === 'hook prompt') return runHook(parsed.options, streams);
    const result = await dispatch(parsed, cwd);
    diagnostics(result.diagnostics, streams.stderr);
    display(result, parsed.options.json, streams.stdout);
    return result.interrupted ? (result.interrupted === 'SIGINT' ? 130 : 143) : result.ok === false ? 1 : 0;
  } catch (error) {
    streams.stderr.write('code-flow [' + (error.code || 'operation_failed') + '] ' + error.message + '\n');
    if (isHook) {
      const value = argv.find(arg => arg.startsWith('--format='));
      const format = value ? value.slice(9) : argv[argv.indexOf('--format') + 1];
      streams.stdout.write(JSON.stringify(hook.payload(format, '')) + '\n'); return 0;
    }
    if (argv.includes('--json')) streams.stdout.write(JSON.stringify({ ok: false, code: error.code || 'operation_failed', message: error.message }) + '\n');
    return error.exitCode ?? (error instanceof SyntaxError ? 2 : 1);
  }
}
module.exports = { main, parse, usage, dispatch, runHook };
