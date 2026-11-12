'use strict';

function paginate(items, { limit = 10, cursor = null } = {}) {
  const start = cursor === null ? 0 : Number(cursor);
  return { items: items.slice(start, start + limit), nextCursor: null };
}

module.exports = { paginate };
