This module adds MultiSafepay Cloud POS payment terminal support to Odoo
Point of Sale.

It lets Odoo create Cloud POS orders, track terminal status, process
webhook or event-stream confirmations, and handle POS-side reversals and
refunds through the backend MultiSafepay API.

Each Cloud POS request creates a local tracking record with the remote
transaction identifier, the latest MultiSafepay status, and the related
refund or reversal details. This makes terminal activity auditable from
the POS order and lets later status checks reconcile Odoo with the
MultiSafepay order state.

The addon is intentionally independent from `pos_multisafepay` and keeps
that addon as a reference only.
