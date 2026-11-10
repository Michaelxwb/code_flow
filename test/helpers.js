'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const fm = require('../lib/frontmatter');
const f = require('../lib/fs');

const DEFAULT_TASK = '.code-flow/tasks/2026-11-10/demo/demo.md';

function project(t, settings = {}) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'cf-v1-')));
  t.after(() => {
    fs.rmSync(f.transientRoot(root), { recursive: true, force: true });
    fs.rmSync(root, { recursive: true, force: true });
  });
  fs.mkdirSync(path.join(root, '.code-flow/specs/cli'), { recursive: true });
  fs.writeFileSync(path.join(root, '.code-flow/config.json'), JSON.stringify({ version: 1, ...settings }));
  return root;
}

function write(root, relative, text) {
  const file = path.join(root, relative);
  fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, text);
  return file;
}

function spec(root, id = 'cli/runtime', rule = 'Current rule.') {
  return write(root, '.code-flow/specs/' + id + '.md', fm.create(
    { description: id + ' rules', next_rule: 2 }, '## Rules\n\n- [RULE-001] ' + rule + '\n'));
}

function list(value) {
  return Array.isArray(value) ? value.join(', ') : '';
}

function section(task, id) {
  const fields = [
    ['Status', task.status || 'draft'],
    ['Depends', list(task.depends)],
    ['Source', task.source || ''],
    ['Scenarios', list(task.scenarios)],
    ['Spec-Refs', list(task.spec_refs || task.specRefs || ['cli/runtime'])],
    ['Paths', list(task.paths)],
    ['E2E', task.e2e || ''],
    ['Skip-Tests', task.skip_tests === undefined ? '' : String(task.skip_tests)],
    ['Skip-Reason', task.skip_reason || '']
  ];
  const tests = JSON.stringify(task.tests || [
    { id: 'unit', argv: [process.execPath, '-e', 'process.exit(0)'] }
  ], null, 2);
  const delta = JSON.stringify(task.spec_delta || task.specDelta || [], null, 2);
  return ['## ' + id + ': Demo', '',
    ...fields.map(([name, value]) => '- **' + name + '**:' + (value ? ' ' + value : '')), '',
    '### Tests', '', '```json', tests, '```', '',
    '### Description', '', 'Deliver behavior.', '',
    '### Checklist', '', '- [ ] Deliver behavior.', '',
    '### Spec Delta', '', '```json', delta, '```', '',
    '### Log', '', '- [2026-11-10] created', ''].join('\n');
}

function taskDocument(root, items, relative = DEFAULT_TASK) {
  const requirement = path.basename(relative, '.md');
  const body = '# Tasks: ' + requirement + '\n\n' + items.map((item, index) =>
    section(item, item.id || 'TASK-' + String(index + 1).padStart(3, '0'))).join('\n');
  const text = fm.create({ version: 1, requirement }, body);
  write(root, relative, text);
  return relative;
}

function task(root, overrides = {}, relative = DEFAULT_TASK) {
  return taskDocument(root, [overrides], relative);
}

function tasks(root, items, relative = DEFAULT_TASK) {
  return taskDocument(root, items, relative);
}

module.exports = { project, write, spec, task, tasks };
