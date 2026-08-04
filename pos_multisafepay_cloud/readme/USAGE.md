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
