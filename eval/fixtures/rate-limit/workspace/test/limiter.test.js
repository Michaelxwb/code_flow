'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { Limiter } = require('../limiter');

test('limits calls per key', () => {
  const limiter = new Limiter({ limit: 2, windowMs: 1000 });
  assert.equal(limiter.allow('a', 0), true);
  assert.equal(limiter.allow('a', 100), true);
  assert.equal(limiter.allow('a', 200), false);
});
