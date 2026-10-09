# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import logging

from odoo import api, fields, models

from .. import const

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
            Pricelist filtering moved to payment_multisafepay_enhanced module (custom feature)

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
            self._report_filtered_methods(
                report, filtered_out, "amount", {"amount": amount}
            )

        # Apply BNPL filtering if shopping cart is disabled
        providers = (
            self.env["payment.provider"].browse(provider_ids)
            if isinstance(provider_ids, list)
            else provider_ids
        )

        multisafepay_providers = providers.filtered(lambda p: p.code == "multisafepay")

        if any(
            not getattr(p, "multisafepay_active_shopping_cart", False)
            for p in multisafepay_providers
        ):
            methods_before_bnpl = payment_methods

            def is_not_bnpl(method):
                if not method.code.startswith(const.PAYMENT_METHOD_PREFIX):
                    return True
                clean_code = method.code[len(const.PAYMENT_METHOD_PREFIX) :]
                return clean_code not in const.BNPL_METHODS

            payment_methods = payment_methods.filtered(is_not_bnpl)

            filtered_out_bnpl = methods_before_bnpl - payment_methods
            self._report_filtered_methods(
                report,
                filtered_out_bnpl,
                "bnpl",
                "Shopping cart is disabled, 'Pay After Delivery' (BNPL) methods are unavailable",
            )

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

        # Log filtering information
        filtered_out_methods = multisafepay_methods - allowed_multisafepay_methods
        if filtered_out_methods:
            filtered_method_names = [m.name for m in filtered_out_methods]
            _logger.info(
                "Amount filtering: %d MultiSafepay methods filtered out for amount %.2f: %s",
                len(filtered_out_methods),
                amount,
                ", ".join(filtered_method_names),
            )

        # Return all non-MultiSafepay methods plus filtered MultiSafepay methods
        return other_methods + allowed_multisafepay_methods

    # ===================================
    # MULTISAFEPAY - Availability Report
    # ===================================

    def _add_method_to_availability_report(
        self, report, method, reason, available=False
    ):
        """Add or update a payment method entry in the availability report.

        :param report: The availability report dictionary
        :type report: dict or None
        :param method: The payment method to add/update
        :type method: recordset
        :param reason: The reason why the method is/isn't available
        :type reason: str
        :param available: Whether the method is available
        :type available: bool
        :return: None
        """
        if report is None:
            return

        if "payment_methods" not in report:
            report["payment_methods"] = {}

        if method in report["payment_methods"]:
            # Update existing entry - combine reasons
            existing_reason = report["payment_methods"][method].get("reason", "")
            if existing_reason:
                report["payment_methods"][method]["reason"] = (
                    f"{existing_reason}; {reason}"
                )
            else:
                report["payment_methods"][method]["reason"] = reason
            report["payment_methods"][method]["available"] = available
        else:
            # Create new entry
            report["payment_methods"][method] = {
                "available": available,
                "reason": reason,
                "supported_providers": [
                    (provider, True) for provider in method.provider_ids
                ],
            }

    def _report_filtered_methods(self, report, filtered_methods, filter_type, context):
        """Add filtered methods to availability report with appropriate reasons.

        :param report: Availability report dictionary (can be None)
        :type report: dict or None
        :param filtered_methods: Recordset of methods that were filtered out
        :type filtered_methods: recordset
        :param filter_type: Type of filter ('amount' or 'pricelist', or 'bnpl')
        :type filter_type: str
        :param context: Dictionary with context data (e.g., {'amount': 100.0} or {'pricelist': recordset}) or a string message for simple filters like 'bnpl'
        :type context: dict or str
        :return: None
        """
        if report is None or not filtered_methods:
            return

        for method in filtered_methods:
            if filter_type == "amount":
                reason_parts = self._generate_amount_filter_reasons(
                    method, context.get("amount")
                )
            elif filter_type == "pricelist":
                reason_parts = self._generate_pricelist_filter_reasons(
                    method, context.get("pricelist")
                )
            elif filter_type == "bnpl":
                reason_parts = (
                    [context]
                    if isinstance(context, str)
                    else [f"Filtered by {filter_type}"]
                )
            else:
                reason_parts = [f"Filtered by {filter_type}"]

            if reason_parts:
                self._add_method_to_availability_report(
                    report, method, "; ".join(reason_parts), available=False
                )

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

    # Note: _generate_pricelist_filter_reasons() method moved to payment_multisafepay_enhanced module (custom feature)
