# pos_multisafepay_cloud

Proof of concept for initiating MultiSafepay Cloud POS payments from Odoo POS.

## Scope

- POS flow only.
- Uses the Cloud POS order flow introduced in the Python SDK branch `PTHMINT-108`.

## Configuration

Set `Use a Payment Terminal` to `MultiSafepay Cloud POS` and configure:

- `MSP Cloud Terminal ID`
- `MSP Cloud Terminal Group ID`
- `MSP Cloud Terminal Group API Key`
- `MSP Cloud Merchant Account API Key`
- `MSP Cloud Environment`
- `Confirmation Channel` (`Webhook only` by default, `Webhook and socket`, or `Socket only`)

## Notes

- Real status polling requires a merchant account API key.
- `Webhook only` is the default confirmation mode because webhook requests provide clearer HTTP/log traceability.
- `Socket only` refers to the backend MultiSafepay event stream. It does not disable the POS frontend websocket used by Odoo bus notifications.
- The module is intentionally independent from `pos_multisafepay` and keeps that addon as reference only.
