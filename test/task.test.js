'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const h = require('./helpers');
const task = require('../lib/task');
const taskdoc = require('../lib/taskdoc');
const spec = require('../lib/spec');

test('task updates preserve dollar replacement sequences and JSON payloads', t => {
  const root = h.project(t); h.spec(root);
  const file = h.task(root, { status: 'in-progress', tests: [{
    id: 'dollars', argv: ['node', '-e', 'process.stdout.write("$$ $& $` $1")']
  }] });
  const document = task.loadDocument(root, file);
  const updated = taskdoc.updateTask(document, 'TASK-001', {
    field: 'source', value: 'src/$&/file.js', log: 'changed $$ and $& and $`'
  });
  const text = taskdoc.write(updated);
  assert.match(text, /- \*\*Source\*\*: src\/\$&\//);
  assert.match(text, /changed \$\$ and \$& and \$`/);
  const parsed = taskdoc.parse(text, path.join(root, file));
  assert.equal(parsed.tasks[0].tests[0].argv[2], 'process.stdout.write("$$ $& $` $1")');
});

test('actual finish success writes done, failure preserves progress and E2E is not invoked', async t => {
  const root = h.project(t); h.spec(root);
  const file = h.task(root, { e2e: 'must-never-run' });
  await task.start(root, file);
  assert.equal((await task.finish(root, file)).ok, true);
  assert.equal(task.load(root, file).meta.status, 'done');
  assert.ok(task.load(root, file).body.includes('PASS commands=1/1'));
  await task.transition(root, file, 'TASK-001', 'reopen', 'regression');
  h.task(root, { status: 'in-progress',
    tests: [{ id: 'fail', argv: [process.execPath, '-e', 'process.exit(9)'] }] });
  const failed = await task.finish(root, file);
  assert.equal(failed.ok, false);
  assert.equal(task.load(root, file).meta.status, 'in-progress');
  assert.ok(task.load(root, file).body.includes('FAIL commands=0/1'));
});

test('archive resumes after move failure without reallocating learned rules', async t => {
  const root = h.project(t); h.spec(root);
  const file = h.task(root, { status: 'done', spec_delta: [
    { id: 'D1', op: 'add', target: 'cli/runtime', rule: 'Move retry rule.', evidence: 'actual failure' }
  ] });
  const directory = path.posix.dirname(file), actual = path.join(root, directory);
  const original = fs.renameSync;
  fs.renameSync = (source, destination) => {
    if (source === actual) throw new Error('simulated move failure');
    return original(source, destination);
  };
  try { await assert.rejects(task.archive(root, directory), /move failure/); }
  finally { fs.renameSync = original; }
  assert.ok(fs.existsSync(actual));
  assert.equal(spec.load(root, 'cli/runtime').meta.next_rule, 3);
  const result = await task.archive(root, directory);
  assert.equal(result.results[0].status, 'already-applied');
  assert.equal(spec.load(root, 'cli/runtime').meta.next_rule, 3);
});

test('empty tests require explicit skip reason, verify never moves state', async t => {
  const root = h.project(t); h.spec(root);
  const file = h.task(root, { status: 'in-progress', tests: [] });
  await assert.rejects(task.finish(root, file), /Declare tests/);
  h.task(root, { status: 'in-progress', tests: [], skip_tests: true, skip_reason: 'documentation only' });
  assert.equal((await task.verify(root, file)).ok, true);
  assert.equal(task.load(root, file).meta.status, 'in-progress');
  assert.equal((await task.finish(root, file)).ok, true);
  assert.ok(task.load(root, file).body.includes('SKIPPED'));
});

test('concurrent edit while testing is preserved and prevents done', async t => {
  const root = h.project(t); h.spec(root);
  const file = h.task(root, { status: 'in-progress',
    tests: [{ id: 'slow', argv: [process.execPath, '-e', 'setTimeout(()=>{},150)'] }] });
  const running = task.finish(root, file);
  const timer = setTimeout(() => fs.appendFileSync(path.join(root, file), '\nUser concurrent edit\n'), 50);
  t.after(() => clearTimeout(timer));
  await assert.rejects(running, /Concurrent/);
  assert.equal(task.load(root, file).meta.status, 'in-progress');
  assert.ok(fs.readFileSync(path.join(root, file), 'utf8').includes('User concurrent edit'));
});

test('archive applies Delta then moves the whole requirement without testing', async t => {
  const root = h.project(t); h.spec(root);
  const file = h.task(root, { status: 'done', tests: [{ id: 'never', run: 'must-never-run' }],
    spec_delta: [{ id: 'D1', op: 'add', target: 'cli/runtime', rule: 'New rule.', evidence: 'fixed bug' }] });
  const dir = path.posix.dirname(file), before = fs.readFileSync(path.join(root, file), 'utf8');
  const preview = await task.archive(root, dir, { dryRun: true });
  assert.equal(preview.dry_run, true);
  assert.equal(fs.readFileSync(path.join(root, file), 'utf8'), before);
  assert.equal(spec.load(root, 'cli/runtime').rules.length, 1);
  const result = await task.archive(root, dir);
  assert.equal(result.ok, true);
  assert.equal(fs.existsSync(path.join(root, dir)), false);
  assert.ok(fs.existsSync(path.join(result.archived_to, 'demo.md')));
  assert.equal(spec.load(root, 'cli/runtime').rules.length, 2);
});

test('archive refuses incomplete, empty and conflicting requirements', async t => {
  const root = h.project(t); h.spec(root); const file = h.task(root), dir = path.posix.dirname(file);
  await assert.rejects(task.archive(root, dir), /All tasks/);
  h.task(root, { status: 'done' });
  fs.mkdirSync(path.join(root, '.code-flow/tasks/archived/2026-11-10/demo'), { recursive: true });
  await assert.rejects(task.archive(root, dir), /target exists/);
  assert.ok(fs.existsSync(path.join(root, file)));
  fs.mkdirSync(path.join(root, '.code-flow/tasks/2026-11-10/empty'));
  await assert.rejects(task.archive(root, '.code-flow/tasks/2026-11-10/empty'), /task document missing|no Task/);
});

test('bad learning data warns at finish and requires explicit no-learn for archive', async t => {
  const root = h.project(t); h.spec(root);
  const file = h.task(root, { status: 'in-progress', spec_delta: [{ id: 'D1' }] });
  assert.ok((await task.finish(root, file)).diagnostics.length > 0);
  await assert.rejects(task.archive(root, path.posix.dirname(file)), /Delta/);
  assert.equal((await task.archive(root, path.posix.dirname(file), { noLearn: true })).learning_skipped, true);
});

test('multiple TASK sections parse, batch by Depends and keep independent identity', t => {
  const root = h.project(t); h.spec(root);
  const file = h.tasks(root, [
    { id: 'TASK-001', status: 'done' },
    { id: 'TASK-002', depends: ['TASK-001'] },
    { id: 'TASK-003', depends: ['TASK-002'] }
  ]);
  const document = task.loadDocument(root, file);
  assert.deepEqual(document.tasks.map(item => item.id), ['TASK-001', 'TASK-002', 'TASK-003']);
  assert.deepEqual(document.tasks[1].depends, ['TASK-001']);
  assert.deepEqual(taskdoc.batches(document.tasks), [['TASK-002'], ['TASK-003']]);
  h.tasks(root, [{ id: 'TASK-001', depends: ['TASK-002'] }, { id: 'TASK-002', depends: ['TASK-001'] }]);
  assert.throws(() => taskdoc.batches(task.loadDocument(root, file).tasks), /cycle|dependency/i);
  h.tasks(root, [{ id: 'TASK-001' }, { id: 'TASK-001' }]);
  assert.throws(() => task.loadDocument(root, file), /Duplicate TASK ID/);
  h.tasks(root, [{ id: 'TASK-001', depends: ['TASK-999'] }]);
  assert.throws(() => task.loadDocument(root, file), /depends on missing/);
});

test('archive reads every TASK section in one document and moves it once', async t => {
  const root = h.project(t); h.spec(root);
  const file = h.tasks(root, [
    { id: 'TASK-001', status: 'done', spec_delta: [{ id: 'D1', op: 'add', target: 'cli/runtime', rule: 'First rule.', evidence: 'e1' }] },
    { id: 'TASK-002', status: 'done', spec_delta: [{ id: 'D2', op: 'add', target: 'cli/runtime', rule: 'Second rule.', evidence: 'e2' }] }
  ]);
  const directory = path.posix.dirname(file);
  const result = await task.archive(root, directory);
  assert.equal(result.ok, true);
  assert.ok(fs.existsSync(path.join(result.archived_to, 'demo.md')));
  assert.equal(spec.load(root, 'cli/runtime').rules.length, 3);
});

test('two TASK sections in one document finish concurrently and preserve both verifications', async t => {
  const root = h.project(t); h.spec(root);
  const file = h.tasks(root, [
    { id: 'TASK-001', status: 'in-progress', tests: [{ id: 'one', argv: [process.execPath, '-e', 'process.exit(0)'] }] },
    { id: 'TASK-002', status: 'in-progress', tests: [{ id: 'two', argv: [process.execPath, '-e', 'process.exit(0)'] }] }
  ]);
  const results = await Promise.all([task.finish(root, file, 'TASK-001'), task.finish(root, file, 'TASK-002')]);
  assert.deepEqual(results.map(item => item.ok), [true, true]);
  const document = task.loadDocument(root, file);
  assert.deepEqual(document.tasks.map(item => item.status), ['done', 'done']);
  assert.equal((document.body.match(/PASS commands=1\/1/g) || []).length, 2);
});
