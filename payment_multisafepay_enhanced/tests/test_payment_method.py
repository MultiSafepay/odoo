# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from odoo.tests.common import TransactionCase

from odoo.addons.payment_multisafepay_official.utils import (
    _get_default_payment_method_image,
)


class TestMultiSafepayEnhancedPricelists(TransactionCase):
    # migracion_19_20: the pricelist filter now extends _apply_multisafepay_filters, which the
    # provider hook payment.provider._find_available_payment_methods calls in Odoo 20.

    def setUp(self):
        super().setUp()
        self.provider = self.env["payment.provider"].create(
            {"name": "MultiSafepay Enhanced Test", "code": "multisafepay"}
        )
        self.pricelist_a, self.pricelist_b = self.env["product.pricelist"].create(
            [{"name": "Pricelist A"}, {"name": "Pricelist B"}]
        )
        values = {
            "provider_id": self.provider.id,
            "image": _get_default_payment_method_image(),
            "active": True,
        }
        self.restricted = self.env["payment.method"].create(
            {
                **values,
                "name": "iDEAL",
                "code": "multisafepay_ideal",
                "pricelist_ids": [(6, 0, [self.pricelist_a.id])],
            }
        )
        self.open = self.env["payment.method"].create(
            {**values, "name": "Visa", "code": "multisafepay_visa"}
        )
        self.partner = self.env["res.partner"].create({"name": "Buyer"})
        self.currency = self.env.company.currency_id

    def test_pricelist_filter_removes_restricted_methods_and_reports_it(self):
        methods = self.restricted | self.open
        report = {}

        found = methods._apply_multisafepay_filters(
            report=report, pricelist_id=self.pricelist_b.id
        )

        self.assertEqual(found, self.open)
        self.assertIn(
            "Not allowed for pricelist 'Pricelist B'",
            report["payment_methods"][self.restricted]["reason"],
        )
        found = methods._apply_multisafepay_filters(pricelist_id=self.pricelist_a.id)
        self.assertEqual(found, methods)

    def test_provider_hook_uses_the_sale_order_pricelist(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner.id,
                "pricelist_id": self.pricelist_b.id,
                "order_line": [
                    (0, 0, {"name": "Item", "product_uom_qty": 1, "price_unit": 5.0})
                ],
            }
        )

        found = self.provider._find_available_payment_methods(
            self.partner.id, currency_id=self.currency.id, sale_order_id=order.id
        )

        self.assertEqual(found, self.open)

    def test_helper_filters_by_the_explicit_pricelist(self):
        found = self.env[
            "payment.method"
        ]._get_compatible_payment_methods_with_pricelist(
            [self.provider.id],
            self.partner.id,
            currency_id=self.currency.id,
            pricelist_id=self.pricelist_b.id,
        )

        self.assertEqual(found, self.open)

    def test_refund_reason_is_copied_to_the_refund_transaction(self):
        tx = self.env["payment.transaction"].create(
            {
                "provider_id": self.provider.id,
                "payment_method_id": self.open.id,
                "reference": "TEST-MSP-ENH-001",
                "amount": 10.0,
                "currency_id": self.currency.id,
                "partner_id": self.partner.id,
                "operation": "online_redirect",
            }
        )

        refund_tx = tx.with_context(
            multisafepay_refund_reason="Damaged product"
        )._create_child_transaction(5.0, is_refund=True)

        self.assertEqual(refund_tx.multisafepay_refund_reason, "Damaged product")
