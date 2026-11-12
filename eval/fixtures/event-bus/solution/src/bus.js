'use strict';

function createBus() {
  const listeners = new Map();
  const remove = (event, target) => {
    const list = listeners.get(event) ?? [];
    listeners.set(event, list.filter(entry =>
      entry !== target && entry.handler !== target && entry.original !== target));
  };
  const add = (event, handler, once = false) => {
    const list = listeners.get(event) ?? [];
    const entry = { handler, original: handler };
    if (once) entry.handler = (...args) => { remove(event, entry); return handler(...args); };
    list.push(entry);
    listeners.set(event, list);
    return () => remove(event, entry);
  };
  return {
    on(event, handler) { return add(event, handler); },
    once(event, handler) { return add(event, handler, true); },
    off(event, handler) { remove(event, handler); },
    emit(event, ...args) {
      const errors = [];
      for (const entry of [...(listeners.get(event) ?? [])]) {
        try { entry.handler(...args); } catch (error) { errors.push(error); }
      }
      if (errors.length) throw new AggregateError(errors, 'listener errors');
    }
  };
}

module.exports = { createBus };
