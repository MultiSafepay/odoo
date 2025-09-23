# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from odoo import models, fields, api, _
import logging

from multisafepay.api.paths.orders.order_id.update.request.update_request import UpdateOrderRequest

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    multisafepay_notified = fields.Boolean(
        string="MultiSafepay Notified",
        copy=False,
        default=False,
        help="Indicates whether MultiSafepay has been notified about this shipment"
    )


    def _action_done(self):
        """Override to detect when pickings are marked as done."""
        # Call original method first
        result = super(StockPicking, self)._action_done()

        multisafepay_tx = False

        # Search for MultiSafepay transactions related to this picking
        for picking in self:

            # Check if this picking have is related to a multisafepay transaction
            if picking.multisafepay_notified:
                _logger.info("MultiSafepay already notified for picking %s", picking.name)
                continue

            # Find MultiSafepay transaction through the sale order
            multisafepay_tx = self.env['payment.transaction'].search([
                ('sale_order_ids', 'in', [picking.sale_id.id]),
                ('provider_code', '=', 'multisafepay')
            ], limit=1)

            # If no transaction found, log and continue
            if not multisafepay_tx:
                _logger.info("No MultiSafepay transaction found for order %s", picking.sale_id.name)
                continue

            # Check if this is the last picking (all others are done or cancelled)
            pending_pickings = self.env['stock.picking'].search([
                ('sale_id', '=', picking.sale_id.id),
                ('state', 'not in', ['done', 'cancel']),
                ('id', '!=', picking.id)  # Exclude current picking
            ])

            # Only notify MultiSafepay if this is the last shipment
            if pending_pickings:
                _logger.info("Order %s has pending pickings: %s. Not notifying MultiSafepay yet.",
                        picking.sale_id.name, pending_pickings.mapped('name'))
                continue

            # If we have a transaction, check if we need to notify MultiSafepay
            if not picking.multisafepay_notified:
                _logger.info("Notifying MultiSafepay for picking %s", picking.name)

                try:

                    provider = multisafepay_tx.provider_id
                    multisafepay_sdk = provider.get_multisafepay_sdk()

                    if not multisafepay_sdk:
                        _logger.warning("No MultiSafepay SDK found for provider %s", provider.name)
                        continue

                    order_manager = multisafepay_sdk.get_order_manager()

                    update_order_request = UpdateOrderRequest().add_status('shipped')

                    if picking.carrier_tracking_ref and picking.carrier_tracking_url and picking.carrier_id and picking.date_done:
                        update_order_request.add_tracktrace_code(picking.carrier_tracking_ref)
                        update_order_request.add_tracktrace_url(picking.carrier_tracking_url)
                        update_order_request.add_carrier(picking.carrier_id.name)
                        update_order_request.add_ship_date(picking.date_done.strftime('%Y-%m-%dT%H:%M:%S') if picking.scheduled_date else None)

                    _logger.debug("MultiSafepay update order request: %s", str(update_order_request.to_dict()))

                    response = order_manager.update(multisafepay_tx.reference, update_order_request)

                    _logger.debug("MultiSafepay update order request response: %s", str(response))

                    if response.status_code == 200:
                        _logger.info("MultiSafepay notified successfully for picking %s", picking.name)
                        # Mark the picking as notified
                        picking.multisafepay_notified = True

                    else:
                        _logger.error("Failed to notify MultiSafepay for picking %s", picking.name)

                except Exception as e:
                    _logger.error("Error notifying MultiSafepay for picking %s: %s", picking.name, str(e))
                    continue

                picking.multisafepay_notified = True

        return result
