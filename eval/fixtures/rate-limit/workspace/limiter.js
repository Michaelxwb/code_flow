'use strict';

class Limiter {
  constructor({ limit, windowMs }) {
    this.limit = limit;
    this.windowMs = windowMs;
    this.windows = new Map();
  }

  allow(key, now) {
    const start = Math.floor(now / this.windowMs) * this.windowMs;
    const entry = this.windows.get(key);
    if (!entry || entry.start !== start) {
      this.windows.set(key, { start, count: 1 });
      return true;
    }
    if (entry.count >= this.limit) return false;
    entry.count++;
    return true;
  }
}

module.exports = { Limiter };
