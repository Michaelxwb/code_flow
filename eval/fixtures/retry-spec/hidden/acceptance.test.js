'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { retry } = require('../src/retry');

test('retries only retryable errors', async () => {
  let calls = 0;
  const fatal = Object.assign(new Error('fatal'), { retryable: false });
  await assert.rejects(retry(async () => { calls++; throw fatal; }, { attempts: 3 }), /fatal/);
  assert.equal(calls, 1);
  let count = 0;
  const value = await retry(async attempt => {
    count++;
    if (count < 3) throw Object.assign(new Error('again'), { retryable: true });
    return attempt;
  }, { attempts: 3, sleep: () => {} });
  assert.equal(value, 3);
});

test('caps and jitters delays using the injected sleep', async () => {
  const error = Object.assign(new Error('x'), { retryable: true });
  const delays = [];
  await assert.rejects(retry(async () => { throw error; },
    { attempts: 4, baseDelayMs: 100, sleep: ms => delays.push(ms) }));
  assert.deepEqual(delays, [75, 200, 200]);
  const capped = [];
  await assert.rejects(retry(async () => { throw error; },
    { attempts: 3, baseDelayMs: 1000, sleep: ms => capped.push(ms) }));
  assert.deepEqual(capped, [750, 1000]);
});
