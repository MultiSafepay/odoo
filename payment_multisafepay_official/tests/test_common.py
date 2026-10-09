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
        self.assertIn(provider.state, ("disabled", "test"))


class TestMultiSafepaySdkWiring(TransactionCase):
    def setUp(self):
        super().setUp()
        utils._get_requests_session.cache_clear()
        self.provider = self.env["payment.provider"].create(
            {
                "name": "MultiSafepay SDK Test",
                "code": "multisafepay",
                "state": "test",
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
