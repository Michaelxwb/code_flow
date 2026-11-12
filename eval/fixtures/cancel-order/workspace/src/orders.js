'use strict';

function createStore() {
  const stock = new Map(), prices = new Map(), orders = new Map();
  return {
    addProduct(id, quantity, priceCents = 0) {
      stock.set(id, (stock.get(id) ?? 0) + quantity);
      prices.set(id, priceCents);
    },
    stock(id) { return stock.get(id) ?? 0; },
    place(orderId, productId, quantity, now = Date.now()) {
      if ((stock.get(productId) ?? 0) < quantity) throw new Error('out of stock');
      stock.set(productId, stock.get(productId) - quantity);
      orders.set(orderId, { id: orderId, productId, quantity, now,
        totalCents: quantity * (prices.get(productId) ?? 0), status: 'placed' });
      return orders.get(orderId);
    },
    ship(orderId) {
      const order = orders.get(orderId);
      if (!order) throw new Error('unknown order');
      order.status = 'shipped';
      return order;
    },
    cancel(orderId) {
      const order = orders.get(orderId);
      if (!order) throw new Error('unknown order');
      order.status = 'cancelled';
      return order;
    },
    order(orderId) { return orders.get(orderId); }
  };
}

module.exports = { createStore };
