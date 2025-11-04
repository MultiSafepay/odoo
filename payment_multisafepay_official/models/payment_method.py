# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import logging

from odoo import api, fields, models

try:
    from odoo.http import request
except ImportError:
    # Graceful handling when http module is not available (e.g., during module installation)
    request = None

_logger = logging.getLogger(__name__)


class PaymentMethod(models.Model):
    _inherit = 'payment.method'

    # ===================================
    # FIELDS
    # ===================================
    
    main_currency_id = fields.Many2one(
        'res.currency',
        string="Main Currency",
        compute='_compute_main_currency_id',
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
        compute='_compute_is_multisafepay',
        store=False,
        help="Technical field to identify if this payment method has MultiSafepay as one of its providers.",
    )

    pricelist_ids = fields.Many2many(
        'product.pricelist',
        'payment_method_pricelist_rel',
        'method_id',
        'pricelist_id',
        string='Allowed Pricelists',
        help="Restrict this payment method to specific pricelists. "
             "If empty, the payment method will be available for all pricelists. "
             "When set, this payment method will only be visible for orders using one of the selected pricelists.",
    )

    # ===================================
    # COMPUTED FIELDS
    # ===================================

    @api.depends('provider_ids.code')
    def _compute_is_multisafepay(self):
        """Compute if this payment method has MultiSafepay as one of its providers."""
        for method in self:
            providers = method.provider_ids
            # Check if ANY provider is MultiSafepay (not just if it's the only one)
            method.only_multisafepay = any(
                provider.code == 'multisafepay' for provider in providers
            )

    @api.depends('provider_ids.main_currency_id')
    def _compute_main_currency_id(self):
        """Compute the main currency from the first provider."""
        for method in self:
            provider = method.provider_ids[:1]
            method.main_currency_id = provider.main_currency_id if provider else False

    # ===================================
    # ODOO CORE OVERRIDES
    # ===================================#
    def _get_compatible_payment_methods(
        self, provider_ids, partner_id, currency_id=None, force_tokenization=False,
        is_express_checkout=False, report=None, **kwargs):
        """Override core method to add amount and pricelist filtering for MultiSafepay payment methods.
        
        This method extends Odoo's standard payment method filtering to support:
        - Amount-based filtering (minimum/maximum amount restrictions)
        - Pricelist-based filtering (restrict methods to specific pricelists)
        - Availability reporting for debugging
        :param provider_ids: List of provider IDs to filter payment methods.
        :param partner_id: ID of the partner for whom the payment methods are being fetched.
        :param currency_id: ID of the currency for which the payment methods are being fetched.
        :param force_tokenization: Boolean indicating if tokenization is forced.
        :param is_express_checkout: Boolean indicating if the request is for express checkout.
        :param report: Dictionary to store availability report information.
        :param kwargs: Additional keyword arguments.
        :return: Filtered payment methods based on the provided criteria.
        :rtype: recordset of `payment.method`
        """

        payment_methods = super()._get_compatible_payment_methods(
            provider_ids, partner_id, currency_id, force_tokenization, is_express_checkout, 
            report=report, **kwargs
        )

        # Store original methods for reporting
        original_multisafepay_methods = payment_methods.filtered(lambda method: method.only_multisafepay)

        amount = kwargs.get('amount')

        sale_order_id = kwargs.get('sale_order_id')
        if sale_order_id and 'sale.order' in self.env:
            try:
                order = self.env['sale.order'].browse(sale_order_id)
                if order.exists():
                    amount = order.amount_total
                    _logger.debug("Using amount %s from sale order %s", amount, order.name)
            except (ValueError, TypeError, AttributeError) as e:
                _logger.error("Error getting amount from sale order: %s", str(e))

        if amount is None:
            _logger.debug("Amount not found in kwargs, checking request parameters")
            try:
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
            except (AttributeError, KeyError) as e:
                _logger.error("Error getting amount from request: %s", str(e))

        # Apply amount filtering
        if amount is not None:
            methods_before_amount = payment_methods.filtered(lambda m: m.only_multisafepay)
            payment_methods = payment_methods._filter_by_amount(amount)
            methods_after_amount = payment_methods.filtered(lambda m: m.only_multisafepay)
            
            # Report filtered methods
            filtered_out = methods_before_amount - methods_after_amount
            self._report_filtered_methods(report, filtered_out, 'amount', {'amount': amount})

        # Apply pricelist filtering automatically if we have access to the current order
        try:
            if request and hasattr(request, 'cart') and request.cart and request.cart.exists():
                pricelist = request.cart.pricelist_id
                if pricelist and pricelist.exists():
                    multisafepay_methods_before_pricelist = payment_methods.filtered(lambda method: method.only_multisafepay)
                    payment_methods = payment_methods._filter_by_pricelist(pricelist)
                    multisafepay_methods_after_pricelist = payment_methods.filtered(lambda method: method.only_multisafepay)
                    
                    # Add pricelist filtering information to report
                    if report is not None:
                        filtered_out_by_pricelist = multisafepay_methods_before_pricelist - multisafepay_methods_after_pricelist
                        for method in filtered_out_by_pricelist:
                            pricelist_reason = f"Not allowed for pricelist '{pricelist.name}'"
                            self._add_method_to_availability_report(
                                report, method, pricelist_reason, available=False
                            )
                    
                    _logger.debug("Applied pricelist filtering for pricelist: %s", pricelist.name)
        except (ImportError, AttributeError) as e:
            # No request context or cart available, skip pricelist filtering
            _logger.debug("No request context available for pricelist filtering: %s", str(e))

        return payment_methods

    # ===================================
    # FILTERING HELPER METHODS
    # ===================================

    def _filter_by_amount(self, amount):
        """Filter payment methods based on amount restrictions.
        
        Only applies amount filtering to MultiSafepay payment methods.
        Other payment providers are not affected by amount restrictions.
        
        Args:
            amount (float): The payment amount to filter by
            
        Returns:
            recordset: Filtered payment methods that are allowed for the given amount
        """
        if amount is None:
            return self
        
        # Separate MultiSafepay methods from other payment methods
        multisafepay_methods = self.filtered(lambda method: method.only_multisafepay)
        other_methods = self.filtered(lambda method: not method.only_multisafepay)
        
        # Apply amount filtering only to MultiSafepay methods
        allowed_multisafepay_methods = multisafepay_methods.filtered(
            lambda method: (not method.minimum_amount or amount >= method.minimum_amount) and
                          (not method.maximum_amount or amount <= method.maximum_amount)
        )
        
        # Log filtering information
        filtered_out_methods = multisafepay_methods - allowed_multisafepay_methods
        if filtered_out_methods:
            filtered_method_names = [m.name for m in filtered_out_methods]
            _logger.info(
                "Amount filtering: %d MultiSafepay methods filtered out for amount %.2f: %s",
                len(filtered_out_methods),
                amount,
                ', '.join(filtered_method_names)
            )
        
        # Return all non-MultiSafepay methods plus filtered MultiSafepay methods
        return other_methods + allowed_multisafepay_methods

    def _filter_by_pricelist(self, pricelist):
        """Filter payment methods based on pricelist restrictions.
        
        Only applies pricelist filtering to MultiSafepay payment methods.
        Other payment providers are not affected by pricelist restrictions.
        
        Args:
            pricelist (product.pricelist): The pricelist to filter by
            
        Returns:
            recordset: Filtered payment methods that are allowed for the given pricelist
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
                ', '.join(filtered_method_names)
            )
            
        if allowed_multisafepay_methods:
            allowed_method_names = [m.name for m in allowed_multisafepay_methods]
            _logger.info(
                "Pricelist filtering: %d MultiSafepay methods allowed for pricelist '%s': %s", 
                len(allowed_multisafepay_methods),
                pricelist.name,
                ', '.join(allowed_method_names)
            ) 
        
        # Return all non-MultiSafepay methods plus filtered MultiSafepay methods
        return other_methods + allowed_multisafepay_methods

    # ===================================
    # PUBLIC API METHODS
    # ===================================

    @api.model
    def _get_compatible_payment_methods_with_pricelist(
        self, provider_ids, partner_id, currency_id=None, force_tokenization=False,
        is_express_checkout=False, pricelist_id=None, **kwargs):
        """Get payment methods compatible with the given criteria, including pricelist filtering.
        
        This method extends the standard method filtering to include pricelist-based restrictions.
        
        Args:
            provider_ids: Provider IDs for filtering
            partner_id: Partner ID for filtering  
            currency_id: Currency ID for filtering
            force_tokenization: Force tokenization flag
            is_express_checkout: Express checkout flag
            pricelist_id: Pricelist ID for filtering
            **kwargs: Additional filtering criteria
            
        Returns:
            recordset: Compatible payment methods
        """
        # Get standard compatible methods
        methods = self._get_compatible_payment_methods(
            provider_ids, partner_id, currency_id, force_tokenization, 
            is_express_checkout, **kwargs
        )
        
        # Apply pricelist filtering if provided
        if pricelist_id:
            pricelist = self.env['product.pricelist'].browse(pricelist_id)
            methods = methods._filter_by_pricelist(pricelist)
            
        return methods

    # ===================================
    # AVAILABILITY REPORT HELPERS
    # ===================================
    
    def _add_method_to_availability_report(self, report, method, reason, available=False):
        """Add or update a payment method entry in the availability report.
        
        Args:
            report (dict): The availability report dictionary
            method (payment.method): The payment method to add/update
            reason (str): The reason why the method is/isn't available
            available (bool): Whether the method is available
        """
        if report is None:
            return
            
        if 'payment_methods' not in report:
            report['payment_methods'] = {}
            
        if method in report['payment_methods']:
            # Update existing entry - combine reasons
            existing_reason = report['payment_methods'][method].get('reason', '')
            if existing_reason:
                report['payment_methods'][method]['reason'] = f"{existing_reason}; {reason}"
            else:
                report['payment_methods'][method]['reason'] = reason
            report['payment_methods'][method]['available'] = available
        else:
            # Create new entry
            report['payment_methods'][method] = {
                'available': available,
                'reason': reason,
                'supported_providers': [(provider, True) for provider in method.provider_ids]
            }
    
    def _report_filtered_methods(self, report, filtered_methods, filter_type, context):
        """
        Add filtered methods to availability report with appropriate reasons.
        
        Args:
            report: Availability report dictionary (can be None)
            filtered_methods: Recordset of methods that were filtered out
            filter_type: Type of filter ('amount' or 'pricelist')
            context: Dictionary with context data (e.g., {'amount': 100.0} or {'pricelist': recordset})
        """
        if report is None or not filtered_methods:
            return
            
        for method in filtered_methods:
            if filter_type == 'amount':
                reason_parts = self._generate_amount_filter_reasons(method, context.get('amount'))
            elif filter_type == 'pricelist':
                reason_parts = self._generate_pricelist_filter_reasons(method, context.get('pricelist'))
            else:
                reason_parts = [f"Filtered by {filter_type}"]
            
            if reason_parts:
                self._add_method_to_availability_report(
                    report, method, '; '.join(reason_parts), available=False
                )
    
    def _generate_amount_filter_reasons(self, method, amount):
        """Generate reason messages for amount filtering.
        
        Args:
            method (payment.method): The payment method
            amount (float): The payment amount
            
        Returns:
            list: List of reason strings
        """
        reason_parts = []
        if method.minimum_amount and amount < method.minimum_amount:
            reason_parts.append(f"Amount {amount} below minimum {method.minimum_amount}")
        if method.maximum_amount and amount > method.maximum_amount:
            reason_parts.append(f"Amount {amount} above maximum {method.maximum_amount}")
        return reason_parts

    def _generate_pricelist_filter_reasons(self, method, pricelist):
        """
        Generate human-readable reasons why a payment method was filtered by pricelist.
        
        Args:
            method: Payment method record
            pricelist: Pricelist record
            
        Returns:
            List of reason strings
        """
        reason_parts = []
        
        if not pricelist:
            return reason_parts
            
        if method.pricelist_ids and pricelist not in method.pricelist_ids:
            allowed_names = ', '.join(method.pricelist_ids.mapped('name'))
            reason_parts.append(
                f"Not allowed for pricelist '{pricelist.name}' "
                f"(allowed: {allowed_names})"
            )
        
        return reason_parts
