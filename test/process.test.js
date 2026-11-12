'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const h = require('./helpers');

const CLI = path.resolve(__dirname, '../bin/code-flow.js');

function project(t) {
  const root = h.project(t);
  h.spec(root);
  h.task(root);
  h.write(root, '.code-flow/config.json', JSON.stringify({ version: 1, always: ['cli/runtime'],
    capture: { enabled: true, path: '.code-flow/process' } }));
  return root;
}

function run(root, args) {
  return spawnSync(process.execPath, [CLI, ...args], { cwd: root, encoding: 'utf8', timeout: 30000 });
}

test('process collect writes a cross-platform bundle with events and snapshots', t => {
  const root = project(t);
  const status = run(root, ['task', 'status', '--json']);
  assert.equal(status.status, 0, status.stderr);
  const out = path.join(root, 'bundle');
  const collected = run(root, ['process', 'collect', '--out', out, '--json']);
  assert.equal(collected.status, 0, collected.stderr);
  assert.equal(JSON.parse(collected.stdout).ok, true);
  for (const name of ['events.jsonl', 'task-status.json', 'doctor.json', 'spec-list.json',
    'code-flow/specs', 'code-flow/tasks', 'files.sha256', 'README.txt', 'git-status.txt']) {
    assert.ok(fs.existsSync(path.join(out, name)), name);
  }
  assert.match(fs.readFileSync(path.join(out, 'events.jsonl'), 'utf8'), /"command":"task status"/);
  assert.ok(fs.readFileSync(path.join(out, 'files.sha256'), 'utf8').includes('.code-flow/specs/cli/runtime.md'));
});

test('process collect copies an optional transcript', t => {
  const root = project(t);
  const transcript = h.write(root, 'session.jsonl', '{"type":"user"}\n');
  const out = path.join(root, 'bundle2');
  const collected = run(root, ['process', 'collect', '--out', out, '--transcript', transcript, '--json']);
  assert.equal(collected.status, 0, collected.stderr);
  assert.ok(fs.existsSync(path.join(out, 'transcript.jsonl')));
});
