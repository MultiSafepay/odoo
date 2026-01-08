# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import logging

from odoo import api, fields, models

from odoo.addons.payment import utils as payment_utils

try:
    from odoo.http import request
except ImportError:
    # Graceful handling when http module is not available (e.g., during module installation)
    request = None

_logger = logging.getLogger(__name__)


class PaymentMethod(models.Model):
    """MultiSafepay Payment Method.

    Extends Odoo's payment.method model to add MultiSafepay-specific functionality
    including amount filtering, currency handling, and compatibility checks.
    """

    _inherit = "payment.method"

    # ===================================
    # FIELDS
    # ===================================

    main_currency_id = fields.Many2one(
        "res.currency",
        string="Main Currency",
        compute="_compute_main_currency_id",
        store=False,
        help="The main currency of the first provider linked to this payment method.",
    )

    minimum_amount = fields.Float(
        string="Minimum Amount (EUR)",
        help="The minimum payment amount in EUR that this payment provider is available for. "
        "Leave 0 to make it available for any payment amount.",
        default=0.0,
        digits=(16, 2),
    )

    maximum_amount = fields.Float(
        string="Maximum Amount (EUR)",
        help="The maximum payment amount in EUR that this payment provider is available for. "
        "Leave 0 to make it available for any payment amount.",
        default=0.0,
        digits=(16, 2),
    )

    only_multisafepay = fields.Boolean(
        compute="_compute_is_multisafepay",
        store=False,
        help="Technical field to identify if this payment method has MultiSafepay as one of its providers.",
    )

    # Note: pricelist_ids field moved to payment_multisafepay_enhaced module (custom feature)

    # ===================================
    # COMPUTE METHODS (ODOO)
    # ===================================

    @api.depends("provider_ids.code")
    def _compute_is_multisafepay(self):
        """Compute if this payment method has MultiSafepay as one of its providers.

        :return: None
        """
        for method in self:
            providers = method.provider_ids
            # Check if ANY provider is MultiSafepay (not just if it's the only one)
            method.only_multisafepay = any(
                provider.code == "multisafepay" for provider in providers
            )

    @api.depends("provider_ids.main_currency_id")
    def _compute_main_currency_id(self):
        """Compute the main currency from the first provider.

        :return: None
        """
        for method in self:
            provider = method.provider_ids[:1]
            method.main_currency_id = provider.main_currency_id if provider else False

    # ===================================
    # BUSINESS METHODS (ODOO)
    # ===================================

    def _get_compatible_payment_methods(
        self,
        provider_ids,
        partner_id,
        currency_id=None,
        force_tokenization=False,
        is_express_checkout=False,
        report=None,
        **kwargs,
    ):
        """Override core method to add amount filtering for MultiSafepay payment methods.

        This method extends Odoo's standard payment method filtering to support:

        - Amount-based filtering (minimum/maximum amount from MultiSafepay API)
        - Availability reporting for debugging

        .. note::
            Pricelist filtering moved to payment_multisafepay_enhaced module (custom feature)

        :param provider_ids: List of provider IDs to filter payment methods
        :param partner_id: ID of the partner for whom the payment methods are being fetched
        :param currency_id: ID of the currency for which the payment methods are being fetched
        :param force_tokenization: Boolean indicating if tokenization is forced
        :param is_express_checkout: Boolean indicating if the request is for express checkout
        :param report: Dictionary to store availability report information
        :param kwargs: Additional keyword arguments (amount, sale_order_id, etc.)
        :return: Filtered payment methods based on the provided criteria
        :rtype: recordset of `payment.method`
        """

        payment_methods = super()._get_compatible_payment_methods(
            provider_ids,
            partner_id,
            currency_id,
            force_tokenization,
            is_express_checkout,
            report=report,
            **kwargs,
        )

        amount = kwargs.get("amount")

        sale_order_id = kwargs.get("sale_order_id")
        if sale_order_id and "sale.order" in self.env:
            try:
                order = self.env["sale.order"].browse(sale_order_id)
                if order.exists():
                    amount = order.amount_total
                    _logger.debug(
                        "Using amount %s from sale order %s", amount, order.name
                    )
            except (ValueError, TypeError, AttributeError) as e:
                _logger.error("Error getting amount from sale order: %s", str(e))

        if amount is None:
            _logger.debug("Amount not found in kwargs, checking request parameters")
            try:
                if (
                    request
                    and hasattr(request, "httprequest")
                    and hasattr(request.httprequest, "args")
                ):
                    amount_str = request.httprequest.args.get("amount")
                    if amount_str:
                        try:
                            amount = float(amount_str)
                            _logger.debug("Using amount %s from URL parameters", amount)
                        except (ValueError, TypeError):
                            _logger.error(
                                "Could not convert URL amount parameter to float: %s",
                                amount_str,
                            )
            except ImportError:
                _logger.error("Could not import request object to get URL parameters")
            except (AttributeError, KeyError) as e:
                _logger.error("Error getting amount from request: %s", str(e))

        # Apply amount filtering (minimum_amount / maximum_amount from MultiSafepay API)
        if amount is not None:
            methods_before_amount = payment_methods.filtered(
                lambda m: m.only_multisafepay
            )
            payment_methods = payment_methods._filter_by_amount(amount)
            methods_after_amount = payment_methods.filtered(
                lambda m: m.only_multisafepay
            )

            # Report filtered methods
            filtered_out = methods_before_amount - methods_after_amount
            payment_utils.add_to_report(
                report,
                filtered_out,
                available=False,
                reason=f"Amount {amount} outside allowed range",
            )

        # Note: Pricelist filtering moved to payment_multisafepay_enhaced module (custom feature)

        return payment_methods

    # ===================================
    # MULTISAFEPAY - Filtering
    # ===================================

    def _filter_by_amount(self, amount):
        """Filter payment methods based on amount restrictions.

        Only applies amount filtering to MultiSafepay payment methods.
        Other payment providers are not affected by amount restrictions.

        :param amount: The payment amount to filter by
        :type amount: float
        :return: Filtered payment methods that are allowed for the given amount
        :rtype: recordset
        """
        if amount is None:
            return self

        # Separate MultiSafepay methods from other payment methods
        multisafepay_methods = self.filtered(lambda method: method.only_multisafepay)
        other_methods = self.filtered(lambda method: not method.only_multisafepay)

        # Apply amount filtering only to MultiSafepay methods
        allowed_multisafepay_methods = multisafepay_methods.filtered(
            lambda method: (
                not method.minimum_amount or amount >= method.minimum_amount
            )
            and (not method.maximum_amount or amount <= method.maximum_amount)
        )

        return allowed_multisafepay_methods | other_methods

    def _generate_amount_filter_reasons(self, method, amount):
        """Generate reason messages for amount filtering.

        Checks minimum_amount and maximum_amount restrictions from MultiSafepay API.

        :param method: The payment method
        :type method: recordset
        :param amount: The payment amount
        :type amount: float
        :return: List of reason strings
        :rtype: list
        """
        reason_parts = []
        if method.minimum_amount and amount < method.minimum_amount:
            reason_parts.append(
                f"Amount {amount} below minimum {method.minimum_amount}"
            )
        if method.maximum_amount and amount > method.maximum_amount:
            reason_parts.append(
                f"Amount {amount} above maximum {method.maximum_amount}"
            )
        return reason_parts

    # Note: _generate_pricelist_filter_reasons() method moved to payment_multisafepay_enhaced module (custom feature)
