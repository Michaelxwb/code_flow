'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createStore } = require('../src/orders');

test('cancels a placed order', () => {
  const store = createStore();
  store.addProduct('p', 5, 1000);
  store.place('o', 'p', 2, 0);
  assert.equal(store.cancel('o', 1000).status, 'cancelled');
});
