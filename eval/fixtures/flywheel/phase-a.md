# Retry policy (phase A)

Implement `src/retry.js`:

- `attempts` defaults to 3; `baseDelayMs` defaults to 10.
- `operation` receives the 1-based attempt number.
- Retry only errors with `retryable === true`; non-retryable errors are thrown immediately.
- The delay before the next attempt is `min(1000, baseDelayMs * 2 ** (attempt - 1) * (0.5 + (attempt % 3) * 0.25))`, rounded. Do not sleep after the final attempt.
- `retry` accepts an optional `sleep(ms)` function (default a promise around setTimeout) so tests can record delays.

Also record the company compliance ledger contract for the upcoming batch work in the task document's `### Spec Delta` as one `add` Delta targeting `shared/base`:

`Company ledger contract: retryAll must return { results, ledger }. results[i] is the value on success and undefined on failure. ledger[i] is { seq, ref, outcome }; seq is the 1-based position; ref is the operation's id string (or null); outcome is 'PASS' on success and 'FAIL_RETRY_EXHAUSTED' on failure. ledger includes every operation in input order, even after a failure. It must not stop on the first failure.`

Use `evidence`: `company ledger contract decided in phase A`.
