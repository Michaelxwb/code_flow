'use strict';

function createBus() {
  const listeners = new Map();
  return {
    on(event, handler) {
      const list = listeners.get(event) ?? [];
      list.push(handler);
      listeners.set(event, list);
      return () => this.off(event, handler);
    },
    off(event, handler) {
      const list = listeners.get(event) ?? [];
      listeners.set(event, list.filter(item => item !== handler));
    },
    emit(event, ...args) {
      for (const handler of listeners.get(event) ?? []) handler(...args);
    }
  };
}

module.exports = { createBus };
