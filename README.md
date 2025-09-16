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
- Python 3.9+ with pip package manager
- Administrative access to your Odoo installation

## Payment Methods Supported

The MultiSafepay integration supports all major payment methods available through MultiSafepay:

- Credit & Debit Cards: Visa, Mastercard, American Express, Maestro
- Digital Wallets: PayPal, Apple Pay, Google Pay
- Bank Transfers: SEPA Direct Debit, Bancontact, iDEAL, Sofort
- Buy Now Pay Later: Klarna, in3, Pay After Delivery
- Local Methods: And many more regional payment solutions

## Installation

1.  Add to Odoo Path: Ensure the `custom_addons` directory is included in your Odoo `addons_path` configuration:
    ```
    # In your odoo.conf file
    addons_path = /path/to/odoo/addons,/path/to/custom_addons
    ```

2.  Install Dependencies: Navigate to the core module and install required Python packages:
    ```
    pip install -r requirements.txt
    ```

3.  Copy the module in the custom_addons directory: Navigate to the custom_addons and install required Python packages:
    ```
    cd /path/to/custom_addons
    cp -r /path/to/payment_multisafepay_official .
    ```

4.  Restart Odoo Service:
    ```
    # For Docker environments
    docker-compose restart odoo

    # For systemd services
    sudo systemctl restart odoo
    ```

5.  Activate in Odoo:
    - Log into Odoo as Administrator
    - Navigate to **Apps** > **Update Apps List**
    - Search for "MultiSafepay Official"
    - Click **Activate**

## Configuration

1. Navigate to **Invoicing** > **Configuration** > **Payment Providers**
2. Find and configure **MultiSafepay**
3. Enter your **API Key** and **Environment** (Test/Live)
4. Sync Payment Methods: Click the **"Pull Payment Methods"** button to fetch and activate all payment gateways available in your MultiSafepay account.
5. **Test the integration** submit a test transaction to ensure everything is functioning correctly.

## Updates

1.  **Backup Your Database** (always recommended before updates)
2.  **Download Latest Version** from official MultiSafepay repository
3.  **Replace Module Files** with new version
4.  **Update Dependencies**:
    ```
    cd payment_multisafepay_official/
    pip install -r requirements.txt --upgrade
    ```
5.  **Restart Odoo** and **Upgrade Module**: Navigate to Apps > MultiSafepay Official > Upgrade or via command line:
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

This project is licensed under the terms specified in the [LICENSE](https://github.com/MultiSafepay/odoo/blob/18.0/LICENSE.md) file in the root directory of this repository.
