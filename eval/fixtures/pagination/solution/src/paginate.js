'use strict';

function paginate(items, { limit = 10, cursor = null } = {}) {
  const size = Math.min(100, Math.max(1, Number.isSafeInteger(Number(limit)) ? Number(limit) : 10));
  const sorted = [...items].sort((left, right) => left.id.localeCompare(right.id));
  let start = 0;
  if (cursor !== null) {
    const index = sorted.findIndex(item => item.id === cursor);
    if (index < 0) throw new Error('Invalid cursor: ' + cursor);
    start = index + 1;
  }
  const page = sorted.slice(start, start + size);
  return { items: page, nextCursor: start + size < sorted.length ? page.at(-1).id : null };
}

module.exports = { paginate };
