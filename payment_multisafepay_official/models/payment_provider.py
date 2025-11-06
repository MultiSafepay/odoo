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
        """Override to handle MultiSafepay provider configuration changes.

        Detects changes to provider state and API key, then triggers appropriate
        sync or cleanup operations to maintain payment method consistency.

        :param dict vals: Dictionary of field values to write
        :return: Result from parent write() method
        :rtype: bool
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
        """Handle MultiSafepay configuration changes (state and/or API key).

        This method processes state and API key changes to:
        - Clean up payment methods when provider is disabled
        - Sync payment methods when provider is enabled/test with valid API key
        - Avoid duplicate operations when both state and API key change simultaneously

        :param str old_state: Previous provider state
        :param str new_state: New provider state ('enabled', 'test', 'disabled')
        :param bool state_changed: Whether the state field changed
        :param str new_api_key: New API key value
        :param bool api_key_changed: Whether the API key field changed
        :return: None
        :rtype: None
        """

        self.ensure_one()

        if new_state == 'disabled':
            self._on_disable_deactivate_all_methods()
            return

        mode_label = "PRODUCTION" if new_state == 'enabled' else "TEST"

        if state_changed and api_key_changed:
            _logger.debug(f"MultiSafepay provider {self.name}: state changed {old_state} → {new_state} "
                        f"and API key changed in {mode_label} environment")
        elif state_changed:
            _logger.debug(f"MultiSafepay provider {self.name}: state changed {old_state} → {new_state}")
        elif api_key_changed:
            _logger.debug(f"MultiSafepay API key changed for {mode_label} environment")

        if new_state in ['enabled', 'test']:
            try:
                if new_api_key:
                    self._fetch_merchant_payment_methods()
                else:
                    _logger.debug(f"No API key found. Please configure your API key to fetch payment methods in {mode_label} environment.")
            except Exception as e:
                _logger.error(f"Error syncing: {e}")

    def _get_supported_currencies(self):
        """Override of `payment` to return supported currencies for MultiSafepay.

        Filters the parent method's currency list to only include currencies
        supported by the MultiSafepay payment provider (defined in const.SUPPORTED_CURRENCIES).

        :return: res.currency records containing only MultiSafepay-supported currencies
        :rtype: recordset
        """

        supported_currencies = super()._get_supported_currencies()
        if self.code == 'multisafepay':
            supported_currencies = supported_currencies.filtered(
                lambda c: c.name in const.SUPPORTED_CURRENCIES
            )
        return supported_currencies

    def _on_sync_deactivate_unavailable_payment_method_codes(self, synced_payment_method_codes):
        """Deactivate payment methods no longer available in API.

        When a payment method is no longer returned by the MultiSafepay API,
        it is deactivated to preserve transaction history.

        :param set synced_payment_method_codes: Set of payment method codes currently returned by API
        :return: None
        :rtype: None
        """

        self.ensure_one()

        all_provider_methods = self.env['payment.method'].with_context(active_test=False).search([
            ('provider_ids', 'in', [self.id]),
            ('code', '=like', f'{const.PAYMENT_METHOD_PREFIX}%')
        ])

        unavailable_payment_method_codes = all_provider_methods.filtered(lambda m: m.code not in synced_payment_method_codes)

        if not unavailable_payment_method_codes:
            return

        unavailable_payment_method_codes.write({'active': False})

        _logger.debug(f"Deactivated {len(unavailable_payment_method_codes)} unavailable payment methods:")
        for method in unavailable_payment_method_codes:
            _logger.debug(f"  - {method.name} (code: {method.code})")

    def _on_disable_deactivate_all_methods(self):
        """Deactivate all payment methods when provider is disabled.

        When the MultiSafepay provider is disabled, all associated payment methods
        are deactivated to prevent their use while preserving transaction history.

        :return: None
        :rtype: dict
        """

        self.ensure_one()

        _logger.debug("MultiSafepay provider disabled - deactivating all associated payment methods")

        multisafepay_methods = self.env['payment.method'].with_context(active_test=False).search([
            ('provider_ids', 'in', [self.id])
        ])

        if not multisafepay_methods:
            _logger.debug("No payment methods found for this MultiSafepay provider")
            return

        try:
            multisafepay_methods.write({'active': False})
            deactivated_count = len(multisafepay_methods)

            _logger.debug(f"Deactivated {deactivated_count} payment methods:")
            for method in multisafepay_methods:
                _logger.debug(f"  - {method.name} (code: {method.code})")

            return

        except Exception as e:
            _logger.error(f"Error deactivating methods: {e}")

    def _fetch_merchant_payment_methods(self):
        """Sync merchant payment methods from MultiSafepay API.

        This method:
        - Fetches available payment methods (gateways and brands) from the API
        - Creates new methods or updates existing ones preserving user configurations
        - Associates methods with this provider
        - Removes unavailable methods that are no longer in the API

        .. note:: User configurations like 'active' status are preserved on updates.

        :return: None (Logs sync results: count of new and updated methods)
        :rtype: None
        """

        self.ensure_one()
        _logger.debug('Syncing merchant payment methods')

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

            # Track codes from API to identify unavailable methods later
            synced_payment_method_codes = set()

            count_new = 0
            count_updated = 0
            payment_method = self.env['payment.method']

            for gateway in gateways:
                multisafepay_code = gateway.id.lower()
                unique_code = self._map_multisafepay_to_odoo_code(multisafepay_code)
                _logger.debug("Mapping MultiSafepay '%s' to Odoo code '%s'", multisafepay_code, unique_code)
                synced_payment_method_codes.add(unique_code)

                # Prepare values that can be safely updated
                country_ids = self._get_country_ids(gateway.allowed_countries)
                currency_ids = self._get_currency_ids(gateway.allowed_currencies)

                existing = payment_method.with_context(active_test=False).search([
                    ('code', '=', unique_code)
                ], limit=1)

                # Values that are ALWAYS updated from API
                api_vals = {
                    'name': gateway.name or gateway.id,
                    'code': unique_code,
                    'support_refund': 'partial',
                }

                # New methods are disabled by default, except if is a branded method
                creation_only_vals = {
                    'active': False,
                }

                # Optional values from API (update if present)
                if gateway.allowed_amount:
                    if gateway.allowed_amount.min:
                        min_decimal = Decimal(str(gateway.allowed_amount.min))
                        api_vals['minimum_amount'] = float(min_decimal / Decimal('100'))
                    if gateway.allowed_amount.max:
                        max_decimal = Decimal(str(gateway.allowed_amount.max))
                        api_vals['maximum_amount'] = float(max_decimal / Decimal('100'))

                if country_ids:
                    api_vals['supported_country_ids'] = [(6, 0, country_ids)]

                if currency_ids:
                    api_vals['supported_currency_ids'] = [(6, 0, currency_ids)]

                if gateway.icon_urls and gateway.icon_urls.large:
                    api_vals['image'] = _get_image_base64(url=gateway.icon_urls.large)

                if not existing:
                    # Use all values: api_vals and creation_only_vals
                    main_method = payment_method.create({**api_vals, **creation_only_vals})
                    main_method.write({'provider_ids': [(4, self.id, 0)]})
                    count_new += 1
                else:
                    existing.write(api_vals)
                    if self.id not in existing.provider_ids.ids:
                        existing.write({'provider_ids': [(4, self.id, 0)]})
                    main_method = existing
                    count_updated += 1

                for brand in gateway.brands:
                    if not brand.id:
                        continue

                    multisafepay_brand_code = brand.id.lower()
                    brand_code = self._map_multisafepay_to_odoo_code(multisafepay_brand_code)
                    synced_payment_method_codes.add(brand_code)

                    existing_brand = payment_method.with_context(active_test=False).search([
                        ('code', '=', brand_code)
                    ], limit=1)

                    # Values that are ALWAYS updated from API
                    brand_api_vals = {
                        'name': brand.name or brand.id,
                        'code': brand_code,
                        'primary_payment_method_id': main_method.id,
                        'support_refund': 'partial',
                    }

                    # Brands are inactive by default when created
                    brand_creation_vals = {
                        'active': False,
                    }

                    if brand.icon_urls and brand.icon_urls.large:
                        brand_api_vals['image'] = _get_image_base64(brand.icon_urls.large)

                    brand_currency_ids = self._get_currency_ids(gateway.allowed_currencies)
                    if brand_currency_ids:
                        brand_api_vals['supported_currency_ids'] = [(6, 0, brand_currency_ids)]

                    brand_country_ids = self._get_country_ids(brand.allowed_countries)
                    if brand_country_ids:
                        brand_api_vals['supported_country_ids'] = [(6, 0, brand_country_ids)]

                    if not existing_brand:
                        brand_method = payment_method.create({**brand_api_vals, **brand_creation_vals})
                        brand_method.write({'provider_ids': [(4, self.id, 0)]})
                        count_new += 1
                        _logger.debug(f"Created new brand: {brand_method.name} (code: {brand_method.code})")

                    else:
                        existing_brand.write(brand_api_vals)

                        if self.id not in existing_brand.provider_ids.ids:
                            existing_brand.write({'provider_ids': [(4, self.id, 0)]})
                            _logger.info(f"Associated brand with provider: {existing_brand.name}")
                        else:
                            _logger.debug(f"Updated brand (already associated): {existing_brand.name}")

                        count_updated += 1

            self._on_sync_deactivate_unavailable_payment_method_codes(synced_payment_method_codes)

            _logger.debug(f'Successfully synchronized {count_new} new methods, {count_updated} methods updated')

        except Exception as e:
            _logger.error("Error loading payment methods: %s", e)

    def _get_country_ids(self, country_codes):
        """Convert ISO country codes to Odoo country record IDs.

        :param list country_codes: List of ISO 3166-1 alpha-2 country codes (e.g., ['US', 'GB'])
        :return: List of res.country record IDs matching the provided codes
        :rtype: list
        """

        if not country_codes:
            return []

        all_countries = self.env['res.country'].search([])
        country_map = {c.code: c.id for c in all_countries}
        return [country_map[code] for code in country_codes if code in country_map]

    def _get_currency_ids(self, currency_codes):
        """Convert ISO currency codes to Odoo currency record IDs.

        Searches for currencies regardless of their active status to support
        temporarily inactive currencies that may be reactivated.

        :param list currency_codes: List of ISO 4217 currency codes (e.g., ['EUR', 'USD'])
        :return: List of res.currency record IDs matching the provided codes
        :rtype: list
        """

        if not currency_codes:
            return []

        all_currencies = self.env['res.currency'].with_context(active_test=False).search([])
        currency_map = {c.name: c.id for c in all_currencies}
        return [currency_map[code] for code in currency_codes if code in currency_map]

    def pull_merchant_payment_methods(self):
        """Manual sync trigger for merchant payment methods.

        This is a button action that triggers the full sync process from the API.
        It calls _fetch_merchant_payment_methods() to perform the actual sync.

        :return: None
        :rtype: None
        """

        self._fetch_merchant_payment_methods()
        _logger.debug("MultiSafepay payment methods sync completed")

    def _compute_feature_support_fields(self):
        """Override to define MultiSafepay-specific feature support.

        Configures which payment features are supported by MultiSafepay:
        - Express checkout: Enabled
        - Manual capture: Full amount only
        - Refunds: Partial refunds supported
        - Tokenization: Enabled for recurring payments

        :return: None
        :rtype: None
        """

        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == 'multisafepay').update({
            'support_express_checkout': True,
            'support_manual_capture': 'full_only',
            'support_refund': 'partial',
            'support_tokenization': True,
        })

    def get_multisafepay_sdk(self):
        """Get MultiSafepay SDK instance for API operations.

        Creates an SDK client configured with the provider's API key and environment
        (production or test mode based on provider state).

        :return: Configured MultiSafepay SDK instance for making API requests
        :rtype: Sdk
        """

        return Sdk(
            api_key=self.multisafepay_api_key,
            is_production=(self.state == 'enabled')
        )

    def _map_multisafepay_to_odoo_code(self, multisafepay_code):
        """Map MultiSafepay payment method code to Odoo code with multisafepay_ prefix.

        :param str multisafepay_code: Payment method code from MultiSafepay (e.g., 'MISTERCASH', 'mistercash')
        :return: Odoo code with multisafepay_ prefix (e.g., 'multisafepay_mistercash')
        :rtype: str
        """

        if not multisafepay_code:
            return ''

        msp_code_lower = multisafepay_code.lower()
        return f"{const.PAYMENT_METHOD_PREFIX}{msp_code_lower}"

    def _map_odoo_to_multisafepay_code(self, odoo_code):
        """Map Odoo payment method code to MultiSafepay code, handling multisafepay_ prefix.

        :param str odoo_code: Odoo internal payment method code (e.g., 'multisafepay_mistercash')
        :return: MultiSafepay code in uppercase (e.g., 'MISTERCASH')
        :rtype: str
        """

        if not odoo_code:
            return ''

        clean_code = odoo_code
        if odoo_code.startswith(const.PAYMENT_METHOD_PREFIX):
            clean_code = odoo_code[len(const.PAYMENT_METHOD_PREFIX):]

        return clean_code.upper()
