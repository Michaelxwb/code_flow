'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { retryAll } = require('../src/batch');

test('returns results and the company ledger', async () => {
  const outcome = await retryAll([async () => 1]);
  assert.deepEqual(outcome.results, [1]);
  assert.deepEqual(outcome.ledger, [{ seq: 1, ref: null, outcome: 'PASS' }]);
});
