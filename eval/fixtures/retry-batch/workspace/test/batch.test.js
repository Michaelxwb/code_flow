'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { retryAll } = require('../src/batch');

test('runs operations in order', async () => {
  assert.deepEqual(await retryAll([async () => 1, async () => 2]), [1, 2]);
});
