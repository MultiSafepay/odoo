import json
import logging
import os
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from urllib.parse import urlparse

import requests
from multisafepay import Sdk
from multisafepay.api.paths.orders.order_id.refund.request.refund_request import (
    RefundOrderRequest,
)
from multisafepay.api.paths.orders.request import OrderRequest
from multisafepay.api.paths.orders.request.components import AmountDetails, Tip
from multisafepay.api.paths.orders.request.components.checkout_options import (
    CheckoutOptions as CheckoutOptionsRequest,
)
from multisafepay.api.paths.orders.request.components.payment_options import (
    PaymentOptions,
)
from multisafepay.api.paths.orders.response.order_response import Order as OrderResponse
from multisafepay.api.shared.cart.cart_item import CartItem
from multisafepay.api.shared.cart.shopping_cart import ShoppingCart
from multisafepay.api.shared.checkout.checkout_options import (
    CheckoutOptions as CheckoutOptionsTaxTables,
)
from multisafepay.api.shared.checkout.default_tax_rate import DefaultTaxRate
from multisafepay.api.shared.checkout.tax_rate import TaxRate
from multisafepay.api.shared.checkout.tax_rule import TaxRule
from multisafepay.api.shared.customer import Customer
from multisafepay.client import ScopedCredentialResolver
from multisafepay.client.credential_resolver import AuthScope
from multisafepay.transport import RequestsTransport
from multisafepay.util.json_encoder import DecimalEncoder

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def _get_cloud_requests_session(timeout_seconds):
    timeout_seconds = max(int(timeout_seconds or 60), 60)

    session = requests.Session()
    original_request = session.request

    def request_with_default_timeout(method, url, **kwargs):
        kwargs.setdefault("timeout", timeout_seconds)
        return original_request(method, url, **kwargs)

    session.request = request_with_default_timeout
    return session


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    msp_cloud_terminal_id = fields.Char(
        string="Terminal ID",
        copy=False,
        help="Use a dedicated payment method per terminal configuration.",
    )
    msp_cloud_terminal_group_id = fields.Char(
        string="Terminal Group ID",
        copy=False,
        help="Terminal group identifier used by the Cloud POS API auth scope. Use a dedicated payment method per terminal configuration.",
    )
    msp_cloud_account_api_key = fields.Char(
        string="Merchant Account API Key",
        copy=False,
    )
    msp_cloud_terminal_group_api_key = fields.Char(
        string="Terminal Group API Key",
        copy=False,
        help="API key used for the configured Terminal Group ID.",
    )
    msp_cloud_custom_api_url = fields.Char(
        string="Custom API URL",
        copy=False,
        help="Override the API base URL for development. The required SDK dev flags are enabled automatically when this is set.",
    )
    msp_cloud_timeout_seconds = fields.Integer(
        string="API Timeout (seconds)",
        default=60,
    )
    msp_cloud_validate_cart = fields.Boolean(
        string="Validate Shopping Cart",
        default=False,
        help="Ask MultiSafepay to validate the shopping cart total against the payment amount. Enable this only when Cloud POS payments always cover the full POS order amount.",
    )
    msp_cloud_confirmation_channel = fields.Selection(
        [
            ("webhook", "Webhook only"),
            ("both", "Webhook and socket"),
            ("event_stream", "Socket only"),
        ],
        string="Confirmation Channel",
        default="webhook",
        help="Choose which MultiSafepay backend channel can automatically confirm Cloud POS orders. Socket means the MultiSafepay event stream; the POS frontend websocket remains active.",
    )
    msp_cloud_debug_mode = fields.Boolean(
        compute="_compute_msp_cloud_debug_mode",
    )

    @api.depends_context("uid")
    def _compute_msp_cloud_debug_mode(self):
        debug_mode = False
        try:
            session = getattr(request, "session", None)
            debug_mode = bool(getattr(session, "debug", False))
        except RuntimeError:
            # request is not available in non-HTTP contexts (cron/shell)
            debug_mode = False

        for payment_method in self:
            payment_method.msp_cloud_debug_mode = debug_mode

    def _msp_cloud_confirmation_channel_value(self):
        self.ensure_one()
        return self.msp_cloud_confirmation_channel or "webhook"

    def _msp_cloud_use_event_stream(self):
        self.ensure_one()
        return self._msp_cloud_confirmation_channel_value() in {"both", "event_stream"}

    def _msp_cloud_use_webhook_notifications(self):
        self.ensure_one()
        return self._msp_cloud_confirmation_channel_value() in {"both", "webhook"}

    def _msp_cloud_allows_webhook_confirmation(self, method=None):
        self.ensure_one()
        if (method or "").upper() == "GET":
            return True
        return self._msp_cloud_use_webhook_notifications()

    @api.constrains(
        "use_payment_terminal",
        "active",
        "company_id",
        "msp_cloud_terminal_id",
        "msp_cloud_terminal_group_id",
    )
    def _check_msp_cloud_terminal_configuration_uniqueness(self):
        for payment_method in self:
            if payment_method.use_payment_terminal != "multisafepay_cloud":
                continue

            terminal_id = (payment_method.msp_cloud_terminal_id or "").strip()
            terminal_group_id = (
                payment_method.msp_cloud_terminal_group_id or ""
            ).strip()
            if not terminal_id or not terminal_group_id:
                continue

            conflict = self.search(
                [
                    ("id", "!=", payment_method.id),
                    ("active", "=", True),
                    ("company_id", "=", payment_method.company_id.id),
                    ("use_payment_terminal", "=", "multisafepay_cloud"),
                    ("msp_cloud_terminal_id", "=", terminal_id),
                    ("msp_cloud_terminal_group_id", "=", terminal_group_id),
                ],
                limit=1,
            )
            if conflict:
                raise ValidationError(
                    _(
                        "Terminal ID '%(terminal_id)s' with Terminal Group ID '%(terminal_group_id)s' "
                        "is already configured on payment method '%(payment_method_name)s'. "
                        "Use one payment method per terminal configuration."
                    )
                    % {
                        "terminal_id": terminal_id,
                        "terminal_group_id": terminal_group_id,
                        "payment_method_name": conflict.display_name,
                    }
                )

    @api.constrains(
        "use_payment_terminal",
        "msp_cloud_terminal_group_id",
        "msp_cloud_terminal_group_api_key",
    )
    def _check_msp_cloud_group_key_for_configured_group(self):
        for payment_method in self:
            if payment_method.use_payment_terminal != "multisafepay_cloud":
                continue

            terminal_group_id = (
                payment_method.msp_cloud_terminal_group_id or ""
            ).strip()
            if not terminal_group_id:
                continue

            terminal_group_api_key = (
                payment_method.msp_cloud_terminal_group_api_key or ""
            ).strip()
            if terminal_group_api_key:
                continue

            raise ValidationError(
                _(
                    "Configure a Terminal Group API Key for Terminal Group ID '%(terminal_group_id)s'."
                )
                % {"terminal_group_id": terminal_group_id}
            )

    def _get_payment_terminal_selection(self):
        return super()._get_payment_terminal_selection() + [
            ("multisafepay_cloud", "MultiSafepay Cloud POS")
        ]

    def multisafepay_cloud_payment_request(self, data):
        self.ensure_one()

        response = self._api_create_cloud_pos_order(data)
        remote_order_id = (
            response.get("order_id") or response.get("id") or data.get("msp_cloud_uid")
        )
        self.env["pos.multisafepay.cloud.payment"].sudo().create_payment_request(
            response,
            {
                **data,
                "msp_cloud_uid": remote_order_id,
                "payment_method_id": self.id,
            },
        )
        return response

    def _get_multisafepay_cloud_sdk(self):
        self.ensure_one()

        terminal_group_id = (self.msp_cloud_terminal_group_id or "").strip()
        terminal_group_api_key = (self.msp_cloud_terminal_group_api_key or "").strip()
        bootstrap_api_key = (
            self.msp_cloud_account_api_key or terminal_group_api_key or ""
        ).strip()

        transport = RequestsTransport(
            session=_get_cloud_requests_session(self.msp_cloud_timeout_seconds or 60)
        )

        terminal_group_api_keys = (
            {terminal_group_id: terminal_group_api_key}
            if terminal_group_id and terminal_group_api_key
            else None
        )
        credential_resolver = ScopedCredentialResolver(
            default_api_key=bootstrap_api_key,
            terminal_group_api_keys=terminal_group_api_keys,
        )

        sdk_kwargs = {
            "is_production": True,
            "credential_resolver": credential_resolver,
            "transport": transport,
        }

        custom_url = self._normalize_cloud_custom_api_url(
            (self.msp_cloud_custom_api_url or "").strip()
        )
        if custom_url:
            self._enable_sdk_custom_base_url_override(custom_url)
            sdk_kwargs["base_url"] = custom_url

        return Sdk(**sdk_kwargs)

    @staticmethod
    def _enable_sdk_custom_base_url_override(custom_url):
        os.environ["MSP_SDK_BUILD_PROFILE"] = "dev"
        os.environ["MSP_SDK_ALLOW_CUSTOM_BASE_URL"] = "1"
        os.environ["MSP_SDK_CUSTOM_BASE_URL"] = custom_url

    @staticmethod
    def _normalize_cloud_custom_api_url(base_url):
        if not base_url:
            return ""

        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Invalid custom API URL.")

        if parsed.params or parsed.query or parsed.fragment:
            raise ValueError("Invalid custom API URL.")

        path = parsed.path.rstrip("/")
        path = "/" if not path else f"{path}/"
        return f"{parsed.scheme}://{parsed.netloc}{path}"

    @staticmethod
    def _format_cloud_exception(error):
        if not error:
            return ""
        if isinstance(error, str):
            return error

        if isinstance(error, requests.HTTPError):
            response = getattr(error, "response", None)
            if response is not None:
                try:
                    payload = response.json() or {}
                except ValueError:
                    payload = {}

                error_info = (payload.get("error_info") or "").strip()
                error_code = payload.get("error_code")
                if error_info and error_code:
                    return f"{error_info} (error_code: {error_code})"
                if error_info:
                    return error_info

        error_message = str(error).strip()
        error_type = type(error).__name__
        return f"{error_type}: {error_message}" if error_message else error_type

    def _build_cloud_failure_payload(self, default_detail, error=None, operation=None):
        detail = self._humanize_cloud_error_detail(
            self._format_cloud_exception(error),
            default_detail,
            operation=operation,
        )
        return {
            "status": "error",
            "state": "failure",
            "detail": detail or default_detail,
        }

    @staticmethod
    def _extract_cloud_event_payload(event):
        payload = getattr(event, "data", None)
        if not isinstance(payload, dict):
            return {}

        normalized_payload = dict(payload)
        nested_payload = normalized_payload.get("data")
        if isinstance(nested_payload, dict):
            normalized_payload = {
                **nested_payload,
                **{
                    key: value
                    for key, value in normalized_payload.items()
                    if key != "data"
                },
            }

        event_id = getattr(event, "event_id", None)
        if event_id:
            normalized_payload["last_event_id"] = event_id

        event_name = getattr(event, "event", None)
        if event_name:
            normalized_payload.setdefault("event_name", event_name)

        return normalized_payload

    def _wait_for_cloud_order_event(
        self,
        sdk,
        order_or_payload,
        timeout_seconds=None,
        last_event_id=None,
    ):
        self.ensure_one()

        if not self._msp_cloud_use_event_stream():
            _logger.info(
                "MSP Cloud POS event stream skipped for payment method %s because confirmation channel is %s.",
                self.display_name,
                self._msp_cloud_confirmation_channel_value(),
            )
            return {}

        order = order_or_payload
        if isinstance(order_or_payload, dict):
            last_event_id = last_event_id or order_or_payload.get("last_event_id")
            order = OrderResponse.from_dict(dict(order_or_payload))

        if not order:
            return {}

        events_token = getattr(order, "events_token", None) or getattr(
            order,
            "event_token",
            None,
        )
        events_stream_url = getattr(order, "events_stream_url", None) or getattr(
            order,
            "event_stream_url",
            None,
        )
        if not events_token or not events_stream_url:
            return {}

        timeout_seconds = max(
            float(timeout_seconds or self.msp_cloud_timeout_seconds or 60), 60.0
        )
        latest_payload = {}

        try:
            event_manager = sdk.get_event_manager()
            with event_manager.subscribe_order_events(
                order,
                last_event_id=last_event_id,
                timeout=timeout_seconds,
            ) as stream:
                for event in stream:
                    event_payload = self._extract_cloud_event_payload(event)
                    if not event_payload:
                        continue

                    status = self._normalize_cloud_status(event_payload.get("status"))
                    _logger.info(
                        "MSP Cloud POS event received: order_id=%s event=%s status=%s state=%s last_event_id=%s keys=%s",
                        getattr(order, "order_id", None),
                        event_payload.get("event_name") or event_payload.get("event"),
                        status,
                        self._cloud_status_state(status),
                        event_payload.get("last_event_id")
                        or event_payload.get("event_id"),
                        sorted(event_payload.keys()),
                    )
                    latest_payload.update(event_payload)
                    if self._cloud_status_state(status) != "pending":
                        latest_payload["status"] = status
                        latest_payload["state"] = self._cloud_status_state(status)
                        return latest_payload
        except (
            requests.RequestException,
            TimeoutError,
            ValueError,
            OSError,
        ) as error:
            _logger.info(
                "MSP Cloud POS event wait ended without a terminal state "
                "(order_id=%s): %s",
                getattr(order, "order_id", None),
                self._format_cloud_exception(error),
            )

        return latest_payload

    def _finalize_cloud_pos_payload(self, payload, remote_order_id):
        self.ensure_one()

        payload = dict(payload or {})
        order_id = str(
            payload.get("order_id") or payload.get("transaction_id") or remote_order_id
        )
        status = self._normalize_cloud_status(payload.get("status") or "initialized")

        payload.update(
            {
                "id": order_id,
                "order_id": order_id,
                "transaction_id": payload.get("transaction_id") or order_id,
                "status": status,
                "state": self._cloud_status_state(status),
            }
        )
        return payload

    def _humanize_cloud_error_detail(self, detail, default_detail, operation=None):
        normalized_detail = (detail or "").strip()
        if not normalized_detail:
            return default_detail

        normalized_detail_lower = normalized_detail.lower()

        if (
            "timeout" in normalized_detail_lower
            or "timed out" in normalized_detail_lower
        ):
            return _(
                "The MultiSafepay Cloud POS terminal did not return a final result in time. "
                "Check the terminal status before retrying the payment."
            )

        if "No API key configured for terminal_group_id" in normalized_detail:
            terminal_group_id = (self.msp_cloud_terminal_group_id or "").strip()
            if terminal_group_id:
                return _(
                    "Cloud POS authentication failed for Terminal Group ID "
                    "'%(terminal_group_id)s'. Verify the Terminal Group API Key "
                    "on the payment method."
                ) % {"terminal_group_id": terminal_group_id}
            return _(
                "Cloud POS authentication failed. Verify Terminal Group ID and "
                "Terminal Group API Key on the payment method."
            )

        if "Missing terminal_group_id in auth scope" in normalized_detail:
            return _(
                "Cloud POS authentication failed because Terminal Group ID is "
                "missing on the payment method."
            )

        if "Invalid transaction ID" in normalized_detail:
            if operation == "status":
                return _(
                    "The MultiSafepay Cloud POS payment is no longer available as an active terminal transaction. "
                    "It may have timed out or been cancelled on the terminal. Check the terminal before retrying."
                )
            if operation == "cancel":
                return _(
                    "The MultiSafepay Cloud POS payment could not be cancelled because the terminal transaction is no longer available. "
                    "It may already be cancelled or expired."
                )
            return _(
                "MultiSafepay Cloud POS could not start this payment attempt. "
                "The previous terminal transaction may still be active, expired, or already cancelled. Check the terminal before retrying."
            )

        return normalized_detail

    def _api_create_cloud_pos_order(self, data):
        self.ensure_one()

        validation_error = self._validate_cloud_pos_configuration(
            require_account_key=False
        )
        if validation_error:
            return validation_error

        remote_order_id = self._build_cloud_pos_order_id(data)
        attempt_base = self._sanitize_cloud_order_id(
            data.get("msp_cloud_attempt_base")
            or data.get("msp_cloud_uid")
            or data.get("pos_reference")
            or data.get("order_id")
            or self.id
        )
        attempt_number = self._get_cloud_pos_order_attempt_number(
            attempt_base, remote_order_id
        )
        data.update(
            {
                "msp_cloud_uid": remote_order_id,
                "msp_cloud_attempt_base": attempt_base,
                "msp_cloud_attempt_number": attempt_number,
            }
        )

        amount_in_cents = int(round(abs(data.get("amount") or 0.0) * 100))
        currency = data.get("currency") or "EUR"
        shopping_cart_data = data.get("shopping_cart")
        shopping_cart = self._build_cloud_shopping_cart(shopping_cart_data)
        checkout_options = self._build_cloud_checkout_options(shopping_cart)
        shopping_cart_summary = self._build_cloud_shopping_cart_summary(
            shopping_cart_data
        )
        amount_details = self._build_cloud_amount_details(shopping_cart_data)
        customer = self._build_cloud_customer(data.get("customer"))
        order_description = self._build_cloud_order_description(
            data,
            remote_order_id,
            shopping_cart_summary,
        )
        payment_options = None
        if self._msp_cloud_use_webhook_notifications():
            payment_options = (
                PaymentOptions(**{})
                .add_notification_method("POST")
                .add_notification_url(
                    f"{self.get_base_url()}/pos_multisafepay_cloud/notification"
                )
            )
        else:
            _logger.info(
                "MSP Cloud POS webhook notification URL not added for payment method %s because confirmation channel is %s.",
                self.display_name,
                self._msp_cloud_confirmation_channel_value(),
            )

        try:
            order_request = (
                OrderRequest()
                .add_type("redirect")
                .add_order_id(remote_order_id)
                .add_description(order_description)
                .add_amount(amount_in_cents)
                .add_currency(currency)
                .add_gateway_info({"terminal_id": self.msp_cloud_terminal_id.strip()})
            )
            if payment_options:
                order_request.add_payment_options(payment_options)
            if customer:
                order_request.add_customer(customer)
            order_request.add_var1(
                self._truncate_cloud_text(
                    data.get("pos_reference") or remote_order_id,
                    255,
                )
            )
            order_request.add_var3("Cloud POS")
            if shopping_cart:
                order_request.add_shopping_cart(shopping_cart)
            if checkout_options:
                order_request.add_checkout_options(checkout_options)
            if amount_details:
                order_request.add_amount_details(amount_details)

            sdk = self._get_multisafepay_cloud_sdk()
            order_manager = sdk.get_order_manager()
            _logger.warning(
                "MSP Cloud POS order request payload debug: %s",
                json.dumps(order_request.to_dict(), cls=DecimalEncoder, sort_keys=True),
            )
            create_response = order_manager.create(
                order_request,
                terminal_group_id=self.msp_cloud_terminal_group_id.strip(),
            )

            if not create_response.get_body_success():
                return self._build_cloud_failure_payload(
                    _("MultiSafepay Cloud POS order creation failed."),
                    error=create_response.get_body_error_info(),
                    operation="create",
                )

            order = create_response.get_data()
            if not order:
                return {
                    "status": "error",
                    "state": "failure",
                    "detail": _(
                        "MultiSafepay Cloud POS order creation did not return order data."
                    ),
                }

            payload = self._serialize_sdk_model(order)
            if not payload:
                return {
                    "status": "error",
                    "state": "failure",
                    "detail": _(
                        "MultiSafepay Cloud POS order creation returned an invalid order payload."
                    ),
                }

            payload = self._finalize_cloud_pos_payload(
                payload,
                remote_order_id=remote_order_id,
            )
            payload.update(
                {
                    "msp_cloud_attempt_base": attempt_base,
                    "msp_cloud_attempt_number": attempt_number,
                }
            )

            if payload.get("state") == "success":
                receipt = self._api_get_cloud_receipt(payload["order_id"], sdk=sdk)
                if receipt:
                    payload["receipt"] = receipt

            return payload
        except Exception as error:
            _logger.exception(
                "MSP Cloud POS order creation failed "
                "(remote_order_id=%s, terminal_id=%s, terminal_group_id=%s, custom_url_set=%s): %s",
                remote_order_id,
                self.msp_cloud_terminal_id,
                self.msp_cloud_terminal_group_id,
                bool(self.msp_cloud_custom_api_url),
                self._format_cloud_exception(error),
            )
            return self._build_cloud_failure_payload(
                _("Could not contact the MultiSafepay Cloud POS API."),
                error=error,
                operation="create",
            )

    def _build_cloud_shopping_cart(self, shopping_cart_data):
        if not isinstance(shopping_cart_data, dict):
            return None

        items_data = (shopping_cart_data or {}).get("items")
        if not isinstance(items_data, list):
            return None

        cart_items = []
        for item_data in items_data:
            cart_item = self._build_cloud_cart_item(item_data)
            if cart_item:
                cart_items.append(cart_item)

        return ShoppingCart(items=cart_items) if cart_items else None

    def _build_cloud_amount_details(self, shopping_cart_data):
        tip_amount = self._get_cloud_shopping_cart_tip_amount(shopping_cart_data)
        tip_amount_in_cents = self._amount_to_cloud_minor_units(tip_amount)
        if tip_amount_in_cents <= 0:
            return None

        return AmountDetails().add_tip(Tip().add_amount(tip_amount_in_cents))

    def _get_cloud_shopping_cart_tip_amount(self, shopping_cart_data):
        if not isinstance(shopping_cart_data, dict):
            return Decimal("0")

        items_data = shopping_cart_data.get("items")
        if not isinstance(items_data, list):
            return Decimal("0")

        tip_amount = Decimal("0")
        for item_data in items_data:
            if not isinstance(item_data, dict) or not item_data.get(
                "msp_cloud_is_tip"
            ):
                continue

            unit_price = self._decimal_from_cloud_payload(item_data.get("unit_price"))
            quantity = self._decimal_from_cloud_payload(item_data.get("quantity") or 0)
            tip_amount += abs(unit_price * quantity)

        return tip_amount

    @staticmethod
    def _decimal_from_cloud_payload(value):
        try:
            return Decimal(str(value or 0))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal("0")

    def _build_cloud_cart_item(self, item_data):
        if not isinstance(item_data, dict):
            return None

        quantity = item_data.get("quantity") or 0
        if not quantity:
            return None

        name = str(item_data.get("name") or _("POS item"))[:255]
        merchant_item_id = self._sanitize_cloud_order_id(
            item_data.get("merchant_item_id") or name
        )
        cart_item = (
            CartItem(**{})
            .add_name(name)
            .add_description(str(item_data.get("description") or "")[:255])
            .add_unit_price(item_data.get("unit_price") or 0)
            .add_quantity(quantity)
            .add_merchant_item_id(merchant_item_id)
        )
        if item_data.get("currency"):
            cart_item.add_currency(str(item_data.get("currency")))
        if isinstance(item_data.get("options"), list):
            cart_item.add_options(item_data.get("options"))

        tax_rate_percentage = item_data.get("tax_rate_percentage")
        if tax_rate_percentage is not None:
            cart_item.add_tax_rate(
                self._cloud_tax_rate_from_percentage(tax_rate_percentage)
            )
        elif item_data.get("tax_table_selector") is not None:
            cart_item.add_tax_table_selector(str(item_data.get("tax_table_selector")))
        else:
            cart_item.add_tax_rate(Decimal("0"))

        return cart_item

    def _build_cloud_customer(self, customer_data):
        if not isinstance(customer_data, dict):
            return None

        full_name = self._truncate_cloud_text(customer_data.get("name"), 255)
        first_name = self._truncate_cloud_text(customer_data.get("first_name"), 255)
        last_name = self._truncate_cloud_text(customer_data.get("last_name"), 255)
        if full_name and not (first_name or last_name):
            first_name, last_name = self._split_cloud_customer_name(full_name)

        customer_values = {
            "locale": self._truncate_cloud_text(customer_data.get("locale"), 16),
            "reference": self._truncate_cloud_text(customer_data.get("reference"), 255),
            "first_name": first_name,
            "last_name": last_name,
            "address1": self._truncate_cloud_text(customer_data.get("address1"), 255),
            "address2": self._truncate_cloud_text(customer_data.get("address2"), 255),
            "house_number": self._truncate_cloud_text(
                customer_data.get("house_number"), 64
            ),
            "zip_code": self._truncate_cloud_text(customer_data.get("zip_code"), 64),
            "city": self._truncate_cloud_text(customer_data.get("city"), 255),
            "state": self._truncate_cloud_text(customer_data.get("state"), 255),
            "country": self._format_cloud_country_code(customer_data.get("country")),
            "phone": self._truncate_cloud_text(customer_data.get("phone"), 64),
            "email": self._format_cloud_email(customer_data.get("email")),
        }
        customer_values = {
            key: value for key, value in customer_values.items() if value
        }
        return Customer(**customer_values) if customer_values else None

    @staticmethod
    def _split_cloud_customer_name(name):
        name_parts = str(name or "").strip().split()
        if not name_parts:
            return "", ""
        if len(name_parts) == 1:
            return name_parts[0], name_parts[0]
        return name_parts[0], " ".join(name_parts[1:])

    def _format_cloud_country_code(self, country):
        country = self._truncate_cloud_text(country, 2).upper()
        return country if len(country) == 2 else ""

    def _format_cloud_email(self, email):
        email = self._truncate_cloud_text(email, 255)
        return email if email and "@" in email else ""

    def _build_cloud_shopping_cart_summary(self, shopping_cart_data, limit=255):
        if not isinstance(shopping_cart_data, dict):
            return None

        items_data = shopping_cart_data.get("items")
        if not isinstance(items_data, list):
            return None

        summary_parts = []
        for item_data in items_data:
            if not isinstance(item_data, dict):
                continue

            item_name = self._truncate_cloud_text(item_data.get("name"), 80)
            if not item_name:
                continue

            quantity = self._format_cloud_cart_quantity(item_data.get("quantity"))
            summary_parts.append(f"{quantity}x {item_name}")

        if not summary_parts:
            return None

        return self._truncate_cloud_text(
            ", ".join(summary_parts),
            limit,
        )

    def _build_cloud_order_description(
        self,
        data,
        remote_order_id,
        shopping_cart_summary,
    ):
        base_description = self._truncate_cloud_text(
            data.get("description") or remote_order_id,
            255,
        )
        if not shopping_cart_summary:
            return base_description

        return self._truncate_cloud_text(
            f"{base_description} - {shopping_cart_summary}",
            255,
        )

    @staticmethod
    def _format_cloud_cart_quantity(quantity):
        try:
            quantity_decimal = Decimal(str(quantity or 0))
        except (InvalidOperation, TypeError, ValueError):
            quantity_decimal = Decimal("0")

        quantity_decimal = abs(quantity_decimal.normalize())
        if quantity_decimal == quantity_decimal.to_integral_value():
            return str(int(quantity_decimal))
        return format(quantity_decimal, "f")

    @staticmethod
    def _truncate_cloud_text(value, limit):
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) <= limit:
            return text
        return text[: max(limit - 3, 0)].rstrip() + "..."

    def _build_cloud_checkout_options(self, shopping_cart):
        if not shopping_cart or not shopping_cart.items:
            return None

        tax_rules = []
        seen_selectors = set()
        for cart_item in shopping_cart.items:
            selector = getattr(cart_item, "tax_table_selector", None)
            if selector is None:
                continue

            selector = str(selector)
            if selector in seen_selectors:
                continue

            try:
                tax_rate = Decimal(selector)
            except (InvalidOperation, TypeError, ValueError):
                continue

            tax_rules.append(
                TaxRule(
                    name=selector,
                    standalone=True,
                    rules=[TaxRate(rate=float(tax_rate))],
                )
            )
            seen_selectors.add(selector)

        checkout_options = CheckoutOptionsRequest(
            tax_tables=CheckoutOptionsTaxTables(
                default=DefaultTaxRate(rate=0.0, shipping_taxed=True),
                alternate=tax_rules,
            ),
        )
        checkout_options.add_validate_cart(bool(self.msp_cloud_validate_cart))
        return checkout_options

    @staticmethod
    def _cloud_tax_rate_from_percentage(tax_rate_percentage):
        try:
            percentage = Decimal(str(tax_rate_percentage or 0))
        except (InvalidOperation, TypeError, ValueError):
            percentage = Decimal("0")
        if percentage < 0:
            percentage = Decimal("0")
        return (percentage / Decimal("100")).quantize(Decimal("0.000001")).normalize()

    def _api_get_cloud_order_status(self, order_id, sdk=None):
        self.ensure_one()

        validation_error = self._validate_cloud_pos_configuration(
            require_account_key=True
        )
        if validation_error:
            return validation_error

        try:
            sdk = sdk or self._get_multisafepay_cloud_sdk()
            order_manager = sdk.get_order_manager()
            order_response = order_manager.get(str(order_id))
            if not order_response.get_body_success():
                return self._build_cloud_failure_payload(
                    _("Could not fetch MultiSafepay Cloud POS order status."),
                    error=order_response.get_body_error_info(),
                    operation="status",
                )

            order = order_response.get_data()
            if not order:
                return {}

            payload = self._serialize_sdk_model(order)
            status = self._normalize_cloud_status(
                payload.get("status") or "initialized"
            )
            payload.update(
                {
                    "id": order.order_id,
                    "order_id": order.order_id or str(order_id),
                    "transaction_id": order.transaction_id
                    or order.order_id
                    or str(order_id),
                    "status": status,
                    "state": self._cloud_status_state(status),
                }
            )
            return payload
        except Exception as error:
            _logger.exception(
                "MSP Cloud POS order status fetch failed "
                "(order_id=%s, terminal_id=%s, terminal_group_id=%s): %s",
                order_id,
                self.msp_cloud_terminal_id,
                self.msp_cloud_terminal_group_id,
                self._format_cloud_exception(error),
            )
            return self._build_cloud_failure_payload(
                _("Could not fetch MultiSafepay Cloud POS order status."),
                error=error,
                operation="status",
            )

    def _api_get_cloud_receipt(self, order_id, sdk=None):
        self.ensure_one()

        validation_error = self._validate_cloud_pos_configuration(
            require_account_key=False
        )
        if validation_error:
            return {}

        try:
            sdk = sdk or self._get_multisafepay_cloud_sdk()
            pos_manager = sdk.get_pos_manager()
            receipt_response = pos_manager.get_receipt(
                order_id=str(order_id),
                terminal_group_id=self.msp_cloud_terminal_group_id.strip(),
            )
            receipt = receipt_response.get_data()
            if not receipt:
                return {}
            return self._serialize_sdk_model(receipt)
        except Exception as error:
            _logger.exception(
                "MSP Cloud POS receipt fetch failed "
                "(order_id=%s, terminal_id=%s, terminal_group_id=%s): %s",
                order_id,
                self.msp_cloud_terminal_id,
                self.msp_cloud_terminal_group_id,
                self._format_cloud_exception(error),
            )
            return {}

    def _api_cancel_cloud_pos_order(self, order_id, sdk=None):
        self.ensure_one()

        validation_error = self._validate_cloud_pos_configuration(
            require_account_key=False
        )
        if validation_error:
            return validation_error

        try:
            sdk = sdk or self._get_multisafepay_cloud_sdk()
            order_manager = sdk.get_order_manager()
            cancel_response = order_manager.cancel_transaction(
                str(order_id),
                terminal_group_id=self.msp_cloud_terminal_group_id.strip(),
            )
            if not cancel_response.get_body_success():
                return self._build_cloud_failure_payload(
                    _("Could not cancel the MultiSafepay Cloud POS payment."),
                    error=cancel_response.get_body_error_info(),
                    operation="cancel",
                )

            payload = self._serialize_sdk_model(cancel_response.get_data())
            status = self._normalize_cloud_status(payload.get("status") or "canceled")
            payload.update(
                {
                    "id": str(order_id),
                    "order_id": str(order_id),
                    "transaction_id": payload.get("transaction_id") or str(order_id),
                    "status": status,
                    "state": self._cloud_status_state(status),
                }
            )
            return payload
        except Exception as error:
            _logger.exception(
                "MSP Cloud POS cancellation failed "
                "(order_id=%s, terminal_id=%s, terminal_group_id=%s): %s",
                order_id,
                self.msp_cloud_terminal_id,
                self.msp_cloud_terminal_group_id,
                self._format_cloud_exception(error),
            )
            return self._build_cloud_failure_payload(
                _("Could not cancel the MultiSafepay Cloud POS payment."),
                error=error,
                operation="cancel",
            )

    def _api_find_cloud_refund_transaction(
        self, order_id, amount=None, currency=None, sdk=None
    ):
        self.ensure_one()

        validation_error = self._validate_cloud_pos_configuration(
            require_account_key=True
        )
        if validation_error:
            return {}

        amount_in_cents = self._amount_to_cloud_minor_units(amount)
        target_currency = (currency or "").upper()
        created_from = fields.Datetime.subtract(fields.Datetime.now(), days=7)

        try:
            sdk = sdk or self._get_multisafepay_cloud_sdk()
            transaction_response = sdk.get_transaction_manager().get_transactions(
                {
                    "created_from": created_from.strftime("%Y-%m-%dT%H:%M:%S"),
                    "limit": 100,
                }
            )
            listing = transaction_response.get_data() if transaction_response else None
            transactions = (
                listing.get_data() if listing and hasattr(listing, "get_data") else []
            )

            for transaction in transactions or []:
                transaction_payload = self._serialize_sdk_model(transaction)
                if str(transaction_payload.get("order_id") or "") != str(order_id):
                    continue

                transaction_type = (transaction_payload.get("type") or "").lower()
                if transaction_type not in {"refund", "reversal", "returned-refund"}:
                    continue

                if transaction_payload.get("financial_status") not in {
                    None,
                    "completed",
                }:
                    continue
                if transaction_payload.get("status") not in {
                    None,
                    "completed",
                    "refunded",
                }:
                    continue

                if (
                    amount_in_cents
                    and int(transaction_payload.get("amount") or 0) != amount_in_cents
                ):
                    continue
                if (
                    target_currency
                    and (transaction_payload.get("currency") or "").upper()
                    != target_currency
                ):
                    continue

                refund_transaction_id = transaction_payload.get("transaction_id")
                transaction_payload.update(
                    {
                        "id": refund_transaction_id or str(order_id),
                        "order_id": str(order_id),
                        "transaction_id": refund_transaction_id or str(order_id),
                        "refund_id": refund_transaction_id or str(order_id),
                        "amount": transaction_payload.get("amount") or amount_in_cents,
                        "currency": transaction_payload.get("currency")
                        or currency
                        or "EUR",
                        "status": "refunded",
                        "state": "success",
                        "already_refunded": True,
                    }
                )
                return transaction_payload
        except Exception as error:
            _logger.info(
                "MSP Cloud POS existing refund lookup failed (order_id=%s): %s",
                order_id,
                self._format_cloud_exception(error),
            )

        return {}

    def _api_refund_cloud_pos_order(
        self, order_id, amount, currency, description=None, sdk=None
    ):
        self.ensure_one()

        validation_error = self._validate_cloud_pos_configuration(
            require_account_key=True
        )
        if validation_error:
            return validation_error

        amount_in_cents = self._amount_to_cloud_minor_units(amount)
        if amount_in_cents <= 0:
            return {
                "status": "error",
                "state": "failure",
                "detail": _(
                    "The MultiSafepay Cloud POS refund amount must be greater than zero."
                ),
            }

        try:
            sdk = sdk or self._get_multisafepay_cloud_sdk()
            existing_refund = self._api_find_cloud_refund_transaction(
                order_id,
                amount=amount,
                currency=currency,
                sdk=sdk,
            )
            if existing_refund:
                return existing_refund

            order_manager = sdk.get_order_manager()
            refund_payload = (
                RefundOrderRequest(**{})
                .add_amount(amount_in_cents)
                .add_currency(currency or "EUR")
                .add_description(
                    description or _("POS reversal for %s") % str(order_id)
                )
            )
            if (
                self.msp_cloud_terminal_group_id
                and self.msp_cloud_terminal_group_api_key
            ):
                terminal_group_id = self.msp_cloud_terminal_group_id.strip()
                refund_response = order_manager.client.create_post_request(
                    f"json/orders/{order_manager.encode_path_segment(str(order_id))}/refunds",
                    request_body=json.dumps(
                        refund_payload.to_dict(), cls=DecimalEncoder
                    ),
                    auth_scope=AuthScope(
                        scope=ScopedCredentialResolver.AUTH_SCOPE_TERMINAL_GROUP,
                        group_id=terminal_group_id,
                    ),
                    context={
                        "order_id": str(order_id),
                        "terminal_group_id": terminal_group_id,
                    },
                )
            else:
                refund_response = order_manager.refund(str(order_id), refund_payload)
            if not refund_response or not refund_response.get_body_success():
                return self._build_cloud_failure_payload(
                    _("Could not refund the MultiSafepay Cloud POS payment."),
                    error=(refund_response and refund_response.get_body_error_info()),
                    operation="refund",
                )

            refund_data = self._serialize_cloud_response_data(refund_response)
            refund_transaction_id = (
                refund_data.get("transaction_id")
                or refund_data.get("id")
                or refund_data.get("refund_id")
            )
            refund_data.update(
                {
                    "id": refund_transaction_id or str(order_id),
                    "order_id": str(order_id),
                    "transaction_id": refund_transaction_id or str(order_id),
                    "refund_id": refund_transaction_id or str(order_id),
                    "amount": amount_in_cents,
                    "currency": currency or "EUR",
                    "status": "refunded",
                    "state": "success",
                }
            )
            return refund_data
        except Exception as error:
            _logger.exception(
                "MSP Cloud POS refund failed "
                "(order_id=%s, terminal_id=%s, terminal_group_id=%s): %s",
                order_id,
                self.msp_cloud_terminal_id,
                self.msp_cloud_terminal_group_id,
                self._format_cloud_exception(error),
            )
            return self._build_cloud_failure_payload(
                _("Could not refund the MultiSafepay Cloud POS payment."),
                error=error,
                operation="refund",
            )

    def _serialize_cloud_response_data(self, response):
        if not response:
            return {}
        if hasattr(response, "get_data") and callable(response.get_data):
            return self._serialize_sdk_model(response.get_data())
        if hasattr(response, "get_body_data") and callable(response.get_body_data):
            return self._serialize_sdk_model(response.get_body_data())
        data = getattr(response, "data", None)
        if data is not None:
            return self._serialize_sdk_model(data)
        return {}

    @staticmethod
    def _amount_to_cloud_minor_units(amount):
        try:
            amount_decimal = Decimal(str(abs(amount or 0)))
        except (InvalidOperation, TypeError, ValueError):
            amount_decimal = Decimal("0")
        return int((amount_decimal * Decimal("100")).quantize(Decimal("1")))

    def _validate_cloud_pos_configuration(self, require_account_key=False):
        self.ensure_one()

        if not (self.msp_cloud_terminal_id or "").strip():
            return {
                "status": "error",
                "state": "failure",
                "detail": _("Set MSP Cloud Terminal ID on the payment method."),
            }
        if not (self.msp_cloud_terminal_group_id or "").strip():
            return {
                "status": "error",
                "state": "failure",
                "detail": _("Set MSP Cloud Terminal Group ID on the payment method."),
            }
        if not (self.msp_cloud_terminal_group_api_key or "").strip():
            return {
                "status": "error",
                "state": "failure",
                "detail": _(
                    "Set MSP Cloud Terminal Group API Key on the payment method."
                ),
            }
        if require_account_key and not (self.msp_cloud_account_api_key or "").strip():
            return {
                "status": "error",
                "state": "failure",
                "detail": _(
                    "Set MSP Cloud Merchant Account API Key on the payment method to poll real Cloud POS statuses and refund completed payments."
                ),
            }
        return {}

    def _build_cloud_pos_order_id(self, data):
        self.ensure_one()
        attempt_base = self._sanitize_cloud_order_id(
            data.get("msp_cloud_attempt_base")
            or data.get("msp_cloud_uid")
            or data.get("pos_reference")
            or data.get("order_id")
            or self.id
        )
        requested_order_id = self._sanitize_cloud_order_id(
            data.get("msp_cloud_uid") or attempt_base
        )
        if not (
            requested_order_id == attempt_base
            or requested_order_id.startswith(f"{attempt_base}-")
        ):
            requested_order_id = attempt_base

        return self._next_cloud_pos_order_id(attempt_base, requested_order_id)

    def _next_cloud_pos_order_id(self, attempt_base, requested_order_id):
        self.ensure_one()
        attempt_number = self._get_cloud_pos_order_attempt_number(
            attempt_base,
            requested_order_id,
        )
        payment_model = self.env["pos.multisafepay.cloud.payment"].sudo()
        candidate_order_id = requested_order_id
        while payment_model.search_count([("name", "=", candidate_order_id)]):
            attempt_number += 1
            candidate_order_id = self._format_cloud_pos_order_attempt_id(
                attempt_base,
                attempt_number,
            )
        return candidate_order_id

    def _format_cloud_pos_order_attempt_id(self, attempt_base, attempt_number):
        return (
            attempt_base if not attempt_number else f"{attempt_base}-{attempt_number}"
        )

    def _get_cloud_pos_order_attempt_number(self, attempt_base, order_id):
        order_id = str(order_id or "")
        if order_id == attempt_base:
            return 0
        prefix = f"{attempt_base}-"
        if order_id.startswith(prefix) and order_id[len(prefix) :].isdigit():
            return int(order_id[len(prefix) :])
        return 0

    def _sanitize_cloud_order_id(self, value):
        sanitized = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "")).strip("-")[:80]
        return sanitized or str(self.id)

    def _normalize_cloud_status(self, status):
        normalized = (status or "initialized").lower()
        status_map = {
            "created": "initialized",
            "waiting": "pending",
            "authorised": "processing",
            "authorized": "processing",
            "cancelled": "canceled",
            "success": "paid",
            "reversed": "refunded",
        }
        return status_map.get(normalized, normalized)

    def _cloud_status_state(self, status):
        normalized = self._normalize_cloud_status(status)
        if normalized in {"paid", "completed", "refunded", "partial_refunded"}:
            return "success"
        if normalized in {"failed", "declined", "expired", "canceled", "void", "error"}:
            return "failure"
        return "pending"

    def _serialize_sdk_model(self, sdk_model):
        if sdk_model is None:
            return {}
        # pydantic v2
        if hasattr(sdk_model, "model_dump"):
            return self._json_safe_cloud_payload(sdk_model.model_dump(mode="python"))
        # pydantic v1 (current SDK)
        if hasattr(sdk_model, "dict") and callable(sdk_model.dict):
            try:
                return self._json_safe_cloud_payload(sdk_model.dict())
            except TypeError:
                pass
        if isinstance(sdk_model, dict):
            return self._json_safe_cloud_payload(dict(sdk_model))
        return {}

    def _json_safe_cloud_payload(self, payload):
        if isinstance(payload, dict):
            return {
                str(key): self._json_safe_cloud_payload(value)
                for key, value in payload.items()
            }
        if isinstance(payload, (list, tuple, set)):
            return [self._json_safe_cloud_payload(value) for value in payload]
        if isinstance(payload, Decimal):
            if payload == payload.to_integral_value():
                return int(payload)
            return float(payload)
        if isinstance(payload, (date, datetime)):
            return payload.isoformat()
        if isinstance(payload, (str, int, float, bool)) or payload is None:
            return payload
        value = getattr(payload, "value", None)
        if value is not None:
            return self._json_safe_cloud_payload(value)
        return str(payload)
