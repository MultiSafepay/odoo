# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PaymentMethod(models.Model):
    _inherit = 'payment.method'

    main_currency_id = fields.Many2one(
        'res.currency',
        string="Main Currency",
        compute='_compute_main_currency_id',
        store=False,
        help="The main currency of the first provider linked to this payment method.",
    )

    minimum_amount = fields.Float(
        string="Minimum Amount (EUR)",
        help="The minimum payment amount in EUR that this payment provider is available for. Leave 0 to make it available for any payment amount.",
        default=0.0,
        digits=(16, 2),
    )

    maximum_amount = fields.Float(
        string="Maximum Amount (EUR)",
        help="The maximum payment amount in EUR that this payment provider is available for. Leave 0 to make it available for any payment amount.",
        default=0.0,
        digits=(16, 2),
    )

    only_multisafepay = fields.Boolean(
        compute='_compute_is_multisafepay',
        store=False,
    )

    # Depends
    @api.depends('provider_ids.code')
    def _compute_is_multisafepay(self):
        for method in self:
            providers = method.provider_ids
            method.only_multisafepay = (
                len(providers) == 1 and (
                    providers[0].code == 'multisafepay'
                )
            )

    @api.depends('provider_ids.main_currency_id')
    def _compute_main_currency_id(self):
        for method in self:
            provider = method.provider_ids[:1]
            method.main_currency_id = provider.main_currency_id if provider else False


    # === OVERRIDES ===#
    def _get_compatible_payment_methods(
        self, provider_ids, partner_id, currency_id=None, force_tokenization=False,
        is_express_checkout=False, **kwargs):
        """
        Override to filter payment methods based on minimum and maximum amounts.
        :param provider_ids: List of provider IDs to filter payment methods.
        :param partner_id: ID of the partner for whom the payment methods are being fetched.
        :param currency_id: ID of the currency for which the payment methods are being fetched.
        :param force_tokenization: Boolean indicating if tokenization is forced.
        :param is_express_checkout: Boolean indicating if the request is for express checkout.
        :param kwargs: Additional keyword arguments.
        :return: Filtered payment methods based on the provided criteria.
        :rtype: recordset of `payment.method`
        """

        payment_methods = super()._get_compatible_payment_methods(
            provider_ids, partner_id, currency_id, force_tokenization, is_express_checkout, **kwargs
        )

        amount = kwargs.get('amount')

        sale_order_id = kwargs.get('sale_order_id')
        if sale_order_id and 'sale.order' in self.env:
            try:
                order = self.env['sale.order'].browse(sale_order_id)
                if order.exists():
                    amount = order.amount_total
                    _logger.debug("Using amount %s from sale order %s", amount, order.name)
            except Exception as e:
                _logger.error("Error getting amount from sale order: %s", str(e))

        if amount is None:
            _logger.debug("Amount not found in kwargs, checking request parameters")
            try:
                from odoo.http import request
                if request and hasattr(request, 'httprequest') and hasattr(request.httprequest, 'args'):
                    amount_str = request.httprequest.args.get('amount')
                    if amount_str:
                        try:
                            amount = float(amount_str)
                            _logger.debug("Using amount %s from URL parameters", amount)
                        except (ValueError, TypeError):
                            _logger.error("Could not convert URL amount parameter to float: %s", amount_str)
            except ImportError:
                _logger.error("Could not import request object to get URL parameters")
            except Exception as e:
                _logger.error("Error getting amount from request: %s", str(e))


        if amount is not None:
            payment_methods = payment_methods.filtered(
                lambda pm: (not pm.minimum_amount or amount >= pm.minimum_amount) and
                        (not pm.maximum_amount or amount <= pm.maximum_amount)
            )

        return payment_methods


    def _get_from_code(self, code, mapping=None):
        """ Override to ensure that the method is only returned if it is compatible with the given code. """
        mapping = mapping or {}
        methods = super()._get_from_code(code, mapping)
        if not methods:
            return methods
        # Filter methods to ensure they are compatible with the given code
        return methods.filtered(lambda m: m.provider_ids.code == code)

