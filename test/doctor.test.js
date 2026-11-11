'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const h = require('./helpers');
const init = require('../lib/init');
const doctor = require('../lib/doctor');
const f = require('../lib/fs');

function empty(t) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'cf-doctor-')));
  t.after(() => { fs.rmSync(f.transientRoot(root), { recursive: true, force: true }); fs.rmSync(root, { recursive: true, force: true }); });
  return root;
}

test('doctor is read-only and reports a healthy initialized project', async t => {
  const root = empty(t);
  await init.init(root, { platform: 'codex' });
  h.spec(root, 'cli/runtime'); h.spec(root, 'shared/base'); h.task(root);
  h.write(root, '.code-flow/config.json', JSON.stringify({ version: 1,
    always: ['shared/base'], paths: { 'cli/**': ['cli/runtime'] } }));
  const before = fs.readdirSync(root).sort();
  const result = doctor.run(root);
  assert.equal(result.schema_version, 1);
  assert.equal(result.ok, true);
  assert.equal(result.summary.error, 0);
  assert.ok(result.summary.unknown >= 1);
  assert.ok(result.checks.some(item => item.code === 'HOST_TRUST_UNKNOWN' && item.status === 'unknown'));
  assert.ok(result.checks.every(item => item.path === null || typeof item.path === 'string'));
  assert.deepEqual(fs.readdirSync(root).sort(), before);
});

test('doctor reports corrupted Specs, Tasks and missing launcher without repairing them', async t => {
  const root = empty(t);
  await init.init(root, { platform: 'codex' });
  h.write(root, '.code-flow/specs/cli/bad.md', 'not a spec');
  h.write(root, '.code-flow/tasks/2026-11-10/bad/bad.md', 'not a task');
  fs.rmSync(path.join(root, '.code-flow/launcher/bridge.cjs'));
  const result = doctor.run(root);
  assert.equal(result.ok, false);
  assert.ok(result.summary.error >= 3);
  assert.ok(result.checks.some(item => item.code === 'SPEC_INVALID'));
  assert.ok(result.checks.some(item => item.code === 'TASK_INVALID'));
  assert.ok(result.checks.some(item => item.code === 'HOOK_ENTRY_MISSING'));
  assert.equal(fs.readFileSync(path.join(root, '.code-flow/specs/cli/bad.md'), 'utf8'), 'not a spec');
});

test('doctor warns when the fixed fallback Node/JS entry is missing', async t => {
  const root = empty(t);
  await init.init(root, { platform: 'codex', node: '/missing/node', entry: '/missing/entry.js' });
  const result = doctor.run(root);
  assert.ok(result.checks.some(item => item.code === 'HOOK_ENTRY_FALLBACK' &&
    item.severity === 'warning'));
  assert.ok(!result.checks.some(item => item.code === 'HOOK_ENTRY_OK'));
});

test('doctor reports missing config Spec references', async t => {
  const root = empty(t);
  await init.init(root, { platform: 'codex' });
  h.write(root, '.code-flow/config.json', JSON.stringify({ version: 1, always: ['missing/rules'] }));
  const result = doctor.run(root);
  assert.equal(result.ok, false);
  assert.ok(result.checks.some(item => item.code === 'SPEC_REF_MISSING' &&
    item.message.includes('missing/rules')));
});

test('doctor reports invalid and unfinished worktree ledgers as diagnostics', async t => {
  const root = empty(t);
  await init.init(root, { platform: 'codex' });
  h.spec(root); h.task(root);
  h.write(root, '.code-flow/worktrees/bad/run.json', '{broken');
  const invalid = doctor.run(root);
  assert.equal(invalid.ok, false);
  assert.ok(invalid.checks.some(item => item.code === 'WORKTREE_LEDGER_INVALID'));
  fs.rmSync(path.join(root, '.code-flow/worktrees/bad'), { recursive: true });
  h.write(root, '.code-flow/worktrees/run/run.json', JSON.stringify({
    version: 1, run_id: 'run', task_file: '.code-flow/tasks/2026-11-10/demo/demo.md',
    status: 'running', coordinator: { root, branch: 'refs/heads/main' },
    worktrees: [], merge: { order: [] }
  }));
  const unfinished = doctor.run(root);
  assert.equal(unfinished.ok, true);
  assert.ok(unfinished.checks.some(item => item.code === 'WORKTREE_RECOVERY_REQUIRED' &&
    item.severity === 'warning'));
});
