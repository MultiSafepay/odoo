# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from odoo import models, fields, api, _
import logging

from multisafepay.api.paths.orders.order_id.update.request.update_request import UpdateOrderRequest

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = 'account.move'

    multisafepay_notified = fields.Boolean(
        string="MultiSafepay Notified",
        default=False,
        copy=False,
        help="Indicates whether MultiSafepay has been notified about this invoice"
    )

    def action_post(self):
        """Override to detect when invoices are validated/posted."""
        result = super().action_post()

        # Check if the invoice is an outgoing invoice
        for invoice in self.filtered(lambda m: m.move_type == 'out_invoice'):

            # If already notified, skip
            if invoice.multisafepay_notified:
                continue

            multisafepay_tx = False

            # Search for MultiSafepay transactions related to this invoice
            multisafepay_tx = self.env['payment.transaction'].search([
                ('invoice_ids', 'in', invoice.ids),
                ('provider_code', '=', 'multisafepay')
            ], limit=1)

            provider = multisafepay_tx.provider_id

            # If no transaction found, log and continue
            if not provider:
                _logger.warning("No provider found for transaction %s", multisafepay_tx.id)
                continue

            multisafepay_sdk = provider.get_multisafepay_sdk()

            # If no SDK found, log and continue
            if not multisafepay_sdk:
                _logger.warning("No MultiSafepay SDK found for provider %s", provider.name)
                continue

            order_manager = multisafepay_sdk.get_order_manager()

            try:

                update_order_request = UpdateOrderRequest().add_invoice_id(invoice.name)

                _logger.debug("MultiSafepay update order request: %s", str(update_order_request.to_dict()))

                if(invoice.access_url):
                    update_order_request.add_invoice_url(invoice.access_url)

                response = order_manager.update(multisafepay_tx.reference, update_order_request)

                _logger.debug("MultiSafepay update order request response: %s", str(response))

                if response.status_code == 200:

                    # Mark the invoice as notified
                    invoice.multisafepay_notified = True


            except Exception as e:
                _logger.error("Error retrieving MultiSafepay order: %s", e)

        return result
