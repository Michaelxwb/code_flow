# Implement retry

`src/retry.js` exports `retry(operation, options)`.

- `attempts` defaults to 3; `baseDelayMs` defaults to 10.
- `operation` receives the 1-based attempt number.
- Retry failed operations; when attempts are exhausted, throw the last error.
- Keep the export. Add tests.
