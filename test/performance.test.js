'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { performance } = require('node:perf_hooks');
const { spawnSync } = require('node:child_process');
const h = require('./helpers');
const hook = require('../lib/hook');
const session = require('../lib/session');
const verify = require('../lib/verify');
test('bound injection reads only selected files with 500 Specs and 5000 historical Tasks', async t => {
  const root = h.project(t); h.spec(root); const selected = h.task(root, { status: 'in-progress' });
  const selectedId = 'TASK-001';
  for (let i = 0; i < 499; i++) h.spec(root, 'bulk/spec-' + i);
  for (let i = 0; i < 5000; i++) h.write(root, '.code-flow/tasks/2020-01-01/history/TASK-' + i + '.md', 'history need not parse');
  await session.bind(root, session.token(root, 'codex', 'scale'), selected, selectedId);
  const original = fs.readdirSync;
  let scans = 0;
  fs.readdirSync = (...args) => { scans++; return original(...args); };
  let result;
  try { result = hook.build({ cwd: root, session_id: 'scale', prompt: 'continue' }, 'codex'); }
  finally { fs.readdirSync = original; }
  assert.equal(scans, 0, 'Bound route must not enumerate directories');
  assert.ok(result.payload.hookSpecificOutput.additionalContext.includes('Current rule.'));
  const cli = path.resolve(__dirname, '../bin/code-flow.js'), samples = [];
  for (let i = 0; i < 12; i++) {
    const start = performance.now();
    const run = spawnSync(process.execPath, [cli, 'hook', 'prompt', '--format=codex'], {
      cwd: root, input: JSON.stringify({ cwd: root, session_id: 'scale', prompt: 'continue' }), encoding: 'utf8', timeout: 5000
    });
    assert.equal(run.status, 0, run.stderr); JSON.parse(run.stdout); samples.push(performance.now() - start);
  }
  const first = samples[0]; samples.sort((a, b) => a - b);
  t.diagnostic(JSON.stringify({ node: process.version, platform: process.platform, samples: 12, specs: 500, historicalTasks: 5000,
    first_process_ms: first, p50_ms: samples[6], p95_ms: samples[11], directory_scans: scans }));
});
test('plans 1000 declarations without scanning source or collecting framework tests', t => {
  const root = h.project(t);
  const tests = Array.from({ length: 1000 }, (_, i) => ({ id: 'case-' + i, argv: [process.execPath, '-e', ''] }));
  const begin = performance.now();
  const result = verify.prepare(root, tests, { timeoutSeconds: 120, jobs: 2 });
  assert.equal(result.entries.length, 1000); assert.equal(result.commands.length, 1);
  t.diagnostic('1000 command declarations planned in ' + (performance.now() - begin).toFixed(1) + 'ms');
});
