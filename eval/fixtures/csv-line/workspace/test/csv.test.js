'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { parseLine } = require('../csv');

test('splits simple fields', () => {
  assert.deepEqual(parseLine('a,b,c'), ['a', 'b', 'c']);
});
