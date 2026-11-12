'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { words } = require('../words');

test('splits on whitespace', () => {
  assert.deepEqual(words(' one  two '), ['one', 'two']);
  assert.deepEqual(words(''), []);
});
