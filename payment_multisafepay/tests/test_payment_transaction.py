# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details


from odoo.tests.common import TransactionCase


class TestPaymentTransaction(TransactionCase):
    def setUp(self):
        super().setUp()
        self.provider = self.env["payment.provider"].create(
            {
                "name": "MultiSafepay Test",
                "code": "multisafepay",
                "state": "test",
            }
        )

        self.partner = self.env["res.partner"].create(
            {
                "name": "Test Customer",
                "email": "test@example.com",
            }
        )

        self.currency = (
            self.env["res.currency"]
            .with_context(active_test=False)
            .search(
                [("name", "=", "EUR")],
                limit = 1,
            )
        )

        if not self.currency:
            self.currency = self.env["res.currency"].create(
                {
                    "name": "EUR",
                    "symbol": "€",
                    "rate": 1.0,
                }
            )

    def test_compute_reference(self):
        """Test _compute_reference method for MultiSafepay transactions"""

        reference = self.env["payment.transaction"]._compute_reference("multisafepay")

        self.assertIsInstance(reference, str)
        self.assertTrue(reference)
        self.assertNotIn(" ", reference)
