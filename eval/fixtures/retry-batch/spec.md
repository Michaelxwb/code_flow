---
{"description":"project retry and batch policy","next_rule":3}
---
## Rules

- [RULE-001] Retry policy: only errors with `retryable === true` are retried; a non-retryable error is thrown immediately. The delay before the next attempt is `min(1000, baseDelayMs * 2 ** (attempt - 1) * (0.5 + (attempt % 3) * 0.25))`, rounded. Do not sleep after the final attempt. `retry` accepts an optional `sleep(ms)` function (default a promise around setTimeout) so tests can record delays.
- [RULE-002] `retryAll` runs every operation even if one fails, preserves input order, and returns `{ results, errors }`: `results[i]` is the value or `undefined`, `errors[i]` is the error or `undefined`. Use the same retry options. Do not stop on the first failure.
