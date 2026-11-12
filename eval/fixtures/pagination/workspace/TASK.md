# Cursor pagination

`src/paginate.js` exports `paginate(items, options)`.

Implement:

- `items` is an array of objects with a unique string `id`.
- `options.limit`: default 10; clamp to the integer range 1..100.
- `options.cursor`: `null` for the first page, otherwise a value returned by a previous call.
- Return `{ items, nextCursor }`; `nextCursor` is `null` on the last page.
- Order by `id` ascending (string comparison) regardless of input order.
- The cursor is opaque to callers but must be stable for the same position.
- Invalid cursor values throw an `Error`.
- Items added after the first page must not cause duplicates; a later page continues after the last returned id.

Add tests.
