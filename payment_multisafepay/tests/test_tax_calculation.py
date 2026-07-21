# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from decimal import Decimal
from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase
from odoo.addons.payment_multisafepay.controllers.main import MultiSafepayController


class TestTaxCalculation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = MultiSafepayController()

    def test_get_line_tax_rate_percentage_no_taxes(self):
        line = MagicMock()
        line.tax_ids = []
        line.tax_id = None
        
        result = self.controller._get_line_tax_rate_percentage(line)
        self.assertIsNone(result)

    def test_get_line_tax_rate_percentage_from_prices(self):
        line = MagicMock()
        line.tax_ids = [MagicMock()]
        line.price_subtotal = 100.0
        line.price_total = 121.0
        
        result = self.controller._get_line_tax_rate_percentage(line)
        self.assertEqual(result, Decimal("21.0000000000"))

    def test_get_line_tax_rate_percentage_from_prices_zero(self):
        line = MagicMock()
        line.tax_ids = [MagicMock()]
        line.price_subtotal = 100.0
        line.price_total = 100.0
        
        result = self.controller._get_line_tax_rate_percentage(line)
        self.assertEqual(result, Decimal("0.0000000000"))

    def test_get_line_tax_rate_percentage_fallback_to_tax_amount(self):
        line = MagicMock()
        
        tax1 = MagicMock()
        tax1.amount_type = "percent"
        tax1.amount = 10.0
        
        tax2 = MagicMock()
        tax2.amount_type = "percent"
        tax2.amount = 11.0
        
        line.tax_ids = [tax1, tax2]
        line.price_subtotal = 0.0 # Will force fallback
        line.price_total = 0.0
        
        result = self.controller._get_line_tax_rate_percentage(line)
        self.assertEqual(result, Decimal("21.0"))

    def test_get_line_tax_rate_percentage_ignore_non_percent(self):
        line = MagicMock()
        
        tax1 = MagicMock()
        tax1.amount_type = "percent"
        tax1.amount = 10.0
        
        tax2 = MagicMock()
        tax2.amount_type = "fixed" # Should be ignored
        tax2.amount = 11.0
        
        line.tax_ids = [tax1, tax2]
        line.price_subtotal = 0.0
        
        result = self.controller._get_line_tax_rate_percentage(line)
        self.assertEqual(result, Decimal("10.0"))

    def test_get_line_tax_rate_percentage_handle_invalid_data(self):
        line = MagicMock()
        
        tax1 = MagicMock()
        tax1.amount_type = "percent"
        tax1.amount = "invalid_string"
        
        line.tax_ids = tax1 # Not a list, should be converted
        line.price_subtotal = None
        
        result = self.controller._get_line_tax_rate_percentage(line)
        self.assertEqual(result, Decimal("0"))
