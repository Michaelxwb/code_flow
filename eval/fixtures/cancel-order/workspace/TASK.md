# Cancel an order

Customers can cancel an order after placing it.

- Cancelling restores the reserved stock and shows the order status.
- It must be safe to click cancel twice: stock and money must not be applied twice.
- Shipped orders must not be cancelled.
- Cancellation is free within 24 hours of placing (inclusive). After 24 hours, a 10% cancellation fee applies to the order total, rounded down to cents.
- After cancellation the order exposes `feeCents` and `refundCents`.
