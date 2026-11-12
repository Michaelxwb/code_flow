'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { spawnSync, spawn } = require('node:child_process');
const { once } = require('node:events');
const h = require('./helpers');
const cli = path.resolve(__dirname, '../bin/code-flow.js');
function run(root, args, input, env = {}) {
  return spawnSync(process.execPath, [cli, ...args], { cwd: root, input, encoding: 'utf8',
    timeout: 15000, env: { ...process.env, ...env } });
}
test('public CLI exposes v1 and rejects unknown arguments and historical commands', t => {
  const root = h.project(t);
  assert.equal(run(root, ['--version']).stdout.trim(), '1.0.0');
  for (const args of [['task', 'finish', '--help'], ['spec', 'inject', '--help'], ['--help']]) {
    const output = run(root, args); assert.equal(output.status, 0); assert.ok(output.stdout.includes('code-flow'));
  }
  for (const args of [['migrate'], ['spec', 'inject', '--paths', 'x'], ['task', 'finish', 'x', '--jobs=0']]) {
    const output = run(root, [...args, '--json']); assert.equal(output.status, 2); assert.equal(JSON.parse(output.stdout).ok, false);
  }
  const noTask = run(root, ['task', 'start', h.task(root), '--json']);
  assert.equal(noTask.status, 2);
  assert.match(JSON.parse(noTask.stdout).message, /--task/);
  const capabilities = JSON.parse(run(root, ['hook', 'capabilities', '--json']).stdout);
  assert.equal(capabilities.package, '@michaelxwb/code-flow');
  assert.equal(capabilities.hook_protocol, 1);
  assert.equal(capabilities.version, '1.0.0');
});
test('CLI lifecycle starts from a subdirectory and executes only declared commands', t => {
  const root = h.project(t); h.spec(root); const file = h.task(root);
  fs.mkdirSync(path.join(root, 'src'));
  const started = run(path.join(root, 'src'), ['task', 'start', file, '--task', 'TASK-001', '--json']);
  assert.equal(started.status, 0, started.stderr);
  assert.ok(JSON.parse(started.stdout).text.includes('Current rule.'));
  const finished = run(root, ['task', 'finish', file, '--task', 'TASK-001', '--json']);
  assert.equal(finished.status, 0, finished.stderr);
  assert.equal(JSON.parse(finished.stdout).executed, 1);
  const status = JSON.parse(run(root, ['task', 'status', '--json']).stdout);
  assert.equal(status.items[0].status, 'done');
});
test('doctor JSON follows schema, is read-only and exits by severity', t => {
  const root = h.project(t); h.spec(root); h.task(root);
  const initialized = run(root, ['init', '--platform=codex', '--json']);
  assert.equal(initialized.status, 0, initialized.stderr);
  const healthy = run(root, ['doctor', '--json']);
  assert.equal(healthy.status, 0, healthy.stderr);
  const report = JSON.parse(healthy.stdout);
  assert.equal(report.schema_version, 1);
  assert.equal(report.ok, true);
  assert.equal(report.text, undefined);
  assert.ok(report.summary.unknown >= 1);
  assert.ok(report.checks.every(item => ['pass', 'fail', 'unknown'].includes(item.status)));
  const human = run(root, ['doctor']);
  assert.equal(human.status, 0, human.stderr);
  assert.match(human.stdout, /HOST_TRUST_UNKNOWN/);
  h.write(root, '.code-flow/specs/cli/bad.md', 'broken');
  const broken = run(root, ['doctor', '--json']);
  assert.equal(broken.status, 1);
  assert.ok(JSON.parse(broken.stdout).summary.error >= 1);
});

test('node CLI regenerates only machine-local launcher and hook entries', t => {
  const root = h.project(t);
  assert.equal(run(root, ['init', '--platform=claude', '--json']).status, 0);
  fs.rmSync(path.join(root, '.code-flow/launcher/hook.sh'));
  fs.rmSync(path.join(root, '.claude/settings.local.json'));
  const result = run(root, ['node', '--json']);
  assert.equal(result.status, 0, result.stderr);
  const data = JSON.parse(result.stdout);
  assert.equal(data.ok, true);
  assert.equal(data.action, 'node');
  assert.ok(fs.existsSync(path.join(root, '.code-flow/launcher/hook.sh')));
  assert.ok(fs.existsSync(path.join(root, '.claude/settings.local.json')));
  const dry = JSON.parse(run(root, ['node', '--dry-run', '--json']).stdout);
  assert.deepEqual(dry.changes, []);
});

test('Hook CLI parses native stdin, ignores blank input and never blocks malformed data', t => {
  const root = h.project(t, { always: ['cli/runtime'] }); h.spec(root);
  const good = run(root, ['hook', 'prompt', '--format=codex'], JSON.stringify({ cwd: root, prompt: 'continue', session_id: 'x' }));
  assert.equal(good.status, 0); assert.ok(JSON.parse(good.stdout).hookSpecificOutput.additionalContext.includes('Current rule.'));
  const malformed = run(root, ['hook', 'prompt', '--format=codex'], '{not-json');
  assert.equal(malformed.status, 0); assert.ok(malformed.stderr.length);
  assert.equal(JSON.parse(malformed.stdout).hookSpecificOutput.additionalContext, '');
  const blank = run(root, ['hook', 'prompt', '--format=codex'], '');
  assert.equal(blank.status, 0); assert.equal(blank.stdout, '');
  const whitespace = run(root, ['hook', 'prompt', '--format=codex'], JSON.stringify({ cwd: root, prompt: ' ' }));
  assert.equal(whitespace.status, 0); assert.equal(whitespace.stdout, '');
});
test('optional event log records commands and hook injections', t => {
  const root = h.project(t, { always: ['cli/runtime'] }); h.spec(root); const file = h.task(root);
  const log = path.join(root, 'events.jsonl');
  const status = run(root, ['task', 'status', '--json'], undefined, { CF_EVENT_LOG: log });
  assert.equal(status.status, 0, status.stderr);
  const input = JSON.stringify({ cwd: root, session_id: 'log', prompt: 'task: ' + file + '#TASK-001' });
  const hooked = run(root, ['hook', 'prompt', '--format=codex'], input, { CF_EVENT_LOG: log });
  assert.equal(hooked.status, 0, hooked.stderr);
  assert.ok(JSON.parse(hooked.stdout).hookSpecificOutput.additionalContext.includes('Current rule.'));
  const failing = h.task(root, { status: 'in-progress', tests: [
    { id: 'fail', argv: [process.execPath, '-e', 'process.exit(3)'] }] });
  const failed = run(root, ['task', 'finish', failing, '--task', 'TASK-001', '--json'], undefined,
    { CF_EVENT_LOG: log });
  assert.equal(failed.status, 1);
  const events = fs.readFileSync(log, 'utf8').trim().split('\n').map(line => JSON.parse(line));
  assert.deepEqual(events.map(item => item.command), ['task status', 'hook prompt', 'task finish']);
  assert.equal(events[0].summary.tasks, 1);
  assert.equal(events[1].summary.emitted, 1);
  assert.equal(events[2].exit, 1);
  assert.equal(events[2].summary.ok, false);
  assert.equal(events[2].summary.results[0].status, 'fail');
  assert.ok(events.every(item => item.version === 1 && typeof item.ms === 'number'));
});

test('capture config enables the event log automatically', t => {
  const root = h.project(t); h.spec(root);
  const file = h.task(root);
  h.write(root, '.code-flow/config.json', JSON.stringify({ version: 1, always: ['cli/runtime'],
    capture: { enabled: true, path: '.code-flow/process' } }));
  const status = run(root, ['task', 'status', '--json']);
  assert.equal(status.status, 0, status.stderr);
  const log = path.join(root, '.code-flow/process/events.jsonl');
  assert.ok(fs.existsSync(log));
  const input = JSON.stringify({ cwd: root, session_id: 'auto', prompt: 'task: ' + file + '#TASK-001' });
  const hooked = run(root, ['hook', 'prompt', '--format=codex'], input);
  assert.equal(hooked.status, 0, hooked.stderr);
  const events = fs.readFileSync(log, 'utf8').trim().split('\n').map(line => JSON.parse(line));
  assert.deepEqual(events.map(item => item.command), ['task status', 'hook prompt']);
});

test('failed Task tests have exit 1 and useful bounded machine output', t => {
  const root = h.project(t); h.spec(root);
  const file = h.task(root, { status: 'in-progress', tests: [
    { id: 'fail', argv: [process.execPath, '-e', 'console.error("regression");process.exit(3)'] }
  ] });
  const result = run(root, ['task', 'finish', file, '--task', 'TASK-001', '--json']);
  assert.equal(result.status, 1);
  const report = JSON.parse(result.stdout);
  assert.equal(report.results[0].exit_code, 3);
  assert.ok(report.results[0].stderr.includes('regression'));
});
test('interrupting finish reaps running work, preserves state and exits with interrupt status', async t => {
  if (process.platform === 'win32') { t.skip('Windows signal delivery verified by platform CI separately'); return; }
  const root = h.project(t); h.spec(root);
  const file = h.task(root, { status: 'in-progress', tests: [
    { id: 'long', argv: [process.execPath, '-e', 'require("fs").writeFileSync("ready","yes");setInterval(()=>{},1000)'] }
  ] });
  const child = spawn(process.execPath, [cli, 'task', 'finish', file, '--task', 'TASK-001', '--json'], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  let stdout = '', stderr = '';
  child.stdout.on('data', chunk => { stdout += chunk; }); child.stderr.on('data', chunk => { stderr += chunk; });
  t.after(() => { if (child.exitCode === null) child.kill('SIGKILL'); });
  const closed = once(child, 'close');
  for (let i = 0; i < 500 && !fs.existsSync(path.join(root, 'ready')); i++) await new Promise(resolve => setTimeout(resolve, 10));
  assert.ok(fs.existsSync(path.join(root, 'ready')), stderr);
  child.kill('SIGINT');
  const [code] = await closed;
  assert.equal(code, 130, stderr); assert.equal(JSON.parse(stdout).interrupted, 'SIGINT');
  assert.equal(require('../lib/task').load(root, file).meta.status, 'in-progress');
});
