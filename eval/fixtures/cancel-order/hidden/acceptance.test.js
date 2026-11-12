'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createStore } = require('../src/orders');

function setup(priceCents = 1000, quantity = 2) {
  const store = createStore();
  store.addProduct('p', 5, priceCents);
  store.place('o', 'p', quantity, 0);
  return store;
}

test('free cancellation within 24 hours is idempotent', () => {
  const store = setup();
  store.cancel('o', 60 * 60 * 1000);
  assert.equal(store.stock('p'), 5);
  assert.equal(store.order('o').status, 'cancelled');
  assert.equal(store.order('o').feeCents, 0);
  assert.equal(store.order('o').refundCents, 2000);
  store.cancel('o', 2 * 60 * 60 * 1000);
  assert.equal(store.stock('p'), 5);
  assert.equal(store.order('o').feeCents, 0);
  assert.equal(store.order('o').refundCents, 2000);
});

test('late cancellation applies a floor-rounded 10% fee', () => {
  const store = setup(1000, 2);
  store.cancel('o', 25 * 60 * 60 * 1000);
  assert.equal(store.order('o').feeCents, 200);
  assert.equal(store.order('o').refundCents, 1800);
  assert.equal(store.stock('p'), 5);
  const odd = setup(999, 1);
  odd.cancel('o', 25 * 60 * 60 * 1000);
  assert.equal(odd.order('o').feeCents, 99);
  assert.equal(odd.order('o').refundCents, 900);
});

test('boundary at 24 hours is free; shipped and unknown are rejected', () => {
  const boundary = setup();
  boundary.cancel('o', 24 * 60 * 60 * 1000);
  assert.equal(boundary.order('o').feeCents, 0);
  const shipped = setup();
  shipped.ship('o');
  assert.throws(() => shipped.cancel('o', 1000), /shipped/i);
  assert.equal(shipped.stock('p'), 3);
  assert.equal(shipped.order('o').status, 'shipped');
  const unknown = setup();
  assert.throws(() => unknown.cancel('missing', 1000), /unknown/i);
});
