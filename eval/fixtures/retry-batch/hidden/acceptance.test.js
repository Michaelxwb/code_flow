'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { retry } = require('../src/retry');
const { retryAll } = require('../src/batch');

test('retries only retryable errors', async () => {
  let calls = 0;
  const fatal = Object.assign(new Error('fatal'), { retryable: false });
  await assert.rejects(retry(async () => { calls++; throw fatal; }, { attempts: 3 }), /fatal/);
  assert.equal(calls, 1);
  const delays = [];
  await assert.rejects(retry(async () => { throw Object.assign(new Error('x'), { retryable: true }); },
    { attempts: 4, baseDelayMs: 100, sleep: ms => delays.push(ms) }));
  assert.deepEqual(delays, [75, 200, 200]);
});

test('retryAll preserves order, runs every operation and reports per-item outcomes', async () => {
  const error = Object.assign(new Error('bad'), { retryable: false });
  const outcome = await retryAll([
    async () => 1,
    async () => { throw error; },
    async () => 3
  ], { sleep: () => {} });
  assert.deepEqual(outcome.results, [1, undefined, 3]);
  assert.equal(outcome.errors[0], undefined);
  assert.equal(outcome.errors[1], error);
  assert.equal(outcome.errors[2], undefined);
});
