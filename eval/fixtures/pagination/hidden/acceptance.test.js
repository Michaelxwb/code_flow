'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { paginate } = require('../src/paginate');

test('sorts by id and paginates with a stable cursor', () => {
  const items = [{ id: 'c' }, { id: 'a' }, { id: 'b' }];
  const first = paginate(items, { limit: 2 });
  assert.deepEqual(first.items.map(item => item.id), ['a', 'b']);
  assert.ok(first.nextCursor !== null);
  const second = paginate(items, { limit: 2, cursor: first.nextCursor });
  assert.deepEqual(second.items.map(item => item.id), ['c']);
  assert.equal(second.nextCursor, null);
});

test('clamps limit and handles empty input and invalid cursors', () => {
  const items = Array.from({ length: 5 }, (_, index) => ({ id: String(index) }));
  assert.equal(paginate(items, { limit: 0 }).items.length, 1);
  assert.equal(paginate(items, { limit: 500 }).items.length, 5);
  assert.deepEqual(paginate([], { limit: 2 }), { items: [], nextCursor: null });
  assert.throws(() => paginate([{ id: 'a' }], { cursor: 'missing' }), /cursor/i);
});

test('does not duplicate items added after the first page', () => {
  const items = [{ id: 'a' }, { id: 'c' }];
  const first = paginate(items, { limit: 1 });
  items.push({ id: 'b' });
  const second = paginate(items, { limit: 5, cursor: first.nextCursor });
  assert.deepEqual(second.items.map(item => item.id), ['b', 'c']);
});
