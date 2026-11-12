'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { Limiter } = require('../limiter');

test('uses a sliding window and keeps keys independent', () => {
  const limiter = new Limiter({ limit: 2, windowMs: 1000 });
  assert.equal(limiter.allow('a', 900), true);
  assert.equal(limiter.allow('a', 950), true);
  assert.equal(limiter.allow('a', 1000), false, 'a fixed window would allow this');
  assert.equal(limiter.allow('b', 1000), true);
  assert.equal(limiter.allow('a', 1951), true);
});
