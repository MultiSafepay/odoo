# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from unittest.mock import patch, MagicMock

from odoo.tests.common import TransactionCase


class TestPaymentMethod(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        
        cls.provider = cls.env["payment.provider"].create({
            "name": "MultiSafepay Test",
            "code": "multisafepay",
            "state": "test",
        })
        
        cls.other_provider = cls.env["payment.provider"].create({
            "name": "Other Provider",
            "code": "test",
            "state": "test",
        })

        cls.payment_method = cls.env["payment.method"].create({
            "name": "iDEAL",
            "code": "multisafepay_ideal",
            "active": True,
            "provider_ids": [(4, cls.provider.id)],
        })
        
        cls.bnpl_method = cls.env["payment.method"].create({
            "name": "Riverty",
            "code": "multisafepay_riverty",
            "active": True,
            "provider_ids": [(4, cls.provider.id)],
        })
        
        cls.other_method = cls.env["payment.method"].create({
            "name": "Other Method",
            "code": "other",
            "active": True,
            "provider_ids": [(4, cls.other_provider.id)],
        })

    def test_compute_is_multisafepay(self):
        self.assertTrue(self.payment_method.only_multisafepay)
        self.assertFalse(self.other_method.only_multisafepay)
        
    def test_compute_main_currency_id(self):
        eur_currency = self.env.ref("base.EUR")
        self.provider.main_currency_id = eur_currency.id
        self.payment_method._compute_main_currency_id()
        self.assertEqual(self.payment_method.main_currency_id.id, eur_currency.id)

    def test_filter_by_amount(self):
        self.payment_method.write({
            "minimum_amount": 10.0,
            "maximum_amount": 100.0,
        })
        
        # Valid amount
        methods = self.payment_method._filter_by_amount(50.0)
        self.assertIn(self.payment_method, methods)
        
        # Too low
        methods = self.payment_method._filter_by_amount(5.0)
        self.assertNotIn(self.payment_method, methods)
        
        # Too high
        methods = self.payment_method._filter_by_amount(150.0)
        self.assertNotIn(self.payment_method, methods)
        
        # No amount should allow it
        methods = self.payment_method._filter_by_amount(None)
        self.assertIn(self.payment_method, methods)

    def test_get_compatible_payment_methods(self):
        self.payment_method.write({
            "minimum_amount": 10.0,
            "maximum_amount": 100.0,
        })
        
        # Test without amount kwargs
        report = {}
        methods = self.env["payment.method"]._get_compatible_payment_methods(
            self.provider.ids,
            partner_id=self.env.user.partner_id.id,
            report=report,
        )
        self.assertIn(self.payment_method, methods)
        
        # Test with amount
        report = {}
        methods = self.env["payment.method"]._get_compatible_payment_methods(
            self.provider.ids,
            partner_id=self.env.user.partner_id.id,
            amount=5.0,
            report=report,
        )
        self.assertNotIn(self.payment_method, methods)

        # BNPL when shopping cart is disabled
        self.provider.multisafepay_active_shopping_cart = False
        report = {}
        methods = self.env["payment.method"]._get_compatible_payment_methods(
            self.provider.ids,
            partner_id=self.env.user.partner_id.id,
            report=report,
        )
        self.assertNotIn(self.bnpl_method, methods)
        self.assertIn(self.payment_method, methods)
        
        # BNPL when shopping cart is enabled
        self.provider.multisafepay_active_shopping_cart = True
        report = {}
        methods = self.env["payment.method"]._get_compatible_payment_methods(
            self.provider.ids,
            partner_id=self.env.user.partner_id.id,
            report=report,
        )
        self.assertIn(self.bnpl_method, methods)

    def test_generate_amount_filter_reasons(self):
        self.payment_method.write({
            "minimum_amount": 10.0,
            "maximum_amount": 100.0,
        })
        
        # Test below minimum
        reasons = self.payment_method._generate_amount_filter_reasons(self.payment_method, 5.0)
        self.assertEqual(len(reasons), 1)
        self.assertIn("Amount 5.0 below minimum 10.0", reasons[0])
        
        # Test above maximum
        reasons = self.payment_method._generate_amount_filter_reasons(self.payment_method, 150.0)
        self.assertEqual(len(reasons), 1)
        self.assertIn("Amount 150.0 above maximum 100.0", reasons[0])

    def test_get_compatible_payment_methods_with_sale_order(self):
        self.payment_method.write({
            "minimum_amount": 10.0,
            "maximum_amount": 100.0,
        })
        
        # Mock sale order
        mock_order = MagicMock()
        mock_order.exists.return_value = True
        mock_order.amount_total = 150.0 # Above maximum
        mock_order.name = "SO001"
        
        # Mock env["sale.order"]
        mock_env_so = MagicMock()
        mock_env_so.browse.return_value = mock_order
        
        with patch.dict(self.env.registry, {"sale.order": mock_env_so}):
            with patch.object(self.env, "__getitem__", side_effect=lambda k: mock_env_so if k == "sale.order" else super(type(self.env), self.env).__getitem__(k)):
                report = {}
                methods = self.env["payment.method"]._get_compatible_payment_methods(
                    self.provider.ids,
                    partner_id=self.env.user.partner_id.id,
                    sale_order_id=1,
                    report=report,
                )
                self.assertNotIn(self.payment_method, methods)

    @patch("odoo.addons.payment_multisafepay.models.payment_method.request")
    def test_get_compatible_payment_methods_with_request(self, mock_request):
        self.payment_method.write({
            "minimum_amount": 10.0,
            "maximum_amount": 100.0,
        })
        
        # Mock request args
        mock_request.httprequest.args.get.return_value = "5.0" # Below minimum
        
        report = {}
        methods = self.env["payment.method"]._get_compatible_payment_methods(
            self.provider.ids,
            partner_id=self.env.user.partner_id.id,
            report=report,
        )
        self.assertNotIn(self.payment_method, methods)
