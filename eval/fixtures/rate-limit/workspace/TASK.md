# Fix the rate limiter

The current `Limiter` uses a fixed-window counter. Implement a sliding window:

- `allow(key, now)` returns true if fewer than `limit` allowed events for `key` fall in `(now - windowMs, now]`, counting the current call;
- otherwise it returns false and records no event;
- keys are independent;
- `now` is supplied by the caller in milliseconds.

Keep the constructor shape `new Limiter({ limit, windowMs })`. Add tests.
