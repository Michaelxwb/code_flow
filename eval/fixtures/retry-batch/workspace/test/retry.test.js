'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { retry } = require('../src/retry');

test('returns a successful operation', async () => {
  assert.equal(await retry(async () => 1), 1);
});
