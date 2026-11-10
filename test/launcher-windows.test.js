'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const h = require('./helpers');
const init = require('../lib/init');

function prompt(root, file) {
  return JSON.stringify({ cwd: root, session_id: 'windows', prompt: 'task: ' + file + '#TASK-001' });
}

test('Windows CMD and PowerShell launchers preserve prompt context', { skip: process.platform !== 'win32' }, async t => {
  const root = h.project(t);
  await init.init(root, { platform: 'codex' });
  h.spec(root);
  const file = h.task(root);
  const input = prompt(root, file);
  const cmd = spawnSync('cmd.exe', ['/d', '/c', 'call .code-flow\\launcher\\hook.cmd codex'],
    { cwd: root, input, encoding: 'utf8' });
  assert.equal(cmd.status, 0, cmd.stderr);
  assert.ok(JSON.parse(cmd.stdout).hookSpecificOutput.additionalContext.includes('Current rule.'));
  const powershell = spawnSync('powershell.exe',
    ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', path.join('.code-flow', 'launcher', 'hook.ps1'), '-Format', 'codex'],
    { cwd: root, input, encoding: 'utf8' });
  assert.equal(powershell.status, 0, powershell.stderr);
  assert.ok(JSON.parse(powershell.stdout).hookSpecificOutput.additionalContext.includes('Current rule.'));
});
