1.  Go to **Point of Sale \> Configuration \> Payment Methods**.
2.  Create or edit a POS payment method.
3.  Set **Use a Payment Terminal** to **MultiSafepay Cloud POS**.
4.  Configure the Cloud POS credentials and terminal settings:
    - **MSP Cloud Terminal ID**
    - **MSP Cloud Terminal Group ID**
    - **MSP Cloud Terminal Group API Key**
    - **MSP Cloud Merchant Account API Key**
    - **MSP Cloud Environment**

The default confirmation channel is **Webhook only** because webhook
requests provide clearer HTTP and log traceability. **Socket only**
refers to the backend MultiSafepay event stream; it does not disable the
Odoo POS frontend websocket used by bus notifications.
