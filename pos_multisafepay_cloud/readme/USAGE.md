1.  Open an Odoo POS session that uses the configured payment method.
2.  Add products to the order and select **MultiSafepay Cloud POS** as
    payment method.
3.  Odoo creates a Cloud POS order and shows the terminal status in the
    POS.
4.  Complete, cancel, reverse, or refund the payment from the POS flow.

Transaction status is synchronized from MultiSafepay through polling and
notifications. The local Cloud POS tracker stores the remote transaction
ID and the latest response payload, so operators can review completed,
cancelled, refunded, and partially refunded terminal payments from the
related POS order.

Real status polling and completed payment refunds require the Site API
Key. Without that key, the module can still create terminal
orders with the terminal group credentials, but account-level status and
refund calls are not available.
