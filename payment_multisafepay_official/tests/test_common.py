# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from multisafepay.transport import RequestsTransport

from odoo.tests.common import TransactionCase

from .. import utils


class TestMultiSafepayProvider(TransactionCase):
    def test_multisafepay_provider_exists(self):
        provider = self.env["payment.provider"].search(
            [("code", "=", "multisafepay")], limit=1
        )
        self.assertTrue(
            provider, "MultiSafepay provider should exist after module installation."
        )
        self.assertEqual(provider.name, "MultiSafepay")
        # migracion_19_20: payment.provider.state was removed in Odoo 20; the mode derives from active + is_live.
        self.assertIn(provider._get_multisafepay_state(), ("disabled", "test"))


class TestMultiSafepaySdkWiring(TransactionCase):
    def setUp(self):
        super().setUp()
        utils._get_requests_session.cache_clear()
        self.provider = self.env["payment.provider"].create(
            {
                "name": "MultiSafepay SDK Test",
                "code": "multisafepay",
                # migracion_19_20: payment.provider.state was removed in Odoo 20, test mode is is_live=False.
                "is_live": False,
                "multisafepay_api_key": "test-api-key-12345",
            }
        )

    def tearDown(self):
        utils._get_requests_session.cache_clear()
        super().tearDown()

    def test_get_multisafepay_sdk_uses_requests_transport_with_shared_session(self):
        first_sdk = self.provider.get_multisafepay_sdk()
        second_sdk = self.provider.get_multisafepay_sdk()

        self.assertIsInstance(first_sdk.client.transport, RequestsTransport)
        self.assertIs(
            first_sdk.client.transport.session,
            utils._get_requests_session(),
        )
        self.assertIs(
            first_sdk.client.transport.session,
            second_sdk.client.transport.session,
        )


class TestMultiSafepayMoneyConversion(TransactionCase):
    def test_minor_units_are_converted_to_the_currency_precision(self):
        eur = self.env.ref("base.EUR")
        jpy = self.env.ref("base.JPY")

        self.assertEqual(utils.minor_units_to_money(3998, eur), 39.98)
        self.assertEqual(utils.minor_units_to_money("250", eur), 2.5)
        self.assertEqual(utils.minor_units_to_money(500, jpy), 500.0)
        self.assertEqual(utils.minor_units_to_money(None, eur), 0.0)

    def test_money_survives_a_round_trip_through_minor_units(self):
        eur = self.env.ref("base.EUR")

        for amount in (0.01, 0.1, 4.0, 39.98, 1234.56):
            with self.subTest(amount=amount):
                minor_units = utils.money_to_minor_units(amount, eur)
                self.assertEqual(utils.minor_units_to_money(minor_units, eur), amount)
