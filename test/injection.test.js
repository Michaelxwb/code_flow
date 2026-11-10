'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const h = require('./helpers');
const hook = require('../lib/hook');
const spec = require('../lib/spec');
const task = require('../lib/task');
const session = require('../lib/session');
const render = require('../lib/render');
function event(root, prompt = 'continue', id = 'main') {
  return { cwd: root, prompt, session_id: id };
}
function context(result) { return result.payload?.hookSpecificOutput?.additionalContext || ''; }

test('does not infer the sole active task, but start binds a session precisely', async t => {
  const root = h.project(t); h.spec(root); const file = h.task(root, { status: 'in-progress' });
  assert.ok(!context(hook.build(event(root), 'codex')).includes('Current rule.'));
  const token = session.token(root, 'codex', 'main');
  await task.start(root, file, 'TASK-001', token);
  assert.ok(context(hook.build(event(root), 'codex')).includes('Current rule.'));
  assert.ok(!context(hook.build(event(root, 'continue', 'other'), 'codex')).includes('Current rule.'));
  await task.transition(root, file, 'TASK-001', 'block', 'waiting');
  const ended = hook.build(event(root), 'codex');
  assert.ok(!context(ended).includes('Current rule.'));
  assert.ok(ended.diagnostics.some(item => item.code === 'binding_stale'));
});

test('unclosed fences never become task directives, and Costrict sessions are distinct', t => {
  const root = h.project(t); h.spec(root); const file = h.task(root);
  const fenced = hook.build(event(root, '~~~text\ntask: ' + file + '#TASK-001'), 'codex');
  assert.ok(!context(fenced).includes('Current rule.'));
  const input = event(root, 'task: ' + file + '#TASK-001');
  const claude = hook.build(input, 'claude'), costrict = hook.build(input, 'costrict');
  const a = context(claude).match(/session: ([a-f0-9]+)/)[1];
  const b = context(costrict).match(/session: ([a-f0-9]+)/)[1];
  assert.notEqual(a, b);
});

test('explicit task overrides binding for one prompt and reads live changes', async t => {
  const root = h.project(t); h.spec(root, 'cli/runtime', 'Old rule.');
  h.spec(root, 'other/runtime', 'Other rule.');
  const a = h.task(root), b = h.task(root, { spec_refs: ['other/runtime'] }, '.code-flow/tasks/2026-11-10/other/other.md');
  await task.start(root, a, 'TASK-001', session.token(root, 'codex', 'main'));
  assert.ok(context(hook.build(event(root, 'task: ' + b + '#TASK-001'), 'codex')).includes('Other rule.'));
  assert.ok(context(hook.build(event(root), 'codex')).includes('Old rule.'));
  h.spec(root, 'cli/runtime', 'New rule.');
  assert.ok(context(hook.build(event(root), 'codex')).includes('New rule.'));
  const invalid = hook.build(event(root, 'task: .code-flow/tasks/2026-11-10/missing/missing.md#TASK-001'), 'codex');
  assert.ok(!context(invalid).includes('New rule.'));
  assert.ok(invalid.diagnostics.length > 0);
});

test('path routes ignore fenced instructions, URLs and harness metadata', t => {
  const root = h.project(t, { paths: { 'src/**/*.js': ['cli/runtime'] } }); h.spec(root);
  assert.ok(context(hook.build(event(root, 'edit @src/app.js'), 'claude')).includes('Current rule.'));
  const prompt = '~~~text\ntask: .code-flow/tasks/2026-11-10/demo/demo.md#TASK-001\nsrc/a.js\n~~~\n' +
    '<task-notification>src/a.js</task-notification>\nhttps://example.com/src/a.js\njust discuss';
  assert.ok(!context(hook.build(event(root, prompt), 'claude')).includes('Current rule.'));
  assert.deepEqual(hook.paths('read "src/a.js" and `src/b.js`', root), ['src/a.js', 'src/b.js']);
});

test('budgets omit whole blocks and keep UTF-8 output bounded', t => {
  const root = h.project(t, { always: ['cli/runtime'], budget: { maxTokens: 200, maxBytes: 900 } });
  h.spec(root, 'cli/runtime', '约束'.repeat(2000));
  const result = render.inject(root);
  assert.equal(result.omitted.length, 1);
  assert.ok(result.text.includes('omitted:'));
  assert.ok(!result.text.includes('约束'));
  assert.ok(Buffer.byteLength(result.text) <= 900);
  assert.ok(render.inject(root, { full: true }).text.includes('约束'));
});

test('native OpenCode and malformed inputs produce nonblocking JSON only', t => {
  const root = h.project(t); h.spec(root); const file = h.task(root);
  const result = hook.build({ directory: root, event: { sessionID: 's', prompt: { text: 'task: ' + file + '#TASK-001' } } }, 'opencode');
  assert.ok(result.payload.context.includes('Current rule.'));
  for (const format of ['codex', 'claude', 'opencode']) {
    const invalid = hook.build({ invalid: true }, format);
    assert.ok(invalid.diagnostics.length);
    assert.ok(!JSON.stringify(invalid.payload).includes('decision'));
  }
});

test('catalog exposes only headers while spec list reports exact rule counts', t => {
  const root = h.project(t);
  h.spec(root, 'cli/runtime', 'Current rule.');
  h.spec(root, 'shared/base', 'Shared rule.');
  const text = context(hook.build(event(root), 'codex'));
  assert.match(text, /## Spec Catalog/);
  assert.match(text, /cli\/runtime: cli\/runtime rules/);
  assert.doesNotMatch(text, /rules=\d/);
  const listing = spec.list(root);
  assert.deepEqual(listing.items.map(item => [item.id, item.rules]).sort(),
    [['cli/runtime', 1], ['shared/base', 1]]);
});

test('real workspace path and platform are part of the session identity', t => {
  const one = h.project(t), two = h.project(t);
  assert.notEqual(session.token(one, 'codex', 'same'), session.token(two, 'codex', 'same'));
  assert.notEqual(session.token(one, 'codex', 'same'), session.token(one, 'claude', 'same'));
  assert.throws(() => session.location(one, '../bad'), /token/i);
});

test('Task identity, duplicate commands, skip flags and state errors are explicit', async t => {
  const root = h.project(t); h.spec(root);
  const file = h.task(root, { skip_tests: 'maybe' });
  assert.throws(() => task.load(root, file), /true or false/);
  h.task(root, { status: 'done' });
  await assert.rejects(task.start(root, file, 'TASK-001'), /reopen/);
  assert.throws(() => task.load(root, 'demo.md'), /complete/);
});
