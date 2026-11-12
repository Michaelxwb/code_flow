'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { retry } = require('../src/retry');

test('returns a successful operation', async () => {
  assert.equal(await retry(async () => 1), 1);
});

test('retries a failing operation and reports the attempt number', async () => {
  let calls = 0;
  const value = await retry(async attempt => {
    calls++;
    if (calls < 2) throw Object.assign(new Error('again'), { retryable: true });
    return attempt;
  });
  assert.equal(value, 2);
});
