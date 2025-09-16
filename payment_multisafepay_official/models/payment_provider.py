# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import logging

from multisafepay.sdk import Sdk

from odoo import fields, models

from .. import const
from ..utils import _get_image_base64

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):

    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('multisafepay', "Multisafepay")], ondelete={'multisafepay': 'set default'})

    multisafepay_api_key = fields.Char(
        string='API Key',
        help="The API key for the Multisafepay account. This is used to authenticate requests to the Multisafepay API.",
    )


    def write(self, vals):
        """Override to detect state changes and execute actions"""
        # Capture the state and API key before the write
        old_states = {record.id: record.state for record in self}
        old_api_keys = {record.id: record.multisafepay_api_key for record in self}

        # Execute original write
        result = super().write(vals)

        # If 'state' in vals and self.code == 'multisafepay':
        if 'state' in vals:
            for record in self.filtered(lambda r: r.code == 'multisafepay'):
                old_state = old_states.get(record.id)
                new_state = record.state

                if old_state != new_state:
                    try:
                        # Execute actions based on state change
                        record._on_state_changed(old_state, new_state)
                    except Exception as e:
                        _logger.error(f"Error in state change handling: {e}")
                        # Do not re-raise the exception to allow the change to complete


        #  Handle API key changes
        if 'multisafepay_api_key' in vals:
            for record in self.filtered(lambda r: r.code == 'multisafepay'):
                old_api_key = old_api_keys.get(record.id)
                new_api_key = record.multisafepay_api_key

                # Just in case, check that the API key actually changed and the provider is active or in test mode
                if (old_api_key != new_api_key and
                    record.state in ['enabled', 'test'] and
                    new_api_key):  # Only if new key is not empty
                    try:
                        record._on_api_key_changed(old_api_key, new_api_key)
                    except Exception as e:
                        _logger.error(f"Error in API key change handling: {e}")

        return result

    def _on_api_key_changed(self, old_api_key, new_api_key):
        """Handle API key change for MultiSafepay provider"""
        self.ensure_one()

        mode_label = "PRODUCTION" if self.state == 'enabled' else "TEST"
        _logger.info(f"MultiSafepay API key changed for {mode_label} environment")

        try:
            # Clean up payment methods related to the old API key
            cleanup_result = self._cleanup_multisafepay_payment_methods()
            _logger.info(f"API key change cleanup: {cleanup_result['removed']} removed, "
                        f"{cleanup_result['unlinked']} unlinked, {cleanup_result['deactivated']} deactivated")

            # Validate the new API key by fetching payment methods
            sync_result = self.fetch_merchant_payment_methods()

            # Verificar si la sincronización fue exitosa
            if sync_result.get('params', {}).get('type') == 'success':
                _logger.info(f"New API key validated and payment methods synchronized for {mode_label}")
                self._notify_api_key_change_success(mode_label, sync_result.get('params', {}).get('message', ''))
            else:
                # If the sync failed, revert to the old API key
                error_msg = sync_result.get('params', {}).get('message', 'Invalid API key or sync failed')
                _logger.error(f"API key validation failed: {error_msg}")
                self._notify_api_key_change_error(error_msg)

        except Exception as e:
            _logger.error(f"Failed to process API key change: %s", e)
            self._notify_api_key_change_error(f"API key change failed: {str(e)}")

    def _notify_api_key_change_success(self, mode_label, message):
        """Notify successful API key change"""
        self.env['bus.bus']._sendone(
            f'res.partner_{self.env.user.partner_id.id}',
            'simple_notification',
            {
                'title': f'MultiSafepay API Key Updated ({mode_label})',
                'message': f'API key successfully updated and payment methods synchronized. {message}',
                'type': 'success'
            }
        )

    def _notify_api_key_change_error(self, error_msg):
        """Notify API key change error"""
        self.env['bus.bus']._sendone(
            f'res.partner_{self.env.user.partner_id.id}',
            'simple_notification',
            {
                'title': 'MultiSafepay API Key Error',
                'message': f'Failed to validate new API key: {error_msg}',
                'type': 'danger'
            }
        )

    def _on_state_changed(self, old_state, new_state):
        """Handle state change for MultiSafepay provider"""
        self.ensure_one()

        _logger.info(f"MultiSafepay provider {self.name} state changed: {old_state} → {new_state}")

        if new_state in ['enabled', 'test']:
            self._on_provider_update(old_state)
        elif new_state == 'disabled':
            self._on_provider_disabled(old_state)


    def _on_provider_disabled(self, old_state):
        """Actions when provider is disabled"""

        # Cancel transactions that are in draft or pending state
        pending_transactions = self.env['payment.transaction'].search([
            ('provider_id', '=', self.id),
            ('state', 'in', ['draft', 'pending'])
        ])

        # Remove payment methods related to MultiSafepay
        self._cleanup_multisafepay_payment_methods()
        _logger.info("MultiSafepay provider disabled")


    def _on_provider_update(self, old_state):
        """Actions when provider is in test mode"""
        _logger.info("MultiSafepay provider in TEST mode")

        try:
            self.pull_merchant_payment_methods()
            _logger.info("MultiSafepay provider updated")

        except Exception as e:
            _logger.error("Failed the Multisafepay update: %s", e)

        self._notify_state_change("test", "Provider is in TEST mode - no real payments will be processed")


    def _notify_state_change(self, new_state, message):
        """Send notification about state change"""
        # Notification in the system

        self.env['bus.bus']._sendone(
            f'res.partner_{self.env.user.partner_id.id}',
            'simple_notification',
            {
                'title': f'MultiSafepay Provider {new_state.title()}',
                'message': message,
                'type': 'info' if new_state == 'test' else 'success' if new_state == 'enabled' else 'warning'
            }
        )

    def _get_default_support_refund(self):
        if self.code == 'multisafepay':
            return True
        return super()._get_default_support_refund()


    def _get_supported_currencies(self):
        """ Override of `payment` to return the supported currencies for MultiSafepay.
        This method retrieves the supported currencies for the MultiSafepay payment provider.
        Returns:
            recordset: A recordset of res.currency containing the supported currencies."""

        supported_currencies = super()._get_supported_currencies()
        if self.code == 'multisafepay':
            supported_currencies = supported_currencies.filtered(
                lambda c: c.name in const.SUPPORTED_CURRENCIES
            )
        return supported_currencies


    def _cleanup_multisafepay_payment_methods(self):
        """Clean up payment methods associated with this MultiSafepay provider

        This method handles payment methods in three ways:
        - Remove: Delete methods that only belong to this provider and have no transactions
        - Unlink: Remove provider association from methods shared with other providers
        - Deactivate: Disable methods that have transactions but keep them for history

        Returns:
            dict: Summary with counts of removed, unlinked, and deactivated methods
        """
        self.ensure_one()

        # Search payment methods only if the provider is MultiSafepay
        multisafepay_methods = self.env['payment.method'].with_context(active_test=False).search([
            ('provider_ids', 'in', [self.id])
        ])

        _logger.info(f"Found {len(multisafepay_methods)} payment methods for this provider")

        if not multisafepay_methods:
            _logger.info("No payment methods found for this MultiSafepay provider")
            return {'removed': 0, 'unlinked': 0, 'deactivated': 0}

        methods_to_remove = []
        methods_to_unlink = []
        methods_to_deactivate = []

        for method in multisafepay_methods:
            # Use .ids to access the IDs of the many2many
            provider_ids = method.provider_ids.ids

            # Verify if the method has transactions
            has_transactions = self.env['payment.transaction'].search_count([
                ('payment_method_id', '=', method.id)
            ]) > 0

            if has_transactions:
                # If it has transactions, we deactivate it
                methods_to_deactivate.append(method.id)
                _logger.info(f"Deactivating payment method (has transactions): {method.name} (code: {method.code})")
            elif len(provider_ids) == 1 and self.id in provider_ids:
                # Only related to this provider and has no transactions -> remove
                methods_to_remove.append(method.id)
                _logger.info(f"Removing payment method: {method.name} (code: {method.code})")
            elif len(provider_ids) > 1 and self.id in provider_ids:
                # Related with other providers -> just unlink
                methods_to_unlink.append(method.id)
                _logger.info(f"Unlinking payment method: {method.name} from MultiSafepay provider")

        # Remove methods that have no transactions and only belong to this provider
        removed_count = 0
        if methods_to_remove:
            try:
                self.env['payment.method'].browse(methods_to_remove).unlink()
                removed_count = len(methods_to_remove)
                _logger.info(f"Removed {removed_count} payment methods")
            except Exception as e:
                _logger.error(f"Error removing methods: {e}")
                # If fails, move to deactivate
                methods_to_deactivate.extend(methods_to_remove)
                removed_count = 0

        # Unlink methods that contain other providers
        unlinked_count = 0
        if methods_to_unlink:
            try:
                for method_id in methods_to_unlink:
                    method = self.env['payment.method'].browse(method_id)
                    method.write({'provider_ids': [(3, self.id, 0)]})  # (3, id, 0) = unlink
                unlinked_count = len(methods_to_unlink)
                _logger.info(f"Unlinked {unlinked_count} payment methods from provider")
            except Exception as e:
                _logger.error(f"Error unlinking methods: {e}")

        # Disable methods that have transactions
        deactivated_count = 0
        if methods_to_deactivate:
            try:
                deactivate_methods = self.env['payment.method'].browse(methods_to_deactivate)
                deactivate_methods.write({'active': False})
                # Also unlink the provider
                deactivate_methods.write({'provider_ids': [(3, self.id, 0)]})
                deactivated_count = len(methods_to_deactivate)
                _logger.info(f"Deactivated {deactivated_count} payment methods (had transactions)")
            except Exception as e:
                _logger.error(f"Error deactivating methods: {e}")

        _logger.info(f"Payment methods cleanup complete: {removed_count} removed, {unlinked_count} unlinked, {deactivated_count} deactivated")

        return {
            'removed': removed_count,
            'unlinked': unlinked_count,
            'deactivated': deactivated_count
        }


    def _fetch_merchant_payment_methods(self):
        """ Pulls the merchant payment methods from MultiSafepay and updates or creates them in Odoo.
        This method connects to the MultiSafepay API using the provided API key, retrieves the available payment methods,
        and updates the payment methods in Odoo accordingly. If the API key is not set, it returns a warning notification.
        If the API key is set, it fetches the payment methods, creates new ones or updates existing ones based on the
        unique code derived from the payment method ID, and associates them with the current provider.

        Returns:
            dict: A dictionary containing the action to display a notification with the result of the operation.
        """

        self.ensure_one()
        _logger.info('Pulling merchant payment methods')

        if not self.multisafepay_api_key:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'MultiSafepay',
                    'message': 'No API key found. Please configure your API key first.',
                    'type': 'warning',
                }
            }

        try:
            multisafepay_sdk = self.get_multisafepay_sdk()

            gateway_manager = multisafepay_sdk.get_payment_method_manager()
            custom_response = gateway_manager.get_payment_methods()
            gateways = custom_response.get_data()
            if not gateways or len(gateways) == 0:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'MultiSafepay',
                        'message': 'No payment methods found',
                        'type': 'warning',
                    }
                }

            count_new = 0
            count_updated = 0
            payment_method = self.env['payment.method']

            for gateway in gateways:

                multisafepay_code = gateway.id.lower()
                unique_code = self._map_multisafepay_to_odoo_code(multisafepay_code)
                _logger.info("Mapping MultiSafepay '%s' to Odoo code '%s'", multisafepay_code, unique_code)

                country_ids = []
                if gateway.allowed_countries and len(gateway.allowed_countries) > 0:
                    all_countries = self.env['res.country'].search([])
                    for country in gateway.allowed_countries:
                        country_record = all_countries.filtered(lambda r: r.code == country)
                        if country_record:
                            country_ids.append(country_record.id)

                currency_ids = []
                if gateway.allowed_currencies and len(gateway.allowed_currencies) > 0:
                    all_currencies = self.env['res.currency'].with_context(active_test=False).search([])
                    for currency in gateway.allowed_currencies:
                        currency_record = all_currencies.filtered(lambda r: r.name == currency)
                        if currency_record:
                            currency_ids.append(currency_record.id)

                domain = [
                    ('code', '=', unique_code),
                    '|',
                    ('provider_ids', 'in', [self.id]),
                    ('provider_ids', '=', False)
                ]
                existing = payment_method.search(domain, limit=1)

                vals = {
                    'name': gateway.name or gateway.id,
                    'code': unique_code,
                    'active': True,
                    'support_refund': 'partial',  # MultiSafepay supports partial refunds
                }

                if gateway.allowed_amount:
                    if gateway.allowed_amount.min:
                        vals['minimum_amount'] = gateway.allowed_amount.min / 100.0
                    if gateway.allowed_amount.max:
                        vals['maximum_amount'] = gateway.allowed_amount.max / 100.0

                if country_ids:
                    vals['supported_country_ids'] = [(6, 0, country_ids)]

                if currency_ids:
                    vals['supported_currency_ids'] = [(6, 0, currency_ids)]

                if gateway.icon_urls and gateway.icon_urls.large:
                    vals['image'] = _get_image_base64(url=gateway.icon_urls.large)

                if not existing:
                    main_method = payment_method.create(vals)
                    main_method.write({'provider_ids': [(4, self.id, 0)]})
                    count_new += 1
                else:
                    existing.write(vals)
                    if self.id not in existing.provider_ids.ids:
                        existing.write({'provider_ids': [(4, self.id, 0)]})
                    main_method = existing
                    count_updated += 1

                for brand in gateway.brands:
                    if not brand.id:
                        continue

                    multisafepay_brand_code = brand.id.lower()
                    brand_code = self._map_multisafepay_to_odoo_code(multisafepay_brand_code)
                    brand_domain = [('code', '=', brand_code)]
                    brand_vals = {
                        'name': brand.name or brand.id,
                        'code': brand_code,
                        'active': False,
                        'primary_payment_method_id': main_method.id,
                        'support_refund': 'partial',  # MultiSafepay supports partial refunds
                    }

                    if brand.icon_urls and brand.icon_urls.large:
                        brand_vals['image'] = _get_image_base64(brand.icon_urls.large)

                    if currency_ids:
                        brand_vals['supported_currency_ids'] = [(6, 0, currency_ids)]

                    country_ids = []
                    if brand.allowed_countries and len(brand.allowed_countries) > 0:
                        all_countries = self.env['res.country'].search([])
                        for country in brand.allowed_countries:
                            country_record = all_countries.filtered(lambda r: r.code == country)
                            if country_record:
                                country_ids.append(country_record.id)

                    if country_ids:
                        brand_vals['supported_country_ids'] = [(6, 0, country_ids)]

                    brand_rec = payment_method.search(brand_domain, limit=1)

                    if not brand_rec:
                        main_brand_method = payment_method.create(brand_vals)
                        main_brand_method.write({'provider_ids': [(4, self.id, 0)]})

                    else:
                        brand_rec.write(brand_vals)
                        if self.id not in brand_rec.provider_ids.ids:
                            brand_rec.write({'provider_ids': [(4, self.id, 0)]})

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'MultiSafepay',
                    'message': f'{count_new} new methods, {count_updated} methods updated,',
                    'type': 'success',
                }
            }

        except Exception as e:
            _logger.error("Error loading payment methods: %s", e)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error',
                    'message': f'Failed to load payment methods: {str(e)}',
                    'type': 'danger',
                }
            }

    def pull_merchant_payment_methods(self):
        # Remove payment methods related to MultiSafepay
        self._cleanup_multisafepay_payment_methods()
        # Bring MultiSafepay payment methods
        self._fetch_merchant_payment_methods()
        _logger.info("MultiSafepay provider updated")

    def _compute_feature_support_fields(self):
        """ Compute the feature support fields based on the provider.

        Feature support fields are used to specify which additional features are supported by a given provider.
        These fields are as follows:

        support_express_checkout: Whether the “express checkout” feature is supported. False by default.
        support_manual_capture: Whether the “manual capture” feature is supported. False by default.
        support_refund: Which type of the “refunds” feature is supported: None, 'full_only', or 'partial'. None by default.
        support_tokenization: Whether the “tokenization feature” is supported. False by default.

        For a provider to specify that it supports additional features, it must override this method and set the related
        feature support fields to the desired value on the appropriate payment.provider records. """
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == 'multisafepay').update({
            'support_express_checkout': True,
            'support_manual_capture': 'full_only',
            'support_refund': 'partial',
            'support_tokenization': True,
        })


    def get_multisafepay_sdk(self):
        """ Get the MultiSafepay SDK instance.
        This method returns an instance of the MultiSafepay SDK based on the provider's API key and state.
        If the provider code is 'multisafepay', it creates and returns a new Sdk instance.
        If the provider code is not 'multisafepay', it calls the parent method to get the default SDK instance.
        Returns:
            Sdk: An instance of the MultiSafepay SDK.
        """
        return Sdk(
            api_key=self.multisafepay_api_key,
            is_production=(self.state == 'enabled')
        )

    def _map_multisafepay_to_odoo_code(self, multisafepay_code):
        """
        Map MultiSafepay payment method code to Odoo code.

        Args:
            multisafepay_code (str): Payment method code from MultiSafepay (e.g., 'MISTERCASH', 'mistercash')

        Returns:
            str: Corresponding Odoo code (e.g., 'bancontact') or lowercase MultiSafepay code
        """
        if not multisafepay_code:
            return ''

        # Convert to lowercase for comparison
        msp_code_lower = multisafepay_code.lower()

        # Search for the MultiSafepay code in the dictionary values
        for odoo_code, msp_code in const.PAYMENT_METHOD_CODES.items():
            if msp_code == msp_code_lower:
                return odoo_code

        # If no mapping found, return the original code in lowercase
        return msp_code_lower

    def _map_odoo_to_multisafepay_code(self, odoo_code):
        """
        Map Odoo payment method code to MultiSafepay code.

        Args:
            odoo_code (str): Odoo internal payment method code (e.g., 'bancontact')

        Returns:
            str: Corresponding MultiSafepay code (e.g., 'MISTERCASH') or uppercase Odoo code
        """
        if not odoo_code:
            return ''

        # Get MultiSafepay code from dictionary
        multisafepay_code = const.PAYMENT_METHOD_CODES.get(odoo_code.lower())

        if multisafepay_code:
            # Return MultiSafepay code in uppercase (as MultiSafepay expects)
            return multisafepay_code.upper()

        # If no mapping found, return the original code in uppercase
        return odoo_code.upper()
