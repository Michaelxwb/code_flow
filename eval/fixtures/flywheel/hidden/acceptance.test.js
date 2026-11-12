'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { retryAll } = require('../src/batch');

test('returns results and the ordered company ledger', async () => {
  const first = async () => 1;
  first.id = 'A';
  const bad = async () => { throw Object.assign(new Error('bad'), { retryable: false }); };
  bad.id = 'B';
  const last = async () => 3;
  last.id = 'C';
  const outcome = await retryAll([first, bad, last], { sleep: () => {} });
  assert.deepEqual(outcome.results, [1, undefined, 3]);
  assert.deepEqual(outcome.ledger, [
    { seq: 1, ref: 'A', outcome: 'PASS' },
    { seq: 2, ref: 'B', outcome: 'FAIL_RETRY_EXHAUSTED' },
    { seq: 3, ref: 'C', outcome: 'PASS' }
  ]);
});
