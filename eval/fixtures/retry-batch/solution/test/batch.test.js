'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { retryAll } = require('../src/batch');

test('returns results and errors in order', async () => {
  const outcome = await retryAll([async () => 1, async () => 2]);
  assert.deepEqual(outcome.results, [1, 2]);
  assert.deepEqual(outcome.errors, [undefined, undefined]);
});
