# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

"""
ENHANCED MODULE: Adds pricelist filtering functionality to MultiSafepay payment methods.
This module EXTENDS payment_multisafepay (CORE) by adding custom pricelist restrictions.
"""

import logging

from odoo import api, fields, models

try:
    from odoo.http import request
except ImportError:
    request = None

_logger = logging.getLogger(__name__)


class PaymentMethod(models.Model):
    """Extend payment.method to add pricelist filtering (ENHANCED feature).

    This enhanced model extends the CORE payment_multisafepay functionality by adding
    pricelist-based filtering for payment methods, allowing merchants to restrict
    payment methods to specific pricelists.
    """

    _inherit = "payment.method"

    # ===================================
    # ENHANCED CUSTOM FIELDS
    # ===================================

    pricelist_ids = fields.Many2many(
        "product.pricelist",
        "payment_method_pricelist_rel",
        "method_id",
        "pricelist_id",
        string="Allowed Pricelists",
        help="Restrict this payment method to specific pricelists. "
        "If empty, the payment method will be available for all pricelists. "
        "When set, this payment method will only be visible for orders using one of the selected pricelists.",
    )

    # ===================================
    # ENHANCED: OVERRIDE CORE METHOD
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
        """Extend CORE method to add pricelist filtering for MultiSafepay methods.

        :param provider_ids: List of provider IDs to filter payment methods
        :param partner_id: ID of the partner for whom payment methods are fetched
        :param currency_id: ID of the currency for filtering
        :param force_tokenization: Whether tokenization is forced
        :param is_express_checkout: Whether this is for express checkout
        :param report: Dictionary to store availability report information
        :param kwargs: Additional keyword arguments
        :return: Filtered payment methods based on criteria
        :rtype: recordset
        """

        # Call CORE method first (handles amount filtering)
        payment_methods = super()._get_compatible_payment_methods(
            provider_ids,
            partner_id,
            currency_id,
            force_tokenization,
            is_express_checkout,
            report=report,
            **kwargs,
        )

        # ENHANCED: Apply pricelist filtering - try to get pricelist from multiple sources
        pricelist = self._get_pricelist_from_context(kwargs)

        if pricelist and pricelist.exists():
            multisafepay_methods_before_pricelist = payment_methods.filtered(
                lambda method: method.only_multisafepay
            )
            payment_methods = payment_methods._filter_by_pricelist(pricelist)
            multisafepay_methods_after_pricelist = payment_methods.filtered(
                lambda method: method.only_multisafepay
            )

            # Add pricelist filtering information to report
            if report is not None:
                filtered_out_by_pricelist = (
                    multisafepay_methods_before_pricelist
                    - multisafepay_methods_after_pricelist
                )
                for method in filtered_out_by_pricelist:
                    pricelist_reason = f"Not allowed for pricelist '{pricelist.name}'"
                    self._add_method_to_availability_report(
                        report, method, pricelist_reason, available=False
                    )

            _logger.debug(
                "Applied pricelist filtering for pricelist: %s", pricelist.name
            )
        else:
            _logger.debug("No pricelist found in context, skipping pricelist filtering")

        return payment_methods

    # ===================================
    # ENHANCED: PRICELIST FILTERING METHODS
    # ===================================

    def _get_pricelist_from_context(self, kwargs):
        """Get pricelist from multiple possible sources in the context.

        Tries to retrieve the pricelist in this priority order:
        1. Explicit pricelist_id in kwargs
        2. Sale order from sale_order_id in kwargs
        3. Current cart from website.sale_get_order() (e-commerce)
        4. Website's default pricelist

        :param kwargs: Additional keyword arguments that may contain pricelist information
        :type kwargs: dict
        :return: Pricelist recordset or empty recordset
        :rtype: recordset
        """
        # 1. Check if pricelist_id was explicitly passed
        pricelist_id = kwargs.get("pricelist_id")
        if pricelist_id:
            pricelist = self.env["product.pricelist"].browse(pricelist_id)
            if pricelist.exists():
                _logger.debug(
                    "Pricelist found from explicit pricelist_id: %s", pricelist.name
                )
                return pricelist

        # 2. Try to get pricelist from sale order
        sale_order_id = kwargs.get("sale_order_id")
        if sale_order_id and "sale.order" in self.env:
            try:
                order = self.env["sale.order"].browse(sale_order_id)
                if order.exists() and order.pricelist_id:
                    _logger.debug(
                        "Pricelist found from sale order %s: %s",
                        order.name,
                        order.pricelist_id.name,
                    )
                    return order.pricelist_id
            except (ValueError, TypeError, AttributeError) as e:
                _logger.debug("Error getting pricelist from sale order: %s", str(e))

        # 3. Try to get pricelist from current cart (e-commerce context)
        # Odoo 18: use website.sale_get_order() instead of request.cart
        try:
            if request and hasattr(request, "website") and request.website:
                sale_order = request.website.sale_get_order()
                if sale_order and sale_order.exists() and sale_order.pricelist_id:
                    _logger.debug(
                        "Pricelist found from cart: %s", sale_order.pricelist_id.name
                    )
                    return sale_order.pricelist_id
        except (ImportError, AttributeError) as e:
            _logger.debug("Error getting pricelist from cart: %s", str(e))

        # 4. Try to get pricelist from website (if in website context)
        try:
            if request and hasattr(request, "website") and request.website:
                website_pricelist = request.website.get_current_pricelist()
                if website_pricelist and website_pricelist.exists():
                    _logger.debug(
                        "Pricelist found from website: %s", website_pricelist.name
                    )
                    return website_pricelist
        except (ImportError, AttributeError) as e:
            _logger.debug("Error getting pricelist from website: %s", str(e))

        # No pricelist found
        return self.env["product.pricelist"]

    def _filter_by_pricelist(self, pricelist):
        """Filter payment methods based on pricelist restrictions (ENHANCED feature).

        Only applies pricelist filtering to MultiSafepay payment methods.
        Other payment providers are not affected by pricelist restrictions.

        :param pricelist: The pricelist to filter by
        :type pricelist: recordset
        :return: Filtered payment methods that are allowed for the given pricelist
        :rtype: recordset
        """
        if not pricelist:
            return self

        # Separate MultiSafepay methods from other payment methods
        multisafepay_methods = self.filtered(lambda method: method.only_multisafepay)
        other_methods = self.filtered(lambda method: not method.only_multisafepay)

        # Apply pricelist filtering only to MultiSafepay methods
        # Other methods are always allowed regardless of pricelist
        allowed_multisafepay_methods = multisafepay_methods.filtered(
            lambda method: not method.pricelist_ids or pricelist in method.pricelist_ids
        )

        # Log filtering information for debugging and reporting
        filtered_out_methods = multisafepay_methods - allowed_multisafepay_methods
        if filtered_out_methods:
            filtered_method_names = [m.name for m in filtered_out_methods]
            _logger.info(
                "Pricelist filtering: %d MultiSafepay methods filtered out due to pricelist '%s': %s",
                len(filtered_out_methods),
                pricelist.name,
                ", ".join(filtered_method_names),
            )

        if allowed_multisafepay_methods:
            allowed_method_names = [m.name for m in allowed_multisafepay_methods]
            _logger.info(
                "Pricelist filtering: %d MultiSafepay methods allowed for pricelist '%s': %s",
                len(allowed_multisafepay_methods),
                pricelist.name,
                ", ".join(allowed_method_names),
            )

        # Return all non-MultiSafepay methods plus filtered MultiSafepay methods
        return other_methods + allowed_multisafepay_methods

    @api.model
    def _get_compatible_payment_methods_with_pricelist(
        self,
        provider_ids,
        partner_id,
        currency_id=None,
        force_tokenization=False,
        is_express_checkout=False,
        pricelist_id=None,
        **kwargs,
    ):
        """Get payment methods compatible with given criteria, including pricelist filtering.

        This method extends the standard method filtering to include pricelist-based restrictions.

        :param provider_ids: Provider IDs for filtering
        :type provider_ids: list
        :param partner_id: Partner ID for filtering
        :type partner_id: int
        :param currency_id: Currency ID for filtering
        :type currency_id: int or None
        :param force_tokenization: Force tokenization flag
        :type force_tokenization: bool
        :param is_express_checkout: Express checkout flag
        :type is_express_checkout: bool
        :param pricelist_id: Pricelist ID for filtering
        :type pricelist_id: int or None
        :param kwargs: Additional filtering criteria
        :return: Compatible payment methods
        :rtype: recordset
        """
        # Get standard compatible methods
        methods = self._get_compatible_payment_methods(
            provider_ids,
            partner_id,
            currency_id,
            force_tokenization,
            is_express_checkout,
            **kwargs,
        )

        # Apply pricelist filtering if provided
        if pricelist_id:
            pricelist = self.env["product.pricelist"].browse(pricelist_id)
            methods = methods._filter_by_pricelist(pricelist)

        return methods

    def _generate_pricelist_filter_reasons(self, method, pricelist):
        """Generate human-readable reasons for pricelist filtering (ENHANCED feature).

        :param method: Payment method record
        :type method: recordset
        :param pricelist: Pricelist record
        :type pricelist: recordset
        :return: List of reason strings
        :rtype: list
        """
        reason_parts = []

        if not pricelist:
            return reason_parts

        if method.pricelist_ids and pricelist not in method.pricelist_ids:
            allowed_names = ", ".join(method.pricelist_ids.mapped("name"))
            reason_parts.append(
                f"Not allowed for pricelist '{pricelist.name}' "
                f"(allowed: {allowed_names})"
            )

        return reason_parts
