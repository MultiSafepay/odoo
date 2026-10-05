# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests.common import TransactionCase


def _brand(code, name):
    return SimpleNamespace(id=code, name=name, icon_urls=None, allowed_countries=["NL"])


def _gateway(code, name, brands=(), min_cents=None, max_cents=None):
    return SimpleNamespace(
        id=code,
        name=name,
        allowed_countries=["NL"],
        allowed_currencies=["EUR"],
        allowed_amount=SimpleNamespace(min=min_cents, max=max_cents),
        icon_urls=None,
        brands=list(brands),
    )


class TestMultiSafepayPaymentMethods(TransactionCase):
    # migracion_19_20: payment methods belong to one provider (provider_id) and the
    # provider mode comes from active + is_live in Odoo 20; these tests cover both.

    def setUp(self):
        super().setUp()
        self.provider = self._create_provider("MultiSafepay Methods Test")

    def _create_provider(self, name, api_key="test-api-key"):
        return self.env["payment.provider"].create(
            {
                "name": name,
                "code": "multisafepay",
                "is_live": False,
                "multisafepay_api_key": api_key,
            }
        )

    def _sync(self, provider, gateways):
        manager = SimpleNamespace(
            get_payment_methods=lambda: SimpleNamespace(get_data=lambda: gateways)
        )
        sdk = SimpleNamespace(get_payment_method_manager=lambda: manager)
        with patch.object(type(provider), "get_multisafepay_sdk", return_value=sdk):
            provider._fetch_merchant_payment_methods()

    def _methods(self, provider):
        return (
            self.env["payment.method"]
            .with_context(active_test=False)
            .search([("provider_id", "=", provider.id)])
        )

    def test_provider_state_is_derived_from_active_and_is_live(self):
        provider = self._create_provider("MultiSafepay No Key", api_key=False)
        self.assertEqual(provider._get_multisafepay_state(), "test")
        provider.is_live = True
        self.assertEqual(provider._get_multisafepay_state(), "enabled")
        provider.active = False
        self.assertEqual(provider._get_multisafepay_state(), "disabled")

    def test_sync_creates_methods_owned_by_the_provider(self):
        gateway = _gateway(
            "IDEAL",
            "iDEAL",
            brands=[_brand("ABNAMRO", "ABN AMRO")],
            min_cents=100,
            max_cents=500000,
        )
        self._sync(self.provider, [gateway])

        methods = self._methods(self.provider)
        method = methods.filtered(lambda m: m.code == "multisafepay_ideal")
        brand = methods.filtered(lambda m: m.code == "multisafepay_abnamro")
        self.assertEqual(method.provider_id, self.provider)
        self.assertEqual((method.minimum_amount, method.maximum_amount), (1.0, 5000.0))
        self.assertFalse(method.active)
        self.assertTrue(method.image, "payment.method.image is required in Odoo 20")
        self.assertEqual(brand.primary_payment_method_id, method)
        self.assertTrue(brand.image)

    def test_sync_is_idempotent_and_scoped_per_provider(self):
        other = self._create_provider("MultiSafepay Other")
        gateways = [_gateway("IDEAL", "iDEAL")]

        self._sync(self.provider, gateways)
        self._sync(self.provider, gateways)
        self._sync(other, gateways)

        self.assertEqual(len(self._methods(self.provider)), 1)
        self.assertEqual(len(self._methods(other)), 1)

    def test_sync_deactivates_methods_removed_from_the_api(self):
        self._sync(
            self.provider,
            [_gateway("IDEAL", "iDEAL"), _gateway("BANCONTACT", "Bancontact")],
        )
        self._methods(self.provider).write({"active": True})

        self._sync(self.provider, [_gateway("IDEAL", "iDEAL")])

        active_by_code = {m.code: m.active for m in self._methods(self.provider)}
        self.assertTrue(active_by_code["multisafepay_ideal"])
        self.assertFalse(active_by_code["multisafepay_bancontact"])

    def test_filters_by_amount_and_bnpl_and_reports_reasons(self):
        self._sync(
            self.provider,
            [
                _gateway("IDEAL", "iDEAL", min_cents=1000, max_cents=5000),
                _gateway("KLARNA", "Klarna"),
                _gateway("VISA", "Visa"),
            ],
        )
        methods = self._methods(self.provider)
        methods.write({"active": True})
        self.provider.multisafepay_active_shopping_cart = False

        report = {}
        available = methods._apply_multisafepay_filters(report=report, amount=5.0)

        self.assertEqual(available.mapped("code"), ["multisafepay_visa"])
        self.assertEqual(len(report["payment_methods"]), 2)
        for entry in report["payment_methods"].values():
            self.assertFalse(entry["available"])
            self.assertTrue(entry["reason"])

        self.provider.multisafepay_active_shopping_cart = True
        self.assertEqual(len(methods._apply_multisafepay_filters(amount=20.0)), 3)

    def test_provider_hook_filters_available_payment_methods(self):
        self._sync(
            self.provider,
            [
                _gateway("IDEAL", "iDEAL", min_cents=1000, max_cents=5000),
                _gateway("VISA", "Visa"),
            ],
        )
        self._methods(self.provider).write({"active": True})
        partner = self.env["res.partner"].create(
            {"name": "Buyer", "country_id": self.env.ref("base.nl").id}
        )
        currency = self.env.ref("base.EUR")

        found = self.provider._find_available_payment_methods(
            partner.id, currency_id=currency.id, amount=5.0
        )

        self.assertEqual(found.mapped("code"), ["multisafepay_visa"])

    def test_amount_is_taken_from_the_sale_order(self):
        if "sale.order" not in self.env:
            self.skipTest("sale is not installed")
        self._sync(
            self.provider,
            [_gateway("IDEAL", "iDEAL", min_cents=1000, max_cents=5000)],
        )
        self._methods(self.provider).write({"active": True})
        partner = self.env["res.partner"].create(
            {"name": "Buyer", "country_id": self.env.ref("base.nl").id}
        )
        order = self.env["sale.order"].create(
            {
                "partner_id": partner.id,
                "order_line": [
                    (0, 0, {"name": "Item", "product_uom_qty": 1, "price_unit": 5.0})
                ],
            }
        )

        found = self.provider._find_available_payment_methods(
            partner.id,
            currency_id=self.env.ref("base.EUR").id,
            sale_order_id=order.id,
        )

        self.assertFalse(found)
