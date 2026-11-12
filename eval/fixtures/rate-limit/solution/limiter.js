'use strict';

class Limiter {
  constructor({ limit, windowMs }) {
    this.limit = limit;
    this.windowMs = windowMs;
    this.events = new Map();
  }

  allow(key, now) {
    const cutoff = now - this.windowMs;
    const events = (this.events.get(key) ?? []).filter(time => time > cutoff);
    if (events.length >= this.limit) {
      this.events.set(key, events);
      return false;
    }
    events.push(now);
    this.events.set(key, events);
    return true;
  }
}

module.exports = { Limiter };
