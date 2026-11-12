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
      orders.set(orderId, { id: orderId, productId, quantity, placedAt: now,
        totalCents: quantity * (prices.get(productId) ?? 0), status: 'placed' });
      return orders.get(orderId);
    },
    ship(orderId) {
      const order = orders.get(orderId);
      if (!order) throw new Error('unknown order');
      order.status = 'shipped';
      return order;
    },
    cancel(orderId, now = Date.now()) {
      const order = orders.get(orderId);
      if (!order) throw new Error('unknown order');
      if (order.status === 'shipped') throw new Error('shipped order cannot be cancelled');
      if (order.status === 'cancelled') return order;
      stock.set(order.productId, (stock.get(order.productId) ?? 0) + order.quantity);
      order.feeCents = now - order.placedAt <= 24 * 60 * 60 * 1000 ? 0 : Math.floor(order.totalCents * 0.10);
      order.refundCents = order.totalCents - order.feeCents;
      order.status = 'cancelled';
      return order;
    },
    order(orderId) { return orders.get(orderId); }
  };
}

module.exports = { createStore };
