# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

"""Odoo pos.payment model extension for MultiSafepay Cloud POS."""

from odoo import api, models


class PosPayment(models.Model):
    """Extend POS payment to load fields for Cloud POS refunds."""

    _inherit = "pos.payment"

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Load POS payment fields needed to select refundable terminal payments.

        These fields feed the POS refund UI and let the cashier pick the original
        MultiSafepay Cloud payment line. Refund execution is still revalidated by
        the backend tracking model before calling MultiSafepay.

        :param int config_id: POS configuration id being loaded.
        :return: Field names loaded for ``pos.payment`` records in the POS cache.
        :rtype: list[str]
        """
        base_fields = super()._load_pos_data_fields(config_id)
        required_fields = [
            "amount",
            "is_change",
            "pos_order_id",
            "payment_method_id",
            "payment_ref_no",
            "payment_status",
            "ticket",
            "transaction_id",
            "uuid",
        ]
        missing_fields = []
        for field_name in required_fields:
            if field_name in base_fields:
                continue
            missing_fields.append(field_name)
        return base_fields + missing_fields
