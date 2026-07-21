# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from unittest.mock import patch, MagicMock

from odoo.tests.common import TransactionCase


class TestPaymentProvider(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        
        cls.provider = cls.env["payment.provider"].create({
            "name": "MultiSafepay Test",
            "code": "multisafepay",
            "state": "test",
            "multisafepay_api_key": "dummy_api_key",
        })

    def test_compute_feature_support_fields(self):
        self.provider._compute_feature_support_fields()
        self.assertTrue(self.provider.support_express_checkout)
        self.assertEqual(self.provider.support_manual_capture, "full_only")
        self.assertEqual(self.provider.support_refund, "partial")
        self.assertTrue(self.provider.support_tokenization)

    def test_get_supported_currencies(self):
        currencies = self.provider._get_supported_currencies()
        eur_currency = self.env.ref("base.EUR")
        if eur_currency.active:
            self.assertIn(eur_currency, currencies)

    @patch("odoo.addons.payment_multisafepay.models.payment_provider.PaymentProvider._fetch_merchant_payment_methods")
    def test_on_multisafepay_config_changed_enable(self, mock_fetch):
        self.provider.write({"state": "enabled"})
        mock_fetch.assert_called_once()

    def test_on_disable_deactivate_all_methods(self):
        method = self.env["payment.method"].create({
            "name": "iDEAL",
            "code": "multisafepay_ideal",
            "active": True,
            "provider_ids": [(4, self.provider.id)],
        })
        
        self.provider.write({"state": "disabled"})
        
        # Ensure it got deactivated
        self.assertFalse(method.active)

    def test_map_multisafepay_to_odoo_code(self):
        self.assertEqual(self.provider._map_multisafepay_to_odoo_code("MISTERCASH"), "multisafepay_mistercash")
        self.assertEqual(self.provider._map_multisafepay_to_odoo_code("ideal"), "multisafepay_ideal")
        self.assertEqual(self.provider._map_multisafepay_to_odoo_code(""), "")

    def test_map_odoo_to_multisafepay_code(self):
        self.assertEqual(self.provider._map_odoo_to_multisafepay_code("multisafepay_mistercash"), "MISTERCASH")
        self.assertEqual(self.provider._map_odoo_to_multisafepay_code("multisafepay_ideal"), "IDEAL")
        self.assertEqual(self.provider._map_odoo_to_multisafepay_code(""), "")

    def test_get_country_ids(self):
        # Assuming US and GB exist in base data
        us_country = self.env.ref("base.us")
        gb_country = self.env.ref("base.uk")
        
        country_ids = self.provider._get_country_ids(["US", "GB"])
        self.assertIn(us_country.id, country_ids)
        self.assertIn(gb_country.id, country_ids)
        
        # Invalid country code should be ignored
        invalid_ids = self.provider._get_country_ids(["XX"])
        self.assertEqual(len(invalid_ids), 0)

    def test_get_currency_ids(self):
        eur_currency = self.env.ref("base.EUR")
        usd_currency = self.env.ref("base.USD")
        
        currency_ids = self.provider._get_currency_ids(["EUR", "USD"])
        self.assertIn(eur_currency.id, currency_ids)
        self.assertIn(usd_currency.id, currency_ids)
        
    @patch("odoo.addons.payment_multisafepay.models.payment_provider.PaymentProvider.get_multisafepay_sdk")
    def test_fetch_merchant_payment_methods(self, mock_get_sdk):
        mock_sdk = MagicMock()
        mock_manager = MagicMock()
        mock_get_sdk.return_value = mock_sdk
        mock_sdk.get_payment_method_manager.return_value = mock_manager
        
        mock_response = MagicMock()
        
        # Create a mock gateway
        mock_gateway = MagicMock()
        mock_gateway.id = "MISTERCASH"
        mock_gateway.name = "Bancontact"
        mock_gateway.allowed_countries = ["BE"]
        mock_gateway.allowed_currencies = ["EUR"]
        
        mock_amount = MagicMock()
        mock_amount.min = 100 # cents -> 1.00 EUR
        mock_amount.max = 100000 # cents -> 1000.00 EUR
        mock_gateway.allowed_amount = mock_amount
        
        # Gateway icon
        mock_icon = MagicMock()
        mock_icon.large = "https://example.com/icon.png"
        mock_gateway.icon_urls = mock_icon
        
        # No brands
        mock_gateway.brands = []
        
        mock_response.get_data.return_value = [mock_gateway]
        mock_manager.get_payment_methods.return_value = mock_response
        
        # Execute sync
        self.provider._fetch_merchant_payment_methods()
        
        # Verify method created
        method = self.env["payment.method"].search([("code", "=", "multisafepay_mistercash")])
        self.assertTrue(method)
        self.assertEqual(method.name, "Bancontact")
        self.assertEqual(method.minimum_amount, 1.00)
        self.assertEqual(method.maximum_amount, 1000.00)
        self.assertIn(self.provider.id, method.provider_ids.ids)
