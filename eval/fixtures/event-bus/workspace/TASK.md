# Event bus

`src/index.js` exports `createBus()`. Keep the public shape.

Required behavior:

- `on(event, handler)` registers a listener and returns an unsubscribe function.
- `off(event, handler)` removes the listener; removing an unknown handler is a no-op.
- `once(event, handler)` registers a listener that fires at most once. `off(event, handler)` with the original handler removes it before it fires.
- `emit(event, ...args)` calls listeners in registration order using a snapshot: listeners added or removed during the current emit do not affect the current dispatch.
- If a listener throws, later listeners still run. After all listeners run, `emit` throws an `AggregateError` containing the thrown errors, if any.

Keep `src/index.js` working. Add tests.
