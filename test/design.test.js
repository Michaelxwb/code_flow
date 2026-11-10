'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const project = path.resolve(__dirname, '..');
const read = name => fs.readFileSync(path.join(project, 'docs', name), 'utf8');
const design = read('v1-design.md');

function section(document, start, end) {
  const first = document.indexOf(start);
  const last = document.indexOf(end, first + start.length);
  assert.ok(first >= 0 && last > first, 'Missing or out-of-order document sections');
  return document.slice(first, last);
}
function jsonExamples(document) {
  return [...document.matchAll(/^```json\r?\n([\s\S]*?)^```[ \t]*$/gm)]
    .map(match => JSON.parse(match[1]));
}
function taskSamples() {
  const document = section(design, '### 4.3 Task 文档', '### 4.4 状态转移');
  const headings = [...document.matchAll(/^## (TASK-\d+): .+$/gm)];
  return headings.map((match, index) => ({
    id: match[1],
    text: document.slice(match.index, headings[index + 1]?.index ?? document.length)
  }));
}
function validateDelta(delta) {
  assert.match(delta.id, /^DELTA-\d+$/);
  assert.ok(['add', 'update', 'remove'].includes(delta.op));
  for (const field of ['target', 'evidence']) assert.ok(typeof delta[field] === 'string' && delta[field].length > 0);
  if (delta.op !== 'remove') assert.ok(typeof delta.rule === 'string' && delta.rule.length > 0);
  if (delta.op !== 'add') {
    assert.match(delta.ref, /^RULE-/);
    assert.ok(typeof delta.before === 'string' && delta.before.length > 0);
  }
}

test('all fenced JSON examples in design and usage are valid JSON', () => {
  for (const document of [design, read('USAGE.md')]) {
    assert.ok(jsonExamples(document).length > 0);
  }
});

test('documented multi-TASK sample has distinct identities and valid declared commands', () => {
  const tasks = taskSamples();
  assert.ok(tasks.length > 1);
  assert.equal(new Set(tasks.map(task => task.id)).size, tasks.length);
  for (const task of tasks) {
    const commands = jsonExamples(section(task.text, '### Tests', '### Description'))[0];
    assert.ok(Array.isArray(commands) && commands.length > 0);
    assert.equal(new Set(commands.map(command => command.id)).size, commands.length);
    for (const command of commands) {
      const argv = Object.hasOwn(command, 'argv');
      assert.notEqual(argv, Object.hasOwn(command, 'run'));
      if (argv) {
        assert.ok(Array.isArray(command.argv) && command.argv.length > 0);
        assert.ok(command.argv.every(arg => typeof arg === 'string'));
      } else {
        assert.ok(typeof command.run === 'string' && command.run.trim().length > 0);
      }
    }
    const depends = task.text.match(/^- \*\*Depends\*\*:([^\n]*)/m)[1].trim();
    for (const id of depends.split(',').map(value => value.trim()).filter(Boolean)) {
      assert.ok(tasks.some(candidate => candidate.id === id) && id !== task.id);
    }
  }
});

test('Task, learning and usage examples use direct Delta arrays and agree on the shared add', () => {
  const taskDelta = jsonExamples(section(taskSamples()[0].text, '### Spec Delta', '### Log'))[0];
  const learning = jsonExamples(section(design, '### 8.1 Delta 模型', '### 8.2 校验与预览'))[0];
  const usage = jsonExamples(section(read('USAGE.md'), '## 5. 沉淀与归档', '## 6. 升级'))[0];
  for (const deltas of [taskDelta, learning, usage]) {
    assert.ok(Array.isArray(deltas));
    assert.equal(new Set(deltas.map(delta => delta.id)).size, deltas.length);
    deltas.forEach(validateDelta);
  }
  assert.deepEqual(taskDelta[0], learning[0]);
});

test('ledger example maps each Task, branch, environment and merge order consistently', () => {
  const ledger = jsonExamples(section(design, '### 7.10.3 run ledger', '### 7.10.4 Baseline'))[0];
  assert.equal(ledger.version, 1);
  assert.ok(path.posix.isAbsolute(ledger.coordinator.root));
  assert.ok(path.posix.isAbsolute(ledger.coordinator.git_common_dir));
  assert.match(ledger.coordinator.branch, /^refs\/heads\//);
  assert.deepEqual(ledger.merge.order, ledger.worktrees.map(worker => worker.task));
  assert.equal(new Set(ledger.worktrees.map(worker => worker.path)).size, ledger.worktrees.length);
  assert.equal(new Set(ledger.worktrees.map(worker => worker.branch)).size, ledger.worktrees.length);
  for (const worker of ledger.worktrees) {
    assert.equal(worker.env.CF_TASK_ID, worker.task);
    assert.equal(worker.env.CF_RUN_ID, ledger.run_id);
    assert.equal(worker.env.CF_WORKTREE_ID, ledger.run_id + '/' + worker.task);
    assert.equal(worker.path, '.code-flow/worktrees/' + ledger.run_id + '/' + worker.task);
    assert.equal(worker.base_head, ledger.base_head);
    assert.equal(worker.status, 'prepared');
    assert.equal(worker.collected_head, null);
  }
  assert.equal(ledger.integration.env.CF_RUN_ID, ledger.run_id);
  assert.equal(ledger.integration.env.CF_TASK_IDS, ledger.merge.order.join(','));
  assert.equal(ledger.integration.env.CF_TASK_ID, '');
  assert.equal(ledger.integration.env.CF_WORKTREE_ID, ledger.run_id + '/integration');
  assert.equal(ledger.integration.status, 'not-run');
  assert.equal(ledger.integration.tested_head, null);
});

test('doctor JSON example has actionable diagnostics and accurate overlapping summary counts', () => {
  const report = jsonExamples(section(design, '### 9.6 doctor', '## 10. 分发'))[0];
  assert.equal(report.schema_version, 1);
  const summary = { pass: 0, warning: 0, error: 0, unknown: 0 };
  for (const check of report.checks) {
    assert.match(check.code, /^[A-Z][A-Z_]+$/);
    assert.ok(['info', 'warning', 'error'].includes(check.severity));
    assert.ok(['pass', 'fail', 'unknown'].includes(check.status));
    assert.ok(check.path === null || typeof check.path === 'string');
    assert.ok(check.message.length > 0 && check.next_action.length > 0);
    if (check.status === 'pass') summary.pass++;
    else if (check.severity !== 'info') summary[check.severity]++;
    if (check.status === 'unknown') summary.unknown++;
  }
  assert.deepEqual(report.summary, summary);
});

test('design section references and acceptance IDs resolve without duplicates or gaps', () => {
  const headings = new Set([...design.matchAll(/^#{2,6} (\d+(?:\.\d+)*)(?:[.：: ]|$)/gm)]
    .map(match => match[1]));
  for (const match of design.matchAll(/§(\d+(?:\.\d+)*)/g)) {
    assert.ok(headings.has(match[1]), 'Unresolved section ' + match[0]);
  }
  const ids = [...design.matchAll(/^\| AC-(\d+) \|/gm)].map(match => Number(match[1]));
  assert.ok(ids.length > 0);
  assert.deepEqual(ids, Array.from({ length: ids.length }, (_, index) => index + 1));
  const implementation = read('v1-implementation.md');
  for (const id of ids) {
    assert.match(implementation, new RegExp('AC-' + String(id).padStart(2, '0') + '(?![0-9])'));
  }
});

function guardFixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cf-doc ' $ (guard)-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const block = [...design.matchAll(/^```sh\r?\n([\s\S]*?)^```[ \t]*$/gm)]
    .find(match => match[1].startsWith('# code-flow:launcher-exit-guard\n'));
  assert.ok(block, 'Missing executable launcher guard example');
  const guard = path.join(root, 'hook.sh');
  fs.writeFileSync(guard, block[1]);
  return {
    run: (args, input = '') => spawnSync('/bin/sh', [guard, ...args], { input, encoding: 'utf8', timeout: 5000 }),
    child: source => {
      const entry = path.join(root, "bridge ' $ (entry).cjs");
      fs.writeFileSync(entry, source);
      return entry;
    },
    root
  };
}

test('documented shell guard preserves stdin and literal argv through real processes', { skip: process.platform === 'win32' }, t => {
  const fixture = guardFixture(t);
  const entry = fixture.child("const fs = require('node:fs'); process.stdout.write(JSON.stringify({context: JSON.parse(fs.readFileSync(0, 'utf8')).prompt, argv: process.argv.slice(2)}));");
  const args = ['--format=codex', "literal ' $ (argument)"];
  const result = fixture.run([process.execPath, entry, ...args], '{"prompt":"current session"}');
  assert.equal(result.error, undefined);
  assert.equal(result.status, 0);
  assert.deepEqual(JSON.parse(result.stdout), { context: 'current session', argv: args });
  assert.equal(result.stderr, '');
});

test('documented shell guard discards partial stdout and exits zero when bridge exits two', { skip: process.platform === 'win32' }, t => {
  const fixture = guardFixture(t);
  const entry = fixture.child("process.stdout.write('invalid partial output'); process.stderr.write('child diagnostic'); process.exit(2);");
  const result = fixture.run([process.execPath, entry]);
  assert.equal(result.error, undefined);
  assert.equal(result.status, 0);
  assert.equal(result.stdout, '');
  assert.match(result.stderr, /child diagnostic/);
  assert.match(result.stderr, /launcher failed/);
});

test('documented shell guard handles missing commands and terminated bridge without blocking', { skip: process.platform === 'win32' }, t => {
  const fixture = guardFixture(t);
  const entry = fixture.child("process.stdout.write('partial'); process.kill(process.pid, 'SIGTERM');");
  for (const args of [[], [path.join(fixture.root, 'missing node')], [process.execPath, entry]]) {
    const result = fixture.run(args);
    assert.equal(result.error, undefined);
    assert.equal(result.status, 0);
    assert.equal(result.stdout, '');
    assert.match(result.stderr, /code-flow launcher (missing|failed)/);
  }
});
