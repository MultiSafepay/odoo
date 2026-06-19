1.  Open an Odoo POS session that uses the configured payment method.
2.  Add products to the order and select **MultiSafepay Cloud POS** as
    payment method.
3.  Odoo creates a Cloud POS order and shows the terminal status in the
    POS.
4.  Complete, cancel, reverse, or refund the payment from the POS flow.

Real status polling and completed payment refunds require the merchant
account API key. Without that key, the module can still create terminal
orders with the terminal group credentials, but account-level status and
refund calls are not available.
