# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PaymentRefundWizard(models.TransientModel):
    """Extends the standard Odoo payment refund wizard to add MultiSafepay-specific refund reason field."""
    _inherit = 'payment.refund.wizard'

    multisafepay_refund_reason = fields.Char(
        string="Refund Reason",
        help="Optional reason for the refund (specific to MultiSafepay)",
    )
    provider_code = fields.Char(
        string="Provider Code",
        compute='_compute_provider_code',
        store=False,
    )

    @api.depends('transaction_id', 'transaction_id.provider_code')
    def _compute_provider_code(self):
        """Compute the provider code from the transaction."""
        for wizard in self:
            wizard.provider_code = wizard.transaction_id.provider_code if wizard.transaction_id else False

    def action_refund(self):
        """Override to pass the refund reason to the MultiSafepay transaction via context."""
        self.ensure_one()
        
        _logger.debug("Refund wizard - Provider code: %s, Reason: %s", 
                    self.provider_code, self.multisafepay_refund_reason)
        
        # If this is a MultiSafepay transaction and a reason is provided,
        # pass it through the context so _create_child_transaction can use it
        if self.provider_code == 'multisafepay' and self.multisafepay_refund_reason:
            _logger.debug("Passing reason through context: %s", self.multisafepay_refund_reason)
            return self.transaction_id.with_context(
                multisafepay_refund_reason=self.multisafepay_refund_reason
            ).action_refund(amount_to_refund=self.amount_to_refund)
        
        # For non-MultiSafepay transactions or when no reason provided, use standard flow
        _logger.debug("Using standard flow (no reason or not MultiSafepay)")
        return super().action_refund()
