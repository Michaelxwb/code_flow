'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { parseLine } = require('../csv');

test('parses quotes, escaped quotes, empty fields and empty lines', () => {
  assert.deepEqual(parseLine('a,"b,c","d""e",'), ['a', 'b,c', 'd"e', '']);
  assert.deepEqual(parseLine(''), ['']);
  assert.deepEqual(parseLine('"a""b"'), ['a"b']);
  assert.deepEqual(parseLine('a,,c'), ['a', '', 'c']);
});
