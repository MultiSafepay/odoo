# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

"""Cloud POS payment method configuration and SDK helpers."""

import base64
import json
import logging
import os

from multisafepay.api.paths.orders.order_id.refund.request.refund_request import (
    RefundOrderRequest,
)
from multisafepay.api.paths.orders.request import OrderRequest
from multisafepay.api.paths.orders.request.components.payment_options import (
    PaymentOptions,
)
from multisafepay.api.paths.orders.request.components.plugin import Plugin
from multisafepay.util.json_encoder import DecimalEncoder

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.modules.module import get_module_resource

from ..helpers.error_payload import (
    _ErrorPayload,
)
from ..helpers.order_payload_builder import (
    _OrderPayloadBuilder,
)
from ..helpers.sdk_factory import (
    _SDKFactory,
)
from ..helpers.serializer import (
    _Serializer,
)
from ..helpers.status import _Status
from ..helpers.utils import (
    _Utils,
)

_logger = logging.getLogger(__name__)

MSP_CLOUD_PAYMENT_TERMINAL_CODE = "multisafepay_cloud"
MSP_CLOUD_PAYMENT_TERMINAL_SELECTION = (
    MSP_CLOUD_PAYMENT_TERMINAL_CODE,
    "MultiSafepay Cloud POS",
)


class PosPaymentMethod(models.Model):
    """Extend POS payment methods with MultiSafepay Cloud POS settings."""

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
        string="Site API Key",
        copy=False,
        help="Default MultiSafepay Site API Key used for refunds and account-level status calls.",
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
    msp_cloud_validate_cart = fields.Boolean(
        string="Validate Shopping Cart",
        default=False,
        help="Ask MultiSafepay to validate the shopping cart total against the payment amount. Enable this only when Cloud POS payments always cover the full POS order amount.",
    )

    msp_cloud_timeout_seconds = fields.Integer(
        string="Timeout (seconds)",
        default=60,
        help="Maximum wait time when polling Cloud POS order status or event stream.",
    )
    msp_cloud_dev_settings_enabled = fields.Boolean(
        compute="_compute_msp_cloud_dev_settings_enabled",
    )

    @api.depends_context("uid")
    def _compute_msp_cloud_dev_settings_enabled(self):
        """Expose whether development-only Cloud POS settings are enabled."""
        dev_settings_enabled = os.getenv(
            "MSP_CLOUD_POS_ENABLE_DEV_SETTINGS",
            "",
        ).lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        for payment_method in self:
            payment_method.msp_cloud_dev_settings_enabled = dev_settings_enabled

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get(
                "use_payment_terminal"
            ) == MSP_CLOUD_PAYMENT_TERMINAL_CODE and not vals.get("image"):
                icon_path = get_module_resource(
                    "pos_multisafepay_cloud",
                    "static/description",
                    "pos_payment_icon.png",
                )
                if icon_path:
                    with open(icon_path, "rb") as icon_file:
                        vals["image"] = base64.b64encode(icon_file.read())
        return super().create(vals_list)

    @api.constrains(
        "use_payment_terminal",
        "active",
        "msp_cloud_terminal_id",
        "msp_cloud_terminal_group_id",
        "msp_cloud_terminal_group_api_key",
    )
    def _check_msp_cloud_terminal_configuration(self):
        """Validate Cloud POS terminal and terminal group configuration."""

        def check_group_key_configured(payment_method):
            """Require a Terminal Group API Key when a group id is configured.

            :param pos.payment.method payment_method: Payment method record.
            """
            terminal_group_id = (
                payment_method.msp_cloud_terminal_group_id or ""
            ).strip()
            terminal_group_api_key = (
                payment_method.msp_cloud_terminal_group_api_key or ""
            ).strip()

            if terminal_group_id and not terminal_group_api_key:
                raise ValidationError(
                    _(
                        "Configure a Terminal Group API Key for Terminal Group ID '%(terminal_group_id)s'."
                    )
                    % {"terminal_group_id": terminal_group_id}
                )

        def check_terminal_configuration_unique(payment_method):
            """Prevent duplicate active terminal and group configurations.

            :param pos.payment.method payment_method: Payment method record.
            """
            terminal_id = (payment_method.msp_cloud_terminal_id or "").strip()
            terminal_group_id = (
                payment_method.msp_cloud_terminal_group_id or ""
            ).strip()
            if not terminal_id or not terminal_group_id:
                return

            conflict = self.search(
                [
                    ("id", "!=", payment_method.id),
                    ("active", "=", True),
                    ("use_payment_terminal", "=", MSP_CLOUD_PAYMENT_TERMINAL_CODE),
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

        for payment_method in self:
            if payment_method.use_payment_terminal != MSP_CLOUD_PAYMENT_TERMINAL_CODE:
                continue

            check_group_key_configured(payment_method)
            check_terminal_configuration_unique(payment_method)

    def _get_payment_terminal_selection(self):
        """Add MultiSafepay Cloud POS to Odoo's payment terminal selection.

        :return: Terminal options list.
        :rtype: list[tuple[str, str]]
        """
        return super()._get_payment_terminal_selection() + [
            MSP_CLOUD_PAYMENT_TERMINAL_SELECTION
        ]

    def multisafepay_cloud_payment_request(self, data):
        """Create a remote Cloud POS order and persist its tracking record.

        This is the RPC entry point used by the POS frontend when a payment line is
        sent to the MultiSafepay Cloud terminal.

        :param dict data: POS payment payload including amount, currency and cart data.
        :return: Normalized Cloud POS order creation response.
        :rtype: dict
        """
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
        """Build an SDK client scoped to this method's terminal group.

        The scoped credential resolver lets the same client use terminal-group
        credentials for Cloud POS calls and the Site API Key for account-level calls.

        :return: Configured MultiSafepay SDK instance.
        :rtype: multisafepay.Sdk
        """
        self.ensure_one()
        return _SDKFactory.build(
            account_api_key=self.msp_cloud_account_api_key,
            terminal_group_id=self.msp_cloud_terminal_group_id,
            terminal_group_api_key=self.msp_cloud_terminal_group_api_key,
            custom_api_url=self.msp_cloud_custom_api_url,
        )

    def _wait_for_cloud_order_event(
        self,
        sdk,
        order_or_payload,
        timeout_seconds=None,
        last_event_id=None,
    ):
        """Return no event payload while Cloud POS uses webhook confirmations only.

        :param multisafepay.Sdk sdk: SDK instance used to subscribe to order events.
        :param order_or_payload: SDK order model or serialized order payload.
        :param float timeout_seconds: Maximum wait time for the event stream.
        :param str last_event_id: Last consumed event id for stream resumption.
        :return: Empty dict because event-stream confirmations are not enabled.
        :rtype: dict
        """
        self.ensure_one()
        return {}

    def _finalize_cloud_pos_payload(self, payload, remote_order_id):
        """Normalize an order creation payload returned by the Cloud POS API.

        Ensures the POS always receives stable ``order_id``, ``transaction_id``,
        ``status`` and ``state`` fields regardless of the SDK response shape.

        :param dict payload: Serialized SDK order payload.
        :param str remote_order_id: Requested order id used as fallback.
        :return: POS-facing order creation payload.
        :rtype: dict
        """
        self.ensure_one()

        payload = dict(payload or {})
        order_id = str(
            payload.get("order_id") or payload.get("transaction_id") or remote_order_id
        )
        status = _Status.normalize(payload.get("status") or "initialized")

        payload.update(
            {
                "id": order_id,
                "order_id": order_id,
                "transaction_id": payload.get("transaction_id") or order_id,
                "status": status,
                "state": _Status.state(status),
            }
        )
        return payload

    def _api_create_cloud_pos_order(self, data):
        """Create a Cloud POS order through the SDK.

        Builds the remote order id, cart, customer, amount details and notification
        options, then normalizes the SDK response into the POS contract.

        :param dict data: POS payment payload including amount, currency and cart data.
        :return: Normalized order creation or error payload.
        :rtype: dict
        """
        self.ensure_one()

        validation_error = self._validate_cloud_pos_configuration(
            require_account_key=False
        )
        if validation_error:
            return validation_error

        remote_order_id = self._build_cloud_pos_order_id(data)
        attempt_base = _Utils.sanitize_order_id(
            data.get("msp_cloud_attempt_base")
            or data.get("msp_cloud_uid")
            or data.get("pos_reference")
            or data.get("order_id")
            or self.id,
            self.id,
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

        try:
            amount_in_cents = _Utils.amount_to_minor_units(data.get("amount"))
            currency = data.get("currency") or "EUR"
            shopping_cart_data = data.get("shopping_cart")
            shopping_cart = _OrderPayloadBuilder.shopping_cart(
                self,
                shopping_cart_data,
            )
            checkout_options = _OrderPayloadBuilder.checkout_options(
                self,
                shopping_cart,
            )
            shopping_cart_summary = _OrderPayloadBuilder.shopping_cart_summary(
                shopping_cart_data
            )
            amount_details = _OrderPayloadBuilder.amount_details(
                shopping_cart_data,
                tip_amount_override=data.get("tip_amount"),
            )
            customer = _OrderPayloadBuilder.customer(data.get("customer"))
            order_description = _OrderPayloadBuilder.order_description(
                data,
                remote_order_id,
                shopping_cart_summary,
            )
            payment_options = (
                PaymentOptions(**{})
                .add_notification_method("POST")
                .add_notification_url(
                    f"{self.get_base_url()}/pos_multisafepay_cloud/notification"
                )
            )
            plugin = (
                Plugin()
                .add_plugin_version("2.1.2")
                .add_shop("Odoo")
                .add_shop_version("18.0")
                .add_shop_root_url(self.get_base_url())
            )
            order_request = (
                OrderRequest()
                .add_type("redirect")
                .add_order_id(remote_order_id)
                .add_description(order_description)
                .add_amount(amount_in_cents)
                .add_currency(currency)
                .add_gateway_info({"terminal_id": self.msp_cloud_terminal_id.strip()})
                .add_plugin(plugin)
            )
            if payment_options:
                order_request.add_payment_options(payment_options)
            if customer:
                order_request.add_customer(customer)
            if checkout_options:
                order_request.add_checkout_options(checkout_options)

            if amount_details:
                order_request.add_amount_details(amount_details)

            # Keep the POS cart available until this point because the code above
            # still derives local request metadata from it: the terminal description,
            # tip/amount details and cart-validation checkout options. The Cloud POS
            # terminal order request itself must not send shopping_cart or
            # checkout_options to the Python SDK/API, because those fields belong to
            # full checkout/cart validation flows and can make terminal payments fail
            # when the POS amount intentionally differs from the full cart payload.
            # Set them explicitly to None only at the SDK boundary so the original POS
            # payload remains intact for tracker creation, logging and later flows.
            order_request.add_shopping_cart(None).add_checkout_options(None)

            sdk = self._get_multisafepay_cloud_sdk()
            order_manager = sdk.get_order_manager()
            _logger.debug(
                "MSP Cloud POS order request payload debug: %s",
                json.dumps(order_request.to_dict(), cls=DecimalEncoder, sort_keys=True),
            )
            create_response = order_manager.create(
                order_request,
                terminal_group_id=self.msp_cloud_terminal_group_id.strip(),
            )

            if not create_response.get_body_success():
                return _ErrorPayload.build(
                    self,
                    _("MultiSafepay Cloud POS order creation failed."),
                    error=create_response.get_body_error_info(),
                    operation="create",
                )

            order = create_response.get_data()
            if not order:
                return _ErrorPayload.build(
                    _(
                        "MultiSafepay Cloud POS order creation did not return order data."
                    )
                )

            payload = _Serializer.serialize_model(order)
            if not payload:
                return _ErrorPayload.build(
                    _(
                        "MultiSafepay Cloud POS order creation returned an invalid order payload."
                    )
                )

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

            _logger.info(
                "Successfully created MultiSafepay Cloud POS order request %s on terminal %s.",
                remote_order_id,
                self.msp_cloud_terminal_id.strip(),
            )

            return payload
        except Exception as error:
            _logger.exception(
                "MSP Cloud POS order creation failed "
                "(remote_order_id=%s, terminal_id=%s, terminal_group_id=%s, custom_url_set=%s): %s",
                remote_order_id,
                self.msp_cloud_terminal_id,
                self.msp_cloud_terminal_group_id,
                bool(self.msp_cloud_custom_api_url),
                _ErrorPayload.format_exception(error),
            )
            return _ErrorPayload.build(
                self,
                _("Could not contact the MultiSafepay Cloud POS API."),
                error=error,
                operation="create",
            )

    def _api_get_cloud_order_status(self, order_id, sdk=None):
        """Fetch and normalize the remote Cloud POS order status.

        :param str order_id: Cloud POS order id to fetch.
        :param multisafepay.Sdk sdk: Optional prebuilt SDK instance.
        :return: Normalized order status or error payload.
        :rtype: dict
        """
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
                return _ErrorPayload.build(
                    self,
                    _("Could not fetch MultiSafepay Cloud POS order status."),
                    error=order_response.get_body_error_info(),
                    operation="status",
                )

            order = order_response.get_data()
            if not order:
                return {}

            payload = _Serializer.serialize_model(order)
            status = _Status.normalize(payload.get("status") or "initialized")
            payload.update(
                {
                    "id": order.order_id,
                    "order_id": order.order_id or str(order_id),
                    "transaction_id": order.transaction_id
                    or order.order_id
                    or str(order_id),
                    "status": status,
                    "state": _Status.state(status),
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
                _ErrorPayload.format_exception(error),
            )
            return _ErrorPayload.build(
                self,
                _("Could not fetch MultiSafepay Cloud POS order status."),
                error=error,
                operation="status",
            )

    def _api_get_cloud_receipt(self, order_id, sdk=None):
        """Fetch and serialize the Cloud POS receipt for a paid order.

        :param str order_id: Cloud POS order id to fetch the receipt for.
        :param multisafepay.Sdk sdk: Optional prebuilt SDK instance.
        :return: Serialized receipt payload, or an empty dict when unavailable.
        :rtype: dict
        """
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
            return _Serializer.serialize_model(receipt)
        except Exception as error:
            _logger.exception(
                "MSP Cloud POS receipt fetch failed "
                "(order_id=%s, terminal_id=%s, terminal_group_id=%s): %s",
                order_id,
                self.msp_cloud_terminal_id,
                self.msp_cloud_terminal_group_id,
                _ErrorPayload.format_exception(error),
            )
            return {}

    def _api_cancel_cloud_pos_order(self, order_id, sdk=None):
        """Cancel a remote Cloud POS terminal order.

        :param str order_id: Cloud POS order id to cancel.
        :param multisafepay.Sdk sdk: Optional prebuilt SDK instance.
        :return: Normalized cancellation or error payload.
        :rtype: dict
        """
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
                return _ErrorPayload.build(
                    self,
                    _("Could not cancel the MultiSafepay Cloud POS payment."),
                    error=cancel_response.get_body_error_info(),
                    operation="cancel",
                )

            payload = _Serializer.serialize_model(cancel_response.get_data())
            status = _Status.normalize(payload.get("status") or "canceled")
            payload.update(
                {
                    "id": str(order_id),
                    "order_id": str(order_id),
                    "transaction_id": payload.get("transaction_id") or str(order_id),
                    "status": status,
                    "state": _Status.state(status),
                }
            )

            _logger.info(
                "Successfully sent cancellation request for MultiSafepay Cloud POS order %s on terminal %s.",
                order_id,
                self.msp_cloud_terminal_id.strip(),
            )

            return payload
        except Exception as error:
            _logger.exception(
                "MSP Cloud POS cancellation failed "
                "(order_id=%s, terminal_id=%s, terminal_group_id=%s): %s",
                order_id,
                self.msp_cloud_terminal_id,
                self.msp_cloud_terminal_group_id,
                _ErrorPayload.format_exception(error),
            )
            return _ErrorPayload.build(
                self,
                _("Could not cancel the MultiSafepay Cloud POS payment."),
                error=error,
                operation="cancel",
            )

    def _api_refund_cloud_pos_order(
        self, order_id, amount, currency, description=None, sdk=None
    ):
        """Refund a paid Cloud POS order through the backend API flow.

        This method performs the actual MultiSafepay refund call.

        :param str order_id: Original Cloud POS order id.
        :param float amount: Refund amount in major units.
        :param str currency: Refund currency code.
        :param str description: Optional refund description.
        :param multisafepay.Sdk sdk: Optional prebuilt SDK instance.
        :return: Normalized refund or error payload.
        :rtype: dict
        """
        self.ensure_one()

        validation_error = self._validate_cloud_pos_configuration(
            require_account_key=True
        )
        if validation_error:
            return validation_error

        amount_in_cents = _Utils.amount_to_minor_units(amount)
        if amount_in_cents <= 0:
            return _ErrorPayload.build(
                _("The MultiSafepay Cloud POS refund amount must be greater than zero.")
            )

        try:
            sdk = sdk or self._get_multisafepay_cloud_sdk()
            order_manager = sdk.get_order_manager()
            refund_payload = (
                RefundOrderRequest(**{})
                .add_amount(amount_in_cents)
                .add_currency(currency or "EUR")
                .add_description(
                    description or _("POS reversal for #%s") % str(order_id)
                )
            )
            refund_response = order_manager.refund(str(order_id), refund_payload)
            if not refund_response or not refund_response.get_body_success():
                return _ErrorPayload.build(
                    self,
                    _("Could not refund the MultiSafepay Cloud POS payment."),
                    error=(refund_response and refund_response.get_body_error_info()),
                    operation="refund",
                )

            refund_data = _Serializer.serialize_response_data(refund_response)
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
                _ErrorPayload.format_exception(error),
            )
            return _ErrorPayload.build(
                self,
                _("Could not refund the MultiSafepay Cloud POS payment."),
                error=error,
                operation="refund",
            )

    def _validate_cloud_pos_configuration(self, require_account_key=False):
        """Validate the Cloud POS configuration required for API calls.

        :param bool require_account_key: Whether the Site API Key is needed.
        :return: POS-facing error payload, or an empty dict when configuration is valid.
        :rtype: dict
        """
        self.ensure_one()

        if not (self.msp_cloud_terminal_id or "").strip():
            return _ErrorPayload.build(
                _("Set MSP Cloud Terminal ID on the payment method.")
            )
        if not (self.msp_cloud_terminal_group_id or "").strip():
            return _ErrorPayload.build(
                _("Set MSP Cloud Terminal Group ID on the payment method.")
            )
        if not (self.msp_cloud_terminal_group_api_key or "").strip():
            return _ErrorPayload.build(
                _("Set MSP Cloud Terminal Group API Key on the payment method.")
            )
        if require_account_key and not (self.msp_cloud_account_api_key or "").strip():
            return _ErrorPayload.build(
                _(
                    "Set MSP Cloud Site API Key on the payment method to poll real Cloud POS statuses and refund completed payments."
                )
            )
        return {}

    def _build_cloud_pos_order_id(self, data):
        """Build the next safe remote order id for a POS payment attempt.

        :param dict data: POS payment payload containing order reference metadata.
        :return: Sanitized and locally unique Cloud POS order id.
        :rtype: str
        """
        self.ensure_one()
        attempt_base = _Utils.sanitize_order_id(
            data.get("msp_cloud_attempt_base")
            or data.get("msp_cloud_uid")
            or data.get("pos_reference")
            or data.get("order_id")
            or self.id,
            self.id,
        )
        requested_order_id = _Utils.sanitize_order_id(
            data.get("msp_cloud_uid") or attempt_base,
            self.id,
        )
        if not (
            requested_order_id == attempt_base
            or requested_order_id.startswith(f"{attempt_base}-")
        ):
            requested_order_id = attempt_base

        return self._next_cloud_pos_order_id(attempt_base, requested_order_id)

    def _next_cloud_pos_order_id(self, attempt_base, requested_order_id):
        """Find the first unused local tracking order id for an attempt base.

        :param str attempt_base: Stable base id for retries of the same POS payment.
        :param str requested_order_id: Preferred order id for this attempt.
        :return: First unused order id for the local tracking model.
        :rtype: str
        """
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
        """Format retry attempt order ids using the attempt base and number.

        :param str attempt_base: Stable base id for order creation attempts.
        :param int attempt_number: Counter representing retry sequence number.
        :return: Formatted candidate attempt order id.
        :rtype: str
        """
        return (
            attempt_base if not attempt_number else f"{attempt_base}-{attempt_number}"
        )

    def _get_cloud_pos_order_attempt_number(self, attempt_base, order_id):
        """Extract the retry attempt number from a Cloud POS order id.

        :param str attempt_base: Stable base id for order creation attempts.
        :param str order_id: Raw order ID containing retry count suffix.
        :return: Retry count integer parsed from ID suffix.
        :rtype: int
        """
        order_id = str(order_id or "")
        if order_id == attempt_base:
            return 0
        prefix = f"{attempt_base}-"
        if order_id.startswith(prefix) and order_id[len(prefix) :].isdigit():
            return int(order_id[len(prefix) :])
        return 0
