'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createBus } = require('../src');

test('registers, emits and removes listeners', () => {
  const bus = createBus(), calls = [];
  const handler = value => calls.push(value);
  bus.on('x', handler);
  bus.emit('x', 1);
  bus.off('x', handler);
  bus.emit('x', 2);
  assert.deepEqual(calls, [1]);
});
