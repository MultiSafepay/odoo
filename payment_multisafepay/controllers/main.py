# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

"""
MultiSafepay Payment Controller
Handles redirect flow for MultiSafepay payments
"""

import copy
import json
import logging
from typing import cast
from urllib.parse import quote_plus

from multisafepay.api.paths.orders.request.components.checkout_options import (
    CheckoutOptions,
)
from multisafepay.api.paths.orders.request.components.payment_options import (
    PaymentOptions,
)
from multisafepay.api.paths.orders.request.components.plugin import Plugin
from multisafepay.api.paths.orders.request.components.second_chance import SecondChance
from multisafepay.api.paths.orders.request.order_request import OrderRequest
from multisafepay.api.paths.orders.response.order_response import Order
from multisafepay.api.shared.cart.cart_item import CartItem
from multisafepay.api.shared.cart.shopping_cart import ShoppingCart
from multisafepay.api.shared.checkout.tax_rate import TaxRate
from multisafepay.api.shared.checkout.tax_rule import TaxRule
from multisafepay.api.shared.customer import Customer
from multisafepay.api.shared.delivery import Delivery
from multisafepay.api.shared.description import Description
from multisafepay.util.address_parser import AddressParser
from multisafepay.util.webhook import Webhook
from multisafepay.value_object.amount import Amount
from multisafepay.value_object.currency import Currency
from multisafepay.value_object.weight import Weight
from werkzeug.exceptions import Forbidden

from odoo import _, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from ..const import PAYMENT_METHOD_PENDING, PAYMENT_METHOD_PREFIX
from ..utils import money_to_minor_units

_logger = logging.getLogger(__name__)


class MultiSafepayController(http.Controller):
    """Controller to handle MultiSafepay payment flow"""

    _redirect_url = "/payment/multisafepay/redirect"
    _webhook_url = "/payment/multisafepay/webhook"
    _return_url = "/payment/multisafepay/return"
    _cancel_url = "/payment/multisafepay/cancel"

    # ===================================
    # ROUTES (ODOO)
    # ===================================

    @http.route(
        "/payment/multisafepay/redirect",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def multisafepay_redirect(self, **post):
        """Handle redirect to MultiSafepay payment page"""
        _logger.info("MultiSafepay redirect endpoint")
        _logger.debug("MultiSafepay redirect endpoint request POST data: %s", str(post))

        try:
            reference = post.get("reference")
            if not reference:
                return self._redirect_to_payment_with_error(
                    "missing_reference",
                    _("Payment reference is missing. Please try again."),
                )

            payment_transaction = (
                request.env["payment.transaction"]
                .sudo()
                .search(
                    [
                        ("reference", "=", reference),
                        ("provider_code", "=", "multisafepay"),
                    ],
                    limit=1,
                )
            )

            if not payment_transaction:
                return self._redirect_to_payment_with_error(
                    "transaction_not_found",
                    _("Transaction not found. Please refresh and try again."),
                )

            try:
                base_url = self._get_correct_base_url()
                order = self._get_order(base_url, payment_transaction)

                if not order or not order.payment_url:
                    return self._redirect_to_payment_with_error(
                        "multiSafepay_api_error",
                        _(
                            "MultiSafepay API error: Transaction not found. Please refresh and try again."
                        ),
                    )

                _logger.info("Payment url was generated successfully.")
                _logger.debug(
                    "Payment url was generated successfully: %s", order.payment_url
                )

                return request.redirect(order.payment_url, local=False)

            except (ValidationError, UserError) as ve:
                _logger.error("Validation/User error: %s", str(ve))
                return self._redirect_to_payment_with_error("validation_error", str(ve))

            except Exception as api_error:
                _logger.error("Unexpected error: %s", str(api_error))
                return self._redirect_to_payment_with_error(
                    "Unexpected error",
                    _("An unexpected error occurred. Please try again."),
                )

        except Exception as e:
            _logger.error("Unexpected error: %s", str(e))
            return self._redirect_to_payment_with_error(
                "unexpected_error", _("An unexpected error occurred. Please try again.")
            )

    @http.route(
        "/payment/multisafepay/webhook",
        type="http",
        auth="public",
        csrf=False,
        methods=["POST", "GET"],
    )
    def multisafepay_webhook(self, **kwargs):
        """Handle MultiSafepay webhook notifications"""

        _logger.info("MultiSafepay webhook received via %s", request.httprequest.method)
        _logger.debug("MultiSafepay webhook data: %s", str(kwargs))

        try:
            if request.httprequest.method == "POST":
                return self._handle_post_webhook(**kwargs)
            else:
                return self._handle_get_webhook(**kwargs)

        except Exception as e:
            _logger.error("Unexpected error in webhook processing: %s", str(e))
            return request.make_response("Internal Server Error", status=500)

    @http.route(
        "/payment/multisafepay/return",
        type="http",
        auth="public",
        csrf=False,
        methods=["GET", "POST"],
    )
    def multisafepay_return(self, **kwargs):
        """Handle return from MultiSafepay payment page"""
        _logger.info("MultiSafepay return received")
        _logger.debug("Return data: %s", str(kwargs))

        transactionid = kwargs.get("transactionid")

        payment_transaction = (
            request.env["payment.transaction"]
            .sudo()
            .search(
                [
                    ("reference", "=", transactionid),
                    ("provider_code", "=", "multisafepay"),
                ],
                limit=1,
            )
        )

        if (
            payment_transaction.payment_method_code.removeprefix(PAYMENT_METHOD_PREFIX)
            in PAYMENT_METHOD_PENDING
        ):
            _logger.info(
                "Payment method '%s' requires manual confirmation. Setting as pending.",
                payment_transaction.payment_method_code,
            )

            # Get real state from MultiSafepay
            provider = payment_transaction.provider_id
            multisafepay_sdk = provider.get_multisafepay_sdk()
            order_manager = multisafepay_sdk.get_order_manager()
            order_response = order_manager.get(transactionid)
            order = order_response.get_data()

            notification_data = {
                "status": "pending",
                "reference": transactionid,
            }

            # Process notification to update transaction state
            payment_transaction._process_notification_data(notification_data)

            # Redirect for pending payment - can be overridden by e-commerce module
            return self._redirect_pending_payment(
                payment_transaction, order, transactionid
            )

        return request.redirect("/payment/status")

    @http.route(
        "/payment/multisafepay/cancel",
        type="http",
        auth="public",
        csrf=False,
        methods=["GET", "POST"],
    )
    def multisafepay_cancel(self, **kwargs):
        """Handle cancellation from MultiSafepay payment page"""
        _logger.info("MultiSafepay payment cancelled")
        _logger.debug("Cancel data: %s", str(kwargs))

        transactionid = kwargs.get("transactionid")

        payment_transaction = (
            request.env["payment.transaction"]
            .sudo()
            .search(
                [
                    ("reference", "=", transactionid),
                    ("provider_code", "=", "multisafepay"),
                ],
                limit=1,
            )
        )

        notification_data = {
            "status": "cancelled",
            "reference": transactionid,
        }

        payment_transaction._process_notification_data(notification_data)

        _logger.info("MultiSafepay payment cancelled: %s", transactionid)

        return request.redirect("/payment/status?cancelled=1")

    # ===================================
    # MULTISAFEPAY - Webhook Handling
    # ===================================

    def _handle_get_webhook(self, **kwargs):
        """Handle GET webhook from MultiSafepay"""

        transactionid = kwargs.get("transactionid")
        if not transactionid:
            _logger.error("No transaction ID provided in webhook")
            return request.make_response("Transaction ID required", status=400)

        payment_transaction = (
            request.env["payment.transaction"]
            .sudo()
            .search(
                [
                    ("reference", "=", transactionid),
                    ("provider_code", "=", "multisafepay"),
                ],
                limit=1,
            )
        )

        if not payment_transaction:
            _logger.error(
                "Transaction not found for webhook validation: %s", transactionid
            )
            return request.make_response("Transaction not found", status=404)

        # Fetch order details from MultiSafepay API to verify status
        provider = payment_transaction.provider_id
        multisafepay_sdk = provider.get_multisafepay_sdk()

        order_manager = multisafepay_sdk.get_order_manager()
        order_response = order_manager.get(transactionid)
        order = order_response.get_data()
        if not order:
            _logger.error("No order data found for transaction ID: %s", transactionid)
            return request.make_response("No order data found", status=404)

        if not order.status:
            _logger.error(
                "No status found in order data for transaction ID: %s", transactionid
            )
            return request.make_response("No status found", status=400)

        # Prevent duplicate processing of same status
        duplicated = self._duplicated_status(payment_transaction, order.status)
        if duplicated:
            _logger.debug(
                "Duplicate webhook received for transaction %s with status %s, ignoring.",
                transactionid,
                order.status,
            )
            return request.make_response("OK", status=200)

        # Prepare notification data for Odoo transaction processing
        notification_data = {
            "status": order.status,
            "reference": order.transaction_id
            if hasattr(order, "transaction_id")
            else None,
        }

        # Update transaction state based on webhook notification
        payment_transaction._process_notification_data(notification_data)

        _logger.info(
            "Webhook processing completed for transaction %s with status %s",
            transactionid,
            order.status,
        )
        return request.make_response("OK", status=200)

    def _handle_post_webhook(self, **kwargs):
        """Handle POST webhook from MultiSafepay"""

        request_body_raw = request.httprequest.get_data(as_text=True)
        try:
            _logger.debug("POST webhook data: %s", request_body_raw)

            # Parse JSON body into Order object
            order = None
            if request_body_raw:
                try:
                    order_data = json.loads(request_body_raw)
                    # Convert dict to MultiSafepay Order object
                    order = Order.from_dict(order_data)
                    _logger.debug("Parsed POST webhook data: %s", str(order_data))

                except json.JSONDecodeError:
                    _logger.error(
                        "Failed to parse POST webhook body as JSON, using form data"
                    )
                    return request.make_response(
                        "Invalid JSON format in webhook body", status=403
                    )

            # Validate that order data contains transaction ID
            if not order or not order.order_id:
                _logger.error("No transaction ID provided in webhook")
                return request.make_response("Transaction ID required", status=400)

            transactionid = order.order_id
            payment_transaction = (
                request.env["payment.transaction"]
                .sudo()
                .search(
                    [
                        ("reference", "=", transactionid),
                        ("provider_code", "=", "multisafepay"),
                    ],
                    limit=1,
                )
            )

            if not payment_transaction:
                _logger.error(
                    "Transaction not found for webhook validation: %s", transactionid
                )
                return request.make_response("Transaction not found", status=404)

            # Get authentication header and API key for webhook signature validation
            auth_header = request.httprequest.headers.get("Auth", "")

            provider = payment_transaction.provider_id
            api_key = provider.multisafepay_api_key

            try:
                # Validate webhook signature using MultiSafepay SDK
                # This ensures the webhook is genuinely from MultiSafepay
                validated = Webhook.validate(
                    request=request_body_raw,
                    auth=auth_header,
                    api_key=api_key,
                    validation_time_in_seconds=600,
                )

                if not validated:
                    _logger.error(
                        "Webhook validation failed for transaction %s: Invalid signature",
                        transactionid,
                    )
                    payment_transaction._set_error(
                        "Webhook validation failed: Invalid signature"
                    )
                    return request.make_response(
                        "Webhook validation failed", status=403
                    )

                _logger.info(
                    "Webhook validation successful for transaction: %s", transactionid
                )

                if not order.status:
                    _logger.error(
                        "No status found in order data for transaction ID: %s",
                        transactionid,
                    )
                    return request.make_response("No status found", status=400)

                # Check if we already processed this status to avoid duplicate processing
                duplicated = self._duplicated_status(payment_transaction, order.status)
                if duplicated:
                    _logger.info(
                        "Duplicate webhook received for transaction %s with status %s, ignoring.",
                        transactionid,
                        order.status,
                    )
                    return request.make_response("OK", status=200)

                notification_data = {
                    "status": order.status,
                    "reference": order.transaction_id
                    if hasattr(order, "transaction_id")
                    else None,
                }

                payment_transaction._process_notification_data(notification_data)

                _logger.info(
                    "Webhook processing completed for transaction %s with status %s",
                    transactionid,
                    order.status,
                )
                return request.make_response("OK", status=200)

            except Exception as validation_error:
                _logger.error(
                    "Webhook validation failed for transaction %s: %s",
                    transactionid,
                    str(validation_error),
                )
                return request.make_response("Webhook validation failed", status=403)

        except Forbidden as e:
            _logger.error("Forbidden access to MultiSafepay webhook: %s", str(e))
            return request.make_response("Forbidden", status=403)

    # ===================================
    # MULTISAFEPAY - Helpers
    # ===================================

    def _redirect_to_payment_with_error(self, error_code, message):
        """Redirect to payment form with error message

        Returns to standard payment status page.
        Can be overridden by e-commerce module to redirect to /shop/payment.
        """
        return request.redirect(
            f"/payment/status?error={error_code}&message={quote_plus(message)}"
        )

    def _redirect_pending_payment(self, payment_transaction, order, transactionid):
        """Redirect after pending payment confirmation

        Returns to standard payment status page with payment details.
        Can be overridden by e-commerce module to redirect to /shop/confirmation with order details.

        :param payment_transaction: The payment transaction record
        :param order: The MultiSafepay order object
        :param transactionid: The transaction ID
        :return: HTTP redirect response
        """
        params = {
            "payment_method": payment_transaction.payment_method_code,
            "payment_status": order.status if order else "pending",
            "transaction_id": transactionid,
            "multisafepay_order_id": order.order_id
            if order and hasattr(order, "order_id")
            else "",
            "amount": payment_transaction.amount,
            "currency": payment_transaction.currency_id.name,
        }

        # Build URL with parameters
        url_params = "&".join(
            [f"{k}={quote_plus(str(v))}" for k, v in params.items() if v]
        )
        return request.redirect(f"/payment/status?{url_params}")

    def _duplicated_status(self, payment_transaction, new_status, message=""):
        """Check if the transaction already has the specified status to detect duplicates."""
        _logger.debug(
            "Transaction %s status changed to %s: %s",
            payment_transaction.id,
            new_status,
            message,
        )
        return (
            payment_transaction.state
            == payment_transaction._get_multisafepay_status_to_odoo_state(new_status)
        )

    def _extract_partner_data(self, partner):
        """Extract and validate partner data for MultiSafepay order

        Extracts country code, email, phone, ref, and address information from a partner record.
        Returns a dictionary with raw values that can be passed directly to SDK.
        All values default to None if not available.

        :param partner: res.partner recordset
        :return: Dictionary with partner data ready for SDK
        :rtype: dict
        """
        # Extract country code (only from country_id)
        country_raw = None
        if partner and partner.country_id and partner.country_id.code:
            country_raw = partner.country_id.code

        # Extract raw values - SDK will validate them
        email_raw = None
        phone_raw = None
        ref_raw = None

        if partner:
            email_raw = getattr(partner, "email", None)
            phone_raw = getattr(partner, "phone", None)
            ref_raw = getattr(partner, "ref", None)

            # Odoo may return False for empty fields, convert to None
            email_raw = email_raw if email_raw else None
            phone_raw = phone_raw if phone_raw else None
            ref_raw = ref_raw if ref_raw else None

        # Parse name
        first_name = None
        last_name = None
        if partner:
            partner_name = getattr(partner, "name", None)
            if partner_name:
                name_parts = partner_name.split(" ")
                if name_parts:
                    first_name = name_parts[0]
                    if len(name_parts) > 1:
                        last_name = " ".join(name_parts[1:])

        # Parse address
        address1 = None
        house_number = None
        if partner:
            street = getattr(partner, "street", None)
            street2 = getattr(partner, "street2", None)
            address_parser = AddressParser()
            parsed_address = address_parser.parse(street, street2)
            if parsed_address:
                address1 = parsed_address[0]
                if len(parsed_address) > 1:
                    house_number = parsed_address[1]

        # Extract location data
        zip_code = None
        city = None

        if partner:
            zip_code = getattr(partner, "zip", None)
            city = getattr(partner, "city", None)

            # Odoo may return False for empty fields, convert to None
            zip_code = zip_code if zip_code else None
            city = city if city else None
        state = None
        # Many2one fields return False when empty, so we need to check both existence and type
        if partner and partner.state_id and hasattr(partner.state_id, "name"):
            state = partner.state_id.name

        # Convert False values to None for SDK compatibility (Odoo quirk)
        first_name = first_name if first_name else None
        last_name = last_name if last_name else None
        address1 = address1 if address1 else None
        house_number = house_number if house_number else None
        state = state if state else None

        return {
            "country_raw": country_raw,
            "email_raw": email_raw,
            "phone_raw": phone_raw,
            "ref_raw": ref_raw,
            "first_name": first_name,
            "last_name": last_name,
            "address1": address1,
            "house_number": house_number,
            "zip_code": zip_code,
            "city": city,
            "state": state,
        }

    # ===================================
    # MULTISAFEPAY - Order Creation
    # ===================================

    def _validate_transaction(self, payment_transaction):
        """Validate transaction has required fields

        :param payment_transaction: The payment transaction record
        :raises ValidationError: If validation fails
        """
        if not getattr(payment_transaction, "reference", None):
            raise ValidationError(_("Transaction reference is missing."))

        amount = getattr(payment_transaction, "amount", 0)
        if amount <= 0:
            raise ValidationError(_("Transaction amount is missing or invalid."))

        currency_id = getattr(payment_transaction, "currency_id", None)
        if not currency_id or not getattr(currency_id, "name", None):
            raise ValidationError(_("Transaction currency is missing or invalid."))

    def _prepare_amount_and_currency(self, payment_transaction):
        """Prepare amount and currency for MultiSafepay API

        Converts amount to smallest currency unit (cents) to avoid floating-point
        precision issues. Example: 100.00 EUR → 10000 cents

        :param payment_transaction: The payment transaction record
        :return: Tuple of (Currency object, amount in cents as int, currency_id record)
        :rtype: tuple
        """
        currency_id = payment_transaction.currency_id
        amount = payment_transaction.amount

        normalized_amount = money_to_minor_units(amount, currency_id)

        # Create SDK value objects - these validate format internally
        amount_obj = Amount(amount=normalized_amount).amount
        currency_obj = Currency(currency=currency_id.name)

        return (currency_obj, amount_obj, currency_id)

    def _is_partial_payment_link(
        self,
        payment_transaction,
        source_total_amount,
        source_residual_amount,
        source_type,
        currency_id,
    ):
        """Return True when this transaction belongs to a partial payment-link flow.

        A transaction is considered part of a partial flow when all of these are true:
        - cart source is invoice or sale_order
        - transaction operation is online redirect/direct
        - transaction targets exactly one source document
        - and transaction amount differs from source total, or source residual already indicates
          a previous partial payment (invoice flow)

        :param payment_transaction: The payment transaction record
        :param source_total_amount: Total amount from source document
        :param source_residual_amount: Residual amount from source document (invoice)
        :param source_type: Source model used to build cart (invoice/sale_order)
        :param currency_id: Currency record used for decimal precision
        :return: True when transaction is part of a partial payment-link flow
        :rtype: bool
        """
        if source_type not in ("invoice", "sale_order") or source_total_amount is None:
            return False

        operation = getattr(payment_transaction, "operation", None)
        if operation not in ("online_redirect", "online_direct"):
            return False

        if source_type == "invoice":
            invoice_ids = getattr(payment_transaction, "invoice_ids", None)
            if not invoice_ids or len(invoice_ids) != 1:
                return False
        else:
            sale_order_ids = getattr(payment_transaction, "sale_order_ids", None)
            if not sale_order_ids or len(sale_order_ids) != 1:
                return False

        transaction_units = money_to_minor_units(
            getattr(payment_transaction, "amount", 0), currency_id
        )
        total_units = money_to_minor_units(source_total_amount, currency_id)
        if source_type == "invoice" and source_residual_amount is not None:
            residual_units = money_to_minor_units(source_residual_amount, currency_id)
            # We intentionally omit residual_units > total_units: it indicates
            # inconsistent accounting data and should not occur in normal flows.
            if residual_units < total_units:
                return True

        return transaction_units != total_units

    def _get_partners_from_transaction(self, payment_transaction):
        """Get invoice and shipping partners from transaction

        Handles multiple Odoo payment scenarios:
        - E-commerce: Uses sale_order partners (may differ for billing/shipping)
        - Invoice payment: Uses transaction partner for both
        - Manual payment: Fallback to transaction partner

        :param payment_transaction: The payment transaction record
        :return: Tuple of (partner_invoice, partner_shipping, sale_order or None, sale_orders)
        :rtype: tuple
        """
        sale_orders = getattr(payment_transaction, "sale_order_ids", None)
        partner_invoice = None
        partner_shipping = None
        sale_order = None

        if sale_orders:
            sale_order = sale_orders[0]  # Assuming one sale order per transaction
            partner_invoice = getattr(sale_order, "partner_invoice_id", None)
            partner_shipping = getattr(sale_order, "partner_shipping_id", None)
        else:
            # Fallback: use transaction partner for both billing and shipping
            partner_invoice = getattr(payment_transaction, "partner_id", None)
            partner_shipping = partner_invoice

        if not partner_invoice:
            raise ValidationError(_("No customer info partner associated."))

        return (partner_invoice, partner_shipping, sale_order, sale_orders)

    def _get_order(self, url, payment_transaction) -> Order:
        """Create the order request for MultiSafepay transactions.

        Orchestrates order creation by:
        1. Validating transaction data
        2. Preparing amount/currency (converts to cents)
        3. Extracting partners (from sale order or transaction)
        4. Building customer and delivery info
        5. Constructing shopping cart (from invoice or sale order lines)
        6. Configuring payment options and callbacks
        7. Creating order via MultiSafepay SDK

        Works across multiple Odoo modules: payment, account, sale, website_sale, loyalty

        :param str url: The base URL for callbacks
        :param payment_transaction: The payment.transaction record
        :return: The order created in MultiSafepay
        :rtype: Order
        """

        # Validate transaction data
        self._validate_transaction(payment_transaction)

        # Prepare amount and currency (convert to cents)
        currency, amount, currency_id = self._prepare_amount_and_currency(
            payment_transaction
        )

        # Get partners from transaction (invoice/shipping addresses)
        partner_invoice, partner_shipping, sale_order, sale_orders = (
            self._get_partners_from_transaction(payment_transaction)
        )

        # Basic order metadata
        order_id = payment_transaction.reference
        description = Description(description="Order #" + order_id)
        language = getattr(payment_transaction, "partner_lang", "en_US") or "en_US"

        # Extract partner data and HTTP metadata for fraud prevention
        partner_invoice_data = self._extract_partner_data(partner_invoice)

        environ = (
            getattr(request.httprequest, "environ", {})
            if request and hasattr(request, "httprequest")
            else {}
        )
        partner_invoice_ip_address_raw = (
            environ.get("REMOTE_ADDR", None) if isinstance(environ, dict) else None
        )
        partner_invoice_forwarded_ip_raw = (
            environ.get("HTTP_X_FORWARDED_FOR", None)
            if isinstance(environ, dict)
            else None
        )
        partner_invoice_forwarded_ip_raw = (
            partner_invoice_forwarded_ip_raw or partner_invoice_ip_address_raw
        )
        partner_invoice_referrer = (
            environ.get("HTTP_REFERER", None) if isinstance(environ, dict) else None
        )

        user_agent_string = None
        if (
            request
            and hasattr(request, "httprequest")
            and hasattr(request.httprequest, "user_agent")
        ):
            user_agent = request.httprequest.user_agent
            user_agent_string = (
                getattr(user_agent, "string", None) if user_agent else None
            )

        # Build Customer object
        customer = cast(
            Customer,
            (
                Customer(**{})
                .add_locale(language)
                .add_ip_address(partner_invoice_ip_address_raw)
                .add_forwarded_ip(partner_invoice_forwarded_ip_raw)
                .add_referrer(partner_invoice_referrer)
                .add_user_agent(user_agent_string)
                .add_reference(partner_invoice_data["ref_raw"])
                .add_first_name(partner_invoice_data["first_name"])
                .add_last_name(partner_invoice_data["last_name"])
                .add_phone(partner_invoice_data["phone_raw"])
                .add_email(partner_invoice_data["email_raw"])
                .add_address1(partner_invoice_data["address1"])
                .add_address2(None)
                .add_house_number(partner_invoice_data["house_number"])
                .add_zip_code(partner_invoice_data["zip_code"])
                .add_city(partner_invoice_data["city"])
                .add_state(partner_invoice_data["state"])
                .add_country(partner_invoice_data["country_raw"])
            ),
        )

        # SALE MODULE INTEGRATION - Shipping Address
        # If sale order exists and has different shipping address, use it
        # Otherwise, use invoice address for delivery (standard fallback)
        use_delivery_as_billing = False
        partner_shipping = None
        delivery = Delivery(**{})

        if sale_order:
            partner_shipping = sale_order.partner_shipping_id

            # Check if invoice and shipping addresses are the same partner
            if partner_invoice.id == partner_shipping.id:
                use_delivery_as_billing = True

        if partner_shipping:
            # Extract partner data using helper function
            partner_shipping_data = self._extract_partner_data(partner_shipping)

            if sale_orders and not use_delivery_as_billing:
                delivery = (
                    Delivery(**{})
                    .add_first_name(partner_shipping_data["first_name"])
                    .add_last_name(partner_shipping_data["last_name"])
                    .add_phone(partner_shipping_data["phone_raw"])
                    .add_email(partner_shipping_data["email_raw"])
                    .add_address1(partner_shipping_data["address1"])
                    .add_address2(None)
                    .add_house_number(partner_shipping_data["house_number"])
                    .add_zip_code(partner_shipping_data["zip_code"])
                    .add_city(partner_shipping_data["city"])
                    .add_state(partner_shipping_data["state"])
                    .add_country(partner_shipping_data["country_raw"])
                )

        if not sale_orders or sale_orders and use_delivery_as_billing:
            # If no sale order, use the invoice partner details for delivery
            delivery = (
                Delivery(**{})
                .add_first_name(partner_invoice_data["first_name"])
                .add_last_name(partner_invoice_data["last_name"])
                .add_phone(partner_invoice_data["phone_raw"])
                .add_email(partner_invoice_data["email_raw"])
                .add_address1(partner_invoice_data["address1"])
                .add_address2(None)
                .add_house_number(partner_invoice_data["house_number"])
                .add_zip_code(partner_invoice_data["zip_code"])
                .add_city(partner_invoice_data["city"])
                .add_state(partner_invoice_data["state"])
                .add_country(partner_invoice_data["country_raw"])
            )

        # Create a Plugin object with the necessary details
        plugin = (
            Plugin(**{})
            .add_plugin_version("2.1.1")
            .add_shop("Odoo")
            .add_shop_version("19.0")
            .add_shop_root_url(url)
        )

        # Create payment options for the order
        payment_options = (
            PaymentOptions(**{})
            .add_notification_method("POST")
            .add_close_window(True)
            .add_notification_url(f"{url}/payment/multisafepay/webhook")
            .add_redirect_url(f"{url}/payment/multisafepay/return")
            .add_cancel_url(f"{url}/payment/multisafepay/cancel")
        )

        # Prevent Second Chance, not supported at this moment
        second_chance = SecondChance(send_email=False)

        # ===================================================================
        # SHOPPING CART CONSTRUCTION
        # ===================================================================
        # Build cart from invoice lines (preferred) or sale order lines (fallback)
        # Cart is mandatory for correct tax calculations in MultiSafepay API

        order_lines = []
        source_type = None

        # Try invoice lines first (most accurate - final prices and taxes)
        invoice = None
        invoice_ids = getattr(payment_transaction, "invoice_ids", None)
        if invoice_ids and len(invoice_ids) > 0:
            invoice = invoice_ids[0]
            all_invoice_lines = getattr(invoice, "invoice_line_ids", [])

            # Filter: Exclude only known decorative/informational line types
            # Conservative approach: better to include an extra line than miss a monetary one
            # Known decorative types: line_section, line_subsection, line_note
            order_lines = [
                line
                for line in all_invoice_lines
                if getattr(line, "display_type", None)
                not in ("line_section", "line_subsection", "line_note")
            ]

            if order_lines:
                source_type = "invoice"
                _logger.debug(
                    "Using invoice lines for cart: %d lines (filtered from %d total)",
                    len(order_lines),
                    len(all_invoice_lines),
                )

        # Fallback to sale order if no invoice
        if not order_lines and sale_order:
            all_sale_lines = getattr(sale_order, "order_line", [])

            # Same filtering: exclude only known decorative types
            order_lines = [
                line
                for line in all_sale_lines
                if getattr(line, "display_type", None)
                not in ("line_section", "line_subsection", "line_note")
            ]

            if order_lines:
                source_type = "sale_order"
                _logger.debug(
                    "Using sale order lines for cart: %d lines (filtered from %d total)",
                    len(order_lines),
                    len(all_sale_lines),
                )

        source_total_amount = None
        source_residual_amount = None
        if source_type == "invoice" and invoice:
            source_total_amount = getattr(invoice, "amount_total", None)
            source_residual_amount = getattr(invoice, "amount_residual", None)
        elif source_type == "sale_order" and sale_order:
            source_total_amount = getattr(sale_order, "amount_total", None)

        is_partial_payment_link = self._is_partial_payment_link(
            payment_transaction,
            source_total_amount,
            source_residual_amount,
            source_type,
            currency_id,
        )

        # Build cart items
        cart_items = []

        if is_partial_payment_link:
            installment_key = "odoo-partial-payment"
            installment_name = "Partial payment"
            invoice_label = getattr(invoice, "name", None) if invoice else None

            cart_item = (
                CartItem(**{})
                .add_name(installment_name)
                .add_description(invoice_label or installment_key)
                .add_unit_price(getattr(payment_transaction, "amount", 0.0))
                .add_quantity(1)
                .add_merchant_item_id(installment_key)
                .add_weight(Weight(value=0.0, unit="kg"))
            )
            cart_item.add_tax_rate_percentage(0)
            cart_items.append(cart_item)

            _logger.debug(
                "Using synthetic installment cart for partial payment link "
                "(ref=%s, item=%s, source_total=%s, source_residual=%s, tx_amount=%s)",
                payment_transaction.reference,
                installment_key,
                source_total_amount,
                source_residual_amount,
                payment_transaction.amount,
            )

        for line in order_lines if not is_partial_payment_link else []:
            product = getattr(line, "product_id", None)

            # Detect source to use correct field names (invoice vs sale order)
            is_invoice_line = source_type == "invoice"

            # Extract tax rate for MultiSafepay tax calculations
            tax_table_selector = None
            if hasattr(line, "tax_ids") and line.tax_ids:
                tax_table_selector = line.tax_ids[0].amount

            # Build merchant_item_id: SKU → product.id → line.id
            if product and product.default_code:
                merchant_item_id = product.default_code
            elif product:
                merchant_item_id = str(product.id)
            else:
                merchant_item_id = f"line-{line.id}"

            # Loyalty integration: prefix with reward/program type (sale orders only)
            # reward_id only exists on sale.order.line, not on invoice lines
            if source_type == "sale_order":
                reward_id = getattr(line, "reward_id", None)
                if reward_id:
                    reward_type = getattr(reward_id, "reward_type", None)
                    if reward_type:
                        merchant_item_id = f"{reward_type}-{merchant_item_id}"
                    program_type = getattr(reward_id, "program_type", None)
                    if program_type:
                        merchant_item_id = f"{program_type}-{merchant_item_id}"

            # Append product variant attributes to item ID
            if hasattr(line, "product_no_variant_attribute_value_ids"):
                for variant in line.product_no_variant_attribute_value_ids:
                    merchant_item_id += f"-{variant.name}"

            # Get line fields - compatible with both sale and invoice lines
            line_name = getattr(line, "name", "") or ""
            line_description = ""
            if product:
                line_description = getattr(product, "description_sale", "") or ""

            # Field mapping: sale.order.line uses 'product_uom_qty', invoice uses 'quantity'
            if is_invoice_line:
                line_quantity = getattr(line, "quantity", 0)
            else:
                line_quantity = getattr(line, "product_uom_qty", 0)

            # Calculate unit price WITHOUT taxes (price_subtotal is always tax-exclusive)
            line_price_subtotal = getattr(line, "price_subtotal", 0.0)
            if line_quantity:
                line_price_unit = line_price_subtotal / line_quantity
            else:
                line_price_unit = getattr(line, "price_unit", 0.0)

            # Weight: from product
            line_weight = 0.0
            if product:
                line_weight = getattr(product, "weight", 0.0) or 0.0

            cart_item = (
                CartItem(**{})
                .add_name(line_name)
                .add_description(line_description)
                .add_unit_price(line_price_unit)
                .add_quantity(line_quantity)
                .add_merchant_item_id(merchant_item_id)
                .add_weight(Weight(value=line_weight, unit="kg"))
            )

            if tax_table_selector is not None:
                cart_item.add_tax_rate_percentage(tax_table_selector)
            else:
                cart_item.add_tax_rate_percentage(0)

            cart_items.append(cart_item)
            _logger.debug("Order line details: %s", str(cart_item.to_dict()))

        shopping_cart = ShoppingCart(items=cart_items)
        # Generate checkout options from cart (includes tax tables)
        checkout_options = CheckoutOptions.generate_from_shopping_cart(shopping_cart)

        if checkout_options:
            # Keep cart validation enabled for all flows.
            # For partial payment links we send a synthetic installment item
            # that matches the transaction amount to satisfy validation.
            checkout_options.add_validate_cart(True)

            if is_partial_payment_link:
                _logger.debug(
                    "Cart validation enabled with synthetic installment cart "
                    "(ref=%s, source_total=%s, tx_amount=%s)",
                    payment_transaction.reference,
                    source_total_amount,
                    payment_transaction.amount,
                )

        # Create a 0% tax rule as fallback for items without tax
        tax_rule = TaxRule(
            name="0", rules=[TaxRate(rate=0, country="")], standalone=None
        )

        # Check if any cart item already has a 0% tax rate
        has_zero_tax = any(item.name == "0" for item in cart_items)
        if not has_zero_tax:
            # Add 0% tax rule to ensure all items can be processed
            if checkout_options:
                if checkout_options.tax_tables:
                    checkout_options.tax_tables.add_tax_rule(tax_rule)

        # Get the payment method code from transaction and map it to MultiSafepay format
        odoo_method_code = payment_transaction.payment_method_code

        # Convert to MultiSafepay format using the provider's mapping function
        provider = getattr(payment_transaction, "provider_id", None)
        if provider:
            multisafepay_gateway_code = provider._map_odoo_to_multisafepay_code(
                odoo_method_code
            )
        else:
            multisafepay_gateway_code = odoo_method_code.upper()

        _logger.debug(
            "Mapping Odoo method '%s' to MultiSafepay gateway '%s'",
            odoo_method_code,
            multisafepay_gateway_code,
        )

        order_request = (
            OrderRequest(**{})
            .add_type("redirect")
            .add_gateway(multisafepay_gateway_code)
            .add_order_id(order_id)
            .add_currency(currency.currency)
            .add_amount(amount)
            .add_payment_options(payment_options)
            .add_customer(customer)
            .add_delivery(delivery)
            .add_description(description.description if description.description else "")
            .add_shopping_cart(shopping_cart)
            .add_plugin(plugin)
            .add_second_chance(second_chance)
        )

        if checkout_options:
            order_request.add_checkout_options(checkout_options)

        # Get payment provider and initialize MultiSafepay SDK client
        provider = getattr(payment_transaction, "provider_id", None)
        if not provider:
            _logger.error("Payment provider not found on transaction.")
            raise ValidationError(_("Payment provider not found."))

        multisafepay_sdk = provider.get_multisafepay_sdk()

        if not multisafepay_sdk:
            _logger.error("MultiSafepay SDK not initialized.")
            raise ValidationError(_("MultiSafepay SDK is not initialized."))

        _logger.debug("Order request: %s", order_request.to_dict())

        # Create order via MultiSafepay API
        order_manager = multisafepay_sdk.get_order_manager()
        create_response = order_manager.create(order_request)

        _logger.debug("Order created response: %s", str(create_response))

        # Extract order data from API response
        order: Order = create_response.get_data()

        # Verify order was created successfully
        _order_id = getattr(order, "order_id", None)

        if not _order_id:
            # Sanitize order request for logging
            sanitized_request = self._sanitize_order_request_for_logging(
                order_request.to_dict()
            )

            # Log order request with sensitive data masked for debugging
            _logger.error(
                "Order request failed to create a transaction. Order request: %s",
                sanitized_request,
            )

            # Log create_response for debugging
            _logger.error("API response: %s", create_response.get_raw())

            # Order creation failed - provide user-friendly error message
            raise ValidationError(
                _(
                    'There was a problem processing your payment. Possible reasons could be: "insufficient funds", or "verification failed".'
                )
            )

        _logger.info("Order created successfully with ID: %s", _order_id)
        return order

    def _get_correct_base_url(self):
        """Get the correct base URL, prioritizing configured domain over localhost"""

        # Priority 1: System parameter (configured domain)
        base_url = (
            request.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        )
        if base_url and not ("localhost" in base_url or "127.0.0.1" in base_url):
            _logger.debug("Using configured base URL: %s", base_url)
            return base_url

        # Priority 2: X-Forwarded-Host header (from proxy)
        x_forwarded_host = request.httprequest.headers.get("X-Forwarded-Host")
        x_forwarded_proto = request.httprequest.headers.get(
            "X-Forwarded-Proto", "https"
        )

        if x_forwarded_host:
            base_url = f"{x_forwarded_proto}://{x_forwarded_host}"
            _logger.debug("Using X-Forwarded-Host: %s", base_url)
            return base_url

        # Priority 3: Host header
        host = request.httprequest.headers.get("Host")
        if host and not ("localhost" in host or "127.0.0.1" in host):
            is_secure = request.httprequest.is_secure or x_forwarded_proto == "https"
            scheme = "https" if is_secure else "http"
            base_url = f"{scheme}://{host}"
            _logger.debug("Using Host header: %s", base_url)
            return base_url

        # Priority 4: Website domain (if configured)
        if hasattr(request, "website") and request.website:
            website_domain = request.website.domain
            if website_domain and not (
                "localhost" in website_domain or "127.0.0.1" in website_domain
            ):
                base_url = f"https://{website_domain}"
                _logger.debug("Using website domain: %s", base_url)
                return base_url

        # Fallback: Use original method but log warning
        base_url = request.httprequest.url_root.rstrip("/")
        _logger.warning(
            "Falling back to request URL root (may be localhost): %s", base_url
        )
        return base_url

    def _mask_sensitive_value(self, value) -> str:
        """
        Mask a sensitive value for safe logging.

        :param value: The value to mask
        :return: Masked string representation of the value
        :rtype: str
        """
        if value is None:
            return "***"
        str_value = str(value)
        if len(str_value) <= 4:
            return "***"
        return str_value[:2] + "*" * (len(str_value) - 4) + str_value[-2:]

    def _sanitize_dict_recursive(self, d, sensitive_fields) -> dict:
        """
        Recursively sanitize a dictionary by masking sensitive fields.

        :param d: The dictionary to sanitize
        :param sensitive_fields: Set of field names to mask
        :return: Sanitized dictionary
        :rtype: dict
        """
        if not isinstance(d, dict):
            return d
        result = {}
        for key, value in d.items():
            if key.lower() in sensitive_fields:
                result[key] = self._mask_sensitive_value(value)
            elif isinstance(value, dict):
                result[key] = self._sanitize_dict_recursive(value, sensitive_fields)
            elif isinstance(value, list):
                result[key] = [
                    self._sanitize_dict_recursive(i, sensitive_fields)
                    if isinstance(i, dict)
                    else i
                    for i in value
                ]
            else:
                result[key] = value
        return result

    def _sanitize_order_request_for_logging(self, order_data: dict) -> dict:
        """
        Sanitize order request data for safe logging by masking sensitive PII fields.

        :param order_data: The order request dictionary to sanitize
        :return: Sanitized copy of the order data safe for logging
        :rtype: dict
        """

        sensitive_fields = {
            "email",
            "phone",
            "ip_address",
            "forwarded_ip",
            "first_name",
            "last_name",
            "address1",
            "address2",
            "house_number",
            "zip_code",
        }

        return self._sanitize_dict_recursive(
            copy.deepcopy(order_data), sensitive_fields
        )
