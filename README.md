<p align="center">
  <img src="https://raw.githubusercontent.com/MultiSafepay/MultiSafepay-logos/master/MultiSafepay-logo-color.svg" width="400px" position="center">
</p>

# MultiSafepay Official Module for Odoo

[![Odoo Version](https://img.shields.io/badge/Odoo-18.0-purple?style=for-the-badge)](https://www.odoo.com/)

## About MultiSafepay

MultiSafepay is a Dutch payment services provider, which takes care of contracts, processing transactions, and collecting payment for a range of local and international payment methods. Start selling online today and manage all your transactions in one place!


## Prerequisites

Before installing the MultiSafepay module suite, ensure you have:

- Odoo 18.0 or compatible version
- Active MultiSafepay Account. Consider a test account first. [Sign up here](https://testmerchant.multisafepay.com/signup) if you don't have one.
- API Credentials from your MultiSafepay Control Panel
- Python 3.9+
- Administrative access to your Odoo installation
- Before installing, make sure to install the module’s Python dependencies on the same environment where Odoo runs:
  ```
  pip install multisafepay
  ```

## Installation

The module can be installed in two ways:

### Manual Installation from the Odoo Interface

1. Sign in to your Odoo <Glossary>backend</Glossary> as **Administrator**.
2. Go to **Apps** > **Update Apps List**.
3. Go to **Apps** > **Import module**.
4. Select the ZIP file of the module "payment_multisafepay_official".
5. After uploading, search for **MultiSafepay** in the Apps list.
6. Click **Install**.
7. Go to **Apps** > **MultiSafepay** and click Activate.

### Server Installation

This installation method is intended for administrators who have access to the server where Odoo is running.
Unlike the manual upload, the module must be placed on the server inside an existing custom addons directory or in a new directory that you add to Odoo’s configuration file.

1. Edit your odoo.conf file to find (or define a new one) directory where the module is located:
    ```
    # In your odoo.conf file
    addons_path = /path/to/odoo/addons,/path/to/custom_addons
    ```
2. Copy the module into the `custom_addons` directory:
    ```
    cd /path/to/custom_addons
    cp -r /path/to/payment_multisafepay_official .
    ```
3. Restart your Odoo server:
    - Docker: `docker-compose restart odoo`
    - Systemd: `sudo systemctl restart odoo`
4. Sign in to your Odoo backend as **Administrator** and go to **Apps** > **Update Apps List**.
5. Search for the **MultiSafepay** in the Apps list.
6. Click **Install**.
7. Go to **Apps** > **MultiSafepay** and click Activate.

## Configuration

1. Sign in to your Odoo <Glossary>backend</Glossary>.
2. Go to **Invoicing** > **Configuration** > **Payment Providers**.
3. Click **MultiSafepay**.
4. Select a **State** (**Test Mode** for test) and enter your corresponding test **API Key**.
5. Save your changes.
6. To get payment methods from your MultiSafepay account, go to **Configuration** and click **"Pull Payment Methods"** to fetch and activate all payment methods available in your account.
7. **Test the integration**: Submit a test transaction to ensure everything is functioning correctly.
8. Switch to Live Mode changing **State** to **Enabled** and enter your corresponding live **API Key**.
9. Verify that your payment method settings remain in place after switching to live mode.
10. Set the payment provider as **Published**.

## Payment Methods Supported

The MultiSafepay integration supports all major payment methods available through MultiSafepay:

- Credit & Debit Cards: Visa, Mastercard, American Express, Maestro
- Digital Wallets: PayPal, Apple Pay, Google Pay
- Bank Transfers: SEPA Direct Debit, Bancontact, iDEAL, Sofort
- Buy Now Pay Later: Klarna, in3, Pay After Delivery
- Local Methods: And many more regional payment solutions

## Updates

1.  Backup Your Database (always recommended before updates)
2.  Download Latest Version from official MultiSafepay repository
3.  Replace Module Files with new version
4.  Update Dependencies:
    ```
    cd payment_multisafepay_official/
    pip install -r requirements.txt --upgrade
    ```
5.  Restart Odoo and Upgrade Module: Navigate to Apps > MultiSafepay Official > Upgrade or via command line:
    ```
    odoo-bin -u payment_multisafepay_official -d your_database_name
    ```

## Support

- Create an issue on this repository.
- Email <a href="mailto:integration@multisafepay.com">integration@multisafepay.com</a>

## Contributors

If you see an opportunity to make an improvement, we invite you to create a pull request, create an issue, or email <integration@multisafepay.com>

As a thank you for your contribution, we'll send you a MultiSafepay t-shirt, making you part of the team!

## Want to be part of the team?

Are you a developer interested in working at MultiSafepay? Check out our [job openings](https://www.multisafepay.com/careers/#jobopenings) and feel free to get in touch!

## License

This project is licensed under the terms specified in the [LICENSE](https://github.com/MultiSafepay/odoo/blob/19.0/LICENSE.md) file in the root directory of this repository.
