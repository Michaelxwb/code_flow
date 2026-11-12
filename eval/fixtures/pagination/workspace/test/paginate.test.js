'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { paginate } = require('../src/paginate');

test('returns the first page', () => {
  const items = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
  const page = paginate(items, { limit: 2 });
  assert.deepEqual(page.items.map(item => item.id), ['a', 'b']);
});
