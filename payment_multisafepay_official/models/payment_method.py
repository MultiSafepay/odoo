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

    pricelist_ids = fields.Many2many(
        'product.pricelist',
        'payment_method_pricelist_rel',
        'method_id',
        'pricelist_id',
        string='Allowed Pricelists',
        help="Restrict this payment method to specific pricelists. "
             "If empty, the payment method will be available for all pricelists. "
             "When set, this payment method will only be visible for orders using one of the selected pricelists."
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


    # === HELPER METHODS FOR AVAILABILITY REPORT ===#
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


    # === OVERRIDES ===#
    def _get_compatible_payment_methods(
        self, provider_ids, partner_id, currency_id=None, force_tokenization=False,
        is_express_checkout=False, report=None, **kwargs):
        """
        Override to filter payment methods based on minimum and maximum amounts and generate availability report.
        
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
            except (ValueError, TypeError, AttributeError) as e:
                _logger.error("Error getting amount from sale order: %s", str(e))

        if amount is None:
            try:
                if request and hasattr(request, 'httprequest') and hasattr(request.httprequest, 'args'):
                    amount_str = request.httprequest.args.get('amount')
                    if amount_str:
                        try:
                            amount = float(amount_str)
                        except (ValueError, TypeError):
                            _logger.error("Could not convert URL amount parameter to float: %s", amount_str)
            except ImportError:
                _logger.error("Could not import request object to get URL parameters")
            except (AttributeError, KeyError) as e:
                _logger.error("Error getting amount from request: %s", str(e))

        # Apply amount filtering and report results
        try:
            if amount is not None:
                filtered_by_amount = payment_methods.filtered(
                    lambda pm: (not pm.minimum_amount or amount >= pm.minimum_amount) and
                            (not pm.maximum_amount or amount <= pm.maximum_amount)
                )
                
                # Add amount filtering information to report
                if report is not None:
                    for method in original_multisafepay_methods:
                        if method not in filtered_by_amount:
                            reason_parts = self._generate_amount_filter_reasons(method, amount)
                            if reason_parts:
                                self._add_method_to_availability_report(
                                    report, method, '; '.join(reason_parts), available=False
                                )
                
                payment_methods = filtered_by_amount
                
        except (TypeError, ValueError, AttributeError) as e:
            _logger.error("Error applying amount filtering: %s", str(e))
            # Continue without amount filtering to avoid breaking the checkout process

        # Apply pricelist filtering automatically if we have access to the current order
        try:
            if request and hasattr(request, 'website') and request.website:
                sale_order = request.website.sale_get_order()
                if sale_order and sale_order.exists():
                    pricelist = sale_order.pricelist_id
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
        except (ImportError, AttributeError) as e:
            # No request context or website available, skip pricelist filtering
            pass

        return payment_methods

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
        
        # Return all non-MultiSafepay methods plus filtered MultiSafepay methods
        return other_methods + allowed_multisafepay_methods

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


