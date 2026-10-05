# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

PROVIDER_CODE = "multisafepay_cloud"


class TestPosPaymentMethodCloudProvider(TransactionCase):
    """Cover the Odoo 20 provider mechanism used by the Cloud POS payment method.

    migracion_19_20: use_payment_terminal was replaced by payment_provider, so the
    provider selection, the provider cards, the constraints and the default image
    are all driven by payment_provider.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.payment_method_model = cls.env["pos.payment.method"]

    def _create_cloud_payment_method(self, **overrides):
        vals = {
            "name": "MultiSafepay Cloud",
            # migracion_19_20: type is required in Odoo 20 and no longer computed from
            # the journal; pay_later needs no journal.
            "type": "pay_later",
            "payment_method_type": "terminal",
            "payment_provider": PROVIDER_CODE,
            "msp_cloud_terminal_id": "terminal-1",
            "msp_cloud_terminal_group_id": "group-1",
            "msp_cloud_terminal_group_api_key": "group-api-key",
        }
        vals.update(overrides)
        return self.payment_method_model.create(vals)

    def test_terminal_provider_selection_includes_cloud(self):
        selection = dict(self.payment_method_model._get_terminal_provider_selection())
        self.assertEqual(selection.get(PROVIDER_CODE), "MultiSafepay Cloud POS")

        payment_method = self._create_cloud_payment_method()
        self.assertIn(PROVIDER_CODE, payment_method.available_payment_providers)

    def test_provider_cards_include_cloud(self):
        providers = [
            provider
            for provider in self.payment_method_model.get_payment_providers()
            if provider["provider"] == PROVIDER_CODE
        ]
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0]["type"], "terminal")
        self.assertEqual(providers[0]["module"], "pos_multisafepay_cloud")

        status = [
            provider
            for provider in self.payment_method_model.get_provider_status()
            if provider["provider"] == PROVIDER_CODE
        ]
        self.assertEqual(len(status), 1)
        self.assertEqual(status[0]["state"], "installed")

    def test_create_assigns_default_image(self):
        payment_method = self._create_cloud_payment_method()
        self.assertTrue(payment_method.image)
        self.assertTrue(payment_method.custom_image)

    def test_terminal_group_requires_api_key(self):
        with self.assertRaises(ValidationError):
            self._create_cloud_payment_method(msp_cloud_terminal_group_api_key=False)

    def test_terminal_configuration_must_be_unique(self):
        self._create_cloud_payment_method()
        with self.assertRaises(ValidationError):
            self._create_cloud_payment_method(name="Duplicated terminal")

    def test_constraints_ignore_other_payment_providers(self):
        payment_method = self._create_cloud_payment_method(
            name="No integration",
            payment_method_type="none",
            payment_provider=False,
            msp_cloud_terminal_group_api_key=False,
        )
        self.assertFalse(payment_method.payment_provider)

    def test_pos_payment_load_fields_keep_msp_refund_field(self):
        # migracion_19_20: an empty list means "load every field" in Odoo 20, so the
        # override must not narrow it to an explicit list.
        fields_to_load = self.env["pos.payment"]._load_pos_data_fields(
            self.env["pos.config"]
        )
        self.assertTrue(
            not fields_to_load or "msp_cloud_refund_source_order_id" in fields_to_load
        )

    def test_pos_user_can_access_cloud_payments(self):
        # migracion_19_20: ir.model.access was replaced by ir.access in Odoo 20.
        pos_user = (
            self.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "MultiSafepay POS User",
                    "login": "msp_cloud_pos_user",
                    "group_ids": [
                        Command.set([self.env.ref("point_of_sale.group_pos_user").id])
                    ],
                }
            )
        )
        cloud_payments = self.env["pos.multisafepay.cloud.payment"].with_user(pos_user)
        for operation in ("read", "write", "create", "unlink"):
            cloud_payments.check_access(operation)
