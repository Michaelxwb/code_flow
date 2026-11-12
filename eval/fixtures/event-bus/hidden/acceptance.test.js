'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createBus } = require('../src');

test('once fires at most once and off removes it before firing', () => {
  const bus = createBus();
  let calls = 0;
  bus.once('x', () => calls++);
  bus.emit('x');
  bus.emit('x');
  assert.equal(calls, 1);
  const other = () => calls++;
  bus.once('y', other);
  bus.off('y', other);
  bus.emit('y');
  assert.equal(calls, 1);
});

test('emit snapshots listeners', () => {
  const bus = createBus(), calls = [];
  const second = () => calls.push('second');
  bus.on('x', () => {
    calls.push('first');
    bus.off('x', second);
    bus.on('x', () => calls.push('late'));
  });
  bus.on('x', second);
  bus.emit('x');
  assert.deepEqual(calls, ['first', 'second']);
  bus.emit('x');
  assert.deepEqual(calls, ['first', 'second', 'first', 'late']);
});

test('listener errors are isolated and aggregated', () => {
  const bus = createBus(), calls = [];
  bus.on('x', () => { throw new Error('one'); });
  bus.on('x', () => calls.push('after'));
  assert.throws(() => bus.emit('x'), error =>
    error instanceof AggregateError && error.errors.length === 1 && calls[0] === 'after');
});
