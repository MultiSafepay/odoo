# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

# ENHANCED MODULE: Extends CORE with custom business logic
from . import payment_method        # Adds: pricelist_ids field + pricelist filtering
from . import payment_transaction   # Adds: multisafepay_refund_reason field
from . import account_move          # Adds: invoice update notifications to MultiSafepay
from . import stock_picking         # Adds: shipping/tracking notifications to MultiSafepay

# Note: payment_provider is inherited from CORE (no custom logic needed)
