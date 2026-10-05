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
        help="The main currency of the provider of this payment method.",
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
        help="Technical field to identify if this payment method belongs to the MultiSafepay provider.",
    )

    # ===================================
    # COMPUTE METHODS (ODOO)
    # ===================================

    @api.depends("provider_id.code")
    def _compute_is_multisafepay(self):
        """Compute if this payment method belongs to the MultiSafepay provider.

        :return: None
        """
        # migracion_19_20: payment.method.provider_ids (m2m) became provider_id (m2o) in Odoo 20.
        for method in self:
            method.only_multisafepay = method.provider_id.code == "multisafepay"

    @api.depends("provider_id.main_currency_id")
    def _compute_main_currency_id(self):
        """Compute the main currency from the provider.

        :return: None
        """
        # migracion_19_20: payment.method.provider_ids (m2m) became provider_id (m2o) in Odoo 20.
        for method in self:
            method.main_currency_id = method.provider_id.main_currency_id

    # ===================================
    # BUSINESS METHODS (ODOO)
    # ===================================

    # migracion_19_20: replaces payment.method._get_compatible_payment_methods, removed in Odoo 20.
    def _apply_multisafepay_filters(self, report=None, **kwargs):
        """Filter payment methods by MultiSafepay amount limits and BNPL support.

        Called by `payment.provider._find_available_payment_methods` with the methods
        found for the available providers. It supports:

        - Amount-based filtering (minimum/maximum amount from MultiSafepay API)
        - Availability reporting for debugging

        .. note::
            Pricelist filtering moved to payment_multisafepay_enhanced module (custom feature)

        :param report: Dictionary to store availability report information
        :param kwargs: Payment context forwarded by Odoo (amount, sale_order_id, etc.)
        :return: Filtered payment methods based on the provided criteria
        :rtype: recordset of `payment.method`
        """

        payment_methods = self

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
        # migracion_19_20: a payment method has a single provider now, so the cart setting is read from provider_id.
        def is_not_bnpl(method):
            provider = method.provider_id
            if (
                provider.code != "multisafepay"
                or provider.multisafepay_active_shopping_cart
            ):
                return True
            if not method.code.startswith(const.PAYMENT_METHOD_PREFIX):
                return True
            clean_code = method.code[len(const.PAYMENT_METHOD_PREFIX) :]
            return clean_code not in const.BNPL_METHODS

        methods_before_bnpl = payment_methods
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
                (not method.minimum_amount or amount >= method.minimum_amount)
                and (not method.maximum_amount or amount <= method.maximum_amount)
            )
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
            # migracion_19_20: Odoo 20 report entries only hold available and reason (supported_providers is gone).
            report["payment_methods"][method] = {
                "available": available,
                "reason": reason,
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
