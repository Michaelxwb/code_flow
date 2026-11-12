# Retry and batch

Implement two deliverables:

1. `src/retry.js`: `retry(operation, options)` with `attempts` (default 3) and `baseDelayMs` (default 10). The operation receives the 1-based attempt number. Rethrow the last error when attempts are exhausted.
2. `src/batch.js`: `retryAll(operations, options)` runs each operation through `retry`, preserves input order, and returns per-operation outcomes.

Keep the exports. Add tests.
