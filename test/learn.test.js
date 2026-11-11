'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const h = require('./helpers');
const task = require('../lib/task');
const taskdoc = require('../lib/taskdoc');
const spec = require('../lib/spec');
const learn = require('../lib/learn');
const f = require('../lib/fs');
function delta(id, op = 'add', fields = {}) {
  return { id, op, target: 'cli/runtime', rule: 'Learned rule.', evidence: 'actual regression', ...fields };
}
function done(root, spec_delta) {
  return task.load(root, h.task(root, { status: 'done', spec_delta }));
}

test('adds one rule, retries idempotently and refuses changed applied payload', async t => {
  const root = h.project(t); h.spec(root);
  const document = done(root, [delta('DELTA-001')]);
  const first = await learn.apply(root, [document]);
  assert.equal(first.results[0].rule, 'RULE-002');
  assert.equal((await learn.apply(root, [document])).results[0].status, 'already-applied');
  const loaded = spec.load(root, 'cli/runtime');
  assert.equal(loaded.rules.length, 2); assert.equal(loaded.meta.next_rule, 3);
  const changed = done(root, [delta('DELTA-001', 'add', { rule: 'Changed payload.' })]);
  await assert.rejects(learn.apply(root, [changed]), /payload changed/);
});

test('CRLF Specs remain well-formed through repeated learning', async t => {
  const root = h.project(t), file = h.spec(root);
  fs.writeFileSync(file, fs.readFileSync(file, 'utf8').replace(/\n/g, '\r\n'));
  await learn.apply(root, [done(root, [delta('D1')])]);
  await learn.apply(root, [done(root, [delta('D2', 'add', { rule: 'Next rule.' })])]);
  const raw = fs.readFileSync(file, 'utf8');
  assert.ok(!raw.includes('\r\r\n'));
  assert.equal(spec.load(root, 'cli/runtime').rules.length, 3);
});

test('update/remove preserve identity and deleting highest ID never reuses it', async t => {
  const root = h.project(t); h.spec(root);
  await learn.apply(root, [done(root, [delta('D1')])]);
  const update = delta('D2', 'update', { ref: 'RULE-002', before: 'Learned rule.', rule: 'Updated rule.' });
  await learn.apply(root, [done(root, [update])]);
  assert.equal((await learn.apply(root, [task.load(root, '.code-flow/tasks/2026-11-10/demo/demo.md')])).results[0].status, 'already-applied');
  await learn.apply(root, [done(root, [delta('D3', 'remove', { ref: 'RULE-002', before: 'Updated rule.' })])]);
  const result = await learn.apply(root, [done(root, [delta('D4')])]);
  assert.equal(result.results[0].rule, 'RULE-003');
  assert.equal(spec.load(root, 'cli/runtime').meta.next_rule, 4);
});

test('dry-run changes no Spec, counter or temporary lock state', async t => {
  const root = h.project(t); const file = h.spec(root);
  const document = done(root, [delta('D1')]), before = fs.readFileSync(file, 'utf8');
  const output = await learn.apply(root, [document], true);
  assert.equal(output.changes.length, 1);
  assert.equal(fs.readFileSync(file, 'utf8'), before);
  assert.equal(fs.existsSync(f.transientRoot(root)), false);
});

test('preflights all targets before writing and enforces before text', async t => {
  const root = h.project(t); const file = h.spec(root), before = fs.readFileSync(file, 'utf8');
  await assert.rejects(learn.apply(root, [done(root, [delta('D1'), delta('D2', 'add', { target: 'missing/rules' })])]), /Missing Spec/);
  assert.equal(fs.readFileSync(file, 'utf8'), before);
  await assert.rejects(learn.apply(root, [done(root, [delta('D3', 'update', { ref: 'RULE-001', before: 'stale' })])]), /changed or missing/);
});

test('a Delta ID cannot be re-applied to a different target', async t => {
  const root = h.project(t); h.spec(root); h.spec(root, 'other/rules');
  const first = done(root, [delta('D1', 'add', { target: 'cli/runtime', rule: 'First target.' })]);
  await learn.apply(root, [first]);
  const changedTarget = done(root, [delta('D1', 'add', { target: 'other/rules', rule: 'Other target.' })]);
  await assert.rejects(learn.apply(root, [changedTarget]), /payload changed/);
  assert.equal(spec.load(root, 'other/rules').rules.length, 1);
});

test('partial multi-Spec commit can resume without duplicate allocation', async t => {
  const root = h.project(t); h.spec(root); h.spec(root, 'other/rules');
  const document = done(root, [delta('D1'), delta('D2', 'add', { target: 'other/rules' })]);
  const prepared = learn.plan(root, [document]);
  let calls = 0;
  assert.throws(() => learn.commit(prepared, (...args) => {
    if (++calls === 2) throw new Error('simulated disk failure');
    f.atomicWrite(...args);
  }), /disk failure/);
  assert.equal(spec.load(root, 'cli/runtime').meta.next_rule, 3);
  const result = await learn.apply(root, [document]);
  assert.equal(result.results[0].status, 'already-applied');
  assert.equal(spec.load(root, 'cli/runtime').meta.next_rule, 3);
  assert.equal(spec.load(root, 'other/rules').meta.next_rule, 3);
});

test('duplicate text consumes no number and concurrent user edits survive', async t => {
  const root = h.project(t); const file = h.spec(root);
  const document = done(root, [delta('D1', 'add', { rule: 'Current rule.' })]);
  assert.equal((await learn.apply(root, [document])).results[0].status, 'duplicate');
  assert.equal(spec.load(root, 'cli/runtime').meta.next_rule, 2);
  const next = done(root, [delta('D2')]), prepared = learn.plan(root, [next]);
  fs.appendFileSync(file, '\nUser edit\n');
  assert.throws(() => learn.commit(prepared), /Concurrent/);
  assert.ok(fs.readFileSync(file, 'utf8').endsWith('User edit\n'));
});

test('multi-TASK learning uses task-document and TASK identity in Applied Deltas', async t => {
  const root = h.project(t); h.spec(root);
  const file = h.tasks(root, [
    { id: 'TASK-001', status: 'done', spec_delta: [delta('D1')] },
    { id: 'TASK-002', status: 'done', spec_delta: [delta('D2', 'add', { rule: 'Second rule.' })] }
  ]);
  const document = task.loadDocument(root, file);
  const tasks = document.tasks.map(item => taskdoc.taskFrom(document, item));
  const prepared = learn.plan(root, tasks);
  assert.deepEqual(prepared.results.map(item => item.source), [
    '2026-11-10/demo/demo.md#TASK-001#D1',
    '2026-11-10/demo/demo.md#TASK-002#D2'
  ]);
  await learn.apply(root, tasks);
  const learned = spec.load(root, 'cli/runtime');
  assert.equal(learned.rules.length, 3);
  const raw = fs.readFileSync(path.join(root, '.code-flow/specs/cli/runtime.md'), 'utf8');
  assert.equal((raw.match(/## Applied Deltas/g) || []).length, 1);
});
