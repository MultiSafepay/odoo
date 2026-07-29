# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from .utils import (
    _Utils,
)


class _OrderContextBuilder:
    """Build Odoo payment context metadata from POS payment data.

    This class keeps tracker metadata aligned with the amounts calculated by POS/Odoo.
    It deliberately avoids recalculating totals from shopping cart lines.
    """

    @classmethod
    def from_payload(cls, data, currency):
        """Extract POS payment metadata and build Odoo payment contextual fields.

        :param dict data: The initialization data payload.
        :param res.currency currency: Odoo currency used for amount precision.
        :return: A dictionary of contextual payment fields (e.g. odoo_tip_amount).
        :rtype: dict
        """
        if not isinstance(data, dict) or "amount" not in data:
            raise ValueError("POS payment payload must include an amount.")

        tip_amount = data.get("tip_amount")
        if tip_amount is None:
            return {}

        tip_amount = _Utils.parse_decimal(tip_amount)

        return {
            "odoo_tip_amount": float(tip_amount),
            "odoo_tip_amount_cents": _Utils.amount_to_minor_units(tip_amount, currency),
        }
