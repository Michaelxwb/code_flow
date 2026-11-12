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

test('successful finish checks the TASK checklist and failure leaves it open', async t => {
  const root = h.project(t); h.spec(root);
  const file = h.task(root, { status: 'in-progress' });
  assert.equal((await task.finish(root, file, 'TASK-001')).ok, true);
  let text = fs.readFileSync(path.join(root, file), 'utf8');
  assert.match(text, /### Checklist\n\n- \[x\] Deliver behavior\./);
  h.task(root, { status: 'in-progress', tests: [{ id: 'fail',
    argv: [process.execPath, '-e', 'process.exit(3)'] }] });
  assert.equal((await task.finish(root, file, 'TASK-001')).ok, false);
  text = fs.readFileSync(path.join(root, file), 'utf8');
  assert.match(text, /### Checklist\n\n- \[ \] Deliver behavior\./);
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

test('task lifecycle writes real sections when commands and examples contain heading text', async t => {
  for (const example of ['', '\n~~~md\n### Log\n\n### Verification\n~~~\n']) {
    const root = h.project(t); h.spec(root);
    const file = h.task(root, { tests: [{ id: 'headings', argv: [process.execPath, '-e',
      'console.log("### Log ### Verification")'] }] });
    const location = path.join(root, file);
    const before = fs.readFileSync(location, 'utf8').replace('Deliver behavior.', 'Deliver behavior.' + example);
    fs.writeFileSync(location, before);
    const testsBefore = before.slice(before.indexOf('### Tests'), before.indexOf('### Description'));
    await task.start(root, file, 'TASK-001');
    assert.equal((await task.finish(root, file, 'TASK-001')).ok, true);
    const after = fs.readFileSync(location, 'utf8');
    const realLog = after.slice(after.lastIndexOf('\n### Log\n')).split('\n### Verification\n')[0];
    assert.match(realLog, /started/);
    assert.match(after, /\n### Verification\n\n- .* PASS commands=1\/1/);
    assert.equal(after.slice(after.indexOf('### Tests'), after.indexOf('### Description')), testsBefore);
    if (example) assert.ok(after.includes(example));
  }
});

test('Task document parsing ignores headings inside fenced examples with language markers', t => {
  const root = h.project(t); h.spec(root); const file = h.task(root);
  const example = ['~~~md', '~~~js', '## TASK-999: example', '- **Status**: done', '~~~'].join('\n');
  const location = path.join(root, file);
  fs.writeFileSync(location, fs.readFileSync(location, 'utf8')
    .replace('Deliver behavior.', 'Deliver behavior.\n' + example));
  const document = task.loadDocument(root, file);
  assert.deepEqual(document.tasks.map(item => item.id), ['TASK-001']);
  assert.equal(document.tasks[0].status, 'draft');
});

test('Task fields update real metadata after a fenced example', async t => {
  const root = h.project(t); h.spec(root);
  const file = h.task(root, { status: 'in-progress' }), location = path.join(root, file);
  const example = '\n~~~md\n- **Status**: draft\n- **Source**: example\n~~~\n';
  fs.writeFileSync(location, fs.readFileSync(location, 'utf8')
    .replace('## TASK-001: Demo\n', '## TASK-001: Demo\n' + example));
  assert.equal((await task.finish(root, file, 'TASK-001')).ok, true);
  assert.equal(task.loadTask(root, file, 'TASK-001').status, 'done');
  const updated = taskdoc.updateTask(task.loadDocument(root, file), 'TASK-001', {
    field: 'source', value: 'src/actual.js'
  });
  const after = taskdoc.write(updated);
  assert.ok(after.includes(example));
  assert.equal(taskdoc.parse(after, location).tasks[0].source, 'src/actual.js');
});

test('duplicate Task fields fail before executing tests or changing the document', async t => {
  const root = h.project(t); h.spec(root);
  const file = h.task(root, { status: 'in-progress', tests: [{ id: 'never', argv: [process.execPath,
    '-e', 'require("fs").writeFileSync("executed", "x")'] }] });
  const location = path.join(root, file);
  const before = fs.readFileSync(location, 'utf8') + '\n- **Status**: in-progress\n';
  fs.writeFileSync(location, before);
  await assert.rejects(task.finish(root, file, 'TASK-001'), error => error.code === 'task_field_duplicate');
  assert.equal(fs.readFileSync(location, 'utf8'), before);
  assert.equal(fs.existsSync(path.join(root, 'executed')), false);
});

test('multiline transition reasons remain log text without creating Task sections', async t => {
  const root = h.project(t); h.spec(root);
  const file = h.task(root, { status: 'in-progress' });
  const reason = 'waiting\n## TASK-999: example\n- **Status**: done';
  await task.transition(root, file, 'TASK-001', 'block', reason);
  let document = task.loadDocument(root, file);
  assert.deepEqual(document.tasks.map(item => item.id), ['TASK-001']);
  assert.equal(document.tasks[0].status, 'blocked');
  assert.ok(document.tasks[0].text.includes('waiting ## TASK-999: example - **Status**: done'));
  await task.start(root, file, 'TASK-001');
  await task.finish(root, file, 'TASK-001');
  await task.transition(root, file, 'TASK-001', 'reopen', reason);
  document = task.loadDocument(root, file);
  assert.equal(document.tasks.length, 1);
  assert.equal(document.tasks[0].status, 'in-progress');
});

test('multiline test IDs fail before running commands or writing Verification', async t => {
  for (const newline of ['\n', '\r\n']) {
    const root = h.project(t); h.spec(root);
    const file = h.task(root, { status: 'in-progress', tests: [{ id: 'unit' + newline + '## TASK-999: example',
      argv: [process.execPath, '-e', 'require("fs").writeFileSync("executed", "x")'] }] });
    const location = path.join(root, file), before = fs.readFileSync(location, 'utf8');
    await assert.rejects(task.finish(root, file, 'TASK-001'), error => error.code === 'test_id');
    assert.equal(fs.readFileSync(location, 'utf8'), before);
    assert.equal(fs.existsSync(path.join(root, 'executed')), false);
  }
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
  assert.match(fs.readFileSync(path.join(result.archived_to, 'demo.md'), 'utf8'),
    /### Checklist\n\n- \[x\] Deliver behavior\./);
  assert.equal(spec.load(root, 'cli/runtime').rules.length, 2);
});

test('archive removes an empty date directory and keeps it when other requirements remain', async t => {
  const root = h.project(t); h.spec(root);
  const first = h.task(root, { status: 'done' });
  h.task(root, { status: 'done' }, '.code-flow/tasks/2026-11-10/other/other.md');
  const date = path.join(root, '.code-flow/tasks/2026-11-10');
  await task.archive(root, path.posix.dirname(first));
  assert.ok(fs.existsSync(date));
  await task.archive(root, '.code-flow/tasks/2026-11-10/other');
  assert.equal(fs.existsSync(date), false);
});

function archivedRunLedger(root, file, runId, workerStatus) {
  return JSON.stringify({ version: 1, run_id: runId, task_file: file, status: 'done',
    coordinator: { root, branch: 'refs/heads/main', git_common_dir: path.join(root, '.git') },
    worktrees: [{ task: 'TASK-001', path: '.code-flow/worktrees/' + runId + '/TASK-001',
      branch: 'cf-task/' + runId + '/TASK-001', status: workerStatus }],
    merge: { order: ['TASK-001'] } });
}

test('archive clears completed run ledgers for the requirement', async t => {
  const root = h.project(t); h.spec(root); const file = h.task(root, { status: 'done' });
  h.write(root, '.code-flow/worktrees/run-archive/run.json',
    archivedRunLedger(root, file, 'run-archive', 'removed'));
  h.write(root, '.code-flow/worktrees/run-other/run.json',
    archivedRunLedger(root, '.code-flow/tasks/2026-11-10/other/other.md', 'run-other', 'removed'));
  const result = await task.archive(root, path.posix.dirname(file));
  assert.deepEqual(result.cleared_runs, ['run-archive']);
  assert.equal(fs.existsSync(path.join(root, '.code-flow/worktrees/run-archive')), false);
  assert.ok(fs.existsSync(path.join(root, '.code-flow/worktrees/run-other/run.json')));
});

test('archive refuses to clear a run whose worktree was not cleaned', async t => {
  const root = h.project(t); h.spec(root); const file = h.task(root, { status: 'done' });
  h.write(root, '.code-flow/worktrees/run-dirty/run.json',
    archivedRunLedger(root, file, 'run-dirty', 'merged'));
  await assert.rejects(task.archive(root, path.posix.dirname(file)), /Clean worktrees/);
  assert.ok(fs.existsSync(path.join(root, file)));
  assert.ok(fs.existsSync(path.join(root, '.code-flow/worktrees/run-dirty/run.json')));
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

test('task documents tolerate extra sections and report missing fields precisely', async t => {
  const root = h.project(t); h.spec(root);
  const file = h.task(root, { status: 'in-progress' });
  const location = path.join(root, file);
  fs.writeFileSync(location, fs.readFileSync(location, 'utf8')
    .replace('### Description', '## Notes\n\nFree text must survive.\n\n### Description'));
  const document = task.loadDocument(root, file);
  assert.deepEqual(document.tasks.map(item => item.id), ['TASK-001']);
  assert.ok(document.tasks[0].text.includes('Free text must survive.'));
  assert.equal((await task.finish(root, file)).ok, true);
  assert.ok(fs.readFileSync(location, 'utf8').includes('Free text must survive.'));
  const missing = h.task(root, {}, '.code-flow/tasks/2026-11-10/missing/missing.md');
  fs.writeFileSync(path.join(root, missing), fs.readFileSync(path.join(root, missing), 'utf8')
    .replace('- **Status**: draft', '- **Status**:'));
  assert.throws(() => task.load(root, missing), /TASK-001: missing Status field/);
});

test('task status ignores unrelated markdown in a requirement directory', t => {
  const root = h.project(t); h.spec(root);
  const file = h.task(root);
  h.write(root, path.posix.dirname(file) + '/notes.md', '# scratch\n');
  const listed = task.list(root);
  assert.equal(listed.ok, true);
  assert.equal(listed.items.length, 1);
  assert.equal(listed.ignored, 1);
});

test('scenario references are free-form human assets', t => {
  const root = h.project(t); h.spec(root);
  const file = h.task(root, { scenarios: ['manual-checkout', 'S-01'] });
  assert.deepEqual(task.load(root, file).scenarios, ['manual-checkout', 'S-01']);
});

test('finish records tree and declaration provenance', async t => {
  const root = h.project(t); h.spec(root);
  const file = h.task(root, { tests: [{ id: 'ok', argv: [process.execPath, '-e', 'process.exit(0)'] }] });
  await task.start(root, file);
  assert.match(task.load(root, file).text, /started tests=[a-f0-9]{12}/);
  assert.equal((await task.finish(root, file)).ok, true);
  let summary = task.list(root).items[0];
  assert.match(summary.verification, / tests=[a-f0-9]{12} head=none dirty=unknown/);
  assert.equal(summary.tests_changed, false);
  assert.equal(summary.verified_head, null);
  assert.equal(summary.dirty, null);
  await task.transition(root, file, 'TASK-001', 'reopen', 'recheck');
  const location = path.join(root, file);
  fs.writeFileSync(location, fs.readFileSync(location, 'utf8').replace('"id": "ok"', '"id": "changed"'));
  assert.equal((await task.finish(root, file)).ok, true);
  summary = task.list(root).items[0];
  assert.equal(summary.tests_changed, true);
  assert.match(summary.verification, / tests-changed/);
});
