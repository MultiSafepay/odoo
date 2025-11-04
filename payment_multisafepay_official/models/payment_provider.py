# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from decimal import Decimal
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
        """Override to detect state and API key changes and execute actions.
        
        :param vals: Dictionary of values to write
        :return: Result from parent method
        """
        old_states = {record.id: record.state for record in self}
        old_api_keys = {record.id: record.multisafepay_api_key for record in self}

        result = super().write(vals)

        multisafepay_records = self.filtered(lambda r: r.code == 'multisafepay')
        
        for record in multisafepay_records:
            old_state = old_states.get(record.id)
            old_api_key = old_api_keys.get(record.id)
            new_state = record.state
            new_api_key = record.multisafepay_api_key
            
            state_changed = 'state' in vals and old_state != new_state
            api_key_changed = 'multisafepay_api_key' in vals and old_api_key != new_api_key
            
            try:
                if state_changed or api_key_changed:
                    record._on_multisafepay_config_changed(
                        old_state, new_state, state_changed, new_api_key, api_key_changed
                    )
            except Exception as e:
                _logger.error(f"Error in MultiSafepay configuration change handling: {e}")

        return result

    def _on_multisafepay_config_changed(self, old_state, new_state, state_changed, new_api_key, api_key_changed):
        """Handle combined MultiSafepay configuration changes (state and API key).
        
        This method processes state and API key changes together to avoid duplicate operations
        like multiple pulls of payment methods when both fields change simultaneously.
        
        :param old_state: Previous state of the provider
        :param new_state: New state of the provider
        :param state_changed: Boolean indicating if state changed
        :param new_api_key: New API key value
        :param api_key_changed: Boolean indicating if API key changed
        """
        self.ensure_one()
        
        mode_label = "PRODUCTION" if new_state == 'enabled' else "TEST"
        
        if state_changed and api_key_changed:
            _logger.debug(f"MultiSafepay provider {self.name}: state changed {old_state} → {new_state} "
                        f"and API key changed in {mode_label} environment")
        elif state_changed:
            _logger.debug(f"MultiSafepay provider {self.name}: state changed {old_state} → {new_state}")
        elif api_key_changed:
            _logger.debug(f"MultiSafepay API key changed for {mode_label} environment")
        
        if new_state == 'disabled':
            self._on_provider_disabled()
            return
            
        if new_state in ['enabled', 'test']:
            try:
                cleanup_result = self._cleanup_multisafepay_payment_methods()
                _logger.debug(f"Configuration change cleanup: {cleanup_result['removed']} removed, "
                            f"{cleanup_result['removed']} removed, {cleanup_result['deactivated']} deactivated")
                
                if new_api_key:
                    self._fetch_merchant_payment_methods()
                    _logger.debug("MultiSafepay configuration updated successfully")
                else:
                    if api_key_changed:
                        _logger.error("API key is required")
                    elif state_changed:
                        _logger.warning(f"Environment changed to {mode_label} - Configure API key to sync payment methods")
                        
            except Exception as e:
                error_msg = str(e)
                _logger.error(f"Error in MultiSafepay configuration change handling: {error_msg}")

    def _on_provider_disabled(self):
        """Actions when provider is disabled."""

        self._cleanup_multisafepay_payment_methods()
        _logger.debug("MultiSafepay provider disabled")


    def _get_supported_currencies(self):
        """Override of `payment` to return the supported currencies for MultiSafepay.
        
        This method retrieves the supported currencies for the MultiSafepay payment provider.
        
        :return: A recordset of res.currency containing the supported currencies
        :rtype: recordset
        """
        supported_currencies = super()._get_supported_currencies()
        if self.code == 'multisafepay':
            supported_currencies = supported_currencies.filtered(
                lambda c: c.name in const.SUPPORTED_CURRENCIES
            )
        return supported_currencies


    def _cleanup_multisafepay_payment_methods(self):
        """Clean up payment methods associated with this MultiSafepay provider.

        This method handles payment methods in three ways:
        - Remove: Delete methods that only belong to this provider and have no transactions
        - Unlink: Remove provider association from methods shared with other providers
        - Deactivate: Disable methods that have transactions but keep them for history

        :return: Summary with counts of removed, and deactivated methods
        :rtype: dict
        """
        self.ensure_one()

        multisafepay_methods = self.env['payment.method'].with_context(active_test=False).search([
            ('provider_ids', 'in', [self.id])
        ])

        _logger.debug(f"Found {len(multisafepay_methods)} payment methods for this provider")

        if not multisafepay_methods:
            _logger.debug("No payment methods found for this MultiSafepay provider")
            return {'removed': 0, 'deactivated': 0}

        methods_to_remove = []
        methods_to_deactivate = []

        for method in multisafepay_methods:
            provider_ids = method.provider_ids.ids

            has_transactions = self.env['payment.transaction'].search_count([
                ('payment_method_id', '=', method.id)
            ]) > 0

            if has_transactions:
                methods_to_deactivate.append(method.id)
                _logger.debug(f"Deactivating payment method (has transactions): {method.name} (code: {method.code})")
            elif len(provider_ids) == 1 and self.id in provider_ids:
                methods_to_remove.append(method.id)
                _logger.debug(f"Removing payment method: {method.name} (code: {method.code})")

        removed_count = 0
        if methods_to_remove:
            try:
                self.env['payment.method'].browse(methods_to_remove).unlink()
                removed_count = len(methods_to_remove)
                _logger.debug(f"Removed {removed_count} payment methods")
            except Exception as e:
                _logger.error(f"Error removing methods: {e}")
                methods_to_deactivate.extend(methods_to_remove)
                removed_count = 0


        deactivated_count = 0
        if methods_to_deactivate:
            try:
                deactivate_methods = self.env['payment.method'].browse(methods_to_deactivate)
                deactivate_methods.write({'active': False})
                deactivated_count = len(methods_to_deactivate)
                _logger.debug(f"Deactivated {deactivated_count} payment methods (had transactions)")
            except Exception as e:
                _logger.error(f"Error deactivating methods: {e}")

        _logger.debug(f"Payment methods cleanup complete: {removed_count} removed, {deactivated_count} deactivated")

        return {
            'removed': removed_count,
            'deactivated': deactivated_count
        }


    def _fetch_merchant_payment_methods(self):
        """Pull the merchant payment methods from MultiSafepay and update or create them in Odoo.
        
        This method connects to the MultiSafepay API using the provided API key, retrieves the available payment methods,
        and updates the payment methods in Odoo accordingly. If the API key is not set, it returns a warning notification.
        If the API key is set, it fetches the payment methods, creates new ones or updates existing ones based on the
        unique code derived from the payment method ID, and associates them with the current provider.

        :return: A dictionary containing the action to display a notification with the result of the operation
        :rtype: dict
        """
        self.ensure_one()
        _logger.debug('Pulling merchant payment methods')

        if not self.multisafepay_api_key:
            _logger.warning('No API key found. Please configure your API key first.')
            return

        try:
            multisafepay_sdk = self.get_multisafepay_sdk()

            gateway_manager = multisafepay_sdk.get_payment_method_manager()
            custom_response = gateway_manager.get_payment_methods()
            gateways = custom_response.get_data()
            if not gateways or len(gateways) == 0:
                _logger.warning('No payment methods found')
                return

            count_new = 0
            count_updated = 0
            payment_method = self.env['payment.method']

            for gateway in gateways:

                multisafepay_code = gateway.id.lower()
                unique_code = self._map_multisafepay_to_odoo_code(multisafepay_code)
                _logger.debug("Mapping MultiSafepay '%s' to Odoo code '%s'", multisafepay_code, unique_code)

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
                    ('code', '=', unique_code)
                ]
                existing = payment_method.with_context(active_test=False).search(domain, limit=1)

                vals = {
                    'name': gateway.name or gateway.id,
                    'code': unique_code,
                    'active': True,
                    'support_refund': 'partial',
                }

                if gateway.allowed_amount:
                    if gateway.allowed_amount.min:
                        # Use Decimal for precise monetary calculations to avoid floating-point errors
                        min_decimal = Decimal(str(gateway.allowed_amount.min))
                        vals['minimum_amount'] = float(min_decimal / Decimal('100'))
                    if gateway.allowed_amount.max:
                        # Use Decimal for precise monetary calculations to avoid floating-point errors
                        max_decimal = Decimal(str(gateway.allowed_amount.max))
                        vals['maximum_amount'] = float(max_decimal / Decimal('100'))

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
                        'support_refund': 'partial',
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

                    brand_rec = payment_method.with_context(active_test=False).search(brand_domain, limit=1)

                    if not brand_rec:
                        main_brand_method = payment_method.create(brand_vals)
                        main_brand_method.write({'provider_ids': [(4, self.id, 0)]})

                    else:
                        brand_rec.write(brand_vals)
                        if self.id not in brand_rec.provider_ids.ids:
                            brand_rec.write({'provider_ids': [(4, self.id, 0)]})

            _logger.debug(f'Successfully synchronized {count_new} new methods, {count_updated} methods updated')

        except Exception as e:
            _logger.error("Error loading payment methods: %s", e)

    def pull_merchant_payment_methods(self):
        """Pull merchant payment methods from MultiSafepay API.
        
        This method first cleans up existing payment methods, then fetches new ones from the API.
        """
        cleanup_result = self._cleanup_multisafepay_payment_methods()
        _logger.debug(f"Payment methods cleanup: {cleanup_result['removed']} removed, {cleanup_result['deactivated']} deactivated")
        
        self._fetch_merchant_payment_methods()
        _logger.debug("MultiSafepay payment methods pull completed")

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
        """Get the MultiSafepay SDK instance.
        
        This method returns an instance of the MultiSafepay SDK based on the provider's API key and state.
        If the provider code is 'multisafepay', it creates and returns a new Sdk instance.
        If the provider code is not 'multisafepay', it calls the parent method to get the default SDK instance.
        
        :return: An instance of the MultiSafepay SDK
        :rtype: Sdk
        """
        return Sdk(
            api_key=self.multisafepay_api_key,
            is_production=(self.state == 'enabled')
        )

    def _map_multisafepay_to_odoo_code(self, multisafepay_code):
        """Map MultiSafepay payment method code to Odoo code with multisafepay_ prefix.

        :param multisafepay_code: Payment method code from MultiSafepay (e.g., 'MISTERCASH', 'mistercash')
        :return: Odoo code with multisafepay_ prefix (e.g., 'multisafepay_mistercash')
        :rtype: str
        """
        if not multisafepay_code:
            return ''

        msp_code_lower = multisafepay_code.lower()
        return f"{const.PAYMENT_METHOD_PREFIX}{msp_code_lower}"

    def _map_odoo_to_multisafepay_code(self, odoo_code):
        """Map Odoo payment method code to MultiSafepay code, handling multisafepay_ prefix.

        :param odoo_code: Odoo internal payment method code (e.g., 'multisafepay_mistercash')
        :return: MultiSafepay code in uppercase (e.g., 'MISTERCASH')
        :rtype: str
        """
        if not odoo_code:
            return ''

        clean_code = odoo_code
        if odoo_code.startswith(const.PAYMENT_METHOD_PREFIX):
            clean_code = odoo_code[len(const.PAYMENT_METHOD_PREFIX):]

        return clean_code.upper()
