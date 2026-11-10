'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const h = require('./helpers');
const verify = require('../lib/verify');
const locks = require('../lib/locks');
const f = require('../lib/fs');
const settings = { timeoutSeconds: 5, jobs: 3 };
function command(id, code, extra = {}) {
  return { id, argv: [process.execPath, '-e', code], ...extra };
}

test('executes actual argv and shell commands, dedupes only within a call', async t => {
  const root = h.project(t);
  const tests = [command('a', 'console.log("actual")'), command('duplicate', 'console.log("actual")'),
    { id: 'shell', run: '"' + process.execPath + '" -e "process.exit(0)"' }];
  const result = await verify.run(root, tests, settings);
  assert.equal(result.ok, true); assert.equal(result.executed, 2); assert.equal(result.deduped, 1);
  assert.equal(result.results[0].stdout.trim(), 'actual');
  assert.equal(result.results[1].duplicate, true);
  assert.equal((await verify.run(root, tests, settings)).executed, 2);
});

test('failures cancel queued work and preserve actual failure kinds', async t => {
  const root = h.project(t);
  const failed = await verify.run(root, [command('fail', 'process.exit(7)'), command('never', 'process.exit(0)')], settings);
  assert.equal(failed.ok, false);
  assert.equal(failed.results[0].exit_code, 7);
  assert.equal(failed.results[1].status, 'not-run');
  const missing = await verify.run(root, [{ id: 'missing', argv: ['code-flow-missing-executable-unique'] }], settings);
  assert.equal(missing.results[0].status, 'spawn-error');
  const timeout = await verify.run(root, [command('slow', 'setInterval(()=>{},1000)', { timeout: 0.1 })], settings);
  assert.equal(timeout.results[0].status, 'timeout');
});

test('streamed output remains bounded even for enormous lines', async t => {
  const root = h.project(t);
  const result = await verify.run(root, [command('noisy', 'process.stdout.write("x".repeat(2000000)); process.stderr.write("line\\n".repeat(10000))')], settings);
  assert.equal(result.ok, true);
  assert.ok(Buffer.byteLength(result.results[0].stdout) <= 65536);
  assert.ok(result.results[0].stderr.split('\n').length <= 50);
});

test('independent commands overlap, resource groups serialize and barriers wait', async t => {
  const root = h.project(t);
  const code = id => 'const fs=require("fs");const id=' + JSON.stringify(id) + ';' +
    'fs.appendFileSync("times",JSON.stringify([id,"start",Date.now()])+"\\n");' +
    'function finish(){fs.appendFileSync("times",JSON.stringify([id,"end",Date.now()])+"\\n")}' +
    'if(id==="a"||id==="c"){const other=id==="a"?"c":"a";const timer=setInterval(()=>{' +
    'if(fs.readFileSync("times","utf8").includes(JSON.stringify([other,"start"]).slice(0,-1))){' +
    'clearInterval(timer);setTimeout(finish,30)}},5)}else setTimeout(finish,40)';
  const tests = [command('a', code('a'), { parallel: true, group: 'db' }),
    command('b', code('b'), { parallel: true, group: 'db' }),
    command('c', code('c'), { parallel: true, group: 'other' }),
    command('barrier', code('barrier')),
    command('after', code('after'), { parallel: true })];
  const result = await verify.run(root, tests, settings);
  assert.equal(result.ok, true);
  const times = Object.fromEntries(fs.readFileSync(path.join(root, 'times'), 'utf8').trim().split('\n')
    .map(line => { const [id, kind, time] = JSON.parse(line); return [id + ':' + kind, time]; }));
  assert.ok(times['b:start'] >= times['a:end']);
  assert.ok(times['c:start'] < times['a:end'] && times['a:start'] < times['c:end']);
  assert.ok(times['barrier:start'] >= times['b:end']);
  assert.ok(times['after:start'] >= times['barrier:end']);
});

test('cwd cannot escape and timeout/parallel fields are strict', t => {
  const root = h.project(t);
  assert.throws(() => verify.prepare(root, [command('bad', '0', { cwd: '..' })], settings), /path/i);
  assert.throws(() => verify.prepare(root, [command('bad', '0', { parallel: 'true' })], settings), /boolean/);
  assert.throws(() => verify.prepare(root, [command('bad', '0', { timeout: 0 })], settings), /positive/);
});

test('runner and per-test env are applied, reserved identity cannot be overridden', async t => {
  const root = h.project(t);
  const code = 'process.stdout.write(JSON.stringify({task:process.env.CF_TASK_IDS,value:process.env.CF_TEST_VALUE}))';
  const result = await verify.run(root, [command('env', code, { env: { CF_TEST_VALUE: 'one' } })], settings,
    { env: { CF_TASK_IDS: 'TASK-001,TASK-002', CF_TASK_ID: '' } });
  assert.equal(result.ok, true);
  assert.deepEqual(JSON.parse(result.results[0].stdout), { task: 'TASK-001,TASK-002', value: 'one' });
  assert.throws(() => verify.prepare(root, [command('reserved', '0', { env: { CF_TASK_ID: 'TASK-003' } })], settings),
    /cannot override/);
  const distinct = await verify.run(root, [command('a', code, { env: { CF_TEST_VALUE: 'a' } }),
    command('b', code, { env: { CF_TEST_VALUE: 'b' } })], settings);
  assert.equal(distinct.executed, 2);
  process.env.CF_TASK_ID = 'STALE';
  try {
    assert.throws(() => verify.prepare(root, [command('conflict', '0')], settings,
      { CF_TASK_ID: 'TASK-001' }), /does not match/);
  } finally { delete process.env.CF_TASK_ID; }
});

test('repository group locks serialize commands and report lock timeout', async t => {
  const root = h.project(t);
  const held = f.acquireIn(locks.directory(root), 'group:database');
  const blocked = await verify.run(root, [command('blocked', 'process.exit(0)', { group: 'database', timeout: 0.1 })], settings);
  assert.equal(blocked.results[0].status, 'lock-timeout');
  f.releaseLock(held);
  const passed = await verify.run(root, [command('free', 'process.exit(0)', { group: 'database', timeout: 2 })], settings);
  assert.equal(passed.ok, true);
  const again = f.acquireIn(locks.directory(root), 'group:database');
  f.releaseLock(again);
});

test('timeout reaps child processes rather than leaving background work', async t => {
  if (process.platform === 'win32') return;
  const root = h.project(t);
  const code = 'const fs=require("fs");const {spawn}=require("child_process");' +
    'const p=spawn(process.execPath,["-e","setInterval(()=>{},1000)"],{stdio:"inherit"});' +
    'fs.writeFileSync("child.pid",String(p.pid));setInterval(()=>{},1000)';
  const result = await verify.run(root, [command('tree', code, { timeout: 1 })], settings);
  assert.equal(result.results[0].status, 'timeout');
  const pid = Number(fs.readFileSync(path.join(root, 'child.pid'), 'utf8'));
  let alive = true;
  for (let i = 0; i < 20 && alive; i++) {
    try { process.kill(pid, 0); await new Promise(resolve => setTimeout(resolve, 25)); }
    catch (error) { assert.equal(error.code, 'ESRCH'); alive = false; }
  }
  assert.equal(alive, false);
});
