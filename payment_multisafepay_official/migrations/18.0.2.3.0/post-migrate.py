# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        UPDATE payment_provider
        SET multisafepay_validate_shopping_cart = TRUE
        WHERE code = 'multisafepay'
          AND multisafepay_validate_shopping_cart IS NULL
    """)
    updated = cr.rowcount
    if updated:
        _logger.info(
            "Initialized multisafepay_validate_shopping_cart=True on %d existing provider(s).",
            updated,
        )
