# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

"""
ENHANCED MODULE: Adds refund reason functionality to MultiSafepay payment transactions.
This module EXTENDS payment_multisafepay (CORE) by adding custom refund reason tracking.
"""

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    """Extend payment.transaction to add refund reason tracking (ENHANCED feature).
    
    This enhanced model extends the CORE payment_multisafepay functionality by adding
    refund reason tracking for MultiSafepay transactions, allowing better audit trails
    and customer communication during refund operations.
    """

    _inherit = 'payment.transaction'

    # ===================================
    # ENHANCED CUSTOM FIELDS
    # ===================================

    multisafepay_refund_reason = fields.Char(
        string="Refund Reason",
        help="Reason for the refund (MultiSafepay specific)",
        copy=False,
    )

    # ===================================
    # ENHANCED: OVERRIDE CORE METHOD
    # ===================================

    def _create_child_transaction(self, amount, is_refund=False, **custom_create_values):
        """Override to add MultiSafepay refund reason when creating refund transaction.
        
        The reason can come from context (set by the wizard).
        
        :param amount: The transaction amount
        :param is_refund: Whether this is a refund transaction
        :param custom_create_values: Additional values for transaction creation
        :return: Created child transaction
        :rtype: recordset
        """
        # Get the refund reason from the context (set by the wizard)
        if is_refund and self.provider_code == 'multisafepay':
            refund_reason = self.env.context.get('multisafepay_refund_reason')
            _logger.debug("Creating refund transaction. Provider: %s, Reason from context: %s", 
                        self.provider_code, refund_reason)
            if refund_reason:
                custom_create_values['multisafepay_refund_reason'] = refund_reason
                _logger.debug("Added reason to custom_create_values: %s", refund_reason)
        
        # Call the parent method (CORE) with the updated custom_create_values
        result = super()._create_child_transaction(amount, is_refund=is_refund, **custom_create_values)
        _logger.debug("Child transaction created. ID: %s, Reason field: %s", 
                    result.id, result.multisafepay_refund_reason)
        return result
