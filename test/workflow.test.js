'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const h = require('./helpers');
const init = require('../lib/init');
const render = require('../lib/render');
const task = require('../lib/task');
const taskdoc = require('../lib/taskdoc');

test('workflow templates encode the v1 document flow without retired gates', async t => {
  const root = h.project(t);
  await init.init(root, { platform: 'codex' });
  const directory = path.join(root, '.code-flow/templates');
  const names = ['prd.md', 'design-full.md', 'design-lite.md', 'design-frontend.md',
    'scenarios.md', 'task.md', 'project-guidelines.md'];
  const forbidden = /scenarios parse|design lint|acceptance manifest|verify-plan|spec-context\.yml|cf_traceability|\.acceptance-manifest|Stage Gate|task verify/i;
  for (const name of names) {
    const text = fs.readFileSync(path.join(directory, name), 'utf8');
    assert.ok(text.length > 100, name);
    assert.doesNotMatch(text, forbidden, name);
  }
  const scenarios = fs.readFileSync(path.join(directory, 'scenarios.md'), 'utf8');
  assert.match(scenarios, /## S-01 /);
  assert.match(scenarios, /\*\*负责\*\*：TASK-001/);
  assert.match(scenarios, /\*\*前置\*\*/);
  assert.match(scenarios, /\*\*步骤\*\*/);
  assert.match(scenarios, /\*\*期望\*\*/);
  const taskTemplate = fs.readFileSync(path.join(directory, 'task.md'), 'utf8');
  const filled = taskTemplate
    .replaceAll('{requirement}', 'demo')
    .replaceAll('{title}', 'Demo')
    .replaceAll('{design}', 'demo.backend')
    .replaceAll('{section}', '1')
    .replaceAll('{S-01, E-01}', 'S-01, E-01')
    .replaceAll('{spec/path}', 'cli/runtime')
    .replaceAll('{src/**, test/**}', 'src/**, test/**')
    .replaceAll('{ci:e2e or empty}', '')
    .replaceAll('{实现目标}', 'Deliver behavior.')
    .replaceAll('{可验证的步骤}', 'Verify behavior.')
    .replaceAll('{date}', '2026-11-11');
  const relative = '.code-flow/tasks/2026-11-10/demo/demo.md';
  h.write(root, relative, filled);
  const parsed = taskdoc.parse(filled, path.join(root, relative));
  assert.equal(parsed.tasks.length, 1);
  assert.equal(parsed.tasks[0].status, 'draft');
  assert.equal(parsed.tasks[0].tests.length, 1);
  assert.deepEqual(parsed.tasks[0].specRefs, ['cli/runtime']);
  const startSkill = fs.readFileSync(path.join(root, '.agents/skills/cf-task-start/SKILL.md'), 'utf8');
  assert.match(startSkill, /workers/);
  assert.match(startSkill, /CF_\*/);
  assert.match(startSkill, /task parallel collect/);
  assert.match(startSkill, /task parallel merge/);
  assert.match(startSkill, /task parallel cleanup/);
  assert.doesNotMatch(startSkill, /tests\s*→\s*finish/);
});

test('document flow artifacts feed one multi-TASK plan through finish and archive', async t => {
  const root = h.project(t);
  await init.init(root, { platform: 'codex' });
  h.spec(root, 'cli/runtime', 'Checkout rule.');
  const relative = '.code-flow/tasks/2026-11-11/checkout/checkout.md';
  h.write(root, '.code-flow/tasks/2026-11-11/checkout/checkout.prd.md',
    '# PRD: checkout\n\n## 1. Goal\n\nUS-01: user checks out.\n');
  h.write(root, '.code-flow/tasks/2026-11-11/checkout/checkout.frontend.design.md',
    '# Checkout frontend\n\nFEAT-01 renders the form.\n\nScenarios: S-01, E-01.\n');
  h.write(root, '.code-flow/tasks/2026-11-11/checkout/checkout.backend.design.md',
    '# Checkout backend\n\nAPI-01 persists the order.\n');
  h.write(root, '.code-flow/tasks/2026-11-11/checkout/checkout.scenarios.md',
    '---\nschema: 1\nrequirement: checkout\n---\n\n## S-01\n\n- level: manual\n- boundary: browser -> API -> db\n- expected: order exists\n- owner: TASK-001\n');
  const file = h.tasks(root, [
    { id: 'TASK-001', source: 'checkout.frontend.design.md#FEAT-01', scenarios: ['S-01'],
      paths: ['web/**'] },
    { id: 'TASK-002', depends: ['TASK-001'], source: 'checkout.backend.design.md#API-01',
      scenarios: ['E-01'], paths: ['server/**'] }
  ], relative);
  const listed = task.list(root);
  assert.equal(listed.ok, true);
  assert.deepEqual(listed.items.map(item => item.task_id), ['TASK-001', 'TASK-002']);
  assert.deepEqual(taskdoc.batches(task.loadDocument(root, file).tasks), [['TASK-001'], ['TASK-002']]);
  const injected = render.inject(root, { taskFile: file, taskId: 'TASK-001' });
  assert.ok(injected.text.includes('Checkout rule.'));
  assert.ok(injected.text.includes('TASK-001'));
  await task.start(root, file, 'TASK-001');
  assert.equal((await task.finish(root, file, 'TASK-001')).ok, true);
  await task.start(root, file, 'TASK-002');
  assert.equal((await task.finish(root, file, 'TASK-002')).ok, true);
  assert.deepEqual(task.loadDocument(root, file).tasks.map(item => item.status), ['done', 'done']);
  const archived = await task.archive(root, path.posix.dirname(file));
  assert.equal(archived.ok, true);
  for (const name of ['checkout.prd.md', 'checkout.frontend.design.md',
    'checkout.backend.design.md', 'checkout.scenarios.md', 'checkout.md']) {
    assert.ok(fs.existsSync(path.join(archived.archived_to, name)), name);
  }
  assert.equal(fs.existsSync(path.join(root, '.acceptance-manifest.json')), false);
});

test('manual scenarios never block finish or archive and create no manifest', async t => {
  const root = h.project(t);
  h.spec(root);
  const file = h.task(root, { status: 'in-progress', scenarios: ['S-01', 'E-01', 'B-01'] });
  const finished = await task.finish(root, file, 'TASK-001');
  assert.equal(finished.ok, true);
  assert.equal(task.load(root, file).meta.status, 'done');
  const archived = await task.archive(root, path.posix.dirname(file));
  assert.equal(archived.ok, true);
  assert.ok(fs.existsSync(archived.archived_to));
  assert.equal(fs.existsSync(path.join(root, '.acceptance-manifest.json')), false);
  assert.equal(fs.existsSync(path.join(root, '.code-flow/.acceptance-manifest.json')), false);
});
