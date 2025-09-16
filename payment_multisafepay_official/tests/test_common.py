# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from odoo.tests.common import TransactionCase

class TestMultiSafepayProvider(TransactionCase):

    def test_multisafepay_provider_exists(self):
        provider = self.env['payment.provider'].search([('code', '=', 'multisafepay')], limit=1)
        self.assertTrue(provider, "MultiSafepay provider should exist after module installation.")
        self.assertEqual(provider.name, "MultiSafepay")
        self.assertEqual(provider.state, "disabled")
