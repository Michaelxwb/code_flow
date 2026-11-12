# Batch retry (phase B)

Implement `src/batch.js`:

- `retryAll(operations, options)` runs each operation through `src/retry.js`.
- Operations may carry an `id` string.
- Return the per-operation results and the compliance ledger required by the project.
- Keep the exports. Add tests.
