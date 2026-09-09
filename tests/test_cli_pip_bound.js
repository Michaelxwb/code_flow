#!/usr/bin/env node
'use strict';

// [S-10] pip bounded-wait unit tests. Run via `node tests/test_cli_pip_bound.js`.

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const CLI_PATH = path.resolve(__dirname, '..', 'src', 'cli.js');

function loadCliInternals() {
  const src = fs.readFileSync(CLI_PATH, 'utf8');
  const cut = src.indexOf('// --- CLI argument parsing ---');
  if (cut === -1) throw new Error('cli.js sentinel comment moved');
  const head = src.slice(0, cut);
  const wrapped = head + '\nmodule.exports = { ensurePyYaml, PIP_PER_ATTEMPT_MS, PIP_TOTAL_MS };\n';
  const tmp = path.join(path.dirname(CLI_PATH), `.cli-pip-test-${process.pid}.js`);
  fs.writeFileSync(tmp, wrapped);
  try {
    delete require.cache[require.resolve(tmp)];
    return require(tmp);
  } finally {
    try { fs.unlinkSync(tmp); } catch (_) { /* ignore */ }
  }
}

const { ensurePyYaml, PIP_PER_ATTEMPT_MS, PIP_TOTAL_MS } = loadCliInternals();

function testProbeHitIsSilentAndSingleCall() {
  const calls = [];
  const logs = [];
  ensurePyYaml(
    (cmd, args, opts) => { calls.push({ cmd, args, opts }); return { status: 0 }; },
    (message) => logs.push(message),
    () => 0
  );
  assert.equal(calls.length, 1, 'probe hit must not fall through to installs');
  assert.deepEqual(logs, [], 'fast path must stay silent');
}

function testFailuresAreBoundedWithProgressAndTimeouts() {
  const calls = [];
  const logs = [];
  let clock = 1000;
  ensurePyYaml(
    (cmd, args, opts) => { calls.push({ cmd, args, opts }); return { status: 1 }; },
    (message) => logs.push(message),
    () => { clock += 1000; return clock; }
  );
  const installs = calls.slice(1);
  assert.equal(installs.length, 3, 'all three PEP 668 fallbacks attempted');
  for (const call of installs) {
    assert.ok(call.opts.timeout <= PIP_PER_ATTEMPT_MS, 'per-attempt timeout bounded');
  }
  assert.equal(logs.filter((line) => line.startsWith('Installing pyyaml')).length, 3, 'progress per attempt');
  assert.ok(logs.some((line) => line.startsWith('Warning: pyyaml install failed')), 'explicit failure state');
}

function testTotalBudgetCapsAttempts() {
  const calls = [];
  let clock = 0;
  ensurePyYaml(
    (cmd, args, opts) => { calls.push(opts); return { status: 1 }; },
    () => {},
    () => { clock += PIP_TOTAL_MS; return clock; }
  );
  assert.ok(calls.length <= 2, 'exhausted total budget stops looping');
}

assert.equal(PIP_PER_ATTEMPT_MS, 60000);
assert.equal(PIP_TOTAL_MS, 120000);
testProbeHitIsSilentAndSingleCall();
testFailuresAreBoundedWithProgressAndTimeouts();
testTotalBudgetCapsAttempts();
console.log('All pip bound tests passed.');
