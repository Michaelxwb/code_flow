'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const words = require('../words');

test('uniqueWords dedupes case-insensitively and preserves the first spelling', () => {
  assert.deepEqual(words.uniqueWords('Apple banana apple BANANA cherry'), ['Apple', 'banana', 'cherry']);
  assert.deepEqual(words.uniqueWords('  one   ONE  two '), ['one', 'two']);
  assert.deepEqual(words.uniqueWords(''), []);
});

test('words keeps its existing behavior', () => {
  assert.deepEqual(words.words(' one  two '), ['one', 'two']);
});
