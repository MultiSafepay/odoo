# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

"""
MultiSafepay Payment Controller
Handles redirect flow for MultiSafepay payments
"""
import logging
import pprint
import json

from werkzeug.exceptions import Forbidden
from typing import cast
from urllib.parse import quote_plus

from odoo import http, _
from odoo.http import request
from odoo.exceptions import ValidationError, UserError
from odoo.addons.payment.controllers.post_processing import PaymentPostProcessing

from multisafepay.value_object.weight import Weight
from multisafepay.api.shared.cart.cart_item import CartItem
from multisafepay.api.paths.orders.request.components.checkout_options import CheckoutOptions
from multisafepay.api.paths.orders.request.components.payment_options import PaymentOptions
from multisafepay.api.paths.orders.request.components.plugin import Plugin
from multisafepay.api.paths.orders.request.components.second_chance import SecondChance
from multisafepay.api.shared.checkout.tax_rule import TaxRule
from multisafepay.api.shared.checkout.tax_rate import TaxRate
from multisafepay.api.paths.orders.request.order_request import OrderRequest
from multisafepay.api.shared.cart.shopping_cart import ShoppingCart
from multisafepay.api.shared.customer import Customer
from multisafepay.api.shared.delivery import Delivery
from multisafepay.sdk import Sdk
from multisafepay.value_object.amount import Amount
from multisafepay.value_object.country import Country
from multisafepay.value_object.currency import Currency
from multisafepay.api.shared.description import Description
from multisafepay.value_object.email_address import EmailAddress
from multisafepay.value_object.ip_address import IpAddress
from multisafepay.value_object.phone_number import PhoneNumber
from multisafepay.api.paths.orders.response.order_response import Order
from multisafepay.util.address_parser import AddressParser
from multisafepay.util.webhook import Webhook

from ..const import PAYMENT_METHOD_PENDING


_logger = logging.getLogger(__name__)


class MultiSafepayController(http.Controller):
    """Controller to handle MultiSafepay payment flow"""

    _redirect_url = '/payment/multisafepay/redirect'
    _webhook_url = '/payment/multisafepay/webhook'
    _return_url = '/payment/multisafepay/return'
    _cancel_url = '/payment/multisafepay/cancel'

    @http.route('/payment/multisafepay/redirect', type='http', auth='public', methods=['POST'], csrf=False)
    def multisafepay_redirect(self, **post):
        """Handle redirect to MultiSafepay payment page"""
        _logger.info("MultiSafepay redirect endpoint")
        _logger.debug("MultiSafepay redirect endpoint request POST data: %s", str(post))

        try:
            reference = post.get('reference')
            if not reference:
                return self._redirect_to_payment_with_error(
                    "missing_reference",
                    _("Payment reference is missing. Please try again.")
                )

            payment_transaction = request.env['payment.transaction'].sudo().search([
                ('reference', '=', reference),
                ('provider_code', '=', 'multisafepay')
            ], limit=1)

            if not payment_transaction:
                return self._redirect_to_payment_with_error(
                    "transaction_not_found",
                    _("Transaction not found. Please refresh and try again.")
                )

            try:
                base_url = self._get_correct_base_url()
                order = self._get_order(base_url, payment_transaction)

                if not order or not order.payment_url:
                    return self._redirect_to_payment_with_error(
                        "multiSafepay_api_error",
                        _("MultiSafepay API error: Transaction not found. Please refresh and try again.")
                    )

                _logger.info("Payment url was generated successfully.")
                _logger.debug("Payment url was generated successfully: %s", order.payment_url)

                return request.redirect(order.payment_url, local=False)

            except (ValidationError, UserError) as ve:
                _logger.error("Validation/User error: %s", str(ve))
                return self._redirect_to_payment_with_error(
                    "validation_error",
                    str(ve)
                )

            except Exception as api_error:
                _logger.error("Unexpected error: %s", str(api_error))
                return self._redirect_to_payment_with_error(
                    "Unexpected error",
                    _("An unexpected error occurred. Please try again.")
                )

        except Exception as e:
            _logger.error("Unexpected error: %s", str(e))
            return self._redirect_to_payment_with_error(
                "unexpected_error",
                _("An unexpected error occurred. Please try again.")
            )

    def _redirect_to_payment_with_error(self, error_code, message):
        """Redirect to payment form with error message"""
        return request.redirect(f"/shop/payment?error={error_code}&message={quote_plus(message)}")


    @http.route('/payment/multisafepay/webhook', type='http', auth='public', csrf=False, methods=['POST', 'GET'])
    def multisafepay_webhook(self, **kwargs):
        """Handle MultiSafepay webhook notifications"""

        _logger.info("MultiSafepay webhook received via %s", request.httprequest.method)
        _logger.debug("MultiSafepay webhook data: %s", str(kwargs))

        try:
            if request.httprequest.method == 'POST':
                return self._handle_post_webhook(**kwargs)
            else:
                return self._handle_get_webhook(**kwargs)

        except Exception as e:
            _logger.error("Unexpected error in webhook processing: %s", str(e))
            return request.make_response('Internal Server Error', status=500)



    @http.route('/payment/multisafepay/return', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def multisafepay_return(self, **kwargs):
        """Handle return from MultiSafepay payment page"""
        _logger.info("MultiSafepay return received")
        _logger.debug("Return data: %s", str(kwargs))

        transactionid = kwargs.get('transactionid')

        payment_transaction = request.env['payment.transaction'].sudo().search([
            ('reference', '=', transactionid),
            ('provider_code', '=', 'multisafepay')
        ], limit=1)

        if payment_transaction.payment_method_code in PAYMENT_METHOD_PENDING:
            _logger.info("Payment method '%s' requires manual confirmation. Setting as pending.", payment_transaction.payment_method_code)

            # Get real state from MultiSafepay
            provider = payment_transaction.provider_id
            multisafepay_sdk = provider.get_multisafepay_sdk()
            order_manager = multisafepay_sdk.get_order_manager()
            order_response = order_manager.get(transactionid)
            order = order_response.get_data()


            notification_data = {
                'status':'pending',
                'reference': transactionid,
            }

            # Process notification to update transaction state
            payment_transaction._process_notification_data(notification_data)

            # Pass additional information in the URL
            params = {
                'payment_method': payment_transaction.payment_method_code,
                'payment_status': order.status if order else 'pending',
                'transaction_id': transactionid,
                'multisafepay_order_id': order.order_id if order and hasattr(order, 'order_id') else '',
                'amount': payment_transaction.amount,
                'currency': payment_transaction.currency_id.name
            }

            # Build URL with parameters
            url_params = '&'.join([f"{k}={quote_plus(str(v))}" for k, v in params.items() if v])
            return request.redirect(f'/shop/confirmation?{url_params}')

        return request.redirect('/payment/status')


    @http.route('/payment/multisafepay/cancel', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def multisafepay_cancel(self, **kwargs):
        """Handle cancellation from MultiSafepay payment page"""
        _logger.info("MultiSafepay payment cancelled")
        _logger.debug("Cancel data: %s", str(kwargs))

        transactionid = kwargs.get('transactionid')

        payment_transaction = request.env['payment.transaction'].sudo().search([
            ('reference', '=', transactionid),
            ('provider_code', '=', 'multisafepay')
        ], limit=1)

        notification_data = {
            'status': 'cancelled',
            'reference': transactionid,
        }

        payment_transaction._process_notification_data(notification_data)

        _logger.info("MultiSafepay payment cancelled: %s", transactionid)

        return request.redirect('/payment/status?cancelled=1')

    def _handle_get_webhook(self, **kwargs):
        """Handle GET webhook from MultiSafepay"""

        transactionid = kwargs.get('transactionid')
        if not transactionid:
            _logger.error("No transaction ID provided in webhook")
            return request.make_response('Transaction ID required', status=400)

        payment_transaction = request.env['payment.transaction'].sudo().search([
            ('reference', '=', transactionid),
            ('provider_code', '=', 'multisafepay')
        ], limit=1)

        if not payment_transaction:
            _logger.error("Transaction not found for webhook validation: %s", transactionid)
            return request.make_response('Transaction not found', status=404)

        provider = payment_transaction.provider_id
        multisafepay_sdk = provider.get_multisafepay_sdk()

        order_manager = multisafepay_sdk.get_order_manager()
        order_response = order_manager.get(transactionid)
        order = order_response.get_data()
        if not order:
            _logger.error("No order data found for transaction ID: %s", transactionid)
            return request.make_response('No order data found', status=404)

        if not order.status:
            _logger.error("No status found in order data for transaction ID: %s", transactionid)
            return request.make_response('No status found', status=400)

        duplicated = self._duplicated_status(payment_transaction, order.status)
        if duplicated:
            _logger.debug("Duplicate webhook received for transaction %s with status %s, ignoring.", transactionid, order.status)
            return request.make_response('OK', status=200)

        notification_data = {
            'status': order.status,
            'reference': order.transaction_id if hasattr(order, 'transaction_id') else None,
        }

        payment_transaction._process_notification_data(notification_data)

        _logger.info("Webhook processing completed for transaction %s with status %s", transactionid, order.status)
        return request.make_response('OK', status=200)

    def _handle_post_webhook(self, **kwargs):
        """Handle POST webhook from MultiSafepay"""

        request_body_raw = request.httprequest.get_data(as_text=True)
        try:
            _logger.debug("POST webhook data: %s", request_body_raw)

            order = None
            if request_body_raw:

                try:
                    order_data = json.loads(request_body_raw)
                    order = Order.from_dict(order_data)
                    _logger.debug("Parsed POST webhook data: %s", str(order_data))

                except json.JSONDecodeError:
                    _logger.error("Failed to parse POST webhook body as JSON, using form data")
                    return request.make_response('Invalid JSON format in webhook body', status=403)


            if not order or not order.order_id:
                _logger.error("No transaction ID provided in webhook")
                return request.make_response('Transaction ID required', status=400)

            transactionid = order.order_id
            payment_transaction = request.env['payment.transaction'].sudo().search([
                ('reference', '=', transactionid),
                ('provider_code', '=', 'multisafepay')
            ], limit=1)

            if not payment_transaction:
                _logger.error("Transaction not found for webhook validation: %s", transactionid)
                return request.make_response('Transaction not found', status=404)

            auth_header = request.httprequest.headers.get('Auth', '')

            provider = payment_transaction.provider_id
            api_key = provider.multisafepay_api_key

            try:
                Webhook.validate(request=request_body_raw, auth=auth_header, api_key=api_key, validation_time_in_seconds=600)
                _logger.info("Webhook validation successful for transaction: %s", transactionid)

                if not order.status:
                    _logger.error("No status found in order data for transaction ID: %s", transactionid)
                    return request.make_response('No status found', status=400)

                duplicated = self._duplicated_status(payment_transaction, order.status)
                if duplicated:
                    _logger.info("Duplicate webhook received for transaction %s with status %s, ignoring.", transactionid, order.status)
                    return request.make_response('OK', status=200)

                notification_data = {
                    'status': order.status,
                    'reference': order.transaction_id if hasattr(order, 'transaction_id') else None,
                }

                payment_transaction._process_notification_data(notification_data)

                _logger.info("Webhook processing completed for transaction %s with status %s", transactionid, order.status)
                return request.make_response('OK', status=200)


            except Exception as validation_error:
                _logger.error("Webhook validation failed for transaction %s: %s", transactionid, str(validation_error))
                return request.make_response('Webhook validation failed', status=403)


        except Forbidden as e:
            _logger.error("Forbidden access to MultiSafepay webhook: %s", str(e))
            return request.make_response('Forbidden', status=403)


    def _duplicated_status(self, payment_transaction, new_status, message=''):
        """Check if the transaction already has the specified status to detect duplicates."""
        _logger.debug("Transaction %s status changed to %s: %s", payment_transaction.id, new_status, message)
        return payment_transaction.state == payment_transaction._get_multisafepay_status_to_odoo_state(new_status)



    def _get_order(self, url, payment_transaction) -> Order:
        """ Override of payment to create the order request for multisafepay transactions.

        :param dict processing_values: The processing values to be used for the transaction
        :return: The order request created for the multisafepay transaction
        :rtype: dict
        """

        # Get base URL from Odoo configuration
        if not getattr(payment_transaction, 'reference', None):
            raise ValidationError(_("Transaction reference is missing."))

        amount = getattr(payment_transaction, 'amount', 0)
        if amount <= 0:
            raise ValidationError(_("Transaction amount is missing or invalid."))

        currency_id = getattr(payment_transaction, 'currency_id', None)
        if not currency_id or not getattr(currency_id, 'name', None):
            raise ValidationError(_("Transaction currency is missing or invalid."))

        sale_orders = getattr(payment_transaction, 'sale_order_ids', None)
        partner_invoice = None
        sale_order = None

        # If sale_order_ids is provided, use the first one to get the invoice partner
        if sale_orders:
            sale_order = sale_orders[0] # Assuming one sale order per transaction for simplicity
            partner_invoice = getattr(sale_order, 'partner_invoice_id', None)
        else:
            partner_invoice = getattr(payment_transaction, 'partner_id', None)


        # Create a ShoppingCart with the necessary details
        order_id = payment_transaction.reference

        decimal_places = getattr(currency_id, 'decimal_places', 2)  # Default to 2 if not found
        multiplier = 10 ** decimal_places
        multiplied_amount = amount * multiplier
        normalized_amount = int(multiplied_amount)
        amount = Amount(amount=normalized_amount).amount
        currency = Currency(currency=currency_id.name)

        description = Description(description='Order #' + order_id)
        language = getattr(payment_transaction, 'partner_lang', 'en_US') or 'en_US'

        if not partner_invoice:
            raise ValidationError(_("No customer info partner associated."))

        partner_invoice_country = Country(code=getattr(partner_invoice, 'country_code', '')).code
        partner_invoice_email = EmailAddress(email_address=getattr(partner_invoice, 'email', '')).email_address
        partner_invoice_phone_number = PhoneNumber(phone_number=getattr(partner_invoice, 'phone', '')).phone_number
        partner_invoice_name = getattr(partner_invoice, 'name', '').split(' ') or []
        partner_invoice_first_name = partner_invoice_name[0] if partner_invoice_name else ''
        partner_invoice_last_name = " ".join(partner_invoice_name[1:]) if len(partner_invoice_name) > 1 else ''

        # Get the IP address from the request environment
        remote_addr = request.httprequest.environ.get('REMOTE_ADDR', '')
        partner_invoice_ip_address = IpAddress(ip_address=remote_addr).ip_address if remote_addr else ''

        # If the HTTP_X_FORWARDED_FOR header is present, use it as the forwarded IP address
        http_x_forwarded_for = request.httprequest.environ.get('HTTP_X_FORWARDED_FOR', '') or partner_invoice_ip_address
        partner_invoice_forwarded_ip = IpAddress(ip_address=http_x_forwarded_for).ip_address

        partner_invoice_street = getattr(partner_invoice, 'street', '') or ''
        partner_invoice_street2 = getattr(partner_invoice, 'street2', '') or ''

        address_parser = AddressParser()
        partner_invoice_address = address_parser.parse(partner_invoice_street, partner_invoice_street2)

        partner_invoice_referrer = request.httprequest.environ.get('HTTP_REFERER', '') or ''
        partner_invoice_ref = getattr(partner_invoice, 'ref', '') or ''
        partner_invoice_address1 = partner_invoice_address[0] if partner_invoice_address else ''
        partner_invoice_house_number = partner_invoice_address[1] if partner_invoice_address and len(partner_invoice_address) > 1 else ''
        partner_invoice_zip = getattr(partner_invoice, 'zip', '') or ''
        partner_invoice_city = getattr(partner_invoice, 'city', '') or ''
        partner_invoice_state = partner_invoice.state_id.name if partner_invoice.state_id else ''

        # Create a Customer object with the necessary details
        customer = cast(Customer, (Customer(**{})
            .add_locale(language)
            .add_ip_address(partner_invoice_ip_address)
            .add_forwarded_ip(partner_invoice_forwarded_ip)
            .add_referrer(partner_invoice_referrer)
            .add_user_agent(request.httprequest.user_agent.string)
            .add_reference(partner_invoice_ref)
            .add_first_name(partner_invoice_first_name)
            .add_last_name(partner_invoice_last_name)
            .add_phone(partner_invoice_phone_number)
            .add_email(partner_invoice_email)
            .add_address1(partner_invoice_address1)
            .add_address2('')
            .add_house_number(partner_invoice_house_number)
            .add_zip_code(partner_invoice_zip)
            .add_city(partner_invoice_city)
            .add_state(partner_invoice_state)
            .add_country(partner_invoice_country)))

        company = None
        use_delivery_as_billing = False
        partner_shipping = None
        delivery = Delivery(**{})
        # Create a Delivery object with the same details as the customer
        if sale_order:
            partner_shipping = sale_order.partner_shipping_id

            if partner_invoice.id == partner_shipping.id:
                use_delivery_as_billing = True

        if partner_shipping:
            partner_shipping_name = getattr(partner_shipping, 'name', '').split(' ') if getattr(partner_shipping, 'name', None) else []
            partner_shipping_first_name = partner_shipping_name[0] if partner_shipping_name else ''
            partner_shipping_last_name = " ".join(partner_shipping_name[1:]) if len(partner_shipping_name) > 1 else ''
            partner_shipping_phone = PhoneNumber(phone_number=getattr(partner_shipping, 'phone', '')).phone_number
            partner_shipping_email = EmailAddress(email_address=getattr(partner_shipping, 'email', '')).email_address
            partner_shipping_state = getattr(partner_shipping.state_id, 'name', '') or ''
            partner_shipping_country = Country(code=getattr(partner_shipping, 'country_code', '')).code
            partner_shipping_street = getattr(partner_shipping, 'street', '') or ''
            partner_shipping_street2 = getattr(partner_shipping, 'street2', '') or ''
            partner_shipping_address = address_parser.parse(partner_shipping_street, partner_shipping_street2)
            partner_shipping_address1 = partner_shipping_address[0] if partner_shipping_address else ''
            partner_shipping_house_number =  partner_shipping_address[1] if partner_shipping_address and len(partner_shipping_address1) > 1 else ''
            partner_shipping_zip_code = getattr(partner_shipping, 'zip', '') or ''
            partner_shipping_city = getattr(partner_shipping, 'city', '') or ''

            if sale_orders and not use_delivery_as_billing:
                delivery = (Delivery(**{})
                    .add_first_name(partner_shipping_first_name)
                    .add_last_name(partner_shipping_last_name)
                    .add_phone(partner_shipping_phone)
                    .add_email(partner_shipping_email)
                    .add_address1(partner_shipping_address1)
                    .add_address2('')
                    .add_house_number(partner_shipping_house_number)
                    .add_zip_code(partner_shipping_zip_code)
                    .add_city(partner_shipping_city)
                    .add_state(partner_shipping_state)
                    .add_country(partner_shipping_country))

        if not sale_orders or sale_orders and use_delivery_as_billing:
            # If no sale order, use the invoice partner details for delivery
            delivery = (Delivery(**{}).add_first_name(partner_invoice_first_name)
                .add_last_name(partner_invoice_last_name)
                .add_phone(partner_invoice_phone_number)
                .add_email(partner_invoice_email)
                .add_address1(partner_invoice_address1)
                .add_address2('')
                .add_house_number(partner_invoice_house_number)
                .add_zip_code(partner_invoice_zip)
                .add_city(partner_invoice_city)
                .add_state(partner_invoice_state)
                .add_country(partner_invoice_country))

        # Create a Plugin object with the necessary details
        plugin = (Plugin(**{})
            .add_plugin_version('1.0.0')
            .add_shop('Odoo')
            .add_shop_version('18.0')
            .add_shop_root_url(url))

        # Create payment options for the order
        payment_options = (PaymentOptions(**{})
            .add_notification_method('POST')
            .add_close_window(True)
            .add_notification_url(f'{url}/payment/multisafepay/webhook')
            .add_redirect_url(f'{url}/payment/multisafepay/return')
            .add_cancel_url(f'{url}/payment/multisafepay/cancel')
        )

        # Prevent Second Chance, not supported at this moment
        second_chance = SecondChance(send_email=False)

        # Create a list of CartItem objects for the shopping cart
        order_lines = getattr(sale_order, 'order_line', [])
        cart_items = []

        for line in order_lines:
            product = getattr(line, 'product_id', None)

            order_line_info = {
                "line_id": getattr(line, "id", None),
                "name": getattr(line, "name", ""),
                "quantity": getattr(line, "product_qty", 0),
                "unit_price": getattr(line, "price_unit", 0.0),
                "tax": getattr(line.tax_id, "amount", None) if getattr(line, "tax_id", None) else None,
                "product_id": getattr(product, "id", None),
                "product_code": getattr(product, "code", ""),
                "product_name": getattr(product, "name", ""),
                "description": getattr(product, "description_sale", ""),
                "weight": getattr(product, "weight", 0.0),
                "category": getattr(product.categ_id, "name", "") if getattr(product, "categ_id", None) else "",
                "attributes": [getattr(attr, "name", "") for attr in
                               getattr(line, "product_no_variant_attribute_value_ids", [])],
            }

            _logger.debug("Order line details: %s", str(order_line_info))

            # Create a ShoppingCart object with the items
            tax_table_selector = line.tax_id.amount if line.tax_id else None

            merchant_item_id = line.product_id.code if line.product_id.code else str(line.product_id.id)
            for variant in line.product_no_variant_attribute_value_ids:
                merchant_item_id += f"-{variant.name}"

            cart_item = (CartItem(**{})
                .add_name(getattr(line, 'name', '') or '')
                .add_description(getattr(product, 'description_sale', '') or '')
                .add_unit_price(getattr(line, 'price_unit', 0.0))
                .add_quantity(getattr(line, 'product_qty', 0))
                .add_merchant_item_id(merchant_item_id)
                .add_weight(Weight(value=getattr(product, 'weight', 0.0) or 0.0, unit='kg'))
            )
            if(tax_table_selector is not None):
                cart_item.add_tax_rate_percentage(tax_table_selector)
            else:
                cart_item.add_tax_rate_percentage(0)

            cart_items.append(cart_item)

        shopping_cart = ShoppingCart(items=cart_items)
        checkout_options= CheckoutOptions.generate_from_shopping_cart(shopping_cart)

        tax_rule = TaxRule(
            name="0",
            rules=[TaxRate(rate=0, country="")],
            standalone=None
        )

        # Iterate over the tax rates to see if there is a 0% tax rate, if not add it
        has_zero_tax = any(item.name == '0' for item in cart_items)
        if not has_zero_tax:
            # Add a 0% tax rule to the checkout options
            if checkout_options:
                if checkout_options.tax_tables:
                    checkout_options.tax_tables.add_tax_rule(tax_rule)


        # Get the payment method code from transaction and map it to MultiSafepay format
        odoo_method_code = payment_transaction.payment_method_code

        # Convert to MultiSafepay format using the provider's mapping function
        provider = getattr(payment_transaction, 'provider_id', None)
        if provider:
            multisafepay_gateway_code = provider._map_odoo_to_multisafepay_code(odoo_method_code)
        else:
            multisafepay_gateway_code = odoo_method_code.upper()

        _logger.debug("Mapping Odoo method '%s' to MultiSafepay gateway '%s'", odoo_method_code, multisafepay_gateway_code)

        order_request = (OrderRequest(**{})
            .add_type('redirect')
            .add_gateway(multisafepay_gateway_code)
            .add_order_id(order_id)
            .add_currency(currency.currency)
            .add_amount(amount)
            .add_payment_options(payment_options)
            .add_customer(customer)
            .add_delivery(delivery)
            .add_description(description.description if description.description else '')
            .add_shopping_cart(shopping_cart)
            .add_plugin(plugin)
            .add_second_chance(second_chance)
        )

        if checkout_options:
            order_request.add_checkout_options(checkout_options)

        provider = getattr(payment_transaction, 'provider_id', None)
        if not provider:
            _logger.error("Payment provider not found on transaction.")
            raise ValidationError(_("Payment provider not found."))

        multisafepay_sdk = provider.get_multisafepay_sdk()

        if not multisafepay_sdk:
            _logger.error("MultiSafepay SDK not initialized.")
            raise ValidationError(_("MultiSafepay SDK is not initialized."))

        _logger.debug("Order request: %s", order_request.to_dict())

        order_manager = multisafepay_sdk.get_order_manager()
        create_response = order_manager.create(order_request)

        _logger.debug("Order created response: %s", str(create_response))

        order: Order = create_response.get_data()

        # Prefer order_id, fallback to transaction_id
        _order_id = getattr(order, 'order_id', None)

        if not _order_id:
            # Provide a precise message; caller will redirect with it
            raise ValidationError(_('There was a problem processing your payment. Possible reasons could be: "insufficient funds", or "verification failed".'))

        _logger.info("Order created successfully with ID: %s", _order_id)
        return order


    def _get_correct_base_url(self):
        """Get the correct base URL, prioritizing configured domain over localhost"""

        # Priority 1: System parameter (configured domain)
        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        if base_url and not ('localhost' in base_url or '127.0.0.1' in base_url):
            _logger.debug("Using configured base URL: %s", base_url)
            return base_url

        # Priority 2: X-Forwarded-Host header (from proxy)
        x_forwarded_host = request.httprequest.headers.get('X-Forwarded-Host')
        x_forwarded_proto = request.httprequest.headers.get('X-Forwarded-Proto', 'https')

        if x_forwarded_host:
            base_url = f"{x_forwarded_proto}://{x_forwarded_host}"
            _logger.debug("Using X-Forwarded-Host: %s", base_url)
            return base_url

        # Priority 3: Host header
        host = request.httprequest.headers.get('Host')
        if host and not ('localhost' in host or '127.0.0.1' in host):
            is_secure = request.httprequest.is_secure or x_forwarded_proto == 'https'
            scheme = 'https' if is_secure else 'http'
            base_url = f"{scheme}://{host}"
            _logger.debug("Using Host header: %s", base_url)
            return base_url

        # Priority 4: Website domain (if configured)
        if hasattr(request, 'website') and request.website:
            website_domain = request.website.domain
            if website_domain and not ('localhost' in website_domain or '127.0.0.1' in website_domain):
                base_url = f"https://{website_domain}"
                _logger.debug("Using website domain: %s", base_url)
                return base_url

        # Fallback: Use original method but log warning
        base_url = request.httprequest.url_root.rstrip('/')
        _logger.warning("Falling back to request URL root (may be localhost): %s", base_url)
        return base_url

